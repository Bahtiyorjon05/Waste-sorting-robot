"""
vision_agent.py
================
The Eyes of EcoSort AI.

Responsibilities:
  1. Grab frames from the camera. Three interchangeable backends:
       - "picamera2"  -> Raspberry Pi Camera (CSI ribbon cable)
       - "opencv"     -> USB webcam (also works as the laptop webcam)
       - "simulation" -> synthetic frames, so the whole app runs with no camera
  2. Run YOLOv8 inference to classify waste (PLASTIC / PAPER).
  3. Stream annotated frames to the dashboard at a steady frame rate.

THREADING MODEL
---------------
Three background threads, so a slow YOLO never bottlenecks the live video:

    capture thread  -> grabs frames from the camera as fast as it can,
                       stores the latest one in a buffer
    stream thread   -> ~TARGET_FPS times per second, reads the latest frame,
                       annotates it with the latest detection, JPEG-encodes
                       it, publishes to SharedState (this is what the
                       dashboard streams)
    detect thread   -> runs YOLO inference on the latest frame in a loop,
                       updates the "latest detection" slot

The orchestrator just reads ``vision.latest_detection()`` and decides whether
to act. It no longer touches frames or runs YOLO itself.

Every method degrades gracefully: a missing library, missing model, or dead
camera all fall back to a synthetic "no camera" frame instead of crashing.
"""

import logging
import os
import random
import threading
import time
from typing import Any, Dict, Optional

import numpy as np

logger = logging.getLogger("ecosort.vision")

# A buffered camera frame older than this (seconds) is treated as "camera not
# delivering" and the stream falls back to a synthetic frame.
_FRAME_STALE_SEC = 2.5
# How long a detection box keeps showing on the stream after YOLO last saw it.
_DETECTION_LINGER_SEC = 1.5

# --- optional imports: absent on the laptop, present on the Pi --------------
try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]

try:
    from ultralytics import YOLO
except ImportError:  # pragma: no cover
    YOLO = None  # type: ignore[assignment]

try:
    from picamera2 import Picamera2
except ImportError:  # pragma: no cover
    Picamera2 = None  # type: ignore[assignment]

# Colours (BGR) used when drawing on frames.
_COLOURS = {
    "PLASTIC": (231, 180, 22),    # blue-ish
    "PAPER": (80, 200, 120),      # green-ish
    "_box": (60, 220, 75),
    "_text": (255, 255, 255),
    "_banner": (28, 28, 30),
    "_warn": (60, 60, 230),
}


class VisionAgent:
    """Camera capture + YOLO inference + frame streaming, all multi-threaded."""

    def __init__(self, config: Dict[str, Any]) -> None:
        self._cfg = config
        self._w = int(config.get("FRAME_WIDTH", 640))
        self._h = int(config.get("FRAME_HEIGHT", 480))
        self._target_fps = float(config.get("TARGET_FPS", 12))
        # YOLO inference at a smaller image size is much faster on a Pi CPU
        # (320 ~= 3-4x faster than 640, with a small accuracy trade-off).
        self._yolo_imgsz = int(config.get("YOLO_IMGSZ", 320))

        # --- pick the camera backend ---
        self.camera_backend = self._resolve_camera_backend(
            str(config.get("CAMERA_BACKEND", "auto")).lower()
        )
        self._cap: Any = None
        self._picam: Any = None
        if self.camera_backend == "opencv":
            self._init_opencv()
        elif self.camera_backend == "picamera2":
            self._init_picamera2()

        # --- shared state between the threads ---
        self._camera_lock = threading.Lock()
        self._camera_frame: Optional[np.ndarray] = None
        self._camera_frame_ts: float = 0.0

        self._det_lock = threading.Lock()
        # The orchestrator reads this; None means "platform is empty".
        self._latest_detection: Optional[Dict[str, Any]] = None
        # The stream thread draws this; lingers briefly so the box doesn't
        # flicker between YOLO inferences.
        self._det_for_draw: Optional[Dict[str, Any]] = None
        self._det_draw_until: float = 0.0

        # --- load the YOLO model (optional) ---
        self._model: Any = None
        self.model_backend = "none"
        self._conf = float(config.get("CONFIDENCE_THRESHOLD", 0.50))
        self._iou = float(config.get("IOU_THRESHOLD", 0.45))
        self._class_map = {
            str(k).strip().lower(): str(v).strip().upper()
            for k, v in dict(config.get("CLASS_MAP", {})).items()
        }
        self._load_model(str(config.get("MODEL_PATH", "")))

        # --- simulation state ---
        self._sim_interval = float(config.get("SIMULATED_DETECTION_INTERVAL_SEC", 4.0))
        self._sim_cycle = ["PLASTIC", "PAPER"]
        self._sim_index = 0
        self._last_sim_time = 0.0

        # --- fps tracking (computed in the stream thread) ---
        self._fps_ema: float = 0.0
        self._last_pub_ts: float = 0.0

        # --- threads (started by .start()) ---
        self._state: Any = None
        self._running = False
        self._capture_thread: Any = None
        self._stream_thread: Any = None
        self._detect_thread: Any = None

        # Start the camera capture immediately so frames start flowing right
        # away; the publish + detect threads only need SharedState (started in
        # .start() below by the orchestrator).
        if self.camera_backend in ("opencv", "picamera2"):
            self._running = True
            self._capture_thread = threading.Thread(
                target=self._capture_loop, daemon=True, name="vision-capture",
            )
            self._capture_thread.start()

    # ------------------------------------------------------------------
    # Public API used by the orchestrator
    # ------------------------------------------------------------------
    def start(self, state: Any) -> None:
        """Start the stream + detect threads. Call once, after SharedState exists."""
        self._state = state
        self._running = True
        self._stream_thread = threading.Thread(
            target=self._stream_loop, daemon=True, name="vision-stream",
        )
        self._stream_thread.start()
        self._detect_thread = threading.Thread(
            target=self._detect_loop, daemon=True, name="vision-detect",
        )
        self._detect_thread.start()
        logger.info("Vision threads started (stream + detect).")

    def latest_detection(self) -> Optional[Dict[str, Any]]:
        """The most recent real detection, or None if nothing is in view."""
        with self._det_lock:
            return self._latest_detection

    def shutdown(self) -> None:
        """Stop all vision threads and release the camera."""
        self._running = False
        for t in (self._capture_thread, self._stream_thread, self._detect_thread):
            if t is not None:
                t.join(timeout=2.0)
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
        if self._picam is not None:
            try:
                self._picam.stop()
            except Exception:
                pass
        logger.info("[VisionAgent] Shut down.")

    # ------------------------------------------------------------------
    # Backend resolution & initialisation
    # ------------------------------------------------------------------
    def _resolve_camera_backend(self, requested: str) -> str:
        if requested == "picamera2":
            if Picamera2 is None:
                logger.warning("picamera2 not installed -> camera simulation.")
                return "simulation"
            return "picamera2"
        if requested == "opencv":
            if cv2 is None:
                logger.warning("opencv not installed -> camera simulation.")
                return "simulation"
            return "opencv"
        if requested == "simulation":
            return "simulation"
        # auto: prefer the Pi camera, then a USB webcam, else simulate.
        if Picamera2 is not None:
            return "picamera2"
        if cv2 is not None:
            return "opencv"
        return "simulation"

    def _init_opencv(self) -> None:
        try:
            self._cap = cv2.VideoCapture(int(self._cfg.get("CAMERA_INDEX", 0)))
            if self._cap is not None and self._cap.isOpened():
                self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._w)
                self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._h)
                logger.info("Camera ready (opencv backend).")
            else:
                logger.warning("Could not open USB webcam -> camera simulation.")
                self._cap = None
                self.camera_backend = "simulation"
        except Exception as exc:
            logger.warning("opencv camera init failed: %s -> simulation.", exc)
            self._cap = None
            self.camera_backend = "simulation"

    def _init_picamera2(self) -> None:
        try:
            self._picam = Picamera2()
            cfg = self._picam.create_preview_configuration(
                main={"size": (self._w, self._h), "format": "RGB888"}
            )
            self._picam.configure(cfg)
            self._picam.start()
            time.sleep(1.0)  # let auto-exposure settle
            logger.info("Camera ready (picamera2 backend).")
        except Exception as exc:
            logger.warning("picamera2 init failed: %s -> simulation.", exc)
            self._picam = None
            self.camera_backend = "simulation"

    def _load_model(self, model_path: str) -> None:
        if YOLO is None:
            logger.warning("ultralytics not installed -> detections simulated.")
            return
        if not model_path:
            logger.warning("MODEL_PATH is empty -> detections simulated.")
            return
        is_bare_name = os.path.basename(model_path) == model_path
        if not os.path.isfile(model_path) and not is_bare_name:
            logger.warning("Model file not found (%s) -> detections simulated.",
                           model_path)
            return
        try:
            self._model = YOLO(model_path)
            self.model_backend = os.path.basename(model_path)
            logger.info("YOLO model loaded: %s (imgsz=%d)",
                        model_path, self._yolo_imgsz)
            logger.info("Model classes: %s",
                        list(self._model.names.values()))
        except Exception as exc:
            logger.warning("Model load failed: %s -> detections simulated.", exc)
            self._model = None

    # ------------------------------------------------------------------
    # Thread 1: CAPTURE — pulls frames from the real camera as fast as it can
    # ------------------------------------------------------------------
    def _capture_loop(self) -> None:
        while self._running:
            frame = self._grab_real_frame()
            if frame is not None:
                with self._camera_lock:
                    self._camera_frame = frame
                    self._camera_frame_ts = time.monotonic()
            else:
                time.sleep(0.2)   # brief pause before retrying a failed read

    def _grab_real_frame(self) -> Optional[np.ndarray]:
        try:
            if self.camera_backend == "opencv" and self._cap is not None:
                ok, frame = self._cap.read()
                return frame if ok and frame is not None else None
            if self.camera_backend == "picamera2" and self._picam is not None:
                arr = self._picam.capture_array()
                if cv2 is not None:
                    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
                return arr
        except Exception as exc:
            logger.debug("camera read error: %s", exc)
        return None

    # ------------------------------------------------------------------
    # Thread 2: STREAM — annotates the latest frame + publishes to dashboard
    # ------------------------------------------------------------------
    def _stream_loop(self) -> None:
        target_dt = 1.0 / max(1.0, self._target_fps)
        while self._running:
            t0 = time.monotonic()
            # 1. get a frame to publish (real or synthetic)
            if self.camera_backend == "simulation":
                frame = self._synthetic_frame("SIMULATION MODE - no camera")
            else:
                with self._camera_lock:
                    cf = self._camera_frame
                    cf_ts = self._camera_frame_ts
                if cf is not None and (t0 - cf_ts) < _FRAME_STALE_SEC:
                    frame = cf
                else:
                    frame = self._synthetic_frame(
                        "NO CAMERA SIGNAL - check the ribbon cable")

            # 2. get the detection to draw (linger so the box doesn't flicker)
            with self._det_lock:
                if t0 < self._det_draw_until:
                    det_draw = self._det_for_draw
                else:
                    det_draw = None
                    self._det_for_draw = None

            # 3. annotate + encode + publish
            status = self._read_status()
            annotated = self.annotate(frame, det_draw, status)
            jpeg = self.encode_jpeg(annotated)
            if jpeg is not None and self._state is not None:
                self._state.set_frame(jpeg)

            # 4. update stream FPS (this is what the user sees)
            now = time.monotonic()
            if self._last_pub_ts > 0:
                inst = 1.0 / max(1e-3, now - self._last_pub_ts)
                self._fps_ema = (0.85 * self._fps_ema + 0.15 * inst
                                 if self._fps_ema else inst)
                if self._state is not None:
                    self._state.fps = self._fps_ema
            self._last_pub_ts = now

            # 5. pace to the target frame rate
            dt = time.monotonic() - t0
            if dt < target_dt:
                time.sleep(target_dt - dt)

    def _read_status(self) -> Dict[str, Any]:
        """Snapshot the bits of SharedState the stream banner needs."""
        if self._state is None:
            return {"servo_state": "FLAT", "bin_full": False, "fps": 0.0}
        return {
            "servo_state": getattr(self._state, "servo_state", "FLAT"),
            "bin_full": getattr(self._state, "bin_full", False),
            "fps": getattr(self._state, "fps", 0.0),
        }

    # ------------------------------------------------------------------
    # Thread 3: DETECT — runs YOLO (or simulated detection) in a loop
    # ------------------------------------------------------------------
    def _detect_loop(self) -> None:
        while self._running:
            if self.camera_backend == "simulation" or self._model is None:
                det = self._detect_simulated()
                time.sleep(0.1)
            else:
                with self._camera_lock:
                    frame = self._camera_frame
                if frame is None:
                    time.sleep(0.1)
                    continue
                det = self._detect_yolo(frame)
            now = time.monotonic()
            with self._det_lock:
                self._latest_detection = det
                if det is not None:
                    self._det_for_draw = det
                    self._det_draw_until = now + _DETECTION_LINGER_SEC

    def _enhance_for_detection(self, frame: np.ndarray) -> np.ndarray:
        """Apply CLAHE to the L-channel before YOLO inference. Boosts contrast
        in varying / dim / harsh lighting -- much better detection of crumpled
        paper, dark plastics, items on busy backgrounds. The dashboard stream
        still shows the original frame; this only feeds an enhanced copy to
        the model."""
        if cv2 is None:
            return frame
        try:
            lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            l = clahe.apply(l)
            return cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)
        except Exception:
            return frame

    def _detect_yolo(self, frame: np.ndarray) -> Optional[Dict[str, Any]]:
        frame = self._enhance_for_detection(frame)
        try:
            results = self._model.predict(
                source=frame, conf=self._conf, iou=self._iou,
                imgsz=self._yolo_imgsz, verbose=False,
            )
        except Exception as exc:
            logger.warning("Inference error: %s", exc)
            return None
        if not results or results[0].boxes is None or len(results[0].boxes) == 0:
            return None

        names = self._model.names
        best: Optional[Dict[str, Any]] = None
        for box in results[0].boxes:
            cls_id = int(box.cls[0])
            cls_name = str(names.get(cls_id, "")).strip().lower()
            label = self._class_map.get(cls_name)
            if label is None:
                continue
            conf = float(box.conf[0])
            if best is None or conf > best["confidence"]:
                x1, y1, x2, y2 = (int(v) for v in box.xyxy[0])
                best = {"label": label, "confidence": conf,
                        "box": (x1, y1, x2, y2)}
        return best

    def _detect_simulated(self) -> Optional[Dict[str, Any]]:
        now = time.monotonic()
        interval = float(self._cfg.get("SIMULATED_DETECTION_INTERVAL_SEC",
                                       self._sim_interval))
        if now - self._last_sim_time < interval:
            return None
        self._last_sim_time = now

        fixed = str(self._cfg.get("SIMULATED_DETECTION_LABEL", "")).strip().upper()
        if fixed in self._sim_cycle:
            label = fixed
        else:
            label = self._sim_cycle[self._sim_index % len(self._sim_cycle)]
            self._sim_index += 1

        bw, bh = int(self._w * 0.34), int(self._h * 0.40)
        cx = self._w // 2 + random.randint(-40, 40)
        cy = self._h // 2 + random.randint(-25, 25)
        box = (cx - bw // 2, cy - bh // 2, cx + bw // 2, cy + bh // 2)
        return {
            "label": label,
            "confidence": round(random.uniform(0.78, 0.97), 2),
            "box": box,
        }

    # ------------------------------------------------------------------
    # Frame annotation (what the dashboard video shows)
    # ------------------------------------------------------------------
    def annotate(self, frame: np.ndarray,
                 detection: Optional[Dict[str, Any]],
                 status: Dict[str, Any]) -> np.ndarray:
        if cv2 is None:
            return frame
        img = frame.copy()
        h, w = img.shape[:2]

        if detection and detection.get("box"):
            x1, y1, x2, y2 = detection["box"]
            colour = _COLOURS.get(detection["label"], _COLOURS["_box"])
            cv2.rectangle(img, (x1, y1), (x2, y2), colour, 3)
            tag = f"{detection['label']} {detection['confidence'] * 100:.0f}%"
            (tw, th), _ = cv2.getTextSize(tag, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
            cv2.rectangle(img, (x1, y1 - th - 12), (x1 + tw + 12, y1), colour, -1)
            cv2.putText(img, tag, (x1 + 6, y1 - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, _COLOURS["_text"], 2)

        cv2.rectangle(img, (0, 0), (w, 28), _COLOURS["_banner"], -1)
        banner = (f"EcoSort AI  |  cam:{self.camera_backend}  "
                  f"|  servo:{status.get('servo_state', '-')}  "
                  f"|  {status.get('fps', 0):.0f} FPS")
        cv2.putText(img, banner, (8, 19),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, _COLOURS["_text"], 1)

        if status.get("bin_full"):
            cv2.rectangle(img, (0, h - 30), (w, h), _COLOURS["_warn"], -1)
            cv2.putText(img, "BIN FULL - sorting paused", (8, h - 9),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, _COLOURS["_text"], 2)
        return img

    def encode_jpeg(self, frame: np.ndarray) -> Optional[bytes]:
        if cv2 is None:
            return None
        try:
            ok, buf = cv2.imencode(".jpg", frame,
                                   [cv2.IMWRITE_JPEG_QUALITY, 80])
            return buf.tobytes() if ok else None
        except Exception:
            return None

    # ------------------------------------------------------------------
    def _synthetic_frame(self, message: str = "SIMULATION MODE") -> np.ndarray:
        img = np.full((self._h, self._w, 3), 24, dtype=np.uint8)
        belt_top, belt_bot = int(self._h * 0.30), int(self._h * 0.82)
        img[belt_top:belt_bot, :] = (44, 44, 48)
        if cv2 is not None:
            for x in range(0, self._w, 60):
                cv2.line(img, (x, belt_top), (x, belt_bot), (60, 60, 66), 1)
            cv2.putText(img, message,
                        (int(self._w * 0.08), int(self._h * 0.93)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (130, 130, 140), 1)
        return img
