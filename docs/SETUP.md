# 🛠️ EcoSort AI — Full Setup Guide (laptop → real robot)

This walks you through everything, in order, from a blank SD card to a working
robot you watch from your laptop.

There are **two tracks**. Do Track A now (today, no hardware). Do Track B when
you have the Pi and parts.

---

## Track A — Run it on your laptop (do this first)

You already did most of this. For reference:

1. **Install Python 3.10+** (you have 3.11 ✅).
2. **Install dependencies** — in the project folder:
   ```
   pip install -r requirements.txt
   ```
3. **Run it**:
   ```
   python -m backend.main
   ```
4. **Open the dashboard**: `http://localhost:8000`
5. Hold a **bottle** or **book** in front of your webcam — it detects and tilts.

That's the whole software loop working. Track B just moves it onto the Pi.

---

## Track B — Put it on the Raspberry Pi

### Step 1 — Flash the SD card with Raspberry Pi Imager

1. On Windows, download & install **Raspberry Pi Imager** from
   <https://www.raspberrypi.com/software/>.
2. Insert your microSD card (16 GB+).
3. Open Imager:
   - **Device:** Raspberry Pi 4
   - **OS:** Raspberry Pi OS (64-bit)
   - **Storage:** your SD card
4. Click **Next → Edit Settings** (the ⚙️ gear). This is the important part —
   set:
   - ✅ **Set hostname:** `ecosort`
   - ✅ **Enable SSH** → "Use password authentication"
   - ✅ **Set username and password** (remember these! e.g. user `pi`)
   - ✅ **Configure wireless LAN:** your WiFi name + password + country
   - ✅ **Set locale / timezone**
5. **Save → Write.** Wait for it to finish, then put the card in the Pi.

> Why the gear settings matter: they let the Pi boot straight onto your WiFi
> with SSH on, so you control it from your laptop with **no monitor or keyboard**.

### Step 2 — Boot the Pi and connect to it

1. Put the SD card in the Pi, plug in power. Wait ~1 minute for first boot.
2. From your laptop (same WiFi), open a terminal (PowerShell) and connect:
   ```
   ssh pi@ecosort.local
   ```
   (use the username you set; if `ecosort.local` doesn't resolve, find the Pi's
   IP from your router and use `ssh pi@192.168.x.x`)
3. Type `yes` to trust it, then enter your password. You're now "inside" the Pi.

### Step 3 — Get the project onto the Pi

**Option A — git clone** (if your code is on GitHub):
```
git clone <your-repo-url> ~/ecosort-ai
cd ~/ecosort-ai
```

**Option B — copy from your laptop** (run this on the *laptop*, not the Pi):
```
scp -r "d:\Inha university\Semester 5\Vertically Integrated theory\VIP project" pi@ecosort.local:~/ecosort-ai
```

Either way the project ends up at `~/ecosort-ai` on the Pi.

### Step 4 — Run the setup script

On the Pi:
```
cd ~/ecosort-ai
bash scripts/setup_pi.sh
```
This installs the camera library, GPIO library, and all Python packages.
**It takes 10–30 minutes** (PyTorch is large) — let it finish.

### Step 5 — Wire the hardware

Power **off** the Pi before wiring (`sudo shutdown -h now`, then unplug).

**Pi Camera:** lift the black clip on the Pi's **CAMERA** port, slide the
ribbon cable in (metal contacts facing the right way — see the Pi's manual),
push the clip back down.

**Servo** (default = wired straight to the Pi):

| Servo wire | Connect to |
|---|---|
| Signal (orange/white) | Pi **GPIO17** (physical pin 11) |
| Power V+ (red) | **+5V of a separate battery/supply** — *not* the Pi |
| Ground (brown/black) | Battery GND **and** a Pi GND pin (shared ground!) |

**Ultrasonic sensor HC-SR04** (optional — skip if you don't have one):

| HC-SR04 pin | Connect to |
|---|---|
| VCC | Pi 5V |
| GND | Pi GND |
| TRIG | Pi GPIO23 (pin 16) |
| ECHO | Pi GPIO24 (pin 18) **through a voltage divider** (2 kΩ + 1 kΩ) |

> ⚠️ Never power the servo from the Pi's 5V pin — it draws too much current and
> will crash the Pi. Use a separate 5V supply and **join the grounds**.

### Step 6 — First real run

Power the Pi back on, SSH in, then:
```
cd ~/ecosort-ai
source .venv/bin/activate
python -m backend.main
```
Watch the log — it should say:
```
Camera ready (picamera2 backend).
YOLO model loaded: yolov8n.pt
Backends -> {'camera': 'picamera2', 'servo': 'gpio', ...}
```
If it says `simulation` instead of `picamera2`/`gpio`, the library or wiring
isn't right — check Step 5 and re-run `setup_pi.sh`.

### Step 7 — Watch it from your laptop

Find the Pi's IP:
```
hostname -I
```
On your **laptop**, open a browser at `http://<that-ip>:8000`.
You'll see the live camera feed, detections, the platform tilting, and the log.

### Step 8 — Make it auto-start (optional but recommended)

So the robot launches itself on power-up, no laptop needed:
```
sudo cp scripts/ecosort.service /etc/systemd/system/ecosort.service
sudo systemctl daemon-reload
sudo systemctl enable ecosort.service
sudo systemctl start ecosort.service
```
(First edit `scripts/ecosort.service` if your username/path differ from
`pi` / `/home/pi/ecosort-ai`.)

Check it / see logs:
```
systemctl status ecosort.service
journalctl -u ecosort.service -f
```

---

## Building the physical robot

The software doesn't care what the body is made of — cardboard, 3D-printed,
acrylic, or wood. The layout that makes detection + sorting reliable:

```
        ┌───────────────────────────────┐
        │  TOP LID — Pi Camera looks ↓   │   camera fixed, pointing straight
        │  + an LED for steady light     │   down at the platform
        ├───────────────────────────────┤
        │  drop the trash item here ↓    │
        │  ═══ TILTING PLATFORM ═══      │   servo at the pivot tilts it
        │           ╱▲╲                  │   ~20° left or right
        │  ┌──────┐    ┌──────┐          │
        │  │PLASTIC│   │ PAPER │         │   two bins under the edges
        │  └──────┘    └──────┘          │
        ├───────────────────────────────┤
        │  BASE: Raspberry Pi, wiring,   │
        │  separate 5V supply for servo  │
        └───────────────────────────────┘
```

Tips for good detection:
- Camera **fixed and pointing straight down** at the platform.
- **Even lighting** (the LED) — YOLO is much more accurate with steady light.
- **Plain platform surface** (white or black) so the item stands out.
- Tilt angle big enough that the item **slides off by gravity** (~20°).

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Log says `camera: simulation` on the Pi | `python3-picamera2` not installed, or ribbon cable loose. Re-run setup, reseat cable. |
| Log says `servo: simulation` on the Pi | `gpiozero`/`lgpio` missing, or run without permission. Re-run setup. |
| Servo tilts the wrong way | Swap the signs of `SERVO_TILT_LEFT` / `SERVO_TILT_RIGHT` in `config.yaml`. |
| Dashboard won't open from the laptop | Pi and laptop must be on the **same WiFi**; check the IP from `hostname -I`. |
| Detection is jumpy / wrong | Improve lighting; raise/lower `CONFIDENCE_THRESHOLD` in `config.yaml`. |
| `python -m backend.main` not found | You forgot `source .venv/bin/activate` first. |
