# WebCardio WC1340 Wi-Fi Pairing & Hardware Connection Guide

This guide walks you through connecting your physical **WebCardio Wearable Biosensor (WC1340)** to your Mac, phone, or laptop so you can stream live ECG data into the web dashboard.

---

## 1. Hardware Overview

- **Model**: WebCardio Wearable Biosensor (REF: `WC1340`, PN: `1000001694B`)
- **Technology Platform**: LifeSignals Multi-Parameter Biosensor SoC (802.11b Wi-Fi client)
- **Electrodes**: 5 contact points (Lead I, Lead II, Reference RL, RA, LA, LL, V)
- **Bar-code DataMatrix ID**: `WC134000000T0010PHNTCMSEN2026050820270608M`
- **Device Prefix**: `CMSEN`

---

## 2. How the Sensor Connects Over Wi-Fi

The WebCardio / LifeSignals biosensor contains an embedded 802.11b Wi-Fi radio configured to automatically seek and join a dedicated 2.4 GHz Wi-Fi hotspot hosted by the receiver relay (phone or laptop).

### Official Pre-Configured Credentials:
| Setting | Recommended Value | Alternate / Fallback |
| :--- | :--- | :--- |
| **Hotspot SSID** | `CMSEN` | `WC1340` or full barcode ID |
| **Hotspot Security** | WPA2-Personal (PSK) | WPA2-PSK (AES/CCMP) |
| **Hotspot Password** | `copernicus` | (Documented standard key) |
| **Wi-Fi Band** | **2.4 GHz Only** | (Sensor does **not** support 5 GHz) |

---

## 3. Step-by-Step Setup

### Step A: Set up the 2.4 GHz Hotspot

#### Option 1: On macOS (Internet Sharing / Personal Hotspot)
1. Go to **System Settings** &rarr; **General** &rarr; **Sharing**.
2. If using iPhone Personal Hotspot or Android Hotspot, ensure **"Maximize Compatibility"** (iOS) or **"2.4 GHz Band"** (Android) is **enabled**.
3. Set your Hotspot name (SSID) to:
   ```
   CMSEN
   ```
4. Set the Password to:
   ```
   copernicus
   ```

#### Option 2: On iPhone / Android Phone
1. Open **Personal Hotspot** settings.
2. Turn on **Maximize Compatibility** (forces 2.4 GHz).
3. Set Hotspot Name to `CMSEN` and Password to `copernicus`.
4. Connect your laptop to this same phone hotspot so both your laptop and the sensor are on the identical subnet (e.g. `172.20.10.x`).

---

### Step B: Power On the Biosensor
1. Press and hold the power button on the front center of the patch (marked with the power icon).
2. The LED will illuminate or begin a slow blink indicating searching/joining mode.
3. Within 5–15 seconds, the patch joins the hotspot.

---

### Step C: Launch the ECG Monitor
1. In your terminal, run:
   ```bash
   ./run.sh
   ```
   Or:
   ```bash
   source .venv/bin/activate
   uvicorn backend.server:app --host 0.0.0.0 --port 8000
   ```
2. Open your browser to:
   ```
   http://localhost:8000
   ```
3. The server automatically listens on:
   - **TCP port 5000**
   - **UDP ports 5000 & 9000**
4. When the sensor sends raw packets, the monitor automatically switches from **Simulator** to **Live Hardware**!

---

### Step D: Discovering the Sensor IP & Port
If your sensor is on the network and you want to discover its IP address:
1. Click the **"Wi-Fi & Pairing Setup"** button in the top navigation bar of the web dashboard.
2. Click **"Scan Local Subnet"**.
3. The system scans the ARP cache and probes candidate ports (5000, 8080, 8000, 9000).
4. When your sensor appears, click **"Connect"** or enter its IP address directly into the connection box.

---

## 4. Packet & Protocol Details

- **Header Framing**:
  - Byte 0: `Length` ($L = \text{payload} + 2$)
  - Byte 1: `~Length & 0xFF` (Ones' complement verification)
- **Data Payload**:
  - Sampling Rate: **244.14 Hz / 250 Hz**
  - Resolution: 16-bit signed integer (ADC scale: ~1.0 µV/LSB)
  - 2 Channels: Channel 1 (Lead I), Channel 2 (Lead II)
  - Lead contact byte (checks 5 electrodes: RA, LA, LL, RL, V)
- **Footer**:
  - 16-bit CRC-CCITT (`0x1021`)
