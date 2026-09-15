# WebCardio WC1340 Real-Time ECG Monitor

A clinical-grade, production-ready web application (Python FastAPI backend + HTML5 Canvas 60 FPS oscilloscope frontend) designed to connect to the **WebCardio Wearable Biosensor (WC1340 / LifeSignals)** over Wi-Fi, stream real-time dual-channel ECG signals, and visualize live waveforms on an interactive telemetry monitor.

---

## Features

- **Direct Sensor Ingestion**: Listens for raw WebCardio / LifeSignals binary packets on TCP/UDP socket ports (`5000`, `9000`) with start-of-packet framing (`Length` + `~Length`), CRC-16 CCITT verification, and 16-bit sample decoding.
- **Hospital-Grade Oscilloscope Frontend**: 60 FPS sweep-bar (erase-head) rendering on dual channels:
  - **Lead I (Channel 1)**: Phosphor green trace (`#00ff88`)
  - **Lead II (Channel 2)**: Cyan trace (`#00e5ff`)
  - Calibrated standard medical ECG paper grid (1mm minor, 5mm major divisions, isoelectric baseline).
- **Real-Time DSP Pipeline**:
  - 50 Hz / 60 Hz IIR notch filter for mains powerline rejection.
  - 0.5 Hz – 40 Hz Butterworth bandpass filter for baseline wander and motion artifact suppression.
  - Real-time online **Pan-Tompkins algorithm** for R-peak detection and instantaneous Heart Rate (BPM) / RR interval calculation.
  - Signal Quality Index (SQI) and Lead Detachment detection.
- **5-Electrode Anatomical Map**: Live contact impedance visualization for all 5 patch contact points (RA, LA, LL, RL, V).
- **Audible QRS Beep**: Web Audio API synthesizer for clinical pulse tone with pitch modulation and mute toggle.
- **Interactive Wi-Fi Setup Wizard**: Built-in subnet discovery scanner that probes the local network for the biosensor's IP address.
- **High-Fidelity Clinical Simulator**: Built-in 250 Hz P-Q-R-S-T waveform generator with selectable pathologies (Normal Sinus, Tachycardia, Bradycardia, PVC ectopic beats, Motion noise) for instant testing out-of-the-box.
- **Session Recording**: One-click recording of clinical sessions with CSV and JSON data export.

---

## Project Structure

```
.
├── backend/
│   ├── __init__.py
│   ├── protocol.py           # LifeSignals binary packet framer & decoder
│   ├── dsp.py                # IIR notch, Butterworth bandpass, Pan-Tompkins QRS
│   ├── simulator.py          # 250 Hz dual-channel clinical ECG synthesizer
│   ├── network_discovery.py  # Subnet, ARP, and port discovery tool
│   └── server.py             # FastAPI WebSocket server & socket listener
├── frontend/
│   ├── index.html            # Medical dashboard interface
│   ├── css/
│   │   └── style.css         # Dark-mode telemetry styling & SVG graphics
│   └── js/
│       ├── ecg_canvas.js     # 60fps sweep-bar canvas renderer
│       ├── audio.js          # Web Audio API pulse tone synthesizer
│       └── app.js            # Telemetry state controller & WebSocket client
├── tests/
│   ├── test_protocol.py      # Protocol & CRC unit tests
│   ├── test_dsp.py           # Digital filter & QRS detector tests
│   └── test_server.py        # REST API & endpoint tests
├── run.sh                    # One-click startup script
├── requirements.txt          # Python dependencies
├── WIFI_SETUP_GUIDE.md       # Hardware Wi-Fi pairing instructions
└── README.md
```

---

## Quick Start

### 1. Requirements
- Python 3.10+
- Modern Web Browser (Chrome, Safari, Firefox, Edge)

### 2. Run Locally
Run the one-click launch script:
```bash
./run.sh
```
Or manually:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=.
uvicorn backend.server:app --host 0.0.0.0 --port 8000 --reload
```

### 3. Open the Dashboard
Open your browser to:
```
http://localhost:8000
```
By default, the monitor starts in **Simulator Mode** displaying live, clinical-grade 2-channel ECG waveforms so you can test all features immediately.

---

## Connecting Your Physical Sensor

See [WIFI_SETUP_GUIDE.md](file:///Users/rammanthanwar/Downloads/ECG%20monitor/WIFI_SETUP_GUIDE.md) for full instructions:
1. Create a **2.4 GHz Wi-Fi Hotspot** on your phone or laptop.
2. Set Hotspot SSID to `CMSEN` (or `WC1340`).
3. Set Password to `copernicus`.
4. Press and hold the power button on the biosensor to turn it on.
5. In the web dashboard, click **"Wi-Fi & Pairing Setup"** &rarr; **"Scan Local Subnet"** to verify connection.
6. The system automatically switches to **Live Hardware** mode as soon as packets arrive!

---

## Running Automated Tests

Run the test suite with:
```bash
PYTHONPATH=. .venv/bin/pytest tests/ -v
```
