"""
routers/classify.py
====================
Read-only endpoints the dashboard uses to SEE the whole flow live:

  GET /api/status   one-shot JSON snapshot of the system
  GET /api/history  recent sort events from the database
  GET /api/stream   live MJPEG video (annotated camera feed)
  GET /api/events   Server-Sent-Events feed -> pushes a fresh snapshot ~2x/sec
"""

import asyncio
import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .. import database

logger = logging.getLogger("ecosort.api")

router = APIRouter(prefix="/api", tags=["classify"])


@router.get("/status")
async def get_status(request: Request) -> dict:
    """Current system state in one JSON object."""
    return request.app.state.shared.snapshot()


@router.get("/history")
async def get_history() -> dict:
    """The last 50 sorts recorded in the database."""
    return {"sorts": database.recent_sorts(50)}


# ---------------------------------------------------------------------------
# Live MJPEG video stream
# ---------------------------------------------------------------------------
async def _mjpeg(shared, fps: float, request: Request):
    delay = 1.0 / max(1.0, fps)
    try:
        while True:
            if await request.is_disconnected():
                break
            frame = shared.get_frame()
            if frame is not None:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(frame)).encode() + b"\r\n\r\n"
                    + frame + b"\r\n"
                )
            await asyncio.sleep(delay)
    except (asyncio.CancelledError, GeneratorExit):
        pass  # client disconnected or server shutting down -- exit quietly


@router.get("/stream")
async def video_stream(request: Request) -> StreamingResponse:
    """The annotated camera feed as a multipart MJPEG stream."""
    shared = request.app.state.shared
    fps = float(request.app.state.config.get("TARGET_FPS", 12))
    return StreamingResponse(
        _mjpeg(shared, fps, request),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


# ---------------------------------------------------------------------------
# Server-Sent-Events status feed
# ---------------------------------------------------------------------------
async def _sse(shared, request: Request):
    try:
        while True:
            if await request.is_disconnected():
                break
            yield f"data: {json.dumps(shared.snapshot())}\n\n"
            await asyncio.sleep(0.5)
    except (asyncio.CancelledError, GeneratorExit):
        pass  # client disconnected or server shutting down -- exit quietly


@router.get("/events")
async def events_stream(request: Request) -> StreamingResponse:
    """Pushes a full status snapshot to the dashboard twice per second."""
    shared = request.app.state.shared
    return StreamingResponse(
        _sse(shared, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
