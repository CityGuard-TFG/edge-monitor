"""Background gpsd client and NMEA parser.

Connects to the local gpsd daemon (port 2947) via streaming socket with
JSON and NMEA enabled, maintaining a thread-safe, non-blocking telemetry snapshot
of satellite signals, constellation breakdown, precision dilution metrics,
and positioning fixes.
"""
import json
import logging
import socket
import threading
import time
from datetime import datetime, timezone

from fastapi import APIRouter

logger = logging.getLogger("cityguard.edge_monitor.gps")
router = APIRouter()

_RECONNECT_DELAY_SECONDS = 3
_SATELLITE_TIMEOUT_SECONDS = 12.0

_FIX_NAMES = {0: "none", 1: "none", 2: "2d", 3: "3d"}

_GNSS_PREFIX_MAP = {
    "GP": "GPS",
    "GL": "GLONASS",
    "BD": "BeiDou",
    "GB": "BeiDou",
    "GA": "Galileo",
    "QZ": "QZSS",
    "GQ": "QZSS",
    "SB": "SBAS",
    "GN": "GNSS",
}

_lock = threading.Lock()
_sat_cache = {}  # prn -> dict(prn, gnss, elevation, azimuth, snr, used, last_seen)

_state = {
    "fix": "none",
    "satellites_used": None,
    "satellites_visible": None,
    "satellites": [],
    "constellations": {
        "GPS": 0,
        "GLONASS": 0,
        "BeiDou": 0,
        "Galileo": 0,
    },
    "avg_snr_db": None,
    "signal_quality": "none",
    "latitude": None,
    "longitude": None,
    "altitude_m": None,
    "speed_kmh": None,
    "track_deg": None,
    "climb_mps": None,
    "hdop": None,
    "vdop": None,
    "pdop": None,
    "gdop": None,
    "tdop": None,
    "epx": None,
    "epy": None,
    "epv": None,
    "eps_kmh": None,
    "time": None,
    "last_update": None,
    "gpsd_connected": False,
    "driver": None,
}


def classify_gnss(prn: int, prefix: str = None) -> str:
    if prefix and prefix in _GNSS_PREFIX_MAP and _GNSS_PREFIX_MAP[prefix] != "GNSS":
        return _GNSS_PREFIX_MAP[prefix]
    if 1 <= prn <= 32:
        return "GPS"
    elif 33 <= prn <= 64:
        return "SBAS"
    elif 65 <= prn <= 96:
        return "GLONASS"
    elif 193 <= prn <= 200:
        return "QZSS"
    elif 201 <= prn <= 260 or 400 <= prn <= 460:
        return "BeiDou"
    elif 301 <= prn <= 336:
        return "Galileo"
    return "GNSS"


def parse_gsv_sentence(line: str, now: float = None):
    """Parse NMEA GSV (Satellites in View) sentences."""
    if now is None:
        now = time.time()
    try:
        content = line.split("*")[0]
        parts = content.split(",")
        if len(parts) < 4:
            return
        prefix = parts[0][1:3].upper() if len(parts[0]) >= 3 else "GN"
        
        idx = 4
        while idx + 3 < len(parts):
            prn_str = parts[idx].strip()
            if prn_str:
                try:
                    prn = int(prn_str)
                    el_str = parts[idx + 1].strip()
                    az_str = parts[idx + 2].strip()
                    snr_str = parts[idx + 3].strip()

                    el = int(el_str) if el_str else None
                    az = int(az_str) if az_str else None
                    snr = float(snr_str) if snr_str else None

                    existing = _sat_cache.get(prn, {})
                    _sat_cache[prn] = {
                        "prn": prn,
                        "gnss": classify_gnss(prn, prefix),
                        "elevation": el if el is not None else existing.get("elevation"),
                        "azimuth": az if az is not None else existing.get("azimuth"),
                        "snr": snr,
                        "used": existing.get("used", False),
                        "last_seen": now,
                    }
                except ValueError:
                    pass
            idx += 4
    except Exception:
        pass


def parse_gsa_sentence(line: str):
    """Parse NMEA GSA (DOP and active satellites) sentences."""
    try:
        content = line.split("*")[0]
        parts = content.split(",")
        if len(parts) < 18:
            return
        
        mode_str = parts[2].strip()
        used_prns = set()
        for p_str in parts[3:15]:
            p_str = p_str.strip()
            if p_str:
                try:
                    used_prns.add(int(p_str))
                except ValueError:
                    pass

        with _lock:
            if mode_str in ("1", "2", "3"):
                _state["fix"] = _FIX_NAMES.get(int(mode_str), "none")
            
            for prn, sat in _sat_cache.items():
                if prn in used_prns:
                    sat["used"] = True

            try:
                if parts[15].strip():
                    _state["pdop"] = float(parts[15].strip())
                if parts[16].strip():
                    _state["hdop"] = float(parts[16].strip())
                if parts[17].strip():
                    _state["vdop"] = float(parts[17].strip())
            except (ValueError, IndexError):
                pass
    except Exception:
        pass


def _compile_satellites_summary(now: float = None):
    """Prune stale satellites and compute constellation counts and average SNR."""
    if now is None:
        now = time.time()
    
    stale = [prn for prn, data in _sat_cache.items() if now - data["last_seen"] > _SATELLITE_TIMEOUT_SECONDS]
    for prn in stale:
        del _sat_cache[prn]

    active_sats = list(_sat_cache.values())
    # Sort: used first, then highest SNR, then PRN
    active_sats.sort(
        key=lambda s: (
            0 if s["used"] else 1,
            -(s["snr"] if s["snr"] is not None else -1),
            s["prn"],
        )
    )

    const_counts = {"GPS": 0, "GLONASS": 0, "BeiDou": 0, "Galileo": 0}
    snr_vals = []
    used_count = 0

    clean_sat_list = []
    for s in active_sats:
        gnss = s["gnss"]
        if gnss in const_counts:
            const_counts[gnss] += 1
        else:
            const_counts.setdefault(gnss, 0)
            const_counts[gnss] += 1
        
        if s["used"]:
            used_count += 1
        
        if s["snr"] is not None and s["snr"] > 0:
            snr_vals.append(s["snr"])
        
        clean_sat_list.append({
            "prn": s["prn"],
            "gnss": s["gnss"],
            "elevation": s["elevation"],
            "azimuth": s["azimuth"],
            "snr": s["snr"],
            "used": s["used"],
        })

    avg_snr = round(sum(snr_vals) / len(snr_vals), 1) if snr_vals else None

    if avg_snr is not None:
        if avg_snr >= 33.0:
            quality = "good"
        elif avg_snr >= 22.0:
            quality = "moderate"
        else:
            quality = "weak"
    else:
        quality = "none"

    _state["satellites"] = clean_sat_list
    _state["satellites_visible"] = len(clean_sat_list)
    _state["satellites_used"] = used_count
    _state["constellations"] = const_counts
    _state["avg_snr_db"] = avg_snr
    _state["signal_quality"] = quality


def _apply_tpv(report: dict):
    with _lock:
        mode = report.get("mode", 1)
        _state["fix"] = _FIX_NAMES.get(mode, "none")
        _state["latitude"] = report.get("lat")
        _state["longitude"] = report.get("lon")
        
        alt = report.get("altHAE")
        if alt is None:
            alt = report.get("alt")
        _state["altitude_m"] = round(alt, 1) if alt is not None else None
        
        speed_mps = report.get("speed")
        _state["speed_kmh"] = round(speed_mps * 3.6, 1) if speed_mps is not None else None
        
        track = report.get("track")
        _state["track_deg"] = round(track, 1) if track is not None else None
        
        climb = report.get("climb")
        _state["climb_mps"] = round(climb, 2) if climb is not None else None
        
        epx = report.get("epx")
        _state["epx"] = round(epx, 1) if epx is not None else None
        
        epy = report.get("epy")
        _state["epy"] = round(epy, 1) if epy is not None else None
        
        epv = report.get("epv")
        _state["epv"] = round(epv, 1) if epv is not None else None
        
        eps = report.get("eps")
        _state["eps_kmh"] = round(eps * 3.6, 1) if eps is not None else None
        
        _state["time"] = report.get("time")
        _state["last_update"] = datetime.now(timezone.utc).isoformat()


def _apply_sky(report: dict):
    with _lock:
        now = time.time()
        sats_raw = report.get("satellites")
        if sats_raw:
            for s in sats_raw:
                prn = s.get("PRN") or s.get("svid")
                if prn is None:
                    continue
                _sat_cache[prn] = {
                    "prn": prn,
                    "gnss": classify_gnss(prn),
                    "elevation": s.get("el"),
                    "azimuth": s.get("az"),
                    "snr": s.get("ss"),
                    "used": bool(s.get("used", False)),
                    "last_seen": now,
                }
        
        for dop in ("hdop", "vdop", "pdop", "gdop", "tdop"):
            val = report.get(dop)
            if val is not None:
                _state[dop] = round(val, 2)
        
        _compile_satellites_summary(now)
        _state["last_update"] = datetime.now(timezone.utc).isoformat()


def _apply_devices(report: dict):
    devices = report.get("devices", [])
    if devices and isinstance(devices, list):
        dev = devices[0]
        with _lock:
            _state["driver"] = dev.get("driver")


def _run_socket_loop():
    """Streaming background client connected directly to gpsd daemon."""
    while True:
        try:
            sock = socket.create_connection(("127.0.0.1", 2947), timeout=5)
            reader = sock.makefile("r", encoding="utf-8", errors="replace")
            
            # Read banner
            _ = reader.readline()
            
            # Request JSON reports and NMEA sentences
            watch_cmd = json.dumps({"enable": True, "json": True, "nmea": True})
            sock.sendall(f"?WATCH={watch_cmd}\r\n".encode("utf-8"))
            
            with _lock:
                _state["gpsd_connected"] = True

            while True:
                line = reader.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                
                if line.startswith("$"):
                    if "GSV" in line:
                        with _lock:
                            parse_gsv_sentence(line)
                            _compile_satellites_summary()
                            _state["last_update"] = datetime.now(timezone.utc).isoformat()
                    elif "GSA" in line:
                        parse_gsa_sentence(line)
                elif line.startswith("{"):
                    try:
                        data = json.loads(line)
                        cls_name = data.get("class")
                        if cls_name == "TPV":
                            _apply_tpv(data)
                        elif cls_name == "SKY":
                            _apply_sky(data)
                        elif cls_name == "DEVICES":
                            _apply_devices(data)
                    except Exception:
                        pass
        except Exception:
            pass
        finally:
            with _lock:
                _state["gpsd_connected"] = False
            time.sleep(_RECONNECT_DELAY_SECONDS)


def start_background_thread():
    thread = threading.Thread(target=_run_socket_loop, daemon=True, name="gpsd-worker")
    thread.start()


@router.get("/gps")
def get_gps():
    with _lock:
        return dict(_state)
