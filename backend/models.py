"""
models.py
==========
SQLAlchemy database schema for EcoSort AI.

A single table, ``sort_events``, records every sort the system performs. The
human-in-the-loop feedback (👍 / 👎) is stored back onto the same row so each
classification carries its own ground-truth label for future model retraining.
"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Integer, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SortEvent(Base):
    """One waste item classified and sorted by the platform."""

    __tablename__ = "sort_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=_utcnow, nullable=False)

    label = Column(String(16), nullable=False)        # PLASTIC | PAPER
    confidence = Column(Float, nullable=False)        # 0.0 - 1.0
    servo_action = Column(String(16), nullable=False)  # TILT LEFT | TILT RIGHT

    # Filled in later by the /api/feedback route:
    #   None       -> user has not reviewed it
    #   "correct"   -> 👍
    #   "incorrect" -> 👎  (frame image is also saved to disk for retraining)
    feedback = Column(String(16), nullable=True)
    feedback_image = Column(String(256), nullable=True)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "label": self.label,
            "confidence": round(self.confidence, 4),
            "servo_action": self.servo_action,
            "feedback": self.feedback,
        }
