"""MPU-6050 vibration-event detection, ported from
edge/runtime/src/sensors.py's MPU6050Sensor (same I2C registers, scale
factors, and 1.5g vertical-impact threshold tuned there to catch a pothole
hit without false-triggering on braking or speed bumps) -- copied rather
than imported since edge-monitor and edge/runtime are separate repos with
independent deployments (see ADR-006's "port, don't share" precedent).

Unlike the source file, this has no mock/Docker fallback: this module only
ever runs on the real device, and degrades to a no-op if the chip isn't on
the bus.
"""

from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger("cityguard.edge_monitor.imu")

_I2C_BUS = 1
_MPU6050_ADDR = 0x68
_PWR_MGMT_1 = 0x6B
_ACCEL_XOUT = 0x3B
_ACCEL_SCALE = 16384.0  # LSB/g at +/-2g range
_SAMPLE_HZ = 100
_VIBRATION_THRESHOLD_G = 1.5

_lock = threading.Lock()
_state = {
    "vibration_g": None,
    "event": False,
}

_thread: threading.Thread | None = None
_stop_event: threading.Event | None = None
_bus = None


def _read_word(bus, reg: int) -> int:
    high = bus.read_byte_data(_MPU6050_ADDR, reg)
    low = bus.read_byte_data(_MPU6050_ADDR, reg + 1)
    val = (high << 8) | low
    return val - 65536 if val >= 32768 else val


def _sample_loop(stop_event: threading.Event) -> None:
    global _bus
    try:
        import smbus2
        _bus = smbus2.SMBus(_I2C_BUS)
        _bus.write_byte_data(_MPU6050_ADDR, _PWR_MGMT_1, 0x00)
        time.sleep(0.1)
        logger.info("MPU-6050 found on I2C bus %d, sampling at %d Hz", _I2C_BUS, _SAMPLE_HZ)
    except Exception as exc:
        logger.warning("MPU-6050 not available (%s); vibration-triggered bursts disabled.", exc)
        return

    interval = 1.0 / _SAMPLE_HZ
    while not stop_event.is_set():
        t0 = time.monotonic()
        try:
            az = _read_word(_bus, _ACCEL_XOUT + 4) / _ACCEL_SCALE
            vibration_g = abs(az - 1.0)
            with _lock:
                _state["vibration_g"] = vibration_g
                if vibration_g > _VIBRATION_THRESHOLD_G and not _state["event"]:
                    _state["event"] = True
                    logger.info("Vibration event detected: %.2f g (threshold %.1f g)", vibration_g, _VIBRATION_THRESHOLD_G)
        except Exception as exc:
            logger.debug("MPU-6050 read error: %s", exc)
        elapsed = time.monotonic() - t0
        stop_event.wait(max(0.0, interval - elapsed))

    try:
        _bus.close()
    except Exception:
        pass


def start() -> None:
    global _thread, _stop_event
    _stop_event = threading.Event()
    _thread = threading.Thread(target=_sample_loop, args=(_stop_event,), daemon=True, name="imu-sampler")
    _thread.start()


def stop() -> None:
    global _thread, _stop_event
    if _stop_event is not None:
        _stop_event.set()
    if _thread is not None:
        _thread.join(timeout=2.0)
    _thread = None
    _stop_event = None
    with _lock:
        _state["vibration_g"] = None
        _state["event"] = False


def peek_event() -> bool:
    with _lock:
        value, _state["event"] = _state["event"], False
        return value


def latest_vibration_g() -> float | None:
    with _lock:
        return _state["vibration_g"]
