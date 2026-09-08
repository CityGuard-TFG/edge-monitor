"""Explicit, local-only camera collection sessions for supervised field tests.

This module is intentionally separate from the production edge privacy/upload
pipeline. It only writes local raw test captures after a person selects a mode
in the LAN dashboard. Every still session records libcamera metadata per JPEG.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response

from . import gps_client, gpx_recorder

try:
    from libcamera import Transform, controls
    from picamera2 import Picamera2
except ImportError:  # pragma: no cover - not present off-device (e.g. CI)
    Transform = None
    controls = None
    Picamera2 = None

logger = logging.getLogger("cityguard.edge_monitor.collection")
router = APIRouter()

_CAMERA_ROTATION = os.getenv("CITYGUARD_CAMERA_ROTATION", "180")
_COLLECTION_ROOT = Path.home() / "cityguard-collection"
_LOW_DISK_RESERVE_BYTES = 5 * 1024**3
_CAPTURE_WIDTH = 4608
_CAPTURE_HEIGHT = 2592
_SPEED_STATIONARY_KMH = 3.0
_STATIONARY_POLL_S = 0.5
_FOCUS_SETTLE_TIMEOUT_S = 5.0
_METADATA_FILENAME = "capture-metadata.csv"
_SESSION_FILENAME = "session.json"
_METADATA_FIELDS = [
    "filename", "timestamp_utc", "mode", "lens_position", "af_state",
    "focus_fom", "exposure_time_us", "analogue_gain", "frame_duration_us",
]


class CaptureMode(str, Enum):
    """Limited, named field-test modes; the UI cannot execute arbitrary controls."""

    FIXED_STILL = "fixed-still"
    CONTINUOUS_AF_STILL = "continuous-af-still"
    LOCKED_AF_STILL = "locked-af-still"
    MJPEG_VIDEO_BASELINE = "mjpeg-video-baseline"


MODE_DETAILS = {
    CaptureMode.FIXED_STILL: {
        "label": "Fixed focus stills (legacy baseline)", "kind": "still",
        "description": "Persistent full-resolution stills with the previous default camera controls.",
    },
    CaptureMode.CONTINUOUS_AF_STILL: {
        "label": "Continuous autofocus stills", "kind": "still",
        "description": "Persistent full-resolution stills while libcamera continuously adjusts autofocus.",
    },
    CaptureMode.LOCKED_AF_STILL: {
        "label": "Autofocus then lock stills", "kind": "still",
        "description": "Waits for autofocus to converge, then fixes the lens position for the session.",
    },
    CaptureMode.MJPEG_VIDEO_BASELINE: {
        "label": "MJPEG video baseline (experimental)", "kind": "video",
        "description": "Full-resolution MJPEG for a quality-only comparison; higher storage use and no frame-level AF metadata.",
    },
}

_lock = threading.Lock()
_state: dict[str, Any] = {
    "recording": False, "started_at": None, "collection_dir": None,
    "capture_thread": None, "stop_event": None, "picam2": None,
    "video_process": None, "shot_count": 0, "total_bytes": 0,
    "current_speed_kmh": None, "capturing": False, "error": None,
    "mode": None, "focus_configuration": None,
}


def is_recording() -> bool:
    with _lock:
        return _state["recording"]


def _is_stationary(speed_kmh: float | None) -> bool:
    return speed_kmh is not None and speed_kmh < _SPEED_STATIONARY_KMH


def _capture_timestamp() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y%m%d_%H%M%S_%f")[:-3], now.isoformat()


def _metadata_row(filename: str, timestamp: str, mode: CaptureMode, metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "filename": filename, "timestamp_utc": timestamp, "mode": mode.value,
        "lens_position": metadata.get("LensPosition"),
        "af_state": str(metadata.get("AfState")) if metadata.get("AfState") is not None else None,
        "focus_fom": metadata.get("FocusFoM"), "exposure_time_us": metadata.get("ExposureTime"),
        "analogue_gain": metadata.get("AnalogueGain"), "frame_duration_us": metadata.get("FrameDuration"),
    }


def _write_session_file(collection_dir: Path, mode: CaptureMode, focus_configuration: dict[str, Any] | None = None) -> None:
    session = {
        "started_at_utc": datetime.now(timezone.utc).isoformat(), "mode": mode.value,
        "mode_detail": MODE_DETAILS[mode],
        "camera": {"width": _CAPTURE_WIDTH, "height": _CAPTURE_HEIGHT, "rotation": _CAMERA_ROTATION},
        "focus_configuration": focus_configuration,
        "metadata_manifest": _METADATA_FILENAME if MODE_DETAILS[mode]["kind"] == "still" else None,
        "limitations": "MJPEG has no equivalent per-encoded-frame autofocus metadata." if mode is CaptureMode.MJPEG_VIDEO_BASELINE else None,
    }
    (collection_dir / _SESSION_FILENAME).write_text(json.dumps(session, indent=2) + "\n", encoding="utf-8")


def _configure_focus(picam2: Picamera2, mode: CaptureMode) -> dict[str, Any]:
    if mode is CaptureMode.FIXED_STILL:
        return {"strategy": "legacy-default-controls"}
    if controls is None:
        raise RuntimeError("libcamera autofocus controls are unavailable")
    picam2.set_controls({"AfMode": controls.AfModeEnum.Continuous})
    if mode is CaptureMode.CONTINUOUS_AF_STILL:
        return {"strategy": "continuous"}
    deadline = time.monotonic() + _FOCUS_SETTLE_TIMEOUT_S
    while time.monotonic() < deadline:
        metadata = picam2.capture_metadata()
        if metadata.get("AfState") == controls.AfStateEnum.Focused:
            lens_position = metadata.get("LensPosition")
            if lens_position is None:
                break
            picam2.set_controls({"AfMode": controls.AfModeEnum.Manual, "LensPosition": lens_position})
            return {"strategy": "autofocus-converged-then-manual-lock", "lens_position": lens_position}
        time.sleep(0.1)
    raise RuntimeError("Autofocus did not converge within 5 seconds; locked-focus session was not started")


def _capture_one(picam2: Picamera2, collection_dir: Path, mode: CaptureMode, writer: csv.DictWriter) -> int:
    name_timestamp, iso_timestamp = _capture_timestamp()
    out_path = collection_dir / f"{name_timestamp}.jpg"
    request = picam2.capture_request()
    try:
        request.save("main", str(out_path))
        metadata = request.get_metadata()
    finally:
        request.release()
    writer.writerow(_metadata_row(out_path.name, iso_timestamp, mode, metadata))
    return out_path.stat().st_size if out_path.exists() else 0


def _capture_loop(collection_dir: Path, stop_event: threading.Event, mode: CaptureMode) -> None:
    transform = Transform(hflip=1, vflip=1) if _CAMERA_ROTATION == "180" else Transform()
    picam2 = Picamera2()
    try:
        config = picam2.create_still_configuration(main={"size": (_CAPTURE_WIDTH, _CAPTURE_HEIGHT)}, transform=transform)
        picam2.configure(config)
        picam2.start()
        focus_configuration = _configure_focus(picam2, mode)
        _write_session_file(collection_dir, mode, focus_configuration)
        with _lock:
            _state["picam2"] = picam2
            _state["focus_configuration"] = focus_configuration
        with open(collection_dir / _METADATA_FILENAME, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=_METADATA_FIELDS)
            writer.writeheader()
            handle.flush()
            while not stop_event.is_set():
                speed_kmh = gps_client.get_gps().get("speed_kmh")
                stationary = _is_stationary(speed_kmh)
                with _lock:
                    _state["current_speed_kmh"] = speed_kmh
                    _state["capturing"] = not stationary
                if stationary:
                    stop_event.wait(_STATIONARY_POLL_S)
                    continue
                added_bytes = _capture_one(picam2, collection_dir, mode, writer)
                handle.flush()
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


def _video_command(output_path: Path) -> list[str]:
    return ["rpicam-vid", "--codec", "mjpeg", "--width", str(_CAPTURE_WIDTH),
            "--height", str(_CAPTURE_HEIGHT), "--framerate", "14", "--rotation", _CAMERA_ROTATION,
            "--autofocus-mode", "continuous", "--timeout", "0", "--output", str(output_path)]


def _video_loop(collection_dir: Path, stop_event: threading.Event, mode: CaptureMode) -> None:
    output_path = collection_dir / "capture.mjpeg"
    process: subprocess.Popen | None = None
    try:
        _write_session_file(collection_dir, mode)
        process = subprocess.Popen(_video_command(output_path), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        with _lock:
            _state["video_process"] = process
            _state["capturing"] = True
        while not stop_event.wait(0.5):
            return_code = process.poll()
            if return_code is not None:
                stderr = process.stderr.read() if process.stderr else ""
                raise RuntimeError(f"rpicam-vid exited with {return_code}: {stderr[-500:]}")
            if output_path.exists():
                with _lock:
                    _state["total_bytes"] = output_path.stat().st_size
    except Exception as exc:
        logger.exception("Video baseline failed")
        with _lock:
            _state["error"] = f"Video baseline crashed: {exc}"
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        with _lock:
            _state["video_process"] = None
            _state["capturing"] = False


def _build_status() -> dict[str, Any]:
    with _lock:
        thread = _state["capture_thread"]
        if _state["recording"] and thread is not None and not thread.is_alive():
            _stop_locked(error=_state["error"] or "Recording stopped: capture thread exited unexpectedly.")
        recording, started_at, collection_dir = _state["recording"], _state["started_at"], _state["collection_dir"]
        values = {key: _state[key] for key in ("shot_count", "total_bytes", "current_speed_kmh", "capturing", "error", "mode", "focus_configuration")}
    available_modes = {mode.value: MODE_DETAILS[mode] for mode in CaptureMode}
    if collection_dir is None:
        return {"recording": False, "started_at": None, "elapsed_seconds": 0.0, "collection_dir": None,
                "shot_count": 0, "total_bytes": 0, "bytes_per_second": 0.0, "free_bytes": None,
                "estimated_hours_remaining": None, "gpx_points": 0, "current_speed_kmh": None,
                "capturing": False, "error": values["error"], "mode": None, "focus_configuration": None,
                "available_modes": available_modes}
    elapsed_seconds = max(1.0, (datetime.now(timezone.utc) - started_at).total_seconds()) if started_at else 1.0
    bytes_per_second = values["total_bytes"] / elapsed_seconds
    free_bytes = shutil.disk_usage(collection_dir).free
    return {"recording": recording, "started_at": started_at.isoformat() if started_at else None,
            "elapsed_seconds": round(elapsed_seconds, 1), "collection_dir": str(collection_dir),
            "shot_count": values["shot_count"], "total_bytes": values["total_bytes"],
            "bytes_per_second": round(bytes_per_second, 1), "free_bytes": free_bytes,
            "estimated_hours_remaining": round(free_bytes / bytes_per_second / 3600, 1) if bytes_per_second > 0 else None,
            "gpx_points": gpx_recorder.point_count(collection_dir), "current_speed_kmh": values["current_speed_kmh"],
            "capturing": values["capturing"], "error": values["error"], "mode": values["mode"],
            "focus_configuration": values["focus_configuration"], "available_modes": available_modes}


def _stop_locked(error: str | None = None) -> None:
    """Caller must hold _lock."""
    stop_event, thread = _state["stop_event"], _state["capture_thread"]
    if stop_event is not None:
        stop_event.set()
    if thread is not None:
        thread.join(timeout=5)
    gpx_recorder.stop()
    collection_dir = _state["collection_dir"]
    if collection_dir is not None:
        (collection_dir / f"{collection_dir.name}.gpx").write_text(gpx_recorder.write_gpx(collection_dir), encoding="utf-8")
    _state.update({"recording": False, "capture_thread": None, "stop_event": None, "picam2": None,
                   "video_process": None, "current_speed_kmh": None, "capturing": False})
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
def start_collection(mode: CaptureMode = Query(CaptureMode.FIXED_STILL)):
    if Picamera2 is None:
        raise HTTPException(status_code=500, detail="picamera2/libcamera not available on this host")
    with _lock:
        if _state["recording"]:
            raise HTTPException(status_code=409, detail="Data collection is already recording")
        started_at = datetime.now(timezone.utc)
        collection_dir = _COLLECTION_ROOT / f"{started_at.strftime('%Y%m%d_%H%M%S')}_{mode.value}"
        collection_dir.mkdir(parents=True, exist_ok=True)
        stop_event = threading.Event()
        target = _video_loop if mode is CaptureMode.MJPEG_VIDEO_BASELINE else _capture_loop
        capture_thread = threading.Thread(target=target, args=(collection_dir, stop_event, mode), daemon=True, name="collection-capture")
        _state.update({"recording": True, "started_at": started_at, "collection_dir": collection_dir,
                       "capture_thread": capture_thread, "stop_event": stop_event, "shot_count": 0,
                       "total_bytes": 0, "current_speed_kmh": None, "capturing": False, "error": None,
                       "mode": mode.value, "focus_configuration": None})
        capture_thread.start()
        threading.Thread(target=_disk_guard_loop, args=(collection_dir, stop_event), daemon=True, name="collection-disk-guard").start()
        gpx_recorder.start(collection_dir)
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
    return Response(content=gpx_recorder.write_gpx(collection_dir), media_type="application/gpx+xml",
                    headers={"Content-Disposition": f'attachment; filename="{collection_dir.name}.gpx"'})
