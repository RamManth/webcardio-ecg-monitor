/**
 * WebCardio WC1340 Studio Application Controller
 * ===============================================
 * Connects to the backend WebSocket stream when available, with an automatic
 * client-side clinical simulator fallback for static/global hosting on Vercel.
 */

document.addEventListener('DOMContentLoaded', () => {
  // 1. Initialize Canvases
  const canvasCh1 = new ECGCanvas('ecg-canvas-ch1', {
    traceColor: '#00ff88',
    glowColor: 'rgba(0, 255, 136, 0.4)',
    fs: 250.0,
  });

  const canvasCh2 = new ECGCanvas('ecg-canvas-ch2', {
    traceColor: '#00e5ff',
    glowColor: 'rgba(0, 229, 255, 0.4)',
    fs: 250.0,
  });

  // 2. Audio Synthesizer
  const audio = new AudioPulseSynthesizer();

  // 3. UI Element References
  const connectionDot = document.getElementById('connection-dot');
  const connectionText = document.getElementById('connection-text');
  const hrValue = document.getElementById('hr-value');
  const heartWrapper = document.getElementById('heart-wrapper');
  const rrIntervalVal = document.getElementById('rr-interval-val');
  const rhythmVal = document.getElementById('rhythm-val');
  const sqiText = document.getElementById('sqi-text');
  const sqiBar = document.getElementById('sqi-bar');
  const batteryValue = document.getElementById('battery-value');
  const ch1PeakVal = document.getElementById('ch1-peak-val');
  const ch2PeakVal = document.getElementById('ch2-peak-val');

  // Mode buttons
  const btnModeSim = document.getElementById('btn-mode-sim');
  const btnModeLive = document.getElementById('btn-mode-live');
  const simConditionsCard = document.getElementById('sim-conditions-card');

  // Audio button
  const btnAudioToggle = document.getElementById('btn-audio-toggle');
  const iconSoundOn = document.getElementById('icon-sound-on');
  const iconSoundOff = document.getElementById('icon-sound-off');

  // Recording
  const btnRecordToggle = document.getElementById('btn-record-toggle');
  const recordBtnText = document.getElementById('record-btn-text');
  const recordIndicator = document.getElementById('record-indicator');
  const recordingTime = document.getElementById('recording-time');
  const btnExportCsv = document.getElementById('btn-export-csv');
  const btnExportJson = document.getElementById('btn-export-json');

  // Wi-Fi Modal
  const wifiModal = document.getElementById('wifi-modal');
  const btnWifiModal = document.getElementById('btn-wifi-modal');
  const btnCloseModal = document.getElementById('btn-close-modal');
  const btnModalDone = document.getElementById('btn-modal-done');
  const btnRunScan = document.getElementById('btn-run-scan');
  const scanResultsContainer = document.getElementById('scan-results-container');
  const copySsid = document.getElementById('copy-ssid');
  const copyPw = document.getElementById('copy-pw');
  const inputSensorIp = document.getElementById('input-sensor-ip');
  const inputSensorPort = document.getElementById('input-sensor-port');
  const btnDirectConnect = document.getElementById('btn-direct-connect');

  // State
  let ws = null;
  let isRecording = false;
  let recordTimerInterval = null;
  let recordSeconds = 0;
  let clientRecordingBuffer = [];
  let currentMode = 'simulator';
  let lastRhythm = 'normal';
  let isWsConnected = false;

  // 4. In-Browser Client-Side 250 Hz Clinical ECG Generator
  // (Ensures 100% standalone functionality on Vercel or when local backend is unreachable)
  class ClientECGSimulator {
    constructor() {
      this.fs = 250.0;
      this.dt = 1.0 / this.fs;
      this.phase = 0.0;
      this.bpm = 72.0;
      this.condition = 'normal';
      this.respPhase = 0.0;
      this.timeElapsed = 0.0;
      this.beatCount = 0;
      this.isPvc = false;
      this.timer = null;
      this.isRunning = false;
    }

    start() {
      if (this.isRunning) return;
      this.isRunning = true;
      let lastTime = performance.now();
      let accumulator = 0;

      const loop = (now) => {
        if (!this.isRunning) return;
        const delta = (now - lastTime) / 1000.0;
        lastTime = now;
        accumulator += Math.min(0.2, delta);

        const samples = [];
        let rPeakDetected = false;

        while (accumulator >= this.dt) {
          accumulator -= this.dt;
          this.timeElapsed += this.dt;

          // Respiratory modulation
          this.respPhase += 2.0 * Math.PI * 0.25 * this.dt;
          const hrVar = 3.5 * Math.sin(this.respPhase);
          const effectiveHr = this.bpm + hrVar;

          const cycleDuration = 60.0 / effectiveHr;
          this.phase += this.dt / cycleDuration;

          let isPeakSample = false;
          if (this.phase >= 1.0) {
            this.phase -= 1.0;
            this.beatCount++;
            this.isPvc = this.condition === 'pvc' && this.beatCount % 5 === 0;
          }

          const p = this.phase;
          // Check R-peak moment (~phase 0.38)
          if (p >= 0.37 && p <= 0.39 && !this.wasPeak) {
            isPeakSample = true;
            rPeakDetected = true;
            this.wasPeak = true;
          } else if (p < 0.35 || p > 0.42) {
            this.wasPeak = false;
          }

          let ch1 = 0;
          let ch2 = 0;
          if (this.isPvc) {
            ch1 = 1.8 * Math.exp(-Math.pow((p - 0.30) / 0.045, 2)) - 1.2 * Math.exp(-Math.pow((p - 0.37) / 0.04, 2));
            ch2 = ch1 * 1.3;
          } else {
            // Normal Gaussian components
            const pW = 0.12 * Math.exp(-Math.pow((p - 0.20) / 0.035, 2));
            const qW = -0.15 * Math.exp(-Math.pow((p - 0.35) / 0.014, 2));
            const rW = 1.05 * Math.exp(-Math.pow((p - 0.38) / 0.016, 2));
            const sW = -0.25 * Math.exp(-Math.pow((p - 0.41) / 0.015, 2));
            const tW = 0.28 * Math.exp(-Math.pow((p - 0.65) / 0.065, 2));
            ch1 = pW + qW + rW + sW + tW;

            const rW2 = 1.45 * Math.exp(-Math.pow((p - 0.38) / 0.016, 2));
            ch2 = (pW * 1.5) + qW + rW2 + sW + (tW * 1.35);
          }

          // Subtle baseline wander
          const baseline = 0.06 * Math.sin(this.timeElapsed * 2.0 * Math.PI * 0.15);
          ch1 += baseline;
          ch2 += baseline * 1.1;

          samples.push({
            ch1: Number(ch1.toFixed(3)),
            ch2: Number(ch2.toFixed(3)),
            r_peak: isPeakSample,
            t: Number(this.timeElapsed.toFixed(3)),
          });
        }

        if (samples.length > 0) {
          const telemetry = {
            bpm: this.bpm,
            sqi: 0.96,
            lead_off: false,
            lead_status: { RA: true, LA: true, LL: true, RL: true, V: true },
            battery: 94,
            mode: 'simulator',
            hardware_connected: false,
          };
          handleEcgBatch(samples, telemetry);
        }

        requestAnimationFrame(loop);
      };

      requestAnimationFrame(loop);
    }

    stop() {
      this.isRunning = false;
    }

    setCondition(condition) {
      this.condition = condition;
      if (condition === 'tachycardia') this.bpm = 125.0;
      else if (condition === 'bradycardia') this.bpm = 48.0;
      else if (condition === 'normal') this.bpm = 72.0;
      else if (condition === 'pvc') this.bpm = 75.0;
    }
  }

  const clientSim = new ClientECGSimulator();

  // 5. WebSocket Client Connection
  function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host || 'localhost:8000';
    const wsUrl = `${protocol}//${host}/ws/ecg`;

    try {
      ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        isWsConnected = true;
        clientSim.stop(); // Stop browser simulator when backend stream connects
        connectionDot.className = 'status-dot online';
        connectionText.textContent = currentMode === 'hardware' ? 'Hardware Connected' : 'Stream Active (Sim)';
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === 'ecg_batch') {
            handleEcgBatch(msg.samples, msg.telemetry);
          }
        } catch (e) {
          console.error('Error parsing WS message:', e);
        }
      };

      ws.onclose = () => {
        isWsConnected = false;
        connectionDot.className = 'status-dot online';
        connectionText.textContent = 'Global Demo (Active)';
        clientSim.start(); // Fallback to client-side simulator
        setTimeout(connectWebSocket, 4000);
      };

      ws.onerror = () => {
        isWsConnected = false;
        clientSim.start();
        ws.close();
      };
    } catch (e) {
      isWsConnected = false;
      clientSim.start();
    }
  }

  // 6. Handle Inbound Batch of ECG Telemetry
  function handleEcgBatch(samples, telemetry) {
    if (!samples || samples.length === 0) return;

    // Push waveform samples to oscilloscope canvases
    for (let i = 0; i < samples.length; i++) {
      const s = samples[i];
      canvasCh1.pushSample(s.ch1);
      canvasCh2.pushSample(s.ch2);

      if (isRecording) {
        clientRecordingBuffer.push(s);
      }

      // Trigger QRS R-peak pulse and audio beat
      if (s.r_peak) {
        triggerQRSBeat(telemetry.bpm);
      }
    }

    // Update Amplitude peaks
    const lastSample = samples[samples.length - 1];
    ch1PeakVal.textContent = `${lastSample.ch1 >= 0 ? '+' : ''}${lastSample.ch1.toFixed(2)} mV`;
    ch2PeakVal.textContent = `${lastSample.ch2 >= 0 ? '+' : ''}${lastSample.ch2.toFixed(2)} mV`;

    // Update Telemetry Vitals
    if (telemetry) {
      updateTelemetryVitals(telemetry);
    }
  }

  // 7. QRS Beat Flash & Audio Pip
  function triggerQRSBeat(bpm) {
    heartWrapper.classList.add('beat');
    setTimeout(() => heartWrapper.classList.remove('beat'), 120);
    audio.playQRSBeep(bpm || 72);
  }

  // 8. Update Telemetry Dashboard
  function updateTelemetryVitals(t) {
    if (t.lead_off) {
      hrValue.textContent = '--';
      rrIntervalVal.textContent = '--';
      rhythmVal.textContent = 'LEAD OFF';
      rhythmVal.className = 'metric-val text-alert';
    } else {
      hrValue.textContent = Math.round(t.bpm || 72);
      const rrMs = Math.round((60.0 / (t.bpm || 72)) * 1000);
      rrIntervalVal.textContent = `${rrMs} ms`;
      rhythmVal.textContent = getRhythmLabel(t.bpm);
      rhythmVal.className = 'metric-val text-accent';
    }

    const sqiVal = Math.round((t.sqi || 0.95) * 100);
    sqiBar.style.width = `${sqiVal}%`;
    if (sqiVal > 80) {
      sqiText.textContent = `${sqiVal}% (Optimal)`;
      sqiBar.style.background = 'linear-gradient(90deg, #ffb703, #00ff88)';
    } else if (sqiVal > 50) {
      sqiText.textContent = `${sqiVal}% (Fair)`;
      sqiBar.style.background = '#ffb703';
    } else {
      sqiText.textContent = `${sqiVal}% (Noisy)`;
      sqiBar.style.background = '#ff3366';
    }

    if (t.battery !== undefined && t.battery !== null) {
      batteryValue.textContent = `${t.battery}%`;
    }

    if (t.hardware_connected) {
      connectionDot.className = 'status-dot online';
      connectionText.textContent = 'Live WebCardio Sensor';
      btnModeLive.classList.add('active');
      btnModeSim.classList.remove('active');
    }

    if (t.lead_status) {
      updateElectrodePad('pad-ra', t.lead_status.RA);
      updateElectrodePad('pad-la', t.lead_status.LA);
      updateElectrodePad('pad-ll', t.lead_status.LL);
      updateElectrodePad('pad-rl', t.lead_status.RL);
      updateElectrodePad('pad-v', t.lead_status.V);
    }
  }

  function updateElectrodePad(id, isActive) {
    const el = document.getElementById(id);
    if (el) {
      if (isActive) {
        el.classList.add('active');
      } else {
        el.classList.remove('active');
      }
    }
  }

  function getRhythmLabel(bpm) {
    if (lastRhythm === 'pvc') return 'PVC Ectopy';
    if (bpm > 100) return 'Sinus Tachycardia';
    if (bpm < 60) return 'Sinus Bradycardia';
    return 'Normal Sinus';
  }

  // 9. Gain, Speed, & Filter Controls
  document.querySelectorAll('[data-gain]').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('[data-gain]').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      const gain = parseFloat(btn.dataset.gain);
      canvasCh1.setGain(gain);
      canvasCh2.setGain(gain);
    });
  });

  document.querySelectorAll('[data-speed]').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('[data-speed]').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      const speed = parseFloat(btn.dataset.speed);
      canvasCh1.setSweepSpeed(speed);
      canvasCh2.setSweepSpeed(speed);
    });
  });

  document.querySelectorAll('[data-filter]').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('[data-filter]').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      const filterMode = btn.dataset.filter;
      if (isWsConnected) {
        fetch('/api/filter', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ filter_mode: filterMode, notch_enabled: true }),
        }).catch(() => {});
      }
    });
  });

  const btnToggleNotch = document.getElementById('btn-toggle-notch');
  let notchActive = true;
  btnToggleNotch.addEventListener('click', () => {
    notchActive = !notchActive;
    btnToggleNotch.className = notchActive ? 'btn-pill-toggle active' : 'btn-pill-toggle off';
    btnToggleNotch.textContent = notchActive ? 'NOTCH ON' : 'NOTCH OFF';
    if (isWsConnected) {
      fetch('/api/filter', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filter_mode: 'monitor', notch_enabled: notchActive }),
      }).catch(() => {});
    }
  });

  // 10. Simulator Rhythm Selector
  document.querySelectorAll('[data-condition]').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('[data-condition]').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      const condition = btn.dataset.condition;
      lastRhythm = condition;
      clientSim.setCondition(condition);

      if (isWsConnected) {
        fetch('/api/mode', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mode: 'simulator', condition }),
        }).catch(() => {});
      }
    });
  });

  // Mode buttons
  btnModeSim.addEventListener('click', () => {
    btnModeSim.classList.add('active');
    btnModeLive.classList.remove('active');
    currentMode = 'simulator';
    simConditionsCard.classList.remove('hidden');
    connectionText.textContent = isWsConnected ? 'Stream Active (Sim)' : 'Global Demo (Active)';
    clientSim.setCondition(lastRhythm);
    if (!isWsConnected) clientSim.start();
    if (isWsConnected) {
      fetch('/api/mode', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: 'simulator', condition: lastRhythm }),
      }).catch(() => {});
    }
  });

  btnModeLive.addEventListener('click', () => {
    btnModeLive.classList.add('active');
    btnModeSim.classList.remove('active');
    currentMode = 'hardware';
    simConditionsCard.classList.add('hidden');
    connectionText.textContent = 'Listening for Sensor...';
    clientSim.stop();
    if (isWsConnected) {
      fetch('/api/mode', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: 'hardware' }),
      }).catch(() => {});
    }
  });

  // Audio Mute Toggle
  btnAudioToggle.addEventListener('click', () => {
    const isMuted = audio.toggleMute();
    if (isMuted) {
      iconSoundOn.classList.add('hidden');
      iconSoundOff.classList.remove('hidden');
    } else {
      iconSoundOn.classList.remove('hidden');
      iconSoundOff.classList.add('hidden');
      audio.initContext();
    }
  });

  // 11. Recording Flow (Client-side download guarantees functionality everywhere)
  btnRecordToggle.addEventListener('click', () => {
    if (!isRecording) {
      // Start Recording
      isRecording = true;
      recordSeconds = 0;
      clientRecordingBuffer = [];
      btnRecordToggle.classList.add('recording');
      recordBtnText.textContent = 'Stop Recording';
      btnExportCsv.disabled = true;
      btnExportJson.disabled = true;

      if (isWsConnected) {
        fetch('/api/record/start', { method: 'POST' }).catch(() => {});
      }

      recordTimerInterval = setInterval(() => {
        recordSeconds++;
        const mins = String(Math.floor(recordSeconds / 60)).padStart(2, '0');
        const secs = String(recordSeconds % 60).padStart(2, '0');
        recordingTime.textContent = `${mins}:${secs}`;
      }, 1000);
    } else {
      // Stop Recording
      isRecording = false;
      clearInterval(recordTimerInterval);
      btnRecordToggle.classList.remove('recording');
      recordBtnText.textContent = 'Start Recording';
      btnExportCsv.disabled = false;
      btnExportJson.disabled = false;

      if (isWsConnected) {
        fetch('/api/record/stop', { method: 'POST' }).catch(() => {});
      }
    }
  });

  btnExportCsv.addEventListener('click', () => {
    if (clientRecordingBuffer.length > 0) {
      let csv = 'timestamp,ch1_mv,ch2_mv,r_peak\n';
      clientRecordingBuffer.forEach((s) => {
        csv += `${s.t || 0},${s.ch1},${s.ch2},${s.r_peak ? 1 : 0}\n`;
      });
      const blob = new Blob([csv], { type: 'text/csv' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'webcardio_ecg_session.csv';
      a.click();
      URL.revokeObjectURL(url);
    } else {
      window.location.href = '/api/record/export?format=csv';
    }
  });

  btnExportJson.addEventListener('click', () => {
    if (clientRecordingBuffer.length > 0) {
      const blob = new Blob([JSON.stringify({ recording: clientRecordingBuffer }, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'webcardio_ecg_session.json';
      a.click();
      URL.revokeObjectURL(url);
    } else {
      window.location.href = '/api/record/export?format=json';
    }
  });

  // 12. Wi-Fi Modal & Discovery Assistant
  btnWifiModal.addEventListener('click', () => {
    wifiModal.classList.remove('hidden');
  });

  btnCloseModal.addEventListener('click', () => {
    wifiModal.classList.add('hidden');
  });

  btnModalDone.addEventListener('click', () => {
    wifiModal.classList.add('hidden');
  });

  function copyText(el, text) {
    navigator.clipboard.writeText(text).then(() => {
      const original = el.textContent;
      el.textContent = 'Copied!';
      setTimeout(() => (el.textContent = original), 1500);
    });
  }

  copySsid.addEventListener('click', () => copyText(copySsid, 'CMSEN'));
  copyPw.addEventListener('click', () => copyText(copyPw, 'copernicus'));

  btnRunScan.addEventListener('click', () => {
    scanResultsContainer.innerHTML = '<div class="scan-placeholder">Scanning local network and ARP table...</div>';
    fetch('/api/discover')
      .then((res) => res.json())
      .then((data) => {
        if (!data.devices || data.devices.length === 0) {
          scanResultsContainer.innerHTML = '<div class="scan-placeholder">No external devices detected on subnet yet. Ensure patch is turned on and connected.</div>';
          return;
        }

        let html = '';
        data.devices.forEach((dev) => {
          html += `
            <div class="scan-item">
              <div>
                <strong>${dev.ip}</strong> (${dev.mac})
                <div style="font-size:0.7rem; color:var(--text-muted);">${dev.vendor} &bull; ${dev.open_ports.length ? 'Open ports: ' + dev.open_ports.join(', ') : 'No open probed ports'}</div>
              </div>
              <button class="btn-primary" style="padding:4px 10px; font-size:0.7rem;" onclick="connectToIp('${dev.ip}')">Connect</button>
            </div>
          `;
        });
        scanResultsContainer.innerHTML = html;
      })
      .catch(() => {
        scanResultsContainer.innerHTML = '<div class="scan-placeholder">Backend discovery unavailable in cloud mode. Run locally with <code>./run.sh</code> to scan local Wi-Fi.</div>';
      });
  });

  window.connectToIp = function (ip) {
    fetch('/api/connect_device', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ip, port: 5000 }),
    })
      .then((r) => r.json())
      .then((res) => {
        if (res.status === 'connected') {
          alert(`Connected to sensor at ${ip}:5000!`);
          wifiModal.classList.add('hidden');
        } else {
          alert(`Connection attempt: ${res.message || 'Waiting for stream'}`);
        }
      })
      .catch((err) => {
        alert('Active connect requires local backend running.');
      });
  };

  btnDirectConnect.addEventListener('click', () => {
    const ip = inputSensorIp.value.trim();
    if (!ip) {
      alert('Please enter an IP address.');
      return;
    }
    window.connectToIp(ip);
  });

  // Start connection
  connectWebSocket();
});
