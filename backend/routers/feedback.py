"""
routers/feedback.py
====================
The Agentic Loop -- human-in-the-loop feedback.

The dashboard shows 👍 / 👎 buttons for the most recent sort. A 👎 means the
AI got it wrong: we save that frame to disk (labelled by the user's correction
is a future step) so the dataset grows for the next round of model retraining.

  POST /api/feedback   body: {"sort_id": 12, "verdict": "up" | "down"}
"""

import logging
import os
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import database

logger = logging.getLogger("ecosort.api")

router = APIRouter(prefix="/api", tags=["feedback"])


class FeedbackIn(BaseModel):
    sort_id: int
    verdict: str  # "up" (correct) or "down" (incorrect)


@router.post("/feedback")
async def submit_feedback(payload: FeedbackIn, request: Request):
    """Record human feedback on a sort; save the image when it was wrong."""
    config = request.app.state.config
    shared = request.app.state.shared

    if payload.verdict == "up":
        ok = database.save_feedback(payload.sort_id, "correct")
        logger.info("Feedback 👍 on sort #%s", payload.sort_id)
        return {"ok": ok, "feedback": "correct"}

    if payload.verdict == "down":
        image_path = None
        frame = shared.get_sort_frame()
        if frame is not None:
            out_dir = str(config.get("FEEDBACK_IMAGE_DIR",
                                     "edge_ai/feedback_images"))
            os.makedirs(out_dir, exist_ok=True)
            image_path = os.path.join(
                out_dir, f"sort_{payload.sort_id}_{int(time.time())}.jpg"
            )
            try:
                with open(image_path, "wb") as fh:
                    fh.write(frame)
            except Exception as exc:
                logger.error("Could not save feedback image: %s", exc)
                image_path = None
        ok = database.save_feedback(payload.sort_id, "incorrect", image_path)
        logger.info("Feedback 👎 on sort #%s (image: %s)",
                    payload.sort_id, image_path)
        return {"ok": ok, "feedback": "incorrect", "image": image_path}

    return JSONResponse(
        {"ok": False, "error": "verdict must be 'up' or 'down'"},
        status_code=400,
    )
