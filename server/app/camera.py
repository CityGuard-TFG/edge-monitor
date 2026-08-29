"""On-demand camera snapshot, throttled to avoid hammering the sensor.

Deliberately serves raw, unblurred JPEG frames -- this is a bring-up/alignment
tool, not the anonymization pipeline. See ../../README.md for the operational
caveat before running this near the public.
"""
import subprocess
import threading
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Response

router = APIRouter()

_MIN_CAPTURE_INTERVAL_SECONDS = 2.0
_CAPTURE_TIMEOUT_SECONDS = 5

_lock = threading.Lock()
_state = {
    "jpeg_bytes": None,
    "captured_at": None,  # datetime
    "error": None,
}


def _capture_now():
    try:
        proc = subprocess.run(
            [
                "rpicam-still",
                "--immediate",
                "--nopreview",
                "--timeout",
                "1",
                "--width",
                "1280",
                "--height",
                "720",
                "--encoding",
                "jpg",
                "-o",
                "-",
            ],
            capture_output=True,
            timeout=_CAPTURE_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        return None, "rpicam-still not found"
    except subprocess.TimeoutExpired:
        return None, "camera capture timed out"
    except Exception as exc:
        return None, str(exc)

    if proc.returncode != 0 or not proc.stdout:
        detail = (proc.stderr or b"").decode(errors="replace").strip()
        return None, detail or "camera capture failed"

    return proc.stdout, None


def _get_frame():
    """Return (jpeg_bytes, error) using the throttled cache."""
    with _lock:
        last_captured_at = _state["captured_at"]
        cached_bytes = _state["jpeg_bytes"]

    now = time.monotonic()
    stale_enough = (
        last_captured_at is None
        or (now - last_captured_at) >= _MIN_CAPTURE_INTERVAL_SECONDS
    )

    if not stale_enough and cached_bytes is not None:
        return cached_bytes, None

    jpeg_bytes, error = _capture_now()

    with _lock:
        if jpeg_bytes is not None:
            _state["jpeg_bytes"] = jpeg_bytes
            _state["captured_at"] = now
            _state["error"] = None
        else:
            _state["error"] = error
        result_bytes = _state["jpeg_bytes"]
        result_error = _state["error"] if jpeg_bytes is None else None

    return result_bytes, result_error if result_bytes is None else None


@router.get("/camera/snapshot.jpg")
def get_snapshot():
    jpeg_bytes, error = _get_frame()
    if jpeg_bytes is None:
        return Response(
            content='{"error": "camera unavailable"}',
            status_code=503,
            media_type="application/json",
        )
    return Response(content=jpeg_bytes, media_type="image/jpeg")


@router.get("/camera/status")
def get_camera_status():
    with _lock:
        captured_at = _state["captured_at"]
        error = _state["error"]
        available = _state["jpeg_bytes"] is not None

    if captured_at is not None:
        # captured_at is a monotonic timestamp; report an absolute time using
        # the offset from "now" so the frontend can compute freshness.
        age = time.monotonic() - captured_at
        last_capture_at = (
            datetime.now(timezone.utc).timestamp() - age
        )
        last_capture_at = datetime.fromtimestamp(
            last_capture_at, tz=timezone.utc
        ).isoformat()
    else:
        last_capture_at = None

    return {
        "available": available,
        "last_capture_at": last_capture_at,
        "error": error,
    }
