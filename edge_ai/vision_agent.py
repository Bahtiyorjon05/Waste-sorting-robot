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
  3. Draw the detection box + a status banner onto the frame for the live feed.

Every method degrades gracefully: a missing library or missing model never
crashes the app, it just falls back to simulation.
"""

import logging
import os
import random
import threading
import time
from typing import Any, Dict, Optional

# A buffered camera frame older than this (seconds) is treated as "camera not
# delivering" and capture() falls back to a synthetic frame.
_FRAME_STALE_SEC = 2.5

import numpy as np

logger = logging.getLogger("ecosort.vision")

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
    """Camera capture + YOLO inference + frame annotation."""

    def __init__(self, config: Dict[str, Any]) -> None:
        self._cfg = config
        self._w = int(config.get("FRAME_WIDTH", 640))
        self._h = int(config.get("FRAME_HEIGHT", 480))

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

        # --- background capture thread ---
        # A real camera is read on its own thread so that a stalled or
        # disconnected camera can NEVER freeze the Sense-Think-Act loop.
        # capture() just returns a synthetic frame when frames go stale.
        self._frame_lock = threading.Lock()
        self._latest_frame: Optional[np.ndarray] = None
        self._latest_frame_ts: float = 0.0
        self._capture_running = False
        self._capture_thread: Any = None
        if self.camera_backend in ("opencv", "picamera2"):
            self._capture_running = True
            self._capture_thread = threading.Thread(
                target=self._capture_loop, daemon=True, name="camera-capture"
            )
            self._capture_thread.start()

        # --- load the YOLO model (optional) ---
        self._model: Any = None
        self.model_backend = "none"
        self._conf = float(config.get("CONFIDENCE_THRESHOLD", 0.50))
        self._iou = float(config.get("IOU_THRESHOLD", 0.45))
        # CLASS_MAP maps the model's own class NAME -> EcoSort label.
        # e.g. {"bottle": "PLASTIC", "book": "PAPER"}
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

    # ------------------------------------------------------------------
    # Backend resolution
    # ------------------------------------------------------------------
    def _resolve_camera_backend(self, requested: str) -> str:
        """Turn 'auto' into a concrete backend based on what is installed."""
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
        # A bare name like "yolov8n.pt" (no folder) is auto-downloaded by
        # ultralytics on first use. A path with folders must already exist.
        is_bare_name = os.path.basename(model_path) == model_path
        if not os.path.isfile(model_path) and not is_bare_name:
            logger.warning("Model file not found (%s) -> detections simulated.",
                           model_path)
            return
        try:
            self._model = YOLO(model_path)
            self.model_backend = os.path.basename(model_path)
            logger.info("YOLO model loaded: %s", model_path)
            logger.info("Model classes: %s",
                        list(self._model.names.values()))
        except Exception as exc:
            logger.warning("Model load failed: %s -> detections simulated.", exc)
            self._model = None

    # ------------------------------------------------------------------
    # Capture
    # ------------------------------------------------------------------
    def capture(self) -> np.ndarray:
        """Return one BGR frame. Never blocks: returns the most recent real
        frame, or a synthetic frame if the camera is not delivering."""
        if self.camera_backend == "simulation":
            return self._synthetic_frame("SIMULATION MODE - no camera")
        with self._frame_lock:
            frame = self._latest_frame
            age = time.monotonic() - self._latest_frame_ts
        if frame is not None and age < _FRAME_STALE_SEC:
            return frame
        return self._synthetic_frame("NO CAMERA SIGNAL - check the ribbon cable")

    # ------------------------------------------------------------------
    # Background capture thread (real cameras only)
    # ------------------------------------------------------------------
    def _capture_loop(self) -> None:
        """Continuously read the real camera on a daemon thread. If the camera
        hangs, only this thread stalls -- the main loop keeps running."""
        while self._capture_running:
            frame = self._grab_real_frame()
            if frame is not None:
                with self._frame_lock:
                    self._latest_frame = frame
                    self._latest_frame_ts = time.monotonic()
            else:
                time.sleep(0.2)   # brief pause before retrying a failed read

    def _grab_real_frame(self) -> Optional[np.ndarray]:
        """Grab one frame from the real camera. May block -- that is exactly
        why it runs on its own thread."""
        try:
            if self.camera_backend == "opencv" and self._cap is not None:
                ok, frame = self._cap.read()
                return frame if ok and frame is not None else None
            if self.camera_backend == "picamera2" and self._picam is not None:
                arr = self._picam.capture_array()
                # picamera2 hands back RGB; OpenCV wants BGR.
                if cv2 is not None:
                    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
                return arr
        except Exception as exc:
            logger.debug("camera read error: %s", exc)
        return None

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------
    def detect(self, frame: np.ndarray) -> Optional[Dict[str, Any]]:
        """Classify the frame. Returns {label, confidence, box} or None.

        Uses the real YOLO model when available; otherwise simulates a
        detection every SIMULATED_DETECTION_INTERVAL_SEC seconds.
        """
        if self._model is not None:
            return self._detect_yolo(frame)
        return self._detect_simulated()

    def _detect_yolo(self, frame: np.ndarray) -> Optional[Dict[str, Any]]:
        try:
            results = self._model.predict(
                source=frame, conf=self._conf, iou=self._iou, verbose=False
            )
        except Exception as exc:
            logger.warning("Inference error: %s", exc)
            return None
        if not results or results[0].boxes is None or len(results[0].boxes) == 0:
            return None

        names = self._model.names  # {class_id: class_name}
        best: Optional[Dict[str, Any]] = None
        for box in results[0].boxes:
            cls_id = int(box.cls[0])
            cls_name = str(names.get(cls_id, "")).strip().lower()
            label = self._class_map.get(cls_name)
            if label is None:
                continue  # model saw something we don't sort (e.g. a person)
            conf = float(box.conf[0])
            if best is None or conf > best["confidence"]:
                x1, y1, x2, y2 = (int(v) for v in box.xyxy[0])
                best = {"label": label, "confidence": conf,
                        "box": (x1, y1, x2, y2)}
        return best

    def _detect_simulated(self) -> Optional[Dict[str, Any]]:
        # Honour a hot-reloadable fixed label, else alternate PLASTIC/PAPER.
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

        # A plausible centred bounding box.
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
        """Draw the detection box and a status banner onto a copy of frame."""
        if cv2 is None:
            return frame
        img = frame.copy()
        h, w = img.shape[:2]

        # --- detection box ---
        if detection and detection.get("box"):
            x1, y1, x2, y2 = detection["box"]
            colour = _COLOURS.get(detection["label"], _COLOURS["_box"])
            cv2.rectangle(img, (x1, y1), (x2, y2), colour, 3)
            tag = f"{detection['label']} {detection['confidence'] * 100:.0f}%"
            (tw, th), _ = cv2.getTextSize(tag, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
            cv2.rectangle(img, (x1, y1 - th - 12), (x1 + tw + 12, y1), colour, -1)
            cv2.putText(img, tag, (x1 + 6, y1 - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, _COLOURS["_text"], 2)

        # --- top status banner ---
        cv2.rectangle(img, (0, 0), (w, 28), _COLOURS["_banner"], -1)
        banner = (f"EcoSort AI  |  cam:{self.camera_backend}  "
                  f"|  servo:{status.get('servo_state', '-')}  "
                  f"|  {status.get('fps', 0):.0f} FPS")
        cv2.putText(img, banner, (8, 19),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, _COLOURS["_text"], 1)

        # --- bin-full warning ---
        if status.get("bin_full"):
            cv2.rectangle(img, (0, h - 30), (w, h), _COLOURS["_warn"], -1)
            cv2.putText(img, "BIN FULL - sorting paused", (8, h - 9),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, _COLOURS["_text"], 2)
        return img

    def encode_jpeg(self, frame: np.ndarray) -> Optional[bytes]:
        """Encode a frame as JPEG bytes for the MJPEG stream."""
        if cv2 is None:
            return None
        try:
            ok, buf = cv2.imencode(".jpg", frame,
                                   [cv2.IMWRITE_JPEG_QUALITY, 80])
            return buf.tobytes() if ok else None
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Internal: synthetic camera frame for simulation mode
    # ------------------------------------------------------------------
    def _synthetic_frame(self, message: str = "SIMULATION MODE") -> np.ndarray:
        """A dark 'conveyor belt' image so the live feed is never blank."""
        img = np.full((self._h, self._w, 3), 24, dtype=np.uint8)
        # belt
        belt_top, belt_bot = int(self._h * 0.30), int(self._h * 0.82)
        img[belt_top:belt_bot, :] = (44, 44, 48)
        if cv2 is not None:
            for x in range(0, self._w, 60):
                cv2.line(img, (x, belt_top), (x, belt_bot), (60, 60, 66), 1)
            cv2.putText(img, message,
                        (int(self._w * 0.08), int(self._h * 0.93)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (130, 130, 140), 1)
        return img

    # ------------------------------------------------------------------
    def shutdown(self) -> None:
        self._capture_running = False
        if self._capture_thread is not None:
            self._capture_thread.join(timeout=2.0)
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
