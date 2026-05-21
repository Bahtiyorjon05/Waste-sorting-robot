"""
orchestrator.py
================
The Sense-Think-Act loop -- the heartbeat of EcoSort AI.

Runs on its own background thread (started by the FastAPI app) so the web
server stays responsive. Every iteration it:

    SENSE  : grab a camera frame + read the bin sensor
    THINK  : run YOLO inference -> {label, confidence}
    ACT    : tilt the platform, record the sort in the database
    PUBLISH: push the annotated frame + status into SharedState so the
             dashboard shows everything live

The loop never sorts the same item twice: after a tilt it 'disarms' and only
re-arms once the platform is seen empty again (no detection).
"""

import logging
import threading
import time
from typing import Any, Dict, Optional

from edge_ai.vision_agent import VisionAgent
from hardware.sensor_read import BinSensor
from hardware.servo_controller import ServoController

from . import database
from .config import hot_reload
from .state import SharedState

logger = logging.getLogger("ecosort.orchestrator")

# label -> the servo action recorded in the database / shown on the dashboard
_LABEL_TO_ACTION = {"PLASTIC": "TILT LEFT", "PAPER": "TILT RIGHT"}


class Orchestrator(threading.Thread):
    """Background thread running the continuous Sense-Think-Act loop."""

    def __init__(self, config: Dict[str, Any], config_path: str,
                 state: SharedState) -> None:
        super().__init__(daemon=True, name="orchestrator")
        self._cfg = config
        self._cfg_path = config_path
        self._state = state

        self._vision = VisionAgent(config)
        self._servo = ServoController(config)
        self._sensor = BinSensor(config)

        self._target_fps = float(config.get("TARGET_FPS", 12))
        self._cooldown = float(config.get("COOLDOWN_SEC", 3.0))

        # loop bookkeeping
        self._armed = True               # ready to sort a new item?
        self._cooldown_until = 0.0
        self._display_detection: Optional[Dict[str, Any]] = None
        self._display_until = 0.0
        self._last_reload = 0.0
        self._fps_ema = 0.0

        # tell the dashboard which backends are actually live
        state.backends = {
            "camera": self._vision.camera_backend,
            "servo": self._servo.backend,
            "sensor": self._sensor.backend,
            "model": self._vision.model_backend,
        }
        logger.info("Backends -> %s", state.backends)

    # ------------------------------------------------------------------
    def run(self) -> None:
        logger.info("=" * 58)
        logger.info("  EcoSort AI - Sense-Think-Act loop RUNNING")
        logger.info("=" * 58)
        frame_budget = 1.0 / max(1.0, self._target_fps)

        while self._state.running:
            t0 = time.monotonic()
            try:
                self._tick()
            except Exception as exc:  # never let one bad frame kill the loop
                logger.exception("Loop iteration error: %s", exc)

            # pace the loop to the target FPS
            elapsed = time.monotonic() - t0
            if elapsed < frame_budget:
                time.sleep(frame_budget - elapsed)

            # rolling FPS estimate
            dt = time.monotonic() - t0
            inst_fps = 1.0 / dt if dt > 0 else 0.0
            self._fps_ema = (0.85 * self._fps_ema + 0.15 * inst_fps
                             if self._fps_ema else inst_fps)
            self._state.fps = self._fps_ema

        self._shutdown()

    # ------------------------------------------------------------------
    def _tick(self) -> None:
        now = time.monotonic()

        # --- periodic config hot-reload (for the live demo) ---
        if now - self._last_reload >= 2.0:
            self._last_reload = now
            hot_reload(self._cfg_path, self._cfg)

        # --- SENSE ---
        frame = self._vision.capture()
        detection = self._vision.detect(frame)
        self._sensor.update()
        self._state.bin_full = self._sensor.is_full
        self._state.bin_distance_cm = self._sensor.distance_cm
        self._state.servo_state = self._servo.state

        # --- THINK + ACT ---
        if detection is None:
            self._armed = True            # platform looks empty -> re-arm
        elif self._can_sort(now):
            self._act(detection, now)

        # keep the detection box on-screen briefly so the demo is readable
        if detection is not None:
            self._display_detection = detection
            self._display_until = now + max(self._cooldown, 1.5)
        elif now > self._display_until:
            self._display_detection = None

        # --- PUBLISH (annotated frame + status to the dashboard) ---
        self._state.detection = (
            {k: detection[k] for k in ("label", "confidence")}
            if detection else None
        )
        status = {
            "servo_state": self._servo.state,
            "bin_full": self._sensor.is_full,
            "fps": self._state.fps,
        }
        annotated = self._vision.annotate(frame, self._display_detection, status)
        jpeg = self._vision.encode_jpeg(annotated)
        if jpeg is not None:
            self._state.set_frame(jpeg)

    # ------------------------------------------------------------------
    def _can_sort(self, now: float) -> bool:
        return (
            self._armed
            and not self._sensor.is_full
            and not self._servo.is_busy()
            and now >= self._cooldown_until
        )

    def _act(self, detection: Dict[str, Any], now: float) -> None:
        label = detection["label"]
        confidence = float(detection["confidence"])
        action = _LABEL_TO_ACTION.get(label)
        if action is None:
            return

        if not self._servo.sort(label):   # queue the tilt
            return
        self._armed = False
        self._cooldown_until = now + self._cooldown

        # record in the database
        try:
            sort_id = database.record_sort(label, confidence, action)
        except Exception as exc:
            logger.error("DB write failed: %s", exc)
            sort_id = -1

        self._state.last_sort_id = sort_id
        self._state.mark_sort_frame()     # for 👎 feedback image saving
        event = {
            "id": sort_id,
            "timestamp": time.strftime("%H:%M:%S"),
            "label": label,
            "confidence": round(confidence, 2),
            "servo_action": action,
        }
        self._state.add_event(event)
        logger.info("SORTED #%s: %s (%.0f%%) -> %s",
                    sort_id, label, confidence * 100, action)

    # ------------------------------------------------------------------
    def _shutdown(self) -> None:
        logger.info("Orchestrator stopping -- releasing hardware.")
        self._vision.shutdown()
        self._servo.shutdown()
        self._sensor.shutdown()
        logger.info("Orchestrator stopped.")
