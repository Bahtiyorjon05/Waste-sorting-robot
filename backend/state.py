"""
state.py
=========
A single thread-safe object that holds the *live* state of the whole system.

The orchestrator loop (background thread) WRITES to it; the FastAPI routes
READ from it. This is the bridge that lets the dashboard show, in real time,
exactly what the Sense-Think-Act loop is doing.
"""

import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional


class SharedState:
    """Mutable, lock-protected snapshot of what the system is doing right now."""

    def __init__(self, log_history: int = 60) -> None:
        self._lock = threading.Lock()

        # --- live video ---
        self._latest_jpeg: Optional[bytes] = None   # annotated frame, JPEG bytes
        self._last_sort_jpeg: Optional[bytes] = None  # frame of the last sort

        # --- current readings ---
        self.detection: Optional[Dict[str, Any]] = None   # {label, confidence}
        self.servo_state: str = "FLAT"                    # FLAT|TILT LEFT|TILT RIGHT
        self.bin_full: bool = False
        self.bin_distance_cm: Optional[float] = None

        # --- backends actually in use (real vs simulation) ---
        self.backends: Dict[str, str] = {
            "camera": "?", "servo": "?", "sensor": "?", "model": "?",
        }

        # --- counters & history ---
        self.stats: Dict[str, int] = {"PLASTIC": 0, "PAPER": 0, "total": 0}
        self.last_sort_id: Optional[int] = None
        self._events: Deque[Dict[str, Any]] = deque(maxlen=log_history)

        # --- lifecycle ---
        self.running: bool = True
        self.started_at: float = time.time()
        self.fps: float = 0.0

    # ------------------------------------------------------------------
    # Video frame
    # ------------------------------------------------------------------
    def set_frame(self, jpeg: bytes) -> None:
        with self._lock:
            self._latest_jpeg = jpeg

    def get_frame(self) -> Optional[bytes]:
        with self._lock:
            return self._latest_jpeg

    def mark_sort_frame(self) -> None:
        """Snapshot the current frame as the 'frame of the last sort' so the
        feedback route can save it if the user taps 👎."""
        with self._lock:
            self._last_sort_jpeg = self._latest_jpeg

    def get_sort_frame(self) -> Optional[bytes]:
        with self._lock:
            return self._last_sort_jpeg

    # ------------------------------------------------------------------
    # Events / log
    # ------------------------------------------------------------------
    def add_event(self, event: Dict[str, Any]) -> None:
        """Record a sort event in the rolling log and bump the counters."""
        with self._lock:
            self._events.appendleft(event)
            label = event.get("label")
            if label in self.stats:
                self.stats[label] += 1
            self.stats["total"] += 1

    def recent_events(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._events)[:limit]

    # ------------------------------------------------------------------
    # Snapshot for the dashboard (/api/status and the SSE feed)
    # ------------------------------------------------------------------
    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "running": self.running,
                "detection": self.detection,
                "servo_state": self.servo_state,
                "bin_full": self.bin_full,
                "bin_distance_cm": self.bin_distance_cm,
                "backends": dict(self.backends),
                "stats": dict(self.stats),
                "last_sort_id": self.last_sort_id,
                "fps": round(self.fps, 1),
                "uptime_sec": int(time.time() - self.started_at),
                "events": list(self._events)[:20],
            }
