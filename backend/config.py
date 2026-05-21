"""
config.py
=========
Loads ``config.yaml`` into a plain dict and supports live hot-reload of a few
safe keys (used for the simulation demo) without restarting the server.
"""

import logging
import sys
from typing import Any, Dict

import yaml

logger = logging.getLogger("ecosort.config")

# Keys that may be changed while the system is running. Hardware keys (GPIO
# pins, model path, ports) are deliberately excluded -- those need a restart.
_HOT_RELOAD_KEYS = (
    "SIMULATED_DETECTION_LABEL",
    "SIMULATED_DETECTION_INTERVAL_SEC",
    "SIMULATED_BIN_DISTANCE_CM",
    "CONFIDENCE_THRESHOLD",
    "COOLDOWN_SEC",
    "SERVO_HOLD_SEC",
)


def load_config(path: str) -> Dict[str, Any]:
    """Read the YAML config file and return it as a flat dict."""
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


def hot_reload(path: str, config: Dict[str, Any]) -> None:
    """Re-read the file and update the live ``config`` dict in-place.

    Only keys in ``_HOT_RELOAD_KEYS`` are touched. Any error (e.g. the file is
    mid-save) is swallowed so the loop never crashes over a config edit.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            fresh = yaml.safe_load(fh) or {}
    except Exception:
        return
    for key in _HOT_RELOAD_KEYS:
        if key in fresh and fresh[key] != config.get(key):
            logger.info("Config hot-reload: %s = %s", key, fresh[key])
            config[key] = fresh[key]
