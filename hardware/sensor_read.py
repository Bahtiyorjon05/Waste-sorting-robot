"""
sensor_read.py
===============
HC-SR04 ultrasonic sensor that watches how full the bin is.

If something is closer than BIN_FULL_THRESHOLD_CM the bin is considered full
and the orchestrator pauses sorting until it is emptied.

Backends (SENSOR_BACKEND in config.yaml):
  - "gpio"        : real HC-SR04 on the Pi (gpiozero.DistanceSensor)
  - "simulation"  : reads SIMULATED_BIN_DISTANCE_CM from config (hot-reloadable)
"""

import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("ecosort.sensor")

try:
    from gpiozero import DistanceSensor
except ImportError:  # pragma: no cover
    DistanceSensor = None  # type: ignore[assignment]


class BinSensor:
    """Polls the ultrasonic sensor and reports whether the bin is full."""

    def __init__(self, config: Dict[str, Any]) -> None:
        self._cfg = config
        self._trig = int(config.get("TRIG_GPIO", 23))
        self._echo = int(config.get("ECHO_GPIO", 24))
        self._threshold = float(config.get("BIN_FULL_THRESHOLD_CM", 8.0))
        self._poll_interval = float(config.get("BIN_POLL_INTERVAL_SEC", 3.0))
        self._max_distance_m = float(config.get("BIN_MAX_DISTANCE_M", 1.0))

        self.is_full = False
        self.distance_cm: Optional[float] = None
        self._last_poll = 0.0
        self._sensor: Any = None

        self.backend = self._resolve_backend(
            str(config.get("SENSOR_BACKEND", "auto")).lower()
        )
        if self.backend == "gpio":
            self._init_gpio()

    # ------------------------------------------------------------------
    def _resolve_backend(self, requested: str) -> str:
        if requested == "gpio":
            return "gpio" if DistanceSensor is not None else "simulation"
        if requested == "simulation":
            return "simulation"
        return "gpio" if DistanceSensor is not None else "simulation"

    def _init_gpio(self) -> None:
        try:
            self._sensor = DistanceSensor(
                echo=self._echo, trigger=self._trig,
                max_distance=self._max_distance_m,
            )
            logger.info("Bin sensor ready (gpio: Trig=%d, Echo=%d).",
                        self._trig, self._echo)
        except Exception as exc:
            logger.warning("HC-SR04 init failed: %s -> simulation.", exc)
            self._sensor = None
            self.backend = "simulation"

    # ------------------------------------------------------------------
    def update(self) -> None:
        """Call every loop. Re-reads the sensor when the poll interval elapses."""
        now = time.monotonic()
        if now - self._last_poll < self._poll_interval:
            return
        self._last_poll = now

        distance = self._read_distance_cm()
        if distance is None:
            return
        self.distance_cm = distance

        was_full = self.is_full
        self.is_full = distance < self._threshold
        if self.is_full and not was_full:
            logger.warning("BIN FULL (%.1f cm) - sorting paused.", distance)
        elif not self.is_full and was_full:
            logger.info("Bin cleared (%.1f cm) - sorting resumed.", distance)

    def _read_distance_cm(self) -> Optional[float]:
        if self.backend == "simulation" or self._sensor is None:
            return float(self._cfg.get("SIMULATED_BIN_DISTANCE_CM", 30.0))
        try:
            return float(self._sensor.distance) * 100.0
        except Exception as exc:
            logger.warning("Distance read failed: %s", exc)
            return None

    def shutdown(self) -> None:
        if self._sensor is not None:
            try:
                self._sensor.close()
            except Exception:
                pass
        logger.info("[BinSensor] Shut down.")
