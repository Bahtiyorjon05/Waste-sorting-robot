"""
sensor_read.py
===============
HC-SR04 ultrasonic sensor that watches how full the bin is.

If something is closer than BIN_FULL_THRESHOLD_CM the bin is considered full
and the orchestrator pauses sorting until it is emptied.

Backends (SENSOR_BACKEND in config.yaml):
  - "gpio"        : real HC-SR04 on the Pi (gpiozero.DistanceSensor)
  - "simulation"  : reads SIMULATED_BIN_DISTANCE_CM from config (hot-reloadable)

The real sensor is read on a BACKGROUND THREAD. gpiozero's ``.distance`` blocks
until it has collected enough echo samples -- if the sensor is absent or
miswired, that call never returns. Keeping it off the main thread means a
missing sensor can never freeze the Sense-Think-Act loop.
"""

import logging
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("ecosort.sensor")

try:
    from gpiozero import DistanceSensor
except ImportError:  # pragma: no cover
    DistanceSensor = None  # type: ignore[assignment]


class BinSensor:
    """Reports whether the bin is full, without ever blocking the main loop."""

    def __init__(self, config: Dict[str, Any]) -> None:
        self._cfg = config
        self._trig = int(config.get("TRIG_GPIO", 23))
        self._echo = int(config.get("ECHO_GPIO", 24))
        self._threshold = float(config.get("BIN_FULL_THRESHOLD_CM", 8.0))
        self._poll_interval = float(config.get("BIN_POLL_INTERVAL_SEC", 3.0))
        self._max_distance_m = float(config.get("BIN_MAX_DISTANCE_M", 1.0))

        self.is_full: bool = False
        self.distance_cm: Optional[float] = None

        self._sensor: Any = None
        self._running = False
        self._thread: Any = None

        self.backend = self._resolve_backend(
            str(config.get("SENSOR_BACKEND", "auto")).lower()
        )
        if self.backend == "gpio":
            self._init_gpio()

        # Background reader thread for the real sensor.
        if self.backend == "gpio" and self._sensor is not None:
            self._running = True
            self._thread = threading.Thread(
                target=self._read_loop, daemon=True, name="bin-sensor"
            )
            self._thread.start()

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
    def _read_loop(self) -> None:
        """Background thread: poll the real ultrasonic sensor. The ``.distance``
        read may block when no echo returns -- harmless here, off the hot path."""
        while self._running:
            try:
                distance = float(self._sensor.distance) * 100.0
                self.distance_cm = distance
                was_full = self.is_full
                self.is_full = distance < self._threshold
                if self.is_full and not was_full:
                    logger.warning("BIN FULL (%.1f cm) - sorting paused.",
                                   distance)
                elif not self.is_full and was_full:
                    logger.info("Bin cleared (%.1f cm) - sorting resumed.",
                                distance)
            except Exception as exc:
                logger.debug("distance read error: %s", exc)
            time.sleep(self._poll_interval)

    # ------------------------------------------------------------------
    def update(self) -> None:
        """Call every loop. Non-blocking. For the real sensor the background
        thread does the work; here we only service the simulation backend."""
        if self.backend == "simulation":
            distance = float(self._cfg.get("SIMULATED_BIN_DISTANCE_CM", 30.0))
            self.distance_cm = distance
            self.is_full = distance < self._threshold

    def shutdown(self) -> None:
        """Release the sensor."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._sensor is not None:
            try:
                self._sensor.close()
            except Exception:
                pass
        logger.info("[BinSensor] Shut down.")
