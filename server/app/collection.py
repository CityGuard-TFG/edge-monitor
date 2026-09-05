"""Data collection mode: continuous segmented raw video + GPX track.

A deliberate, narrow exception to this repo's normal "never persist raw
frames" rule (see camera.py's docstring and the root README) -- used only
for supervised drives gathering fine-tuning footage. Off by default, must be
started explicitly every time (no auto-resume across a restart/reboot), and
nothing here uploads anywhere automatically.

rpicam-vid's `--segment <ms>` breaks one continuous recording into
successive files, which is the "only lose the last N seconds on power loss"
mechanism -- no custom chunking needed. Its `-o` does NOT support strftime
placeholders together with `--segment` (confirmed on-device: it throws
"failed to generate filename"), so segments are written with the default
`clip_%04d.h264` numbering and a background thread renames each finished
segment to its own completion time once rpicam-vid has moved on to the next
number.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import signal
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response

from . import gpx_recorder

logger = logging.getLogger("cityguard.edge_monitor.collection")
router = APIRouter()

_CAMERA_ROTATION = os.getenv("CITYGUARD_CAMERA_ROTATION", "180")
_COLLECTION_ROOT = Path.home() / "cityguard-collection"
_LOW_DISK_RESERVE_BYTES = 5 * 1024**3
_SEGMENT_NAME_RE = re.compile(r"^clip_(\d+)\.h264$")
_RENAME_POLL_SECONDS = 2.0

_lock = threading.Lock()
_state: dict = {
    "recording": False,
    "started_at": None,
    "collection_dir": None,
    "process": None,
    "rename_stop_event": None,
    "rename_thread": None,
    "error": None,
}


def is_recording() -> bool:
    with _lock:
        return _state["recording"]


def _rename_finished_segments(collection_dir: Path, stop_event: threading.Event) -> None:
    """rpicam-vid keeps writing the highest-numbered clip_NNNN.h264; every
    other numbered file in the directory is finished and safe to rename."""
    renamed: set[str] = set()
    while not stop_event.wait(_RENAME_POLL_SECONDS):
        _rename_pass(collection_dir, renamed, keep_highest=True)
    # One final pass after the process has exited: nothing is "the highest
    # still-growing" file any more, so rename everything left.
    _rename_pass(collection_dir, renamed, keep_highest=False)


def _rename_pass(collection_dir: Path, renamed: set[str], keep_highest: bool) -> None:
    numbered = []
    for entry in collection_dir.iterdir():
        if entry.name == "clip_%04d.h264" and entry.stat().st_size == 0:
            # Stray 0-byte artifact rpicam-vid writes once at startup from its
            # own internal probe of the "-o" template -- not a real segment.
            entry.unlink(missing_ok=True)
            continue
        match = _SEGMENT_NAME_RE.match(entry.name)
        if match and entry.name not in renamed and entry.stat().st_size > 0:
            numbered.append((int(match.group(1)), entry))
    if not numbered:
        return
    numbered.sort(key=lambda item: item[0])
    if keep_highest:
        numbered = numbered[:-1]
    for _, entry in numbered:
        timestamp = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc)
        target = collection_dir / f"{timestamp.strftime('%Y%m%d_%H%M%S')}.h264"
        if target.exists():
            target = collection_dir / f"{timestamp.strftime('%Y%m%d_%H%M%S')}_{entry.stem.split('_')[-1]}.h264"
        entry.rename(target)
        renamed.add(entry.name)


def _segment_files(collection_dir: Path) -> list[Path]:
    if not collection_dir.exists():
        return []
    return [
        entry for entry in collection_dir.iterdir()
        if entry.suffix == ".h264" and not _SEGMENT_NAME_RE.match(entry.name) and entry.stat().st_size > 0
    ]


def _build_status() -> dict:
    with _lock:
        if _state["recording"] and _state["process"] is not None and _state["process"].poll() is not None:
            # rpicam-vid exited on its own (crash, camera error) -- the
            # segments already on disk are still safe, but nothing new is
            # being recorded, so don't keep reporting "recording: true".
            _stop_locked(error="Recording stopped: rpicam-vid exited unexpectedly.")
        recording = _state["recording"]
        started_at = _state["started_at"]
        collection_dir = _state["collection_dir"]
        error = _state["error"]

    if collection_dir is None:
        return {
            "recording": False, "started_at": None, "elapsed_seconds": 0.0,
            "collection_dir": None, "segment_count": 0, "total_bytes": 0,
            "bytes_per_second": 0.0, "free_bytes": None,
            "estimated_hours_remaining": None, "gpx_points": 0, "error": error,
        }

    segments = _segment_files(collection_dir)
    total_bytes = sum(entry.stat().st_size for entry in segments)
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
        "segment_count": len(segments),
        "total_bytes": total_bytes,
        "bytes_per_second": round(bytes_per_second, 1),
        "free_bytes": free_bytes,
        "estimated_hours_remaining": estimated_hours_remaining,
        "gpx_points": gpx_recorder.point_count(collection_dir),
        "error": error,
    }


def _stop_locked(error: str | None = None) -> None:
    """Caller must hold _lock."""
    process = _state["process"]
    if process is not None and process.poll() is None:
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    rename_stop_event = _state["rename_stop_event"]
    rename_thread = _state["rename_thread"]
    if rename_stop_event is not None:
        rename_stop_event.set()
    if rename_thread is not None:
        rename_thread.join(timeout=_RENAME_POLL_SECONDS + 2)
    gpx_recorder.stop()
    collection_dir = _state["collection_dir"]
    if collection_dir is not None:
        gpx_path = collection_dir / f"{collection_dir.name}.gpx"
        gpx_path.write_text(gpx_recorder.write_gpx(collection_dir), encoding="utf-8")
    _state["recording"] = False
    _state["process"] = None
    _state["rename_stop_event"] = None
    _state["rename_thread"] = None
    if error is not None:
        _state["error"] = error


def _disk_guard_loop(collection_dir: Path, stop_event: threading.Event) -> None:
    while not stop_event.wait(30):
        if shutil.disk_usage(collection_dir).free < _LOW_DISK_RESERVE_BYTES:
            logger.warning("Low disk space, auto-stopping data collection recording")
            with _lock:
                if _state["recording"]:
                    _stop_locked(error="Recording auto-stopped: free disk space dropped below 5 GB.")
            return


@router.post("/collection/start", status_code=201)
def start_collection(payload: dict | None = None):
    segment_ms = int((payload or {}).get("segment_ms", 60000))

    with _lock:
        if _state["recording"]:
            raise HTTPException(status_code=409, detail="Data collection is already recording")

        started_at = datetime.now(timezone.utc)
        collection_dir = _COLLECTION_ROOT / started_at.strftime("%Y%m%d_%H%M%S")
        collection_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            "rpicam-vid", "--nopreview", "-t", "0",
            "--segment", str(segment_ms),
            "--width", "2304", "--height", "1296", "--framerate", "30",
            "--bitrate", "8000000",
        ]
        if _CAMERA_ROTATION in ("0", "180"):
            cmd.extend(["--rotation", _CAMERA_ROTATION])
        cmd.extend(["-o", str(collection_dir / "clip_%04d.h264")])

        try:
            process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=500, detail="rpicam-vid not found") from exc

        rename_stop_event = threading.Event()
        rename_thread = threading.Thread(
            target=_rename_finished_segments, args=(collection_dir, rename_stop_event),
            daemon=True, name="collection-segment-rename",
        )
        rename_thread.start()

        disk_guard_thread = threading.Thread(
            target=_disk_guard_loop, args=(collection_dir, rename_stop_event),
            daemon=True, name="collection-disk-guard",
        )
        disk_guard_thread.start()

        gpx_recorder.start(collection_dir)

        _state.update({
            "recording": True, "started_at": started_at, "collection_dir": collection_dir,
            "process": process, "rename_stop_event": rename_stop_event,
            "rename_thread": rename_thread, "error": None,
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
