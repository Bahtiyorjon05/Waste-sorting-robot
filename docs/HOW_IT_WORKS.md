# 🧠 How the EcoSort AI Software Works

A plain-English tour of the code, for the VIP report and for anyone extending
it. Read this top to bottom — each section builds on the last.

---

## 1. The big idea

EcoSort AI is **one Python program** that repeats a 3-step cycle forever. This
cycle is called the **Sense–Think–Act loop**:

```
   ┌──────────────────────────────────────────────────┐
   │                                                  │
   │   SENSE  →  THINK  →  ACT  →  (repeat ~12×/sec)   │
   │                                                  │
   └──────────────────────────────────────────────────┘

   SENSE : take a photo with the camera, read the bin sensor
   THINK : run the YOLO AI model on the photo -> PLASTIC or PAPER?
   ACT   : tilt the platform the right way, save the result
```

Everything else in the code exists to support that loop or to let you *watch*
it from a browser.

---

## 2. The parts (and which file is which)

The project is split into four packages, each with one job:

| Package      | Nickname    | What it does | Main file |
|--------------|-------------|--------------|-----------|
| `edge_ai/`   | The Eyes    | Take camera photos, run the AI model | `vision_agent.py` |
| `hardware/`  | The Muscle  | Tilt the servo, read the bin sensor  | `servo_controller.py`, `sensor_read.py` |
| `backend/`   | The Brain   | Run the loop, store data, serve the dashboard | `orchestrator.py`, `main.py` |
| `ui/`        | The Window  | The web page you open on your laptop | `index.html` |

They are **decoupled** — each part only knows its own job. The `backend`
connects them together. This is what the project calls a "microservices-style"
design: you could swap the camera or the servo without touching the rest.

---

## 3. How data flows through the system

Follow one camera frame from the lens to your laptop screen:

```
  ┌─────────┐   photo    ┌──────────────┐  "PLASTIC 0.92"  ┌───────────────┐
  │ Camera  │ ─────────▶ │ vision_agent │ ───────────────▶ │ orchestrator  │
  └─────────┘            │  (The Eyes)  │                  │  (the loop)   │
                         └──────────────┘                  └───────┬───────┘
                                                                   │
                          ┌────────────────────────────────────────┤
                          │                  │                     │
                          ▼                  ▼                     ▼
                  ┌───────────────┐  ┌──────────────┐    ┌──────────────────┐
                  │ servo_control │  │  database    │    │   state.py       │
                  │ tilts LEFT/   │  │  saves the   │    │ the live         │
                  │ RIGHT         │  │  sort (SQLite)│   │ "whiteboard"     │
                  └───────────────┘  └──────────────┘    └────────┬─────────┘
                                                                  │ read by
                                                                  ▼
                                                       ┌──────────────────────┐
                                                       │ backend/routers/...  │
                                                       │  /api/stream  (video)│
                                                       │  /api/events  (status)│
                                                       └──────────┬───────────┘
                                                                  │ over WiFi
                                                                  ▼
                                                       ┌──────────────────────┐
                                                       │ ui/index.html        │
                                                       │ the dashboard in your│
                                                       │ laptop's browser     │
                                                       └──────────────────────┘
```

The key trick: **`state.py` is a shared "whiteboard."** The loop *writes* the
latest photo + status onto it; the web server *reads* from it. Neither has to
wait for the other. That is how the dashboard shows live data without slowing
the loop down.

---

## 4. Three things run at the same time (threads)

A normal program does one thing at a time. EcoSort needs to do three things at
once, so it uses **threads** (independent lines of execution):

1. **The web server** (`backend/main.py`, FastAPI/uvicorn) — answers the
   browser: serves the page, the video stream, the status feed.
2. **The orchestrator loop** (`orchestrator.py`) — the Sense-Think-Act cycle,
   running on its own background thread so it never blocks the web server.
3. **The servo worker** (inside `servo_controller.py`) — actually moving the
   servo. A tilt takes ~2 seconds (tilt → hold → return). If the loop waited
   for that, the camera would freeze for 2 seconds. Instead the loop just drops
   a "please tilt left" note in a queue and moves on; the worker thread handles
   the slow movement separately.

```
  Thread 1: Web server    ──── serving the dashboard ───────────────▶
  Thread 2: The loop      ── sense ─ think ─ act ─ sense ─ think ───▶
  Thread 3: Servo worker  ──────── tilt ── hold ── return ──────────▶
```

---

## 5. One sort, step by step

What happens, in code, when you put a plastic bottle on the platform:

1. **`orchestrator._tick()`** runs (≈12×/second).
2. **SENSE** — `vision_agent.capture()` grabs a camera frame.
3. **THINK** — `vision_agent.detect(frame)` runs the YOLO model. It returns
   `{"label": "PLASTIC", "confidence": 0.92, "box": (x1,y1,x2,y2)}`.
4. The loop checks: is the bin full? is the servo already busy? did we just
   sort something (cooldown)? is the system "armed"? If all clear →
5. **ACT** — `servo_controller.sort("PLASTIC")` drops a note in the servo
   queue. The servo worker picks it up: tilt LEFT (−0.8) → hold 2 s → flat (0).
6. **LOG** — `database.record_sort(...)` writes a row to the SQLite database
   and returns an `id`.
7. **PUBLISH** — the loop writes the event + the annotated photo onto
   `state.py` (the whiteboard).
8. The browser's `/api/events` feed reads the whiteboard and updates the
   dashboard; `/api/stream` shows the photo with a green box drawn on the
   bottle.
9. The loop **"disarms"** — it will not sort again until the camera sees an
   *empty* platform, so the same bottle is never sorted twice.

---

## 6. The "backends" — why the same code runs on laptop and Pi

Each hardware module (`vision_agent`, `servo_controller`, `sensor_read`) has
**three interchangeable backends**, chosen in `config.yaml`:

| Setting value | Meaning |
|---|---|
| `picamera2` / `gpio` | use the **real** Raspberry Pi hardware |
| `opencv` | use a **USB / laptop webcam** |
| `simulation` | no hardware — fake data, so the app still runs |
| `auto` | try the real hardware; if its library is missing, fall back |

With `auto`, the program checks at startup: *"can I import `picamera2`?"* On the
Pi → yes → use the real camera. On your laptop → no → use the webcam (or
simulate). **You never edit code** to move between laptop and Pi — that is the
whole point of the design.

This is also why nothing ever crashes: a missing library or unplugged sensor
just downgrades that one part to `simulation`.

---

## 7. The web side (FastAPI)

`backend/main.py` builds a small web server. Its routes:

| Route | Type | Purpose |
|---|---|---|
| `/` | HTML page | the dashboard (`ui/index.html`) |
| `/api/status` | JSON | one snapshot of the system state |
| `/api/stream` | MJPEG video | the live annotated camera feed |
| `/api/events` | SSE (live feed) | pushes a fresh status snapshot ~2×/sec |
| `/api/history` | JSON | the last 50 sorts from the database |
| `/api/feedback` | POST | record a 👍 / 👎 from the dashboard |

The dashboard page uses two of these live: an `<img>` tag pointed at
`/api/stream` for video, and a JavaScript `EventSource` on `/api/events` that
re-draws the panels every half second.

---

## 8. The database

`backend/models.py` defines one table, `sort_events`, stored in `ecosort.db`
(SQLite — a database that is just a single file). Every sort becomes a row:
timestamp, label, confidence, servo action, and later the human feedback.

This gives you a permanent record you can analyse for the VIP report — e.g.
"how many plastics vs papers", "average confidence", "how often was the AI
wrong" (from the feedback column).

---

## 9. The learning loop (human-in-the-loop)

On the dashboard, each sort can be marked 👍 (correct) or 👎 (wrong):

- 👍 → the database row is marked `correct`.
- 👎 → the database row is marked `incorrect` **and** the photo of that item is
  saved to `edge_ai/feedback_images/`.

Over time the 👎 images become a dataset of the AI's mistakes. You can label
those and **retrain** the YOLO model on them, so the next version is more
accurate. This is the `ui/` "agentic loop" from the project blueprint.

---

## 10. Configuration & hot-reload

All settings live in `config.yaml` — no values are hard-coded. A few keys
(the `SIMULATED_*` ones, `CONFIDENCE_THRESHOLD`, `SERVO_HOLD_SEC`) **hot-reload**:
edit `config.yaml` while the robot is running and the change takes effect within
~2 seconds, with no restart. This is handled by `backend/config.py` and is very
handy during a live demo.

---

## Summary in one sentence

> A background loop senses (camera), thinks (YOLO), and acts (servo); it writes
> everything onto a shared whiteboard; a web server reads that whiteboard so
> your laptop browser can watch the whole thing live.
