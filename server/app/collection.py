"""Data collection mode: adaptive-interval + IMU-triggered still capture,
plus a GPX track. A deliberate, narrow exception to this repo's normal
"never persist raw frames" rule (see camera.py's docstring and the root
README) -- used only for supervised drives gathering fine-tuning footage.
Off by default, must be started explicitly every time (no auto-resume
across a restart/reboot), and nothing here uploads anywhere automatically.

Captures full-resolution (4608x2592) JPEG stills via a persistent
`picamera2` process, not video: a sustained on-device benchmark showed this
matches the production pipeline's own capture paradigm
(edge/runtime/src/sensors.py's speed-adaptive interval + IMU-triggered
event capture) far more closely than continuous video ever could, at a
fraction of the CPU/thermal cost -- see
knowledge-base/03-hardware-deployment.md's "Capture mode benchmark and
redesign" for the full measurements. The interval thresholds and the
1.5g vibration threshold below are ported from that same sensors.py, not
re-derived, so the collected dataset and the deployed capture behavior
stay in sync.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response
from libcamera import Transform
from picamera2 import Picamera2

from . import gps_client, gpx_recorder, imu

logger = logging.getLogger("cityguard.edge_monitor.collection")
router = APIRouter()

_CAMERA_ROTATION = os.getenv("CITYGUARD_CAMERA_ROTATION", "180")
_COLLECTION_ROOT = Path.home() / "cityguard-collection"
_LOW_DISK_RESERVE_BYTES = 5 * 1024**3
_CAPTURE_WIDTH = 4608
_CAPTURE_HEIGHT = 2592

# Ported from edge/runtime/src/sensors.py -- keep these in sync with that
# file rather than retuning independently, so the dataset this collects
# matches the interval/event behavior the deployed pipeline actually uses.
_SPEED_STATIONARY_KMH = 3.0
_SPEED_SLOW_KMH = 15.0
_SPEED_FAST_KMH = 50.0
_INTERVAL_STATIONARY_S = 0.0  # 0 = skip capture entirely
_INTERVAL_SLOW_S = 5.0
_INTERVAL_NORMAL_S = 2.5
_INTERVAL_FAST_S = 1.5

_EVENT_BURST_SHOTS = 3
_EVENT_BURST_GAP_S = 0.15
_POLL_GRANULARITY_S = 0.5

_lock = threading.Lock()
_state: dict = {
    "recording": False,
    "started_at": None,
    "collection_dir": None,
    "capture_thread": None,
    "stop_event": None,
    "picam2": None,
    "shot_count": 0,
    "event_count": 0,
    "total_bytes": 0,
    "current_speed_kmh": None,
    "current_interval_s": None,
    "error": None,
}


def is_recording() -> bool:
    with _lock:
        return _state["recording"]


def _interval_for_speed(speed_kmh: float | None) -> float:
    if speed_kmh is None or speed_kmh < _SPEED_STATIONARY_KMH:
        return _INTERVAL_STATIONARY_S
    if speed_kmh < _SPEED_SLOW_KMH:
        return _INTERVAL_SLOW_S
    if speed_kmh < _SPEED_FAST_KMH:
        return _INTERVAL_NORMAL_S
    return _INTERVAL_FAST_S


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
            interval = _interval_for_speed(speed_kmh)
            with _lock:
                _state["current_speed_kmh"] = speed_kmh
                _state["current_interval_s"] = interval

            if imu.peek_event():
                added_bytes = 0
                for _ in range(_EVENT_BURST_SHOTS):
                    added_bytes += _capture_one(picam2, collection_dir)
                    if stop_event.wait(_EVENT_BURST_GAP_S):
                        break
                with _lock:
                    _state["shot_count"] += _EVENT_BURST_SHOTS
                    _state["event_count"] += 1
                    _state["total_bytes"] += added_bytes
                continue

            if interval > 0:
                added_bytes = _capture_one(picam2, collection_dir)
                with _lock:
                    _state["shot_count"] += 1
                    _state["total_bytes"] += added_bytes
                remaining = interval
                while remaining > 0 and not stop_event.is_set():
                    step = min(_POLL_GRANULARITY_S, remaining)
                    if stop_event.wait(step):
                        break
                    remaining -= step
            else:
                # Stationary: don't busy-loop, just poll speed periodically.
                stop_event.wait(_POLL_GRANULARITY_S)
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
        event_count = _state["event_count"]
        total_bytes = _state["total_bytes"]
        current_speed_kmh = _state["current_speed_kmh"]
        current_interval_s = _state["current_interval_s"]
        error = _state["error"]

    if collection_dir is None:
        return {
            "recording": False, "started_at": None, "elapsed_seconds": 0.0,
            "collection_dir": None, "shot_count": 0, "event_count": 0,
            "total_bytes": 0, "bytes_per_second": 0.0, "free_bytes": None,
            "estimated_hours_remaining": None, "gpx_points": 0,
            "current_speed_kmh": None, "current_interval_s": None,
            "current_vibration_g": None, "error": error,
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
        "event_count": event_count,
        "total_bytes": total_bytes,
        "bytes_per_second": round(bytes_per_second, 1),
        "free_bytes": free_bytes,
        "estimated_hours_remaining": estimated_hours_remaining,
        "gpx_points": gpx_recorder.point_count(collection_dir),
        "current_speed_kmh": current_speed_kmh,
        "current_interval_s": current_interval_s,
        "current_vibration_g": imu.latest_vibration_g(),
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
    imu.stop()
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
    _state["current_interval_s"] = None
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

        imu.start()
        gpx_recorder.start(collection_dir)

        _state.update({
            "recording": True, "started_at": started_at, "collection_dir": collection_dir,
            "capture_thread": capture_thread, "stop_event": stop_event,
            "shot_count": 0, "event_count": 0, "total_bytes": 0, "error": None,
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
