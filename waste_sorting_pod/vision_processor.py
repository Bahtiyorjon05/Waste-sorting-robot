"""
vision_processor.py
====================
Captures frames from the Pi Camera (or simulation), turns on the forward-facing
LED array for illumination, and runs YOLOv8 inference locally.

Classes detected: Plastic, Paper, Metal
Output: dict with keys  {"label": str, "confidence": float}  or None
"""

import logging
import os
import random
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional imports – graceful fallback when running without hardware / libs
# ---------------------------------------------------------------------------
try:
    import cv2
except ImportError:
    cv2 = None  # type: ignore[assignment]

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None  # type: ignore[assignment]

try:
    from gpiozero import LED
except ImportError:
    LED = None  # type: ignore[assignment]

# Canonical class-id → label mapping expected from the model
CLASS_MAP: Dict[int, str] = {
    0: "Plastic",
    1: "Paper",
    2: "Metal",
}


class VisionProcessor:
    """Handles camera capture, LED illumination, and YOLO inference."""

    def __init__(self, config: Dict[str, Any]) -> None:
        self._cfg = config
        self._sim = bool(config.get("USE_SIMULATION", True))

        # Simulation state
        self._sim_label: str = config.get("SIMULATED_DETECTION_LABEL", "")
        self._sim_interval: float = float(
            config.get("SIMULATED_DETECTION_INTERVAL_SEC", 5.0)
        )
        self._last_sim_time: float = 0.0

        # Cycle through all classes in simulation for demo purposes
        self._sim_cycle: List[str] = ["Plastic", "Paper", "Metal"]
        self._sim_index: int = 0

        # Camera
        self._cap: Any = None
        self._frame_w: int = int(config.get("FRAME_WIDTH", 640))
        self._frame_h: int = int(config.get("FRAME_HEIGHT", 480))
        self._camera_index: int = int(config.get("CAMERA_INDEX", 0))

        # YOLO model
        self._model: Any = None
        self._conf_thresh: float = float(config.get("CONFIDENCE_THRESHOLD", 0.50))
        self._iou_thresh: float = float(config.get("IOU_THRESHOLD", 0.45))
        self._model_path: str = str(config.get("MODEL_PATH", "models/yolov8n_waste.pt"))

        # LED
        self._led: Any = None
        self._led_gpio: int = int(config.get("LED_GPIO", 22))

        if not self._sim:
            self._init_camera()
            self._init_led()
            self._load_model()
        else:
            logger.info("[VisionProcessor] Running in SIMULATION mode.")

    # ------------------------------------------------------------------
    # Initialisation helpers
    # ------------------------------------------------------------------
    def _init_camera(self) -> None:
        if cv2 is None:
            logger.error("OpenCV is not installed. Cannot open camera.")
            return
        try:
            self._cap = cv2.VideoCapture(self._camera_index)
            if self._cap and self._cap.isOpened():
                self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._frame_w)
                self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._frame_h)
                logger.info("Camera %d opened successfully.", self._camera_index)
            else:
                logger.error("Failed to open camera %d.", self._camera_index)
                self._cap = None
        except Exception as exc:
            logger.error("Camera init error: %s", exc)
            self._cap = None

    def _init_led(self) -> None:
        if LED is None:
            logger.warning("gpiozero.LED not available; LED control disabled.")
            return
        try:
            self._led = LED(self._led_gpio)
            self._led.on()
            logger.info("LED array ON (GPIO %d).", self._led_gpio)
        except Exception as exc:
            logger.warning("LED init failed: %s", exc)
            self._led = None

    def _load_model(self) -> None:
        if YOLO is None:
            logger.error("ultralytics is not installed. Inference disabled.")
            return
        if not os.path.isfile(self._model_path):
            logger.error("Model file not found: %s", self._model_path)
            return
        try:
            self._model = YOLO(self._model_path)
            logger.info("YOLO model loaded from %s", self._model_path)
        except Exception as exc:
            logger.error("Model load failed: %s", exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def detect(self) -> Optional[Dict[str, Any]]:
        """Run one detection cycle. Returns {"label": ..., "confidence": ...} or None."""
        if self._sim:
            return self._simulate_detection()
        return self._real_detection()

    def shutdown(self) -> None:
        """Release hardware resources."""
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        if self._led is not None:
            try:
                self._led.off()
            except Exception:
                pass
            self._led = None
        logger.info("[VisionProcessor] Shut down.")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _simulate_detection(self) -> Optional[Dict[str, Any]]:
        # Re-read from live config dict so hot-reload takes effect
        sim_label = self._cfg.get("SIMULATED_DETECTION_LABEL", "")
        sim_interval = float(self._cfg.get("SIMULATED_DETECTION_INTERVAL_SEC", 5.0))

        now = time.monotonic()
        if now - self._last_sim_time < sim_interval:
            return None
        self._last_sim_time = now

        # If a fixed label is configured, use it; otherwise cycle all classes
        if sim_label:
            label = sim_label
        else:
            label = self._sim_cycle[self._sim_index % len(self._sim_cycle)]
            self._sim_index += 1

        confidence = round(random.uniform(0.75, 0.98), 2)
        logger.info("[SIM] Simulated detection: %s (%.0f%%)", label, confidence * 100)
        return {"label": label, "confidence": confidence}

    def _real_detection(self) -> Optional[Dict[str, Any]]:
        if self._cap is None or self._model is None:
            return None
        try:
            ok, frame = self._cap.read()
        except Exception as exc:
            logger.warning("Camera read error: %s", exc)
            return None
        if not ok or frame is None:
            return None

        try:
            results = self._model.predict(
                source=frame,
                conf=self._conf_thresh,
                iou=self._iou_thresh,
                verbose=False,
            )
        except Exception as exc:
            logger.warning("Inference error: %s", exc)
            return None

        if not results:
            return None
        boxes = results[0].boxes
        if boxes is None or len(boxes) == 0:
            return None

        # Pick the highest-confidence known class
        best: Optional[Dict[str, Any]] = None
        for box in boxes:
            cls_id = int(box.cls[0])
            if cls_id not in CLASS_MAP:
                continue
            conf = float(box.conf[0])
            if conf < self._conf_thresh:
                continue
            if best is None or conf > best["confidence"]:
                best = {"label": CLASS_MAP[cls_id], "confidence": conf}

        return best
