import numpy as np
import pytest
from backend.dsp import (
    create_notch_filter,
    create_bandpass_filter,
    PanTompkinsQRSDetector,
    ECGSignalProcessor,
)
from backend.simulator import ECGWaveformGenerator


def test_notch_filter_attenuates_50hz():
    fs = 250.0
    notch = create_notch_filter(50.0, fs=fs, q=30.0)
    # Generate 50Hz sine wave
    t = np.linspace(0, 1.0, int(fs), endpoint=False)
    sine_50hz = np.sin(2 * np.pi * 50.0 * t)

    # Filter signal
    filtered = [notch.process_sample(s) for s in sine_50hz]
    # In steady state (last 50 samples), the 50 Hz amplitude should be strongly attenuated (< 0.25)
    steady_state_amp = np.max(np.abs(filtered[-50:]))
    assert steady_state_amp < 0.25


def test_bandpass_passes_qrs_frequency():
    fs = 250.0
    bp = create_bandpass_filter(0.5, 40.0, fs=fs)
    # 5 Hz physiological ECG component
    t = np.linspace(0, 1.0, int(fs), endpoint=False)
    sine_5hz = np.sin(2 * np.pi * 5.0 * t)
    filtered = [bp.process_sample(s) for s in sine_5hz]
    steady_state_amp = np.max(np.abs(filtered[-50:]))
    # Should pass through with minimal loss (> 0.8)
    assert steady_state_amp > 0.8


def test_pan_tompkins_qrs_detection():
    fs = 250.0
    sim = ECGWaveformGenerator(fs=fs)
    sim.set_condition("normal")  # 72 bpm
    detector = PanTompkinsQRSDetector(fs=fs)

    peaks_detected = 0
    # Run 5 seconds of simulated ECG (expected ~6 beats)
    for _ in range(int(5.0 * fs)):
        ch1, _, _, _ = sim.next_sample()
        is_peak, bpm, _ = detector.process_sample(ch1)
        if is_peak:
            peaks_detected += 1

    assert 4 <= peaks_detected <= 8
    assert 60.0 <= detector.current_bpm <= 85.0


def test_ecg_signal_processor():
    proc = ECGSignalProcessor(fs=250.0, powerline_hz=50.0)
    out = proc.process_sample(1.2, 1.5)
    assert "ch1_clean" in out
    assert "ch2_clean" in out
    assert "is_r_peak" in out
    assert "bpm" in out
    assert "sqi" in out
    assert "lead_off" in out
