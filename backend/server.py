"""
WebCardio ECG Backend Server
============================
FastAPI + WebSocket server providing:
1. Real-time dual-lead 250 Hz ECG telemetry streaming over WebSocket
2. TCP/UDP socket listeners for direct WebCardio WC1340 / LifeSignals biosensor connection
3. Active TCP client connector (to connect to sensor when sensor is running an AP/server)
4. Subnet discovery scanner
5. Clinical-grade simulator mode with seamless hardware auto-detection
"""

import asyncio
import collections
from contextlib import asynccontextmanager
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .dsp import ECGSignalProcessor
from .network_discovery import discover_sensor, get_local_ip_addresses
from .protocol import UniversalSensorParser
from .simulator import ECGWaveformGenerator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("WebCardioServer")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting WebCardio ECG Server background workers...")
    asyncio.create_task(simulator_worker())
    asyncio.create_task(telemetry_broadcast_worker())
    asyncio.create_task(start_tcp_listener("0.0.0.0", 5000))
    asyncio.create_task(start_udp_listener("0.0.0.0", 5000))
    asyncio.create_task(start_udp_listener("0.0.0.0", 9000))
    yield


app = FastAPI(
    title="WebCardio WC1340 ECG Monitor Backend",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global State
class SystemState:
    def __init__(self):
        self.mode: str = "simulator"  # "simulator" or "hardware"
        self.hardware_connected: bool = False
        self.hardware_last_packet_time: float = 0.0
        self.active_websockets: Set[WebSocket] = set()

        # DSP Pipeline
        self.dsp = ECGSignalProcessor(fs=250.0, powerline_hz=50.0)

        # Protocol Parser
        self.parser = UniversalSensorParser(mv_per_lsb=0.001)

        # Simulator
        self.simulator = ECGWaveformGenerator(fs=250.0)

        # Sample Queues (raw samples waiting to be processed & pushed)
        self.sample_queue: asyncio.Queue = asyncio.Queue()

        # Recording Buffer
        self.is_recording: bool = False
        self.recording_buffer: List[Dict] = []
        self.recording_start_time: float = 0.0

        # Telemetry Cache
        self.latest_telemetry: Dict = {
            "bpm": 72.0,
            "sqi": 0.98,
            "lead_off": False,
            "lead_status": {"RA": True, "LA": True, "LL": True, "RL": True, "V": True},
            "battery": 94,
            "mode": "simulator",
            "hardware_connected": False,
            "packets_received": 0,
        }
        self.packets_received: int = 0


state = SystemState()


# Background Task: Hardware TCP Server (Sensor acts as TCP client)
async def start_tcp_listener(host: str = "0.0.0.0", ports: Optional[Any] = None):
    if ports is None:
        ports = [5000, 5001, 8888]
    elif isinstance(ports, int):
        ports = [ports, ports + 1, 8888]

    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        peer = writer.get_extra_info("peername")
        logger.info(f"Sensor connected via TCP from {peer}")
        state.hardware_connected = True
        state.mode = "hardware"
        state.latest_telemetry["hardware_connected"] = True
        state.latest_telemetry["mode"] = "hardware"

        try:
            while True:
                data = await reader.read(1024)
                if not data:
                    break
                state.hardware_last_packet_time = time.time()
                state.packets_received += 1
                frames = state.parser.parse(data)
                for f in frames:
                    await state.sample_queue.put(f)
        except Exception as e:
            logger.warning(f"TCP sensor stream error: {e}")
        finally:
            logger.info(f"Sensor disconnected: {peer}")
            writer.close()
            await writer.wait_closed()
            state.hardware_connected = False
            state.latest_telemetry["hardware_connected"] = False

    servers = []
    for port in ports:
        try:
            srv = await asyncio.start_server(handle_client, host, port)
            logger.info(f"Started Sensor TCP Listener on {host}:{port}")
            servers.append(srv)
        except OSError as e:
            logger.info(f"Port {port} unavailable ({e}). Skipping.")

    if not servers:
        logger.error("Could not bind any TCP listening ports for sensor.")
        return

    try:
        # Keep listening on all successfully opened servers
        await asyncio.gather(*(srv.serve_forever() for srv in servers))
    except asyncio.CancelledError:
        for srv in servers:
            srv.close()
            await srv.wait_closed()


# Background Task: Hardware UDP Listener (Sensor sends UDP packets)
class SensorUDPProtocol(asyncio.DatagramProtocol):
    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        state.hardware_last_packet_time = time.time()
        state.hardware_connected = True
        state.mode = "hardware"
        state.latest_telemetry["hardware_connected"] = True
        state.latest_telemetry["mode"] = "hardware"
        state.packets_received += 1

        frames = state.parser.parse(data)
        for f in frames:
            try:
                state.sample_queue.put_nowait(f)
            except asyncio.QueueFull:
                pass


async def start_udp_listener(host: str = "0.0.0.0", port: int = 5000):
    loop = asyncio.get_running_loop()
    try:
        transport, _ = await loop.create_datagram_endpoint(
            lambda: SensorUDPProtocol(),
            local_addr=(host, port),
        )
        logger.info(f"Started Sensor UDP Listener on {host}:{port}")
    except Exception as e:
        logger.warning(f"Could not bind UDP port {port}: {e}")


# Background Task: Simulator sample producer
async def simulator_worker():
    """Generates 250 Hz ECG samples when in simulator mode."""
    target_fs = 250.0
    dt = 1.0 / target_fs
    next_time = time.time()

    while True:
        # If in hardware mode and recent data arrived within last 3 seconds, don't inject sim data
        hardware_active = state.hardware_connected and (time.time() - state.hardware_last_packet_time < 3.0)

        if not hardware_active and (state.mode == "simulator" or not state.hardware_connected):
            ch1, ch2, lead_status, battery = state.simulator.next_sample()
            from .protocol import ECGFrame
            frame = ECGFrame(
                ch1_mv=ch1,
                ch2_mv=ch2,
                timestamp=time.time(),
                lead_status=lead_status,
                battery_pct=battery,
            )
            await state.sample_queue.put(frame)

        next_time += dt
        sleep_dur = next_time - time.time()
        if sleep_dur > 0:
            await asyncio.sleep(sleep_dur)
        else:
            # Catch up if running slightly behind
            if sleep_dur < -0.1:
                next_time = time.time()
            await asyncio.sleep(0.001)


# Background Task: Telemetry broadcaster (60 FPS to all connected WebSockets)
async def telemetry_broadcast_worker():
    """
    Pulls processed samples and batches them into ~60 FPS packets for the UI.
    """
    target_fps = 60.0
    batch_interval = 1.0 / target_fps

    while True:
        try:
            start_t = time.time()
            samples_batch = []

            # Drain available frames from the queue
            while not state.sample_queue.empty():
                try:
                    frame = state.sample_queue.get_nowait()
                    # Run through DSP
                    dsp_out = state.dsp.process_sample(frame.ch1_mv, frame.ch2_mv)

                    sample_dict = {
                        "ch1": float(dsp_out["ch1_clean"]),
                        "ch2": float(dsp_out["ch2_clean"]),
                        "ch1_raw": float(dsp_out["ch1_raw"]),
                        "ch2_raw": float(dsp_out["ch2_raw"]),
                        "r_peak": bool(dsp_out["is_r_peak"]),
                        "t": round(frame.timestamp, 3) if frame.timestamp else round(time.time(), 3),
                    }
                    samples_batch.append(sample_dict)

                    # Update telemetry
                    state.latest_telemetry["bpm"] = float(dsp_out["bpm"])
                    state.latest_telemetry["sqi"] = float(dsp_out["sqi"])
                    state.latest_telemetry["lead_off"] = bool(dsp_out["lead_off"])
                    state.latest_telemetry["lead_status"] = frame.lead_status
                    if frame.battery_pct is not None:
                        state.latest_telemetry["battery"] = int(frame.battery_pct)
                    state.latest_telemetry["packets_received"] = int(state.packets_received)

                    # If recording, append
                    if state.is_recording:
                        state.recording_buffer.append(sample_dict)

                except asyncio.QueueEmpty:
                    break

            # Check hardware watchdog
            if state.hardware_connected and (time.time() - state.hardware_last_packet_time > 4.0):
                state.hardware_connected = False
                state.latest_telemetry["hardware_connected"] = False
                if state.mode == "hardware":
                    logger.info("Hardware stream timeout. Reverting to simulator fallback.")

            # Broadcast if there are samples and connected clients
            if samples_batch and state.active_websockets:
                def _json_serial(o):
                    if hasattr(o, 'item'):
                        return o.item()
                    return str(o)

                payload = json.dumps({
                    "type": "ecg_batch",
                    "samples": samples_batch,
                    "telemetry": state.latest_telemetry,
                }, default=_json_serial)

                dead_sockets = set()
                for ws in state.active_websockets:
                    try:
                        await ws.send_text(payload)
                    except Exception:
                        dead_sockets.add(ws)

                for ws in dead_sockets:
                    state.active_websockets.discard(ws)

            elapsed = time.time() - start_t
            sleep_needed = batch_interval - elapsed
            if sleep_needed > 0:
                await asyncio.sleep(sleep_needed)
            else:
                await asyncio.sleep(0.001)

        except Exception as err:
            logger.error(f"Unexpected error in telemetry_broadcast_worker: {err}")
            await asyncio.sleep(0.01)




@app.websocket("/ws/ecg")
async def websocket_ecg(websocket: WebSocket):
    await websocket.accept()
    state.active_websockets.add(websocket)
    logger.info(f"WebSocket client connected. Total clients: {len(state.active_websockets)}")
    try:
        while True:
            # Keep-alive / command receiver from client
            msg_text = await websocket.receive_text()
            data = json.loads(msg_text)
            action = data.get("action")
            if action == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        state.active_websockets.discard(websocket)
        logger.info("WebSocket client disconnected.")
    except Exception as e:
        state.active_websockets.discard(websocket)
        logger.warning(f"WebSocket error: {e}")


# REST API Models & Endpoints
class ModeRequest(BaseModel):
    mode: str  # "simulator" or "hardware"
    condition: Optional[str] = "normal"  # "normal", "tachycardia", "bradycardia", "pvc", "noise"


class FilterRequest(BaseModel):
    filter_mode: str  # "monitor", "diagnostic", "raw"
    notch_enabled: bool = True
    powerline_hz: Optional[float] = 50.0


class ConnectDeviceRequest(BaseModel):
    ip: str
    port: int = 5000
    protocol: str = "tcp"  # "tcp" or "udp"


@app.get("/api/status")
async def get_status():
    return {
        "status": "online",
        "mode": state.mode,
        "hardware_connected": state.hardware_connected,
        "active_clients": len(state.active_websockets),
        "local_ips": get_local_ip_addresses(),
        "telemetry": state.latest_telemetry,
        "recording": state.is_recording,
        "recorded_samples": len(state.recording_buffer),
    }


@app.post("/api/mode")
async def set_mode(req: ModeRequest):
    state.mode = req.mode
    state.latest_telemetry["mode"] = req.mode
    if req.condition:
        state.simulator.set_condition(req.condition)
    return {"status": "ok", "mode": state.mode, "condition": req.condition}


@app.post("/api/filter")
async def set_filter(req: FilterRequest):
    state.dsp.filter_mode = req.filter_mode
    state.dsp.notch_enabled = req.notch_enabled
    if req.powerline_hz:
        state.dsp.powerline_hz = req.powerline_hz
    return {
        "status": "ok",
        "filter_mode": state.dsp.filter_mode,
        "notch_enabled": state.dsp.notch_enabled,
        "powerline_hz": state.dsp.powerline_hz,
    }


@app.get("/api/discover")
async def run_discovery():
    """Scans subnet and ARP table for sensor candidate devices."""
    devices = await discover_sensor()
    return {"status": "ok", "devices": devices, "local_ips": get_local_ip_addresses()}


@app.post("/api/connect_device")
async def connect_to_sensor(req: ConnectDeviceRequest):
    """
    Actively connects to a sensor that is operating as a TCP server on a known IP/port.
    """
    try:
        reader, writer = await asyncio.open_connection(req.ip, req.port)
        state.hardware_connected = True
        state.mode = "hardware"
        state.latest_telemetry["hardware_connected"] = True
        state.latest_telemetry["mode"] = "hardware"

        async def active_client_loop():
            try:
                while True:
                    data = await reader.read(1024)
                    if not data:
                        break
                    state.hardware_last_packet_time = time.time()
                    state.packets_received += 1
                    frames = state.parser.parse(data)
                    for f in frames:
                        await state.sample_queue.put(f)
            except Exception as ex:
                logger.warning(f"Active client connection closed: {ex}")
            finally:
                writer.close()
                await writer.wait_closed()
                state.hardware_connected = False
                state.latest_telemetry["hardware_connected"] = False

        asyncio.create_task(active_client_loop())
        return {"status": "connected", "ip": req.ip, "port": req.port}
    except Exception as e:
        return JSONResponse(status_code=400, content={"status": "error", "message": str(e)})


@app.post("/api/record/start")
async def start_recording():
    state.is_recording = True
    state.recording_buffer = []
    state.recording_start_time = time.time()
    return {"status": "recording_started"}


@app.post("/api/record/stop")
async def stop_recording():
    state.is_recording = False
    return {
        "status": "recording_stopped",
        "sample_count": len(state.recording_buffer),
        "duration_sec": round(time.time() - state.recording_start_time, 2),
    }


@app.get("/api/record/export")
async def export_recording(format: str = "csv"):
    if format == "json":
        return JSONResponse(content={"recording": state.recording_buffer})
    # Export CSV format
    import io
    output = io.StringIO()
    output.write("timestamp,ch1_mv,ch2_mv,ch1_raw_mv,ch2_raw_mv,r_peak\n")
    for s in state.recording_buffer:
        output.write(f"{s.get('t', 0)},{s.get('ch1', 0)},{s.get('ch2', 0)},{s.get('ch1_raw', 0)},{s.get('ch2_raw', 0)},{1 if s.get('r_peak') else 0}\n")

    from fastapi.responses import Response
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=webcardio_ecg_recording.csv"}
    )


# Serve Frontend
frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
if os.path.isdir(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

@app.get("/")
async def serve_index():
    index_path = os.path.join(frontend_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Frontend not yet generated. Please check /frontend/index.html"}
