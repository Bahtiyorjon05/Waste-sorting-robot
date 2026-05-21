"""
database.py
============
SQLite database setup via SQLAlchemy. Holds the engine + session factory and
a few small helpers the rest of the backend uses to record and query sorts.

SQLite is used with ``check_same_thread=False`` because the orchestrator loop
(a background thread) and the FastAPI request handlers both touch the DB.
"""

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine, desc
from sqlalchemy.orm import sessionmaker

from .models import Base, SortEvent

logger = logging.getLogger("ecosort.database")

_engine = None
_Session: Optional[sessionmaker] = None


def init_db(database_url: str) -> None:
    """Create the engine, the session factory, and the tables (idempotent)."""
    global _engine, _Session
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    _engine = create_engine(database_url, connect_args=connect_args, future=True)
    _Session = sessionmaker(bind=_engine, expire_on_commit=False)
    Base.metadata.create_all(_engine)
    logger.info("Database ready: %s", database_url)


def record_sort(label: str, confidence: float, servo_action: str) -> int:
    """Insert a new sort event and return its database id."""
    if _Session is None:
        raise RuntimeError("init_db() was never called")
    with _Session() as session:
        event = SortEvent(
            label=label, confidence=confidence, servo_action=servo_action
        )
        session.add(event)
        session.commit()
        return int(event.id)


def save_feedback(sort_id: int, feedback: str,
                  image_path: Optional[str] = None) -> bool:
    """Attach human feedback ('correct'/'incorrect') to an existing sort row."""
    if _Session is None:
        raise RuntimeError("init_db() was never called")
    with _Session() as session:
        event = session.get(SortEvent, sort_id)
        if event is None:
            return False
        event.feedback = feedback
        if image_path:
            event.feedback_image = image_path
        session.commit()
        return True


def recent_sorts(limit: int = 20) -> List[Dict[str, Any]]:
    """Return the most recent sort events, newest first."""
    if _Session is None:
        return []
    with _Session() as session:
        rows = (
            session.query(SortEvent)
            .order_by(desc(SortEvent.timestamp))
            .limit(limit)
            .all()
        )
        return [r.as_dict() for r in rows]
