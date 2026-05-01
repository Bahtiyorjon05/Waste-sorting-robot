"""
main.py
========
Entry-point for the Waste Sorting Pod.

Usage:
    python -m waste_sorting_pod.main --config config.yaml

Orchestrates the four modules in a continuous Sense-Think-Act loop:
    1. VisionProcessor  – capture frame & run YOLO inference
    2. BinMonitor       – check whether the bin is full
    3. ServoController  – sweep detected waste into the correct bin
    4. AsyncLogger      – log every sort to CSV (+ optional MQTT upload)
"""

import argparse
import logging
import os
import signal
import sys
import time
from typing import Any, Dict

import yaml

from .vision_processor import VisionProcessor
from .servo_controller import ServoController
from .bin_monitor import BinMonitor
from .async_logger import AsyncLogger

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("waste_sorting_pod")


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------
def load_config(path: str) -> Dict[str, Any]:
    """Load a YAML configuration file and return it as a flat dict."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
        logger.info("Configuration loaded from %s", path)
        return cfg
    except FileNotFoundError:
        logger.error("Config file not found: %s", path)
        sys.exit(1)
    except yaml.YAMLError as exc:
        logger.error("Invalid YAML in %s: %s", path, exc)
        sys.exit(1)


# Hot-reload keys that can be changed at runtime without restart
_HOT_RELOAD_KEYS = [
    "SIMULATED_BIN_DISTANCE_CM",
    "SIMULATED_DETECTION_LABEL",
    "SIMULATED_DETECTION_INTERVAL_SEC",
]


def hot_reload_config(path: str, config: Dict[str, Any]) -> None:
    """Re-read the YAML file and update the shared config dict in-place.

    Only updates keys listed in _HOT_RELOAD_KEYS so that hardware-related
    settings (GPIOs, model path, etc.) are never changed mid-run."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            fresh = yaml.safe_load(fh) or {}
        for key in _HOT_RELOAD_KEYS:
            if key in fresh and fresh[key] != config.get(key):
                logger.info("Config hot-reload: %s = %s", key, fresh[key])
                config[key] = fresh[key]
    except Exception:
        pass  # file might be mid-save; skip this cycle


# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------
_shutdown_requested = False


def _signal_handler(sig, frame):
    global _shutdown_requested
    logger.info("Shutdown signal received (%s). Stopping…", sig)
    _shutdown_requested = True


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def run(config: Dict[str, Any], config_path: str = "config.yaml") -> None:
    """Run the Sense-Think-Act loop until interrupted."""
    vision = VisionProcessor(config)
    servos = ServoController(config)
    bins = BinMonitor(config)
    log = AsyncLogger(config)

    loop_delay: float = 0.1  # seconds between loop iterations
    reload_interval: float = 2.0  # how often to re-read config.yaml
    last_reload_time: float = time.monotonic()

    logger.info("=" * 60)
    logger.info("  Waste Sorting Pod — RUNNING")
    logger.info("  Simulation: %s", config.get("USE_SIMULATION", True))
    logger.info("=" * 60)

    try:
        while not _shutdown_requested:
            # --- HOT-RELOAD config.yaml ---
            now = time.monotonic()
            if now - last_reload_time >= reload_interval:
                last_reload_time = now
                hot_reload_config(config_path, config)

            # --- SENSE: update bin status ---
            bins.update()

            # --- THINK: should we sort? ---
            if bins.is_full:
                # Bin is full — skip detection, wait for it to be cleared
                time.sleep(loop_delay)
                continue

            if servos.is_busy():
                # Servo is mid-sweep — wait for it to finish
                time.sleep(loop_delay)
                continue

            # --- SENSE: detect waste ---
            detection = vision.detect()
            if detection is None:
                time.sleep(loop_delay)
                continue

            label = detection["label"]
            confidence = detection["confidence"]
            logger.info(
                "Detection: %s (%.1f%% confidence)", label, confidence * 100
            )

            # --- ACT: sort the waste ---
            servos.sort(label)

            # --- LOG ---
            log.log_sort(label, confidence)

            time.sleep(loop_delay)

    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt — shutting down.")

    finally:
        vision.shutdown()
        servos.shutdown()
        bins.shutdown()
        log.shutdown()
        logger.info("Waste Sorting Pod stopped.")


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Waste Sorting Pod – stationary AI waste-sorting prototype."
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config.yaml",
        help="Path to the YAML configuration file (default: config.yaml).",
    )
    args = parser.parse_args()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    config = load_config(args.config)
    run(config, config_path=args.config)


if __name__ == "__main__":
    main()
