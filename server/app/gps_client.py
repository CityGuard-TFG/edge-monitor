"""Background gpsd client. Keeps a thread-safe snapshot of the last known
GPS fix/quality so the HTTP endpoint is always a fast, non-blocking read.
"""
import threading
import time
from datetime import datetime, timezone

from fastapi import APIRouter

router = APIRouter()

try:
    import gps as gpsd_module
except ImportError:
    gpsd_module = None

_RECONNECT_DELAY_SECONDS = 5
_FIX_NAMES = {0: "none", 1: "none", 2: "2d", 3: "3d"}

_lock = threading.Lock()
_state = {
    "fix": "none",
    "satellites_used": None,
    "satellites_visible": None,
    "latitude": None,
    "longitude": None,
    "altitude_m": None,
    "speed_kmh": None,
    "hdop": None,
    "last_update": None,
    "gpsd_connected": False,
}


def _apply_tpv(report):
    with _lock:
        mode = getattr(report, "mode", 1)
        _state["fix"] = _FIX_NAMES.get(mode, "none")
        _state["latitude"] = getattr(report, "lat", None)
        _state["longitude"] = getattr(report, "lon", None)
        alt = getattr(report, "altHAE", None)
        if alt is None:
            alt = getattr(report, "alt", None)
        _state["altitude_m"] = alt
        speed_mps = getattr(report, "speed", None)
        _state["speed_kmh"] = speed_mps * 3.6 if speed_mps is not None else None
        _state["last_update"] = datetime.now(timezone.utc).isoformat()


def _apply_sky(report):
    satellites = getattr(report, "satellites", None)
    with _lock:
        if satellites is not None:
            _state["satellites_visible"] = len(satellites)
            used = [s for s in satellites if getattr(s, "used", False)]
            _state["satellites_used"] = len(used)
        elif getattr(report, "nSat", None) is not None:
            _state["satellites_visible"] = report.nSat
        hdop = getattr(report, "hdop", None)
        if hdop is not None:
            _state["hdop"] = hdop


def _run_client_loop():
    while True:
        try:
            session = gpsd_module.gps(mode=gpsd_module.WATCH_ENABLE)
        except Exception:
            with _lock:
                _state["gpsd_connected"] = False
            time.sleep(_RECONNECT_DELAY_SECONDS)
            continue

        with _lock:
            _state["gpsd_connected"] = True

        try:
            while True:
                report = next(session)
                if report is None:
                    continue
                cls = getattr(report, "class", None)
                if cls == "TPV":
                    _apply_tpv(report)
                elif cls == "SKY":
                    _apply_sky(report)
        except StopIteration:
            pass
        except (OSError, ConnectionRefusedError):
            pass
        except Exception:
            pass

        with _lock:
            _state["gpsd_connected"] = False
        time.sleep(_RECONNECT_DELAY_SECONDS)


def start_background_thread():
    if gpsd_module is None:
        return
    thread = threading.Thread(target=_run_client_loop, daemon=True)
    thread.start()


@router.get("/gps")
def get_gps():
    with _lock:
        return dict(_state)
