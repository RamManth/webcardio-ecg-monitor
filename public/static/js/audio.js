/**
 * Web Audio API Pulse Beep Synthesizer
 * =====================================
 * Generates authentic medical monitor QRS pulse beeps.
 */

class AudioPulseSynthesizer {
  constructor() {
    this.audioCtx = null;
    this.isMuted = false;
    this.baseFreq = 880.0; // A5 tone standard in clinical monitors
  }

  initContext() {
    if (!this.audioCtx) {
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (AudioContextClass) {
        this.audioCtx = new AudioContextClass();
      }
    }
    if (this.audioCtx && this.audioCtx.state === 'suspended') {
      this.audioCtx.resume();
    }
  }

  toggleMute() {
    this.isMuted = !this.isMuted;
    return this.isMuted;
  }

  playQRSBeep(bpm = 72) {
    if (this.isMuted) return;
    this.initContext();
    if (!this.audioCtx) return;

    try {
      const now = this.audioCtx.currentTime;
      const osc = this.audioCtx.createOscillator();
      const gain = this.audioCtx.createGain();

      // Pitch modulates slightly based on heart rate:
      // Higher heart rate -> slightly higher pitch
      const freq = this.baseFreq + Math.max(-100, Math.min(200, (bpm - 70) * 2));
      osc.type = 'sine';
      osc.frequency.setValueAtTime(freq, now);
      osc.frequency.exponentialRampToValueAtTime(freq * 0.85, now + 0.08);

      // Fast attack, exponential decay (clinical pulse 'pip')
      gain.gain.setValueAtTime(0.001, now);
      gain.gain.linearRampToValueAtTime(0.18, now + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.08);

      osc.connect(gain);
      gain.connect(this.audioCtx.destination);

      osc.start(now);
      osc.stop(now + 0.085);
    } catch (e) {
      console.warn('Audio play error:', e);
    }
  }
}
