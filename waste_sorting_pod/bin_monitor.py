"""
bin_monitor.py
===============
Monitors bin capacity using an HC-SR04 ultrasonic sensor.

If the measured distance drops below ``BIN_FULL_THRESHOLD_CM`` (default 5 cm)
the bin is considered full and sorting should be paused until the bin is
cleared.
"""

import logging
import time
from typing import Any, Dict

logger = logging.getLogger(__name__)

try:
    from gpiozero import DistanceSensor
except ImportError:
    DistanceSensor = None  # type: ignore[assignment]


class BinMonitor:
    """Periodically reads the ultrasonic sensor and reports bin-full status."""

    def __init__(self, config: Dict[str, Any]) -> None:
        self._cfg = config
        self._sim = bool(config.get("USE_SIMULATION", True))

        self._trig_gpio: int = int(config.get("TRIG_GPIO", 23))
        self._echo_gpio: int = int(config.get("ECHO_GPIO", 24))
        self._threshold_cm: float = float(config.get("BIN_FULL_THRESHOLD_CM", 5.0))
        self._poll_interval: float = float(config.get("BIN_POLL_INTERVAL_SEC", 5.0))
        self._max_distance_m: float = float(config.get("BIN_MAX_DISTANCE_M", 1.0))
        self._sim_distance_cm: float = float(
            config.get("SIMULATED_BIN_DISTANCE_CM", 100.0)
        )

        self._sensor: Any = None
        self._is_full: bool = False
        self._last_poll_time: float = 0.0

        if not self._sim:
            self._init_sensor()
        else:
            logger.info("[BinMonitor] Running in SIMULATION mode.")

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------
    def _init_sensor(self) -> None:
        if DistanceSensor is None:
            logger.warning("gpiozero not available; switching to sim mode.")
            self._sim = True
            return
        try:
            self._sensor = DistanceSensor(
                echo=self._echo_gpio,
                trigger=self._trig_gpio,
                max_distance=self._max_distance_m,
            )
            logger.info(
                "Ultrasonic sensor ready (Trig=GPIO%d, Echo=GPIO%d).",
                self._trig_gpio,
                self._echo_gpio,
            )
        except Exception as exc:
            logger.warning("Distance sensor init failed: %s — using sim.", exc)
            self._sensor = None
            self._sim = True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def update(self) -> None:
        """Call periodically from the main loop. Reads the sensor if the poll
        interval has elapsed and updates the ``is_full`` flag."""
        now = time.monotonic()
        if now - self._last_poll_time < self._poll_interval:
            return
        self._last_poll_time = now

        distance_cm = self._read_distance_cm()
        if distance_cm is None:
            return

        was_full = self._is_full
        self._is_full = distance_cm < self._threshold_cm

        # Log state transitions
        if self._is_full and not was_full:
            logger.warning(
                "BIN FULL — distance %.1f cm (threshold %.1f cm). Sorting paused.",
                distance_cm,
                self._threshold_cm,
            )
        elif not self._is_full and was_full:
            logger.info(
                "Bin cleared — distance %.1f cm. Sorting resumed.",
                distance_cm,
            )

    @property
    def is_full(self) -> bool:
        """True when the bin distance is below the full threshold."""
        return self._is_full

    def shutdown(self) -> None:
        """Release hardware resources."""
        if self._sensor is not None:
            try:
                self._sensor.close()
            except Exception:
                pass
            self._sensor = None
        logger.info("[BinMonitor] Shut down.")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _read_distance_cm(self) -> float | None:
        if self._sim:
            return self._sim_distance_cm
        if self._sensor is None:
            return None
        try:
            return float(self._sensor.distance) * 100.0
        except Exception as exc:
            logger.warning("Distance read failed: %s", exc)
            return None
