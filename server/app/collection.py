"""Data collection mode: still capture at the camera's max sustainable
rate while moving, plus a GPX track. A deliberate, narrow exception to
this repo's normal "never persist raw frames" rule (see camera.py's
docstring and the root README) -- used only for supervised drives
gathering fine-tuning footage. Off by default, must be started explicitly
every time (no auto-resume across a restart/reboot), and nothing here
uploads anywhere automatically.

Captures full-resolution (4608x2592) JPEG stills via a persistent
`picamera2` process, not video: a sustained on-device benchmark showed
stills beat continuous video outright on CPU/thermal/storage cost -- see
knowledge-base/03-hardware-deployment.md's "Capture mode benchmark and
redesign" for the full measurements.

There is deliberately no IMU/vibration-triggered burst here (an earlier
version had one, ported from edge/runtime/src/sensors.py -- removed, see
the KB's "IMU-triggered burst capture (considered, discarded)" entry for
why): a reactive trigger fires only after the vehicle is already on top of
the pothole, so a forward-facing camera can no longer see it by the time
any capture happens, no matter how fast the reaction. Coverage instead
comes entirely from capturing as densely as the hardware allows while
moving -- cheap to do (measured ~0.2-0.7 of 4 cores, well under 45C even
at max sustained rate) and the only mechanism here that is geometrically
capable of catching a defect before the vehicle reaches it. An unknown/no
GPS fix is treated as moving, not stationary: missing a data-collection
frame during a real signal dropout is worse than a handful of redundant
frames while genuinely parked.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response

from . import gps_client, gpx_recorder

try:
    from libcamera import Transform
    from picamera2 import Picamera2
except ImportError:  # pragma: no cover - not present off-device (e.g. CI)
    Transform = None
    Picamera2 = None

logger = logging.getLogger("cityguard.edge_monitor.collection")
router = APIRouter()

_CAMERA_ROTATION = os.getenv("CITYGUARD_CAMERA_ROTATION", "180")
_COLLECTION_ROOT = Path.home() / "cityguard-collection"
_LOW_DISK_RESERVE_BYTES = 5 * 1024**3
_CAPTURE_WIDTH = 4608
_CAPTURE_HEIGHT = 2592

# Below this speed, treat the vehicle as parked and stop capturing --
# `None` (no GPS fix at all) is NOT treated as stationary, see module
# docstring: a dropout during real driving must not silently skip frames.
_SPEED_STATIONARY_KMH = 3.0
_STATIONARY_POLL_S = 0.5

_lock = threading.Lock()
_state: dict = {
    "recording": False,
    "started_at": None,
    "collection_dir": None,
    "capture_thread": None,
    "stop_event": None,
    "picam2": None,
    "shot_count": 0,
    "total_bytes": 0,
    "current_speed_kmh": None,
    "capturing": False,
    "error": None,
}


def is_recording() -> bool:
    with _lock:
        return _state["recording"]


def _is_stationary(speed_kmh: float | None) -> bool:
    return speed_kmh is not None and speed_kmh < _SPEED_STATIONARY_KMH


def _capture_one(picam2: Picamera2, collection_dir: Path) -> int:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")[:-3]
    out_path = collection_dir / f"{timestamp}.jpg"
    picam2.capture_file(str(out_path))
    return out_path.stat().st_size if out_path.exists() else 0


def _capture_loop(collection_dir: Path, stop_event: threading.Event) -> None:
    transform = Transform(hflip=1, vflip=1) if _CAMERA_ROTATION == "180" else Transform()
    picam2 = Picamera2()
    try:
        config = picam2.create_still_configuration(
            main={"size": (_CAPTURE_WIDTH, _CAPTURE_HEIGHT)}, transform=transform
        )
        picam2.configure(config)
        picam2.start()
        with _lock:
            _state["picam2"] = picam2

        while not stop_event.is_set():
            speed_kmh = gps_client.get_gps().get("speed_kmh")
            stationary = _is_stationary(speed_kmh)
            with _lock:
                _state["current_speed_kmh"] = speed_kmh
                _state["capturing"] = not stationary

            if stationary:
                stop_event.wait(_STATIONARY_POLL_S)
                continue

            added_bytes = _capture_one(picam2, collection_dir)
            with _lock:
                _state["shot_count"] += 1
                _state["total_bytes"] += added_bytes
    except Exception as exc:
        logger.exception("Capture loop failed")
        with _lock:
            _state["error"] = f"Capture loop crashed: {exc}"
    finally:
        try:
            picam2.stop()
            picam2.close()
        except Exception:
            pass
        with _lock:
            _state["picam2"] = None


def _build_status() -> dict:
    with _lock:
        thread = _state["capture_thread"]
        if _state["recording"] and thread is not None and not thread.is_alive():
            # The capture thread exited on its own (crash, camera error) --
            # already-captured shots are still safe, but nothing new is
            # being captured, so don't keep reporting "recording: true".
            error = _state["error"] or "Recording stopped: capture thread exited unexpectedly."
            _stop_locked(error=error)

        recording = _state["recording"]
        started_at = _state["started_at"]
        collection_dir = _state["collection_dir"]
        shot_count = _state["shot_count"]
        total_bytes = _state["total_bytes"]
        current_speed_kmh = _state["current_speed_kmh"]
        capturing = _state["capturing"]
        error = _state["error"]

    if collection_dir is None:
        return {
            "recording": False, "started_at": None, "elapsed_seconds": 0.0,
            "collection_dir": None, "shot_count": 0,
            "total_bytes": 0, "bytes_per_second": 0.0, "free_bytes": None,
            "estimated_hours_remaining": None, "gpx_points": 0,
            "current_speed_kmh": None, "capturing": False, "error": error,
        }

    elapsed_seconds = max(1.0, (datetime.now(timezone.utc) - started_at).total_seconds()) if started_at else 1.0
    bytes_per_second = total_bytes / elapsed_seconds
    free_bytes = shutil.disk_usage(collection_dir).free
    estimated_hours_remaining = (
        round(free_bytes / bytes_per_second / 3600, 1) if bytes_per_second > 0 else None
    )

    return {
        "recording": recording,
        "started_at": started_at.isoformat() if started_at else None,
        "elapsed_seconds": round(elapsed_seconds, 1),
        "collection_dir": str(collection_dir),
        "shot_count": shot_count,
        "total_bytes": total_bytes,
        "bytes_per_second": round(bytes_per_second, 1),
        "free_bytes": free_bytes,
        "estimated_hours_remaining": estimated_hours_remaining,
        "gpx_points": gpx_recorder.point_count(collection_dir),
        "current_speed_kmh": current_speed_kmh,
        "capturing": capturing,
        "error": error,
    }


def _stop_locked(error: str | None = None) -> None:
    """Caller must hold _lock."""
    stop_event = _state["stop_event"]
    thread = _state["capture_thread"]
    if stop_event is not None:
        stop_event.set()
    if thread is not None:
        thread.join(timeout=5)
    gpx_recorder.stop()
    collection_dir = _state["collection_dir"]
    if collection_dir is not None:
        gpx_path = collection_dir / f"{collection_dir.name}.gpx"
        gpx_path.write_text(gpx_recorder.write_gpx(collection_dir), encoding="utf-8")
    _state["recording"] = False
    _state["capture_thread"] = None
    _state["stop_event"] = None
    _state["picam2"] = None
    _state["current_speed_kmh"] = None
    _state["capturing"] = False
    if error is not None:
        _state["error"] = error


def _disk_guard_loop(collection_dir: Path, stop_event: threading.Event) -> None:
    while not stop_event.wait(30):
        if shutil.disk_usage(collection_dir).free < _LOW_DISK_RESERVE_BYTES:
            logger.warning("Low disk space, auto-stopping data collection")
            with _lock:
                if _state["recording"]:
                    _stop_locked(error="Recording auto-stopped: free disk space dropped below 5 GB.")
            return


@router.post("/collection/start", status_code=201)
def start_collection():
    if Picamera2 is None:
        raise HTTPException(status_code=500, detail="picamera2/libcamera not available on this host")

    with _lock:
        if _state["recording"]:
            raise HTTPException(status_code=409, detail="Data collection is already recording")

        started_at = datetime.now(timezone.utc)
        collection_dir = _COLLECTION_ROOT / started_at.strftime("%Y%m%d_%H%M%S")
        collection_dir.mkdir(parents=True, exist_ok=True)

        stop_event = threading.Event()
        capture_thread = threading.Thread(
            target=_capture_loop, args=(collection_dir, stop_event),
            daemon=True, name="collection-capture",
        )
        capture_thread.start()

        disk_guard_thread = threading.Thread(
            target=_disk_guard_loop, args=(collection_dir, stop_event),
            daemon=True, name="collection-disk-guard",
        )
        disk_guard_thread.start()

        gpx_recorder.start(collection_dir)

        _state.update({
            "recording": True, "started_at": started_at, "collection_dir": collection_dir,
            "capture_thread": capture_thread, "stop_event": stop_event,
            "shot_count": 0, "total_bytes": 0, "error": None,
        })

    return _build_status()


@router.post("/collection/stop")
def stop_collection():
    with _lock:
        if not _state["recording"]:
            raise HTTPException(status_code=409, detail="Data collection is not recording")
        _stop_locked()
    return _build_status()


@router.get("/collection/status")
def get_collection_status():
    return _build_status()


@router.get("/collection/gpx")
def get_collection_gpx():
    with _lock:
        collection_dir = _state["collection_dir"]
    if collection_dir is None:
        raise HTTPException(status_code=404, detail="No collection session yet")
    gpx_content = gpx_recorder.write_gpx(collection_dir)
    filename = f"{collection_dir.name}.gpx"
    return Response(
        content=gpx_content,
        media_type="application/gpx+xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
