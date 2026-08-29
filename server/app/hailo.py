"""Hailo-8L NPU detection via hailortcli, cached briefly to avoid spawning a
subprocess on every poll."""
import subprocess
import threading
import time
from datetime import datetime, timezone

from fastapi import APIRouter

router = APIRouter()

_CACHE_TTL_SECONDS = 10
_cache_lock = threading.Lock()
_cache = {"result": None, "fetched_at": 0.0}


def _identify():
    result = {
        "detected": False,
        "board_name": None,
        "architecture": None,
        "firmware_version": None,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "error": None,
    }
    try:
        proc = subprocess.run(
            ["hailortcli", "fw-control", "identify"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except FileNotFoundError:
        result["error"] = "hailortcli not found"
        return result
    except subprocess.TimeoutExpired:
        result["error"] = "no response from device"
        return result
    except Exception as exc:
        result["error"] = str(exc)
        return result

    if proc.returncode != 0:
        result["error"] = (proc.stderr or proc.stdout or "hailortcli failed").strip()
        return result

    def _clean(value):
        return value.strip().strip("\x00").strip()

    for line in proc.stdout.splitlines():
        line = _clean(line)
        if line.startswith("Board Name:"):
            result["board_name"] = _clean(line.split(":", 1)[1])
        elif line.startswith("Device Architecture:"):
            result["architecture"] = _clean(line.split(":", 1)[1])
        elif line.startswith("Firmware Version:"):
            result["firmware_version"] = _clean(line.split(":", 1)[1])

    result["detected"] = result["board_name"] is not None
    if not result["detected"] and result["error"] is None:
        result["error"] = "identify returned no board information"
    return result


@router.get("/hailo")
def get_hailo():
    now = time.monotonic()
    with _cache_lock:
        cached = _cache["result"]
        fresh = cached is not None and (now - _cache["fetched_at"]) < _CACHE_TTL_SECONDS
        if fresh:
            return cached

    result = _identify()
    with _cache_lock:
        _cache["result"] = result
        _cache["fetched_at"] = now
    return result
