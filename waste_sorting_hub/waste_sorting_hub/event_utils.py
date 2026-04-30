import json
from typing import Dict, Optional


def build_detection_event(class_name: str, confidence: float, x_center: int) -> str:
    payload = {
        "class": class_name,
        "confidence": round(float(confidence), 3),
        "x_center": int(x_center),
    }
    return json.dumps(payload, separators=(",", ":"))


def parse_detection_event(raw: str) -> Optional[Dict[str, object]]:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None

    class_name = data.get("class")
    confidence = data.get("confidence")
    x_center = data.get("x_center")

    if not isinstance(class_name, str):
        return None

    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        return None

    try:
        x_center = int(x_center)
    except (TypeError, ValueError):
        return None

    return {
        "class": class_name,
        "confidence": confidence,
        "x_center": x_center,
    }
