/**
 * High-Performance Medical Oscilloscope Canvas Renderer
 * =====================================================
 * Implements standard hospital monitor sweep-bar rendering using a high-speed
 * circular buffer. Eliminates sub-rectangle slicing errors and guarantees smooth
 * 60 FPS phosphor ECG traces with a moving erase gap and glowing sweep cursor.
 */

class ECGCanvas {
  constructor(canvasId, options = {}) {
    this.canvas = document.getElementById(canvasId);
    if (!this.canvas) {
      throw new Error(`Canvas with ID ${canvasId} not found`);
    }
    this.ctx = this.canvas.getContext('2d');

    // Colors & Styling
    this.traceColor = options.traceColor || '#00ff88';
    this.glowColor = options.glowColor || 'rgba(0, 255, 136, 0.5)';
    this.fs = options.fs || 250.0;

    // Calibration: pixels per mm and standard ECG scales
    // Standard ECG: 25 mm/sec speed, 10 mm/mV amplitude
    this.pixelsPerMm = 4.0;
    this.gainScale = 1.0;
    this.sweepSpeed = 25.0;

    // Offscreen background grid
    this.gridCanvas = document.createElement('canvas');
    this.gridCtx = this.gridCanvas.getContext('2d');

    // Dimensions
    this.setupDimensions();
    this.renderGrid();

    // Circular waveform buffer across screen width
    this.bufferSize = Math.max(800, Math.floor(this.width));
    this.points = new Float32Array(this.bufferSize).fill(this.centerY);
    this.hasData = new Uint8Array(this.bufferSize).fill(0);

    this.cursorX = 0;
    this.eraseGap = 40; // 40-pixel dark erase gap ahead of the sweep cursor

    // Incoming sample queue
    this.sampleQueue = [];
    this.isRunning = true;

    window.addEventListener('resize', () => {
      this.setupDimensions();
      this.renderGrid();
    });

    // Start render loop
    requestAnimationFrame(() => this.renderLoop());
  }

  setupDimensions() {
    const dpr = window.devicePixelRatio || 1;
    const rect = this.canvas.getBoundingClientRect();
    const w = Math.floor(rect.width) || 1200;
    const h = Math.floor(rect.height) || 260;

    this.dpr = dpr;
    this.width = w;
    this.height = h;
    this.centerY = h / 2.0;

    this.canvas.width = Math.floor(w * dpr);
    this.canvas.height = Math.floor(h * dpr);

    if (this.ctx.resetTransform) {
      this.ctx.resetTransform();
    }
    this.ctx.scale(dpr, dpr);

    // Resize circular buffer if needed
    if (this.bufferSize !== w) {
      this.bufferSize = w;
      this.points = new Float32Array(this.bufferSize).fill(this.centerY);
      this.hasData = new Uint8Array(this.bufferSize).fill(0);
      this.cursorX = 0;
    }
  }

  renderGrid() {
    this.gridCanvas.width = this.width;
    this.gridCanvas.height = this.height;
    const g = this.gridCtx;

    // Dark charcoal background
    g.fillStyle = '#080d14';
    g.fillRect(0, 0, this.width, this.height);

    const mm = this.pixelsPerMm; // 4px = 1mm
    const majorBox = mm * 5; // 20px = 5mm

    // Minor grid (1mm)
    g.beginPath();
    g.strokeStyle = 'rgba(0, 229, 255, 0.05)';
    g.lineWidth = 0.5;
    for (let x = 0; x < this.width; x += mm) {
      g.moveTo(x, 0);
      g.lineTo(x, this.height);
    }
    for (let y = 0; y < this.height; y += mm) {
      g.moveTo(0, y);
      g.lineTo(this.width, y);
    }
    g.stroke();

    // Major grid (5mm)
    g.beginPath();
    g.strokeStyle = 'rgba(0, 229, 255, 0.16)';
    g.lineWidth = 1.0;
    for (let x = 0; x < this.width; x += majorBox) {
      g.moveTo(x, 0);
      g.lineTo(x, this.height);
    }
    for (let y = 0; y < this.height; y += majorBox) {
      g.moveTo(0, y);
      g.lineTo(this.width, y);
    }
    g.stroke();

    // Isoelectric baseline (center horizontal line)
    g.beginPath();
    g.strokeStyle = 'rgba(0, 229, 255, 0.28)';
    g.lineWidth = 1.0;
    g.setLineDash([4, 4]);
    g.moveTo(0, this.centerY);
    g.lineTo(this.width, this.centerY);
    g.stroke();
    g.setLineDash([]);
  }

  setGain(gain) {
    this.gainScale = gain;
  }

  setSweepSpeed(speed) {
    this.sweepSpeed = speed;
  }

  pushSample(sampleMv) {
    this.sampleQueue.push(sampleMv);
  }

  renderLoop() {
    if (!this.isRunning) return;

    // 1. Ingest pending samples into circular buffer
    if (this.sampleQueue.length > 0) {
      const pxPerSec = this.sweepSpeed * this.pixelsPerMm; // e.g. 25 * 4 = 100 px/sec
      const dxPerSample = pxPerSec / this.fs; // e.g. 0.4 px/sample
      const pxPerMv = 10.0 * this.pixelsPerMm * this.gainScale; // 40 px/mV

      while (this.sampleQueue.length > 0) {
        const sampleMv = this.sampleQueue.shift();
        const targetY = this.centerY - (sampleMv * pxPerMv);
        const clampedY = Math.max(6, Math.min(this.height - 6, targetY));

        const prevCursorX = this.cursorX;
        this.cursorX += dxPerSample;

        if (this.cursorX >= this.bufferSize) {
          this.cursorX = 0;
        }

        // Fill buffer slots traversed
        const startIdx = Math.floor(prevCursorX);
        const endIdx = Math.floor(this.cursorX);

        if (endIdx >= startIdx) {
          for (let idx = startIdx; idx <= endIdx && idx < this.bufferSize; idx++) {
            this.points[idx] = clampedY;
            this.hasData[idx] = 1;
          }
        } else {
          // Wrapped around 0
          for (let idx = startIdx; idx < this.bufferSize; idx++) {
            this.points[idx] = clampedY;
            this.hasData[idx] = 1;
          }
          for (let idx = 0; idx <= endIdx; idx++) {
            this.points[idx] = clampedY;
            this.hasData[idx] = 1;
          }
        }
      }
    }

    // 2. Clear canvas with pre-rendered grid background
    const ctx = this.ctx;
    ctx.drawImage(this.gridCanvas, 0, 0);

    const currentX = Math.floor(this.cursorX);
    const gap = this.eraseGap;
    const totalW = this.bufferSize;

    // 3. Draw authentic hospital monitor waveform in two segments:
    // Segment A: Older signal ahead of erase gap [currentX + gap -> totalW]
    // Segment B: Fresh signal behind cursor [0 -> currentX]

    ctx.save();
    ctx.lineWidth = 2.4;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.strokeStyle = this.traceColor;
    ctx.shadowColor = this.glowColor;
    ctx.shadowBlur = 6;

    // Segment A: Old data (past the erase gap)
    const segAStart = (currentX + gap) % totalW;
    if (segAStart > currentX) {
      ctx.beginPath();
      let started = false;
      for (let x = segAStart; x < totalW; x++) {
        if (this.hasData[x]) {
          if (!started) {
            ctx.moveTo(x, this.points[x]);
            started = true;
          } else {
            ctx.lineTo(x, this.points[x]);
          }
        }
      }
      ctx.stroke();
    }

    // Segment B: Fresh data up to cursor
    ctx.beginPath();
    let startedB = false;
    for (let x = 0; x <= currentX; x++) {
      if (this.hasData[x]) {
        if (!startedB) {
          ctx.moveTo(x, this.points[x]);
          startedB = true;
        } else {
          ctx.lineTo(x, this.points[x]);
        }
      }
    }
    ctx.stroke();

    // 4. Draw glowing vertical sweep cursor line
    ctx.restore();
    ctx.save();
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 1.5;
    ctx.shadowColor = this.glowColor;
    ctx.shadowBlur = 8;
    ctx.beginPath();
    ctx.moveTo(currentX, 0);
    ctx.lineTo(currentX, this.height);
    ctx.stroke();
    ctx.restore();

    requestAnimationFrame(() => this.renderLoop());
  }
}
