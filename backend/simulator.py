"""
Clinical-Grade Dual-Channel ECG Simulator
=========================================
Generates synthetic 250 Hz ECG waveforms matching clinical Lead I and Lead II
morphology (P-Q-R-S-T waves), respiratory sinus arrhythmia, baseline wander,
and configurable cardiac conditions (Normal Sinus, Tachycardia, Bradycardia, PVC).
"""

import math
import random
import time
from typing import Dict, Tuple


class ECGWaveformGenerator:
    """
    Synthesizes physiological P-Q-R-S-T complexes using Gaussian functions.
    Lead I and Lead II are generated according to Einthoven's cardiac electrical axis.
    """

    def __init__(self, fs: float = 250.0):
        self.fs = fs
        self.dt = 1.0 / fs
        self.phase = 0.0  # Phase within cardiac cycle [0.0, 1.0)
        self.heart_rate_bpm = 72.0
        self.condition = "normal"  # "normal", "tachycardia", "bradycardia", "pvc", "noise"

        # Respiration modulation
        self.resp_phase = 0.0
        self.time_elapsed = 0.0

        # PVC state
        self.beat_count = 0
        self.is_pvc_beat = False

        # Battery & Lead Contact
        self.battery_pct = 94
        self.lead_status = {"RA": True, "LA": True, "LL": True, "RL": True, "V": True}

    def set_condition(self, condition: str):
        self.condition = condition.lower()
        if self.condition == "tachycardia":
            self.heart_rate_bpm = 125.0
        elif self.condition == "bradycardia":
            self.heart_rate_bpm = 48.0
        elif self.condition == "normal":
            self.heart_rate_bpm = 72.0
        elif self.condition == "pvc":
            self.heart_rate_bpm = 75.0

    def next_sample(self) -> Tuple[float, float, Dict[str, bool], int]:
        """
        Generates next sample pair (ch1_raw, ch2_raw, lead_status, battery).
        """
        self.time_elapsed += self.dt

        # Respiratory sinus arrhythmia: HR fluctuates slightly with breathing (0.2 Hz)
        self.resp_phase += 2.0 * math.pi * 0.25 * self.dt
        hr_variation = 3.5 * math.sin(self.resp_phase)
        effective_hr = self.heart_rate_bpm + hr_variation

        # Calculate phase increment for current heart rate
        cycle_duration = 60.0 / effective_hr
        phase_inc = self.dt / cycle_duration
        self.phase += phase_inc

        if self.phase >= 1.0:
            self.phase -= 1.0
            self.beat_count += 1
            # In PVC mode, trigger an abnormal ectopic beat every 5th beat
            if self.condition == "pvc" and (self.beat_count % 5 == 0):
                self.is_pvc_beat = True
            else:
                self.is_pvc_beat = False

        # Compute P-Q-R-S-T wave components
        p = self.phase
        if self.is_pvc_beat:
            # Wide, bizarre QRS without P wave, inverted T wave
            ch1_ecg = self._pvc_complex(p, gain=1.0)
            ch2_ecg = self._pvc_complex(p, gain=1.3)
        else:
            ch1_ecg = self._normal_complex(p, lead="I")
            ch2_ecg = self._normal_complex(p, lead="II")

        # Baseline wander (~0.15 Hz respiration & posture drift)
        baseline = 0.08 * math.sin(self.time_elapsed * 2.0 * math.pi * 0.15)

        # 50 Hz powerline mains hum (~0.015 mV)
        mains_noise = 0.012 * math.sin(self.time_elapsed * 2.0 * math.pi * 50.0)

        # Subtle physiological EMG / muscle noise
        muscle_noise = random.gauss(0, 0.008)

        if self.condition == "noise":
            # High noise / loose electrode
            muscle_noise = random.gauss(0, 0.4)
            baseline += 0.5 * math.sin(self.time_elapsed * 2.0 * math.pi * 1.5)
            self.lead_status["RA"] = random.random() > 0.15
        else:
            self.lead_status = {"RA": True, "LA": True, "LL": True, "RL": True, "V": True}

        ch1_total = ch1_ecg + baseline + mains_noise + muscle_noise
        ch2_total = ch2_ecg + (baseline * 1.1) + mains_noise + muscle_noise

        return ch1_total, ch2_total, self.lead_status, self.battery_pct

    def _normal_complex(self, p: float, lead: str = "I") -> float:
        """
        Generates standard clinical P-Q-R-S-T complex based on phase p in [0, 1).
        """
        # Peak centers and widths in phase space
        # P-wave: center 0.20, width 0.035
        # Q-wave: center 0.35, width 0.015
        # R-peak: center 0.38, width 0.018 (sharp)
        # S-wave: center 0.41, width 0.016
        # T-wave: center 0.65, width 0.070

        if lead == "I":
            amp_p = 0.12
            amp_q = -0.15
            amp_r = 1.05
            amp_s = -0.25
            amp_t = 0.28
        else:  # Lead II (typically higher R-wave amplitude)
            amp_p = 0.18
            amp_q = -0.12
            amp_r = 1.45
            amp_s = -0.30
            amp_t = 0.38

        # Gaussian components: a * exp(-((p - c) / w)^2)
        p_wave = amp_p * math.exp(-(((p - 0.20) / 0.035) ** 2))
        q_wave = amp_q * math.exp(-(((p - 0.35) / 0.014) ** 2))
        r_wave = amp_r * math.exp(-(((p - 0.38) / 0.016) ** 2))
        s_wave = amp_s * math.exp(-(((p - 0.41) / 0.015) ** 2))
        t_wave = amp_t * math.exp(-(((p - 0.65) / 0.065) ** 2))

        return p_wave + q_wave + r_wave + s_wave + t_wave

    def _pvc_complex(self, p: float, gain: float = 1.0) -> float:
        """
        Generates premature ventricular contraction (wide QRS, discordant T-wave).
        """
        # Premature early onset (around phase 0.30)
        # Wide, deep and tall complex
        r_pvc = 1.8 * gain * math.exp(-(((p - 0.30) / 0.045) ** 2))
        s_pvc = -1.2 * gain * math.exp(-(((p - 0.37) / 0.040) ** 2))
        t_inverted = -0.45 * gain * math.exp(-(((p - 0.55) / 0.08) ** 2))
        return r_pvc + s_pvc + t_inverted
