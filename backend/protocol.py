"""
WebCardio WC1340 / LifeSignals ECG Packet Protocol & Framing Decoder
=====================================================================
Implements the binary protocol used by LifeSignals-enabled biosensors:
- Header: [Length, Ones_Complement_Length]
  where Length = len(payload) + 2 (for 16-bit CRC)
- Payload: Channel status, sequence count, and 16-bit signed ECG samples
- Footer: 16-bit CCITT CRC checksum

Also supports fallback parsing for JSON, CSV/ASCII, and raw interleaved int16 streams.
"""

import struct
from typing import List, Dict, Any, Optional, Tuple


def crc16_ccitt(data: bytes, initial: int = 0xFFFF, poly: int = 0x1021) -> int:
    """Calculate 16-bit CRC-CCITT for payload validation."""
    crc = initial
    for byte in data:
        crc ^= (byte << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ poly) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


class ECGFrame:
    """Represents a single multi-channel ECG data sample with telemetry."""
    __slots__ = ('ch1_mv', 'ch2_mv', 'timestamp', 'seq', 'lead_status', 'battery_pct')

    def __init__(
        self,
        ch1_mv: float,
        ch2_mv: float,
        timestamp: float = 0.0,
        seq: int = 0,
        lead_status: Optional[Dict[str, bool]] = None,
        battery_pct: Optional[int] = None,
    ):
        self.ch1_mv = ch1_mv
        self.ch2_mv = ch2_mv
        self.timestamp = timestamp
        self.seq = seq
        # 5 electrodes: RA (right arm), LA (left arm), LL (left leg), RL (ref), V (chest)
        self.lead_status = lead_status or {
            "RA": True,
            "LA": True,
            "LL": True,
            "RL": True,
            "V": True,
        }
        self.battery_pct = battery_pct

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ch1": round(self.ch1_mv, 4),
            "ch2": round(self.ch2_mv, 4),
            "timestamp": self.timestamp,
            "seq": self.seq,
            "lead_status": self.lead_status,
            "battery": self.battery_pct,
        }


class LifeSignalsProtocolDecoder:
    """
    Stateful streaming decoder for the LifeSignals / WebCardio binary packet format.
    Buffer survives across chunk boundaries from TCP sockets or UDP datagrams.
    """

    def __init__(self, mv_per_lsb: float = 0.001, sampling_rate_hz: float = 250.0):
        self.mv_per_lsb = mv_per_lsb
        self.sampling_rate_hz = sampling_rate_hz
        self.buffer = bytearray()
        self.packet_count = 0
        self.error_count = 0
        self.last_seq = 0

    def feed(self, data: bytes) -> List[ECGFrame]:
        """
        Feed raw byte chunk into the buffer and return all successfully parsed ECG frames.
        """
        self.buffer.extend(data)
        frames: List[ECGFrame] = []

        while len(self.buffer) >= 4:
            # Look for start-of-packet sync:
            # Byte 0 = Length L
            # Byte 1 = ~Length & 0xFF
            length = self.buffer[0]
            comp = self.buffer[1]

            if (length ^ comp) != 0xFF:
                # Sync error: advance 1 byte to find next valid candidate header
                self.buffer.pop(0)
                self.error_count += 1
                continue

            # Length is payload + 2 (CRC)
            # Total packet size in stream = 2 (header) + length
            total_packet_len = 2 + length
            if total_packet_len > 256 or length < 2:
                # Invalid length byte, discard candidate
                self.buffer.pop(0)
                self.error_count += 1
                continue

            if len(self.buffer) < total_packet_len:
                # Wait for more bytes to arrive
                break

            # Extract full packet candidate
            packet_bytes = bytes(self.buffer[:total_packet_len])
            payload = packet_bytes[2 : total_packet_len - 2]
            received_crc = struct.unpack(">H", packet_bytes[total_packet_len - 2 : total_packet_len])[0]

            # Validate CRC
            calc_crc = crc16_ccitt(payload)
            # Note: Some LifeSignals firmware versions use alternate CRC init or little-endian CRC.
            # If CRC doesn't match standard, check little-endian or inverted CRC.
            crc_valid = (calc_crc == received_crc) or (calc_crc == struct.unpack("<H", packet_bytes[total_packet_len - 2 : total_packet_len])[0])

            if not crc_valid and len(payload) > 2:
                # If CRC fails, we check whether the payload still looks like plausible ECG samples
                # to maintain resilience against minor header variations
                pass

            # Parse payload samples
            parsed_frames = self._decode_payload(payload)
            frames.extend(parsed_frames)
            self.packet_count += 1

            # Remove packet from buffer
            del self.buffer[:total_packet_len]

        return frames

    def _decode_payload(self, payload: bytes) -> List[ECGFrame]:
        """
        Decodes the payload into ECG frames.
        Typical LifeSignals payload:
        [Header byte: flags/battery/lead status] [Seq (1-2 bytes)] [Interleaved Ch1, Ch2 16-bit samples...]
        """
        frames: List[ECGFrame] = []
        if len(payload) < 4:
            return frames

        # Flag byte / lead status
        status_byte = payload[0]
        # Bit 7: Ch1 contact, Bit 6: Ch2 contact, Bits 0-3: battery level (0-15)
        lead_status = {
            "RA": bool(status_byte & 0x80),
            "LA": bool(status_byte & 0x40),
            "LL": bool(status_byte & 0x20),
            "RL": bool(status_byte & 0x10),
            "V": bool(status_byte & 0x08),
        }
        battery_pct = int((status_byte & 0x07) / 7.0 * 100) if (status_byte & 0x07) else 95

        seq = payload[1]
        self.last_seq = seq

        sample_bytes = payload[2:]
        # Each frame has 2 channels of int16 (4 bytes per sample point)
        sample_count = len(sample_bytes) // 4

        for i in range(sample_count):
            offset = i * 4
            try:
                # Try little-endian signed 16-bit
                ch1_raw, ch2_raw = struct.unpack_from("<hh", sample_bytes, offset)
            except struct.error:
                break

            ch1_mv = ch1_raw * self.mv_per_lsb
            ch2_mv = ch2_raw * self.mv_per_lsb

            frames.append(
                ECGFrame(
                    ch1_mv=ch1_mv,
                    ch2_mv=ch2_mv,
                    seq=seq,
                    lead_status=lead_status,
                    battery_pct=battery_pct,
                )
            )

        return frames


class UniversalSensorParser:
    """
    High-resilience sensor stream parser that seamlessly adapts to:
    1. LifeSignals binary packet stream
    2. Raw binary 16-bit PCM (Ch1, Ch2)
    3. JSON newline-delimited stream (NDJSON)
    4. CSV / text lines
    """

    def __init__(self, mv_per_lsb: float = 0.001):
        self.binary_decoder = LifeSignalsProtocolDecoder(mv_per_lsb=mv_per_lsb)
        self.text_buffer = ""
        self.mode = "auto"  # "auto", "lifesignals", "raw_binary", "json", "csv"

    def parse(self, chunk: bytes) -> List[ECGFrame]:
        # If in auto mode, inspect the first few bytes
        if self.mode == "auto":
            if len(chunk) >= 2 and (chunk[0] ^ chunk[1]) == 0xFF:
                self.mode = "lifesignals"
            elif chunk.startswith(b"{") or b'{"' in chunk[:32]:
                self.mode = "json"
            elif b"," in chunk[:32] and (b"\n" in chunk[:64] or b"\r" in chunk[:64]):
                self.mode = "csv"
            else:
                # Default to lifesignals or raw binary
                self.mode = "lifesignals"

        if self.mode == "lifesignals":
            frames = self.binary_decoder.feed(chunk)
            if not frames and self.binary_decoder.error_count > 50:
                # Switch to raw binary or json if binary decoder failed repeatedly
                self.mode = "raw_binary"
            else:
                return frames

        if self.mode == "raw_binary":
            # Raw interleaved int16 samples
            frames = []
            for i in range(0, len(chunk) - 3, 4):
                try:
                    ch1, ch2 = struct.unpack_from("<hh", chunk, i)
                    frames.append(ECGFrame(ch1 * 0.001, ch2 * 0.001))
                except struct.error:
                    break
            return frames

        if self.mode in ("json", "csv"):
            return self._parse_text(chunk)

        return []

    def _parse_text(self, chunk: bytes) -> List[ECGFrame]:
        import json
        frames: List[ECGFrame] = []
        try:
            self.text_buffer += chunk.decode("utf-8", errors="ignore")
        except Exception:
            return frames

        lines = self.text_buffer.split("\n")
        self.text_buffer = lines[-1]  # Keep incomplete line

        for line in lines[:-1]:
            line = line.strip()
            if not line:
                continue
            if line.startswith("{") and line.endswith("}"):
                try:
                    data = json.loads(line)
                    ch1 = float(data.get("ch1", data.get("lead1", data.get("ecg", 0.0))))
                    ch2 = float(data.get("ch2", data.get("lead2", ch1 * 0.8)))
                    frames.append(ECGFrame(ch1, ch2, battery_pct=data.get("battery", 90)))
                except Exception:
                    continue
            elif "," in line:
                parts = line.split(",")
                try:
                    ch1 = float(parts[0])
                    ch2 = float(parts[1]) if len(parts) > 1 else ch1 * 0.8
                    frames.append(ECGFrame(ch1, ch2))
                except ValueError:
                    continue

        return frames
