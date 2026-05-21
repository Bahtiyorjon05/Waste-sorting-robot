# 🌿 EcoSort AI — Intelligent Waste Classification System

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-async-00a393)
![YOLOv8](https://img.shields.io/badge/YOLO-v8-yellow)
![Hardware](https://img.shields.io/badge/Hardware-Raspberry_Pi_4-red)
![Status](https://img.shields.io/badge/Status-VIP_Capstone-brightgreen)

**EcoSort AI** is an edge-computing waste sorter built for the Vertically
Integrated Project (VIP) at Inha University. A camera watches a platform, an
on-device YOLOv8 model classifies the item as **PLASTIC** or **PAPER**, and a
single servo **tilts the platform left or right** to drop the item into the
correct bin.

The whole system runs on the Raspberry Pi. **You watch everything live from
your laptop's browser** — camera feed, detections, the tilt action, and a
running log — over WiFi.

---

## ♻️ How the sorting works

```
                   ┌──────────────────┐
                   │   YOLOv8 says:   │
                   │  PLASTIC / PAPER │
                   └────────┬─────────┘
                            │
        PLASTIC ◄───────────┴───────────► PAPER
                            │
              ┌─────────────┴─────────────┐
   tilt LEFT  │  ====== platform ======   │  tilt RIGHT
  (servo -0.8)│            ▲              │ (servo +0.8)
              │          pivot            │
              └───────────────────────────┘
   item slides into             item slides into
   the PLASTIC bin              the PAPER bin
              ↓ after 2 s the platform returns FLAT (0.0) ↓
```

One servo, three positions: **FLAT → TILT LEFT → FLAT** or **FLAT → TILT RIGHT
→ FLAT**. Gravity does the rest.

---

## 🖥️ Seeing the flow on your laptop

> The Raspberry Pi Camera's ribbon cable plugs **only into the Pi** — it cannot
> plug into a laptop. So the Pi runs everything and serves a web dashboard;
> your laptop is just the screen.

1. Wire the camera + servo to the Pi, power it on, connect Pi and laptop to the
   **same WiFi**.
2. On the Pi, start the system (see [Running it](#-running-it)).
3. On the Pi, find its IP address: `hostname -I` → e.g. `192.168.1.42`.
4. On your **laptop**, open a browser at **`http://192.168.1.42:8000`**.

You'll see the live camera feed with detection boxes, the platform tilting in
real time, bin status, session totals, a scrolling sort log, and 👍/👎 buttons.

---

## 🏗️ Architecture

Four decoupled modules, orchestrated by the backend in one process on the Pi:

| Module        | Role          | Key files |
|---------------|---------------|-----------|
| `edge_ai/`    | **The Eyes**  | `vision_agent.py` — camera capture + YOLOv8 inference |
| `hardware/`   | **The Muscle**| `servo_controller.py` — single tilting servo · `sensor_read.py` — bin sensor |
| `backend/`    | **The Brain** | `main.py` (FastAPI) · `orchestrator.py` (Sense-Think-Act loop) · SQLite logging |
| `ui/`         | **The Window**| `index.html` — the live dashboard you open on the laptop |

```
ecosort-ai/
├── backend/
│   ├── main.py            # FastAPI app — entry point, serves the dashboard
│   ├── orchestrator.py    # the Sense-Think-Act loop (background thread)
│   ├── state.py           # thread-safe live state shared with the dashboard
│   ├── config.py          # config.yaml loader + live hot-reload
│   ├── database.py        # SQLite (SQLAlchemy)
│   ├── models.py          # database schema: SortEvent
│   └── routers/
│       ├── classify.py    # /api/status, /api/stream (video), /api/events
│       └── feedback.py    # /api/feedback  (👍 / 👎)
├── edge_ai/
│   ├── vision_agent.py    # picamera2 / USB / simulation capture + YOLO
│   └── weights/           # put yolov8n_waste.pt here
├── hardware/
│   ├── servo_controller.py  # tilting servo: gpio / arduino / simulation
│   ├── sensor_read.py       # HC-SR04 ultrasonic bin-full sensor
│   └── arduino/ecosort_servo.ino   # optional Arduino firmware
├── ui/
│   └── index.html         # self-contained live dashboard (no internet needed)
├── config.yaml
├── requirements.txt       # core deps (laptop + Pi)
└── requirements-pi.txt    # Raspberry Pi hardware deps
```

### Pluggable backends — same code on laptop and Pi

Every hardware module has three backends, picked in `config.yaml`. With `auto`
the system uses the real hardware if its library is installed, otherwise it
falls back to **simulation**. That is why the *exact same code* runs:

| Backend  | On your laptop (dev)        | On the Raspberry Pi (real)       |
|----------|-----------------------------|----------------------------------|
| Camera   | `simulation` or USB webcam  | `picamera2` (Pi Camera V2)       |
| Servo    | `simulation` (logs only)    | `gpio` (or `arduino` over USB)   |
| Sensor   | `simulation`                | `gpio` (HC-SR04)                 |
| Model    | simulated detections        | real `yolov8n_waste.pt`          |

So you can build and demo the **entire dashboard on your laptop today**, with
synthetic camera frames, before the hardware is even wired.

---

## 🔌 Hardware

- **Compute:** Raspberry Pi 4
- **Camera:** Raspberry Pi Camera V2 (CSI ribbon cable)
- **Actuation:** one MG996R / SG90 servo (tilts the platform)
- **Bin sensor:** HC-SR04 ultrasonic (optional — pauses sorting when bin full)
- **Power:** dedicated 5V supply for the servo — **do not** power the servo
  from the Pi's 5V pin
- **Optional:** Arduino, if you'd rather drive the servo from it instead of
  the Pi's GPIO (see [Arduino option](#-optional-arduino-for-the-servo))

### Wiring (servo on the Pi's GPIO — the default)

```
Raspberry Pi 4                         Dedicated 5V supply
--------------------------             -------------------
Pi Camera CSI port ──── Pi Camera V2
GPIO17 (pin 11) ─────── Servo signal
GND ─────────────────── Servo GND ──── GND  (common ground!)
                        Servo V+  ──── +5V
GPIO23 (pin 16) ─────── HC-SR04 TRIG
GPIO24 (pin 18) ◄─[2kΩ]─┬─ HC-SR04 ECHO   (voltage divider: 5V → 3.3V)
                       [1kΩ]
                        └─ GND
HC-SR04 VCC ─────────── Pi 5V
```

> ⚠️ Always share a **common ground** between the Pi and the 5V servo supply.

---

## 📦 Installation

### On your laptop (development / simulation)

```bash
pip install -r requirements.txt
```

All of these install fine on Windows. The hardware libraries are *not* needed —
the app auto-detects they're missing and runs in simulation.

With `ultralytics` installed and `MODEL_PATH: "yolov8n.pt"` (the default), the
standard YOLOv8 model auto-downloads on first run and your **webcam detects
real objects immediately** — hold a bottle (→ PLASTIC) or a book (→ PAPER).
No training required to test the full flow.

### On the Raspberry Pi

```bash
# Pi Camera library is best installed via apt:
sudo apt update
sudo apt install -y python3-picamera2 python3-libcamera

pip install -r requirements.txt
pip install -r requirements-pi.txt
```

For the real waste model, train a YOLOv8 model on plastic/paper images, save it
as `edge_ai/weights/yolov8n_waste.pt`, point `MODEL_PATH` at it, and set
`CLASS_MAP` to its class names. Until then, `yolov8n.pt` (the default) gives you
real detection of everyday objects to demo the full pipeline.

---

## ▶️ Running it

From the repository root:

```bash
python -m backend.main
```

Then open the dashboard:

- **Laptop dev:** `http://localhost:8000`
- **Watching the Pi from your laptop:** `http://<raspberry-pi-ip>:8000`

Stop with `Ctrl+C`.

---

## ⚙️ Configuration (`config.yaml`)

Key settings:

| Setting | Meaning |
|---|---|
| `CAMERA_BACKEND` | `auto` · `picamera2` · `opencv` · `simulation` |
| `SERVO_BACKEND`  | `auto` · `gpio` · `arduino` · `simulation` |
| `SENSOR_BACKEND` | `auto` · `gpio` · `simulation` |
| `MODEL_PATH`     | path to your YOLOv8 `.pt` file |
| `SERVO_TILT_LEFT` / `SERVO_TILT_RIGHT` | tilt amounts (gpiozero values, −1…1) |
| `SERVO_HOLD_SEC` | how long the platform stays tilted before resetting |
| `BIN_FULL_THRESHOLD_CM` | distance below which the bin counts as full |
| `WEB_PORT`       | dashboard port (default `8000`) |

A few keys (the `SIMULATED_*` ones, `CONFIDENCE_THRESHOLD`, `SERVO_HOLD_SEC`)
**hot-reload** — edit `config.yaml` while the system runs and the change takes
effect within ~2 seconds. Great for live demos.

### Demo without hardware

In `config.yaml` set everything to simulation and run:

```yaml
CAMERA_BACKEND: "simulation"
SERVO_BACKEND:  "simulation"
SENSOR_BACKEND: "simulation"
SIMULATED_DETECTION_LABEL: ""        # "" = alternate PLASTIC / PAPER
SIMULATED_BIN_DISTANCE_CM: 30.0      # set < 8.0 to test the bin-full pause
```

---

## 🔁 The flow

1. **SENSE** — `vision_agent.py` grabs a frame; `sensor_read.py` checks the bin.
2. **THINK** — YOLOv8 classifies the item → `{label, confidence}`.
3. **ACT** — `orchestrator.py` tells `servo_controller.py` to tilt:
   PLASTIC → **left**, PAPER → **right**; hold ~2 s; return flat.
4. **LOG** — the sort is written to SQLite and pushed to the dashboard.
5. **LEARN** — on the dashboard you tap 👍 / 👎. A 👎 saves that frame to
   `edge_ai/feedback_images/` so the dataset grows for the next retraining round.

The system never sorts the same item twice — after a tilt it waits until the
platform is seen empty again before arming the next sort.

---

## 🤖 Optional: Arduino for the servo

If you'd rather drive the servo from an Arduino than the Pi's GPIO:

1. Flash `hardware/arduino/ecosort_servo.ino` to the Arduino.
2. Connect the Arduino to the Pi by USB.
3. In `config.yaml` set `SERVO_BACKEND: "arduino"` and `ARDUINO_PORT` to the
   right port (`/dev/ttyUSB0` on Linux, `COM3`-style on Windows).

The Pi then sends `L` / `R` / `F` characters over serial and the Arduino tilts.

---

*Architected for the VIP Capstone — Inha University.*
*Beyond the engineering, EcoSort AI reflects **Taharah** (cleanliness) and our
role as **Khalifa** — stewards of the Earth.*
