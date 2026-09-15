import struct
import pytest
from backend.protocol import crc16_ccitt, LifeSignalsProtocolDecoder, UniversalSensorParser, ECGFrame


def test_crc16_ccitt():
    test_data = b"123456789"
    # CCITT with poly 0x1021, init 0xFFFF for "123456789" is 0x29B1
    crc = crc16_ccitt(test_data)
    assert crc == 0x29B1


def test_lifesignals_decoder_valid_packet():
    decoder = LifeSignalsProtocolDecoder()

    # Create payload:
    # byte 0: status = 0xFF (all 5 leads connected, battery high)
    # byte 1: seq = 12
    # samples: 2 samples of Ch1, Ch2 (4 bytes each -> 8 bytes)
    # sample 0: ch1=1000 (1.0 mV), ch2=1500 (1.5 mV)
    # sample 1: ch1=500 (0.5 mV), ch2=800 (0.8 mV)
    sample_bytes = struct.pack("<hhhh", 1000, 1500, 500, 800)
    payload = bytes([0xFF, 12]) + sample_bytes

    # Packet length L = len(payload) + 2 (for CRC)
    length = len(payload) + 2
    comp_length = (~length) & 0xFF

    crc = crc16_ccitt(payload)
    crc_bytes = struct.pack(">H", crc)

    packet = bytes([length, comp_length]) + payload + crc_bytes

    frames = decoder.feed(packet)
    assert len(frames) == 2
    assert pytest.approx(frames[0].ch1_mv, 0.001) == 1.0
    assert pytest.approx(frames[0].ch2_mv, 0.001) == 1.5
    assert pytest.approx(frames[1].ch1_mv, 0.001) == 0.5
    assert pytest.approx(frames[1].ch2_mv, 0.001) == 0.8
    assert frames[0].lead_status["RA"] is True
    assert frames[0].seq == 12


def test_universal_parser_json():
    parser = UniversalSensorParser()
    json_stream = b'{"ch1": 0.45, "ch2": 0.92, "battery": 92}\n{"ch1": 0.48, "ch2": 0.95}\n'
    frames = parser.parse(json_stream)
    assert len(frames) == 2
    assert pytest.approx(frames[0].ch1_mv, 0.01) == 0.45
    assert pytest.approx(frames[0].ch2_mv, 0.01) == 0.92
    assert frames[0].battery_pct == 92


def test_universal_parser_csv():
    parser = UniversalSensorParser()
    csv_stream = b"1.25,1.75\n0.95,1.40\n"
    frames = parser.parse(csv_stream)
    assert len(frames) == 2
    assert pytest.approx(frames[0].ch1_mv, 0.01) == 1.25
    assert pytest.approx(frames[0].ch2_mv, 0.01) == 1.75
