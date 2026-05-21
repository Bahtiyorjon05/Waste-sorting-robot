"""
servo_controller.py
====================
The Muscle of EcoSort AI.

Drives ONE servo that tilts the sorting platform:

        TILT LEFT  (-0.8)  <--  FLAT (0.0)  -->  TILT RIGHT (+0.8)
           PLASTIC                                    PAPER

Three interchangeable backends (chosen by SERVO_BACKEND in config.yaml):
  - "gpio"        : servo wired straight to a Raspberry Pi GPIO pin (gpiozero)
  - "arduino"     : servo wired to an Arduino; the Pi sends commands over USB
                    serial (flash hardware/arduino/ecosort_servo.ino first)
  - "simulation"  : no hardware, just logs -- used on the laptop

The actual movement runs on a background worker thread so it never blocks the
camera / inference loop.
"""

import logging
import queue
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("ecosort.servo")

# --- optional imports ------------------------------------------------------
try:
    from gpiozero import Servo
except ImportError:  # pragma: no cover
    Servo = None  # type: ignore[assignment]

try:
    import serial  # pyserial
except ImportError:  # pragma: no cover
    serial = None  # type: ignore[assignment]

# label -> tilt direction
_LABEL_TO_DIRECTION = {"PLASTIC": "left", "PAPER": "right"}

# servo state strings (also shown on the dashboard)
FLAT = "FLAT"
TILT_LEFT = "TILT LEFT"
TILT_RIGHT = "TILT RIGHT"


class ServoController:
    """Non-blocking single-servo tilt controller."""

    def __init__(self, config: Dict[str, Any]) -> None:
        self._cfg = config
        self._gpio = int(config.get("SERVO_GPIO", 17))
        self._v_left = float(config.get("SERVO_TILT_LEFT", -0.8))
        self._v_flat = float(config.get("SERVO_FLAT", 0.0))
        self._v_right = float(config.get("SERVO_TILT_RIGHT", 0.8))
        self._hold = float(config.get("SERVO_HOLD_SEC", 2.0))
        self._min_pw = float(config.get("SERVO_MIN_PULSE_WIDTH", 0.0005))
        self._max_pw = float(config.get("SERVO_MAX_PULSE_WIDTH", 0.0025))

        self.state: str = FLAT
        self._busy = False
        self._servo: Any = None
        self._serial: Any = None

        self.backend = self._resolve_backend(
            str(config.get("SERVO_BACKEND", "auto")).lower()
        )
        if self.backend == "gpio":
            self._init_gpio()
        elif self.backend == "arduino":
            self._init_arduino()

        # worker thread
        self._queue: "queue.Queue" = queue.Queue()
        self._running = True
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    # ------------------------------------------------------------------
    # Backend resolution
    # ------------------------------------------------------------------
    def _resolve_backend(self, requested: str) -> str:
        if requested == "gpio":
            return "gpio" if Servo is not None else "simulation"
        if requested == "arduino":
            return "arduino" if serial is not None else "simulation"
        if requested == "simulation":
            return "simulation"
        # auto: prefer direct GPIO on the Pi, else simulate.
        if Servo is not None:
            return "gpio"
        return "simulation"

    def _init_gpio(self) -> None:
        try:
            self._servo = Servo(
                self._gpio,
                initial_value=self._v_flat,
                min_pulse_width=self._min_pw,
                max_pulse_width=self._max_pw,
            )
            logger.info("Servo ready (gpio backend, BCM pin %d).", self._gpio)
        except Exception as exc:
            logger.warning("Servo GPIO init failed: %s -> simulation.", exc)
            self._servo = None
            self.backend = "simulation"

    def _init_arduino(self) -> None:
        port = str(self._cfg.get("ARDUINO_PORT", "/dev/ttyUSB0"))
        baud = int(self._cfg.get("ARDUINO_BAUD", 9600))
        try:
            self._serial = serial.Serial(port, baud, timeout=1)
            time.sleep(2.0)  # Arduino resets when the serial port opens
            logger.info("Servo ready (arduino backend, %s @ %d).", port, baud)
        except Exception as exc:
            logger.warning("Arduino serial init failed: %s -> simulation.", exc)
            self._serial = None
            self.backend = "simulation"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def sort(self, label: str) -> bool:
        """Queue a tilt for the given label. Returns False for unsortable labels."""
        direction = _LABEL_TO_DIRECTION.get(label)
        if direction is None:
            logger.warning("'%s' is not sortable by the tilt platform.", label)
            return False
        self._queue.put(direction)
        return True

    def is_busy(self) -> bool:
        return self._busy

    def shutdown(self) -> None:
        self._running = False
        self._queue.put(None)  # sentinel
        self._worker.join(timeout=5.0)
        self._move(self._v_flat, FLAT)
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
        logger.info("[ServoController] Shut down.")

    # ------------------------------------------------------------------
    # Worker thread
    # ------------------------------------------------------------------
    def _worker_loop(self) -> None:
        while self._running:
            try:
                direction = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if direction is None:
                break
            self._busy = True
            try:
                self._execute_tilt(direction)
            except Exception as exc:
                logger.error("Tilt failed (%s): %s", direction, exc)
            finally:
                self._busy = False

    def _execute_tilt(self, direction: str) -> None:
        if direction == "left":
            self._move(self._v_left, TILT_LEFT)
        else:
            self._move(self._v_right, TILT_RIGHT)
        time.sleep(self._hold)              # let the item slide off
        self._move(self._v_flat, FLAT)      # return level

    def _move(self, value: float, state_name: str) -> None:
        """Drive the servo to ``value`` and record the human-readable state."""
        self.state = state_name
        if self.backend == "gpio" and self._servo is not None:
            try:
                self._servo.value = max(-1.0, min(1.0, value))
            except Exception as exc:
                logger.warning("Servo move error: %s", exc)
        elif self.backend == "arduino" and self._serial is not None:
            cmd = {TILT_LEFT: b"L\n", TILT_RIGHT: b"R\n", FLAT: b"F\n"}[state_name]
            try:
                self._serial.write(cmd)
            except Exception as exc:
                logger.warning("Arduino write error: %s", exc)
        else:
            logger.info("[SIM] Servo -> %s (value %.2f)", state_name, value)
