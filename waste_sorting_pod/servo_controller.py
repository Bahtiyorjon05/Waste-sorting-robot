"""
servo_controller.py
====================
Controls dual MG996R servos to sweep detected waste into the correct bin.

Mapping:
    Plastic  → Left servo  (GPIO 17)
    Paper    → Right servo (GPIO 27)
    Metal    → Dual sweep  (both servos, configurable)

Actuation runs in a background worker thread so it never blocks the camera
processing loop.
"""

import logging
import queue
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

try:
    from gpiozero import AngularServo
except ImportError:
    AngularServo = None  # type: ignore[assignment]

# Label → servo target mapping
_LABEL_TO_SERVO = {
    "Plastic": "left",
    "Paper": "right",
    "Metal": "both",
}


class ServoController:
    """Non-blocking servo actuation via a background worker thread."""

    def __init__(self, config: Dict[str, Any]) -> None:
        self._cfg = config
        self._sim = bool(config.get("USE_SIMULATION", True))

        self._left_gpio: int = int(config.get("LEFT_SERVO_GPIO", 17))
        self._right_gpio: int = int(config.get("RIGHT_SERVO_GPIO", 27))
        self._sweep_angle: float = float(config.get("SERVO_SWEEP_ANGLE_DEG", 90.0))
        self._hold_sec: float = float(config.get("SERVO_HOLD_SEC", 1.0))
        self._min_pw: float = float(config.get("SERVO_MIN_PULSE_WIDTH", 0.0005))
        self._max_pw: float = float(config.get("SERVO_MAX_PULSE_WIDTH", 0.0025))

        self._left_servo: Any = None
        self._right_servo: Any = None
        self._busy = False

        # Work queue + daemon thread
        self._queue: queue.Queue = queue.Queue()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)

        if not self._sim:
            self._init_servos()
        else:
            logger.info("[ServoController] Running in SIMULATION mode.")

        self._running = True
        self._worker.start()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------
    def _init_servos(self) -> None:
        if AngularServo is None:
            logger.warning("gpiozero not available; switching to sim mode.")
            self._sim = True
            return
        try:
            self._left_servo = AngularServo(
                self._left_gpio,
                min_angle=0.0,
                max_angle=self._sweep_angle,
                min_pulse_width=self._min_pw,
                max_pulse_width=self._max_pw,
                initial_angle=0.0,
            )
            self._right_servo = AngularServo(
                self._right_gpio,
                min_angle=0.0,
                max_angle=self._sweep_angle,
                min_pulse_width=self._min_pw,
                max_pulse_width=self._max_pw,
                initial_angle=0.0,
            )
            logger.info(
                "Servos initialised (left=GPIO%d, right=GPIO%d).",
                self._left_gpio,
                self._right_gpio,
            )
        except Exception as exc:
            logger.warning("Servo init failed: %s — falling back to sim.", exc)
            self._left_servo = None
            self._right_servo = None
            self._sim = True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def sort(self, label: str) -> None:
        """Enqueue a sort action for the given label (non-blocking)."""
        target = _LABEL_TO_SERVO.get(label)
        if target is None:
            logger.warning("Unknown label '%s'; ignoring.", label)
            return
        self._queue.put((label, target))

    def is_busy(self) -> bool:
        """Return True while a servo sweep is in progress."""
        return self._busy

    def shutdown(self) -> None:
        """Signal the worker to stop and wait for it to finish."""
        self._running = False
        self._queue.put(None)  # sentinel
        self._worker.join(timeout=5.0)
        logger.info("[ServoController] Shut down.")

    # ------------------------------------------------------------------
    # Worker thread
    # ------------------------------------------------------------------
    def _worker_loop(self) -> None:
        while self._running:
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                break
            label, target = item
            self._busy = True
            try:
                self._execute_sweep(label, target)
            except Exception as exc:
                logger.error("Sweep failed for '%s': %s", label, exc)
            finally:
                self._busy = False

    def _execute_sweep(self, label: str, target: str) -> None:
        if target in ("left", "both"):
            self._sweep(self._left_servo, "left", label)
        if target in ("right", "both"):
            self._sweep(self._right_servo, "right", label)

    def _sweep(self, servo: Any, side: str, label: str) -> None:
        if self._sim or servo is None:
            logger.info("[SIM] Sweep %s servo for '%s'.", side, label)
            time.sleep(self._hold_sec)
            return
        try:
            servo.angle = self._sweep_angle
            time.sleep(self._hold_sec)
            servo.angle = 0.0
            logger.info("Swept %s servo for '%s'.", side, label)
        except Exception as exc:
            logger.warning("Servo sweep error (%s): %s", side, exc)
