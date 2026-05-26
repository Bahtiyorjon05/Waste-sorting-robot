"""
orchestrator.py
================
The Think-and-Act loop -- the heartbeat of EcoSort AI.

VisionAgent runs its OWN three threads (capture, stream, detect) so the live
video and YOLO inference never wait for each other. This orchestrator just:

    READ   : the latest detection from vision, the bin sensor, the servo state
    DECIDE : should we sort this item? (armed + not busy + not in cooldown)
    ACT    : queue a tilt, record in the database, push the event to SharedState

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

        self._cooldown = float(config.get("COOLDOWN_SEC", 3.0))
        # decision loop is light -- run a few times per second is plenty.
        self._tick_interval = 0.15

        # loop bookkeeping
        self._armed = True               # ready to sort a new item?
        self._cooldown_until = 0.0
        self._last_reload = 0.0

        # tell the dashboard which backends are actually live
        state.backends = {
            "camera": self._vision.camera_backend,
            "servo": self._servo.backend,
            "sensor": self._sensor.backend,
            "model": self._vision.model_backend,
        }
        logger.info("Backends -> %s", state.backends)

        # hand SharedState to vision so its stream + detect threads can run.
        self._vision.start(state)

    # ------------------------------------------------------------------
    def run(self) -> None:
        logger.info("=" * 58)
        logger.info("  EcoSort AI - Think-and-Act loop RUNNING")
        logger.info("=" * 58)
        while self._state.running:
            try:
                self._tick()
            except Exception as exc:
                logger.exception("Loop iteration error: %s", exc)
            time.sleep(self._tick_interval)
        self._shutdown()

    # ------------------------------------------------------------------
    def _tick(self) -> None:
        now = time.monotonic()

        # --- periodic config hot-reload (for the live demo) ---
        if now - self._last_reload >= 2.0:
            self._last_reload = now
            hot_reload(self._cfg_path, self._cfg)

        # --- READ (everything happens on its own thread elsewhere) ---
        self._sensor.update()
        self._state.bin_full = self._sensor.is_full
        self._state.bin_distance_cm = self._sensor.distance_cm
        self._state.servo_state = self._servo.state

        detection = self._vision.latest_detection()
        self._state.detection = (
            {k: detection[k] for k in ("label", "confidence")}
            if detection else None
        )

        # --- DECIDE + ACT ---
        if detection is None:
            self._armed = True            # platform looks empty -> re-arm
        elif self._can_sort(now):
            self._act(detection, now)

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
