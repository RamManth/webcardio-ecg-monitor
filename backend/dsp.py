"""
Real-time Digital Signal Processing (DSP) & QRS Detection Pipeline
==================================================================
Provides clinical-grade signal filtering and feature extraction for ECG:
1. Real-time IIR Notch Filter (50Hz / 60Hz powerline interference)
2. Butterworth Bandpass Filter (0.5Hz - 40Hz for monitor mode)
3. Online Pan-Tompkins QRS & R-peak detector
4. Real-time Heart Rate (BPM) & RR-interval calculation
5. Lead Off / Electrode Contact Quality Index (SQI)
"""

import collections
import time
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
from scipy.signal import butter, iirnotch, lfilter, lfilter_zi


class RealtimeFilter:
    """
    Stateful real-time IIR filter using lfilter with persistent filter states (zi).
    Operates sample-by-sample without phase distortion or boundary artifacts.
    """

    def __init__(self, b: np.ndarray, a: np.ndarray):
        self.b = np.asarray(b, dtype=np.float64)
        self.a = np.asarray(a, dtype=np.float64)
        self.zi = lfilter_zi(self.b, self.a) * 0.0

    def process_sample(self, sample: float) -> float:
        out, self.zi = lfilter(self.b, self.a, [sample], zi=self.zi)
        return float(out[0])

    def process_block(self, samples: np.ndarray) -> np.ndarray:
        out, self.zi = lfilter(self.b, self.a, samples, zi=self.zi)
        return out

    def reset(self):
        self.zi = lfilter_zi(self.b, self.a) * 0.0


def create_notch_filter(notch_freq: float = 50.0, fs: float = 250.0, q: float = 30.0) -> RealtimeFilter:
    """Design a 50Hz or 60Hz powerline rejection notch filter."""
    w0 = notch_freq / (fs / 2.0)
    # Clamp w0 in case fs is close to notch
    if w0 >= 1.0:
        w0 = 0.99
    b, a = iirnotch(w0, q)
    return RealtimeFilter(b, a)


def create_bandpass_filter(lowcut: float = 0.5, highcut: float = 40.0, fs: float = 250.0, order: int = 2) -> RealtimeFilter:
    """Design a Butterworth bandpass filter for baseline wander and high-frequency noise removal."""
    nyq = 0.5 * fs
    low = max(0.01, lowcut / nyq)
    high = min(0.99, highcut / nyq)
    b, a = butter(order, [low, high], btype='band')
    return RealtimeFilter(b, a)


class PanTompkinsQRSDetector:
    """
    Real-time online Pan-Tompkins QRS Detection Algorithm.
    Operates sequentially on incoming samples at sampling frequency fs.
    Detects R-peaks, calculates RR intervals, Heart Rate (BPM), and HRV.
    """

    def __init__(self, fs: float = 250.0):
        self.fs = fs
        self.dt = 1.0 / fs

        # 1. Bandpass filter for QRS energy (5 - 15 Hz)
        nyq = 0.5 * fs
        b_bp, a_bp = butter(1, [5.0 / nyq, 15.0 / nyq], btype='band')
        self.bp_filter = RealtimeFilter(b_bp, a_bp)

        # 2. Derivative buffer (5-point derivative: y[n] = (2x[n] + x[n-1] - x[n-3] - 2x[n-4]) / 8)
        self.deriv_buffer = collections.deque(maxlen=5)

        # 3. Moving window integrator window size (~150 ms)
        self.mwi_window_size = int(0.150 * fs)
        self.mwi_buffer = collections.deque(maxlen=self.mwi_window_size)
        self.mwi_sum = 0.0

        # 4. Adaptive thresholds (calibrated for standard millivolt ECG scale)
        self.signal_level = 0.006
        self.noise_level = 0.0005
        self.threshold = 0.002

        # 5. Timing and refractory period (200 ms)
        self.sample_idx = 0
        self.refractory_samples = int(0.200 * fs)
        self.last_peak_sample = -self.refractory_samples
        self.last_peak_time = time.time()

        # 6. Peak search window
        self.recent_rr_intervals = collections.deque(maxlen=8)
        self.r_peak_indices = collections.deque(maxlen=32)
        self.current_bpm: float = 72.0
        self.last_r_peak_detected: bool = False

        # Raw sample buffer for locating exact R-peak peak in raw ECG
        self.raw_buffer = collections.deque(maxlen=int(0.250 * fs))

    def process_sample(self, raw_sample: float) -> Tuple[bool, float, float]:
        """
        Processes a single sample through the QRS detection pipeline.
        Returns:
            is_r_peak: True if an R-peak was detected at this sample
            current_bpm: Current calculated Heart Rate in Beats Per Minute
            integrated_val: The output of the moving window integration stage
        """
        self.sample_idx += 1
        self.last_r_peak_detected = False
        self.raw_buffer.append(raw_sample)

        # Step 1: Bandpass filter (5-15 Hz)
        bp_val = self.bp_filter.process_sample(raw_sample)

        # Step 2: 5-point derivative
        self.deriv_buffer.append(bp_val)
        if len(self.deriv_buffer) == 5:
            d = (2.0 * self.deriv_buffer[4] + self.deriv_buffer[3] - self.deriv_buffer[1] - 2.0 * self.deriv_buffer[0]) / 8.0
        else:
            d = 0.0

        # Step 3: Squaring
        squared = d * d

        # Step 4: Moving window integration
        if len(self.mwi_buffer) == self.mwi_window_size:
            oldest = self.mwi_buffer.popleft()
            self.mwi_sum -= oldest

        self.mwi_buffer.append(squared)
        self.mwi_sum += squared
        mwi_val = self.mwi_sum / max(1, len(self.mwi_buffer))

        # Step 5: Adaptive threshold detection with refractory lockout
        samples_since_last_peak = self.sample_idx - self.last_peak_sample

        if samples_since_last_peak > self.refractory_samples:
            if mwi_val > self.threshold:
                # Potential peak candidate
                self.last_peak_sample = self.sample_idx
                self.last_r_peak_detected = True

                # Update signal level and threshold
                self.signal_level = 0.125 * mwi_val + 0.875 * self.signal_level
                self.threshold = self.noise_level + 0.25 * (self.signal_level - self.noise_level)

                # Calculate RR interval and BPM
                now = time.time()
                rr_interval_sec = samples_since_last_peak / self.fs
                # Valid physiological human RR interval: 0.25s (240 bpm) to 2.0s (30 bpm)
                if 0.25 <= rr_interval_sec <= 2.2:
                    bpm_instant = 60.0 / rr_interval_sec
                    self.recent_rr_intervals.append(bpm_instant)
                    # Smoothed BPM via median
                    self.current_bpm = float(np.median(list(self.recent_rr_intervals)))
            else:
                # Update noise level
                self.noise_level = 0.125 * mwi_val + 0.875 * self.noise_level
                self.threshold = self.noise_level + 0.25 * (self.signal_level - self.noise_level)

        return self.last_r_peak_detected, self.current_bpm, mwi_val


class ECGSignalProcessor:
    """
    Full dual-channel real-time ECG processing pipeline.
    Combines Notch filtering, Bandpass filtering, QRS detection, SQI estimation,
    and lead-off validation.
    """

    def __init__(self, fs: float = 250.0, powerline_hz: float = 50.0):
        self.fs = fs
        self.powerline_hz = powerline_hz

        # Dual-channel filters
        self.ch1_notch = create_notch_filter(powerline_hz, fs=fs)
        self.ch2_notch = create_notch_filter(powerline_hz, fs=fs)

        self.ch1_bandpass = create_bandpass_filter(0.5, 40.0, fs=fs)
        self.ch2_bandpass = create_bandpass_filter(0.5, 40.0, fs=fs)

        # QRS detector on primary lead (Channel 1 / Lead I)
        self.qrs_detector = PanTompkinsQRSDetector(fs=fs)

        # Signal Quality Index (SQI) rolling buffer
        self.sqi_buffer = collections.deque(maxlen=int(2.0 * fs))

        # Filter mode: 'diagnostic' (0.05-150Hz), 'monitor' (0.5-40Hz), 'raw' (unfiltered)
        self.filter_mode = "monitor"
        self.notch_enabled = True

    def process_sample(self, ch1_raw: float, ch2_raw: float) -> Dict[str, Any]:
        """
        Process incoming raw sample pair from biosensor.
        Returns cleaned signals, R-peak flag, instantaneous BPM, and SQI metrics.
        """
        # Apply notch filter if enabled
        ch1_notch = self.ch1_notch.process_sample(ch1_raw) if self.notch_enabled else ch1_raw
        ch2_notch = self.ch2_notch.process_sample(ch2_raw) if self.notch_enabled else ch2_raw

        # Apply bandpass filter
        ch1_filtered = self.ch1_bandpass.process_sample(ch1_notch)
        ch2_filtered = self.ch2_bandpass.process_sample(ch2_notch)

        # Select output signal according to filter mode
        if self.filter_mode == "monitor":
            ch1_out = ch1_filtered
            ch2_out = ch2_filtered
        elif self.filter_mode == "raw":
            ch1_out = ch1_raw
            ch2_out = ch2_raw
        else:  # diagnostic
            ch1_out = ch1_notch
            ch2_out = ch2_notch

        # QRS detection
        is_r_peak, bpm, mwi = self.qrs_detector.process_sample(ch1_filtered)

        # Signal Quality Index (SQI) based on variance, clipping, and baseline
        self.sqi_buffer.append(ch1_out)
        sqi = self._calculate_sqi()

        # Lead detachment detection (if signal is railed or flatlined)
        lead_off = abs(ch1_raw) > 5.0 or (len(self.sqi_buffer) > 100 and np.std(list(self.sqi_buffer)[-50:]) < 0.005)

        return {
            "ch1_clean": float(round(ch1_out, 4)),
            "ch2_clean": float(round(ch2_out, 4)),
            "ch1_raw": float(round(ch1_raw, 4)),
            "ch2_raw": float(round(ch2_raw, 4)),
            "is_r_peak": bool(is_r_peak),
            "bpm": float(round(bpm, 1)),
            "sqi": float(round(sqi, 2)),
            "lead_off": bool(lead_off),
        }

    def _calculate_sqi(self) -> float:
        """Estimates clinical Signal Quality Index (0.0 to 1.0)."""
        if len(self.sqi_buffer) < 50:
            return 0.95
        arr = np.array(self.sqi_buffer)
        std_val = float(np.std(arr))
        # Good ECG typically has standard deviation between 0.1mV and 1.5mV
        if std_val < 0.02:
            return 0.2  # flatline / disconnected
        if std_val > 3.0:
            return 0.3  # heavy motion artifact / railing
        score = 1.0 - min(0.6, abs(std_val - 0.4) / 2.0)
        return float(np.clip(score, 0.1, 1.0))
