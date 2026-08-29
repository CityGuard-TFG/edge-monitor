"""System health readings for the Pi host: CPU, RAM, disk, temperature, throttling, IPs."""
import socket
import subprocess
import time
from datetime import datetime, timezone

import psutil
from fastapi import APIRouter

router = APIRouter()

_BOOT_TIME = psutil.boot_time()


def _read_cpu_temp_c():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return round(int(f.read().strip()) / 1000.0, 1)
    except Exception:
        pass
    try:
        out = subprocess.run(
            ["vcgencmd", "measure_temp"], capture_output=True, text=True, timeout=3
        )
        # e.g. "temp=42.8'C"
        raw = out.stdout.strip()
        value = raw.split("=", 1)[1].split("'")[0]
        return round(float(value), 1)
    except Exception:
        return None


def _read_throttled():
    try:
        out = subprocess.run(
            ["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=3
        )
        raw = out.stdout.strip()  # "throttled=0x50000"
        hex_value = raw.split("=", 1)[1]
        bits = int(hex_value, 16)
        return {
            "raw": raw,
            "under_voltage": bool(bits & 0x1),
            "throttled": bool(bits & 0x2),
            "temp_limit": bool(bits & 0x8),
        }
    except Exception:
        return {
            "raw": "unavailable",
            "under_voltage": False,
            "throttled": False,
            "temp_limit": False,
        }


def _read_ram():
    try:
        vm = psutil.virtual_memory()
        return {
            "used_mb": round((vm.total - vm.available) / 1024 / 1024, 1),
            "total_mb": round(vm.total / 1024 / 1024, 1),
            "percent": vm.percent,
        }
    except Exception:
        return {"used_mb": None, "total_mb": None, "percent": None}


def _read_disk():
    try:
        du = psutil.disk_usage("/")
        return {
            "used_gb": round(du.used / 1024 / 1024 / 1024, 2),
            "total_gb": round(du.total / 1024 / 1024 / 1024, 2),
            "percent": du.percent,
        }
    except Exception:
        return {"used_gb": None, "total_gb": None, "percent": None}


def _read_ip_addresses():
    addrs = {}
    try:
        for iface, snics in psutil.net_if_addrs().items():
            for snic in snics:
                if snic.family == socket.AF_INET and snic.address != "127.0.0.1":
                    addrs[iface] = snic.address
    except Exception:
        pass
    return addrs


@router.get("/status")
def get_status():
    try:
        cpu_percent = psutil.cpu_percent(interval=0.2)
    except Exception:
        cpu_percent = None

    try:
        hostname = socket.gethostname()
    except Exception:
        hostname = None

    return {
        "hostname": hostname,
        "uptime_seconds": round(time.time() - _BOOT_TIME, 1),
        "cpu_percent": cpu_percent,
        "cpu_temp_c": _read_cpu_temp_c(),
        "ram": _read_ram(),
        "disk": _read_disk(),
        "throttled": _read_throttled(),
        "ip_addresses": _read_ip_addresses(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
