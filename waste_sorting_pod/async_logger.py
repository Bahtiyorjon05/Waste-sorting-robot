"""
async_logger.py
================
Logs every successful sort to a local CSV file (``sort_log.csv`` by default).
Optionally publishes each event to IBM Watson IoT Platform via MQTT in a
background thread so that logging never blocks the main Sense-Think-Act loop.
"""

import csv
import json
import logging
import os
import queue
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None  # type: ignore[assignment]


class AsyncLogger:
    """Thread-safe CSV logger with optional async MQTT upload."""

    def __init__(self, config: Dict[str, Any]) -> None:
        self._cfg = config

        # CSV
        self._log_file: str = str(config.get("LOG_FILE", "sort_log.csv"))
        self._ensure_csv_header()

        # MQTT
        self._mqtt_enabled: bool = bool(config.get("MQTT_ENABLED", False))
        self._mqtt_client: Any = None
        self._mqtt_connected: bool = False

        # Background upload queue + thread
        self._queue: queue.Queue = queue.Queue()
        self._running: bool = True
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)

        if self._mqtt_enabled:
            self._init_mqtt()

        self._worker.start()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------
    def _ensure_csv_header(self) -> None:
        """Create the CSV with a header row if it doesn't exist yet."""
        if os.path.isfile(self._log_file):
            return
        try:
            with open(self._log_file, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(["timestamp", "label", "confidence"])
            logger.info("Created log file: %s", self._log_file)
        except Exception as exc:
            logger.error("Failed to create log file: %s", exc)

    def _init_mqtt(self) -> None:
        if mqtt is None:
            logger.warning(
                "paho-mqtt is not installed. MQTT upload disabled."
            )
            self._mqtt_enabled = False
            return
        try:
            client_id = str(self._cfg.get("MQTT_CLIENT_ID", ""))
            self._mqtt_client = mqtt.Client(client_id=client_id)

            username = str(self._cfg.get("MQTT_USERNAME", ""))
            password = str(self._cfg.get("MQTT_PASSWORD", ""))
            if username:
                self._mqtt_client.username_pw_set(username, password)

            if bool(self._cfg.get("MQTT_USE_TLS", True)):
                self._mqtt_client.tls_set()

            host = str(self._cfg.get("MQTT_HOST", ""))
            port = int(self._cfg.get("MQTT_PORT", 8883))

            if not host:
                logger.warning("MQTT_HOST is empty. MQTT upload disabled.")
                self._mqtt_enabled = False
                return

            self._mqtt_client.connect(host, port, keepalive=60)
            self._mqtt_client.loop_start()
            self._mqtt_connected = True
            logger.info("MQTT connected to %s:%d.", host, port)
        except Exception as exc:
            logger.warning("MQTT init failed: %s — upload disabled.", exc)
            self._mqtt_enabled = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def log_sort(self, label: str, confidence: float) -> None:
        """Record a successful sort event (non-blocking).

        The CSV write happens immediately; MQTT upload is queued for the
        background thread.
        """
        timestamp = datetime.now(timezone.utc).isoformat()

        # Append to CSV synchronously (fast local I/O)
        try:
            with open(self._log_file, "a", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow([timestamp, label, f"{confidence:.4f}"])
        except Exception as exc:
            logger.error("CSV write failed: %s", exc)

        logger.info("Logged sort: %s (%.2f%%) at %s", label, confidence * 100, timestamp)

        # Queue for MQTT upload
        if self._mqtt_enabled:
            payload = {
                "timestamp": timestamp,
                "label": label,
                "confidence": round(confidence, 4),
            }
            self._queue.put(payload)

    def shutdown(self) -> None:
        """Flush remaining uploads and disconnect."""
        self._running = False
        self._queue.put(None)  # sentinel
        self._worker.join(timeout=5.0)
        if self._mqtt_client is not None:
            try:
                self._mqtt_client.loop_stop()
                self._mqtt_client.disconnect()
            except Exception:
                pass
        logger.info("[AsyncLogger] Shut down.")

    # ------------------------------------------------------------------
    # Worker thread – MQTT upload
    # ------------------------------------------------------------------
    def _worker_loop(self) -> None:
        topic = str(self._cfg.get("MQTT_TOPIC", "iot-2/evt/sort/fmt/json"))
        while self._running:
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                break
            if not self._mqtt_enabled or self._mqtt_client is None:
                continue
            try:
                payload_str = json.dumps(item)
                self._mqtt_client.publish(topic, payload_str, qos=1)
                logger.debug("MQTT published: %s", payload_str)
            except Exception as exc:
                logger.warning("MQTT publish failed: %s", exc)
