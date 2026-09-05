"""GPS track recorder for data collection mode.

Samples the existing gpsd client snapshot at a fixed interval and appends
one flushed CSV row per sample -- a truncated file is still valid history up
to the last complete row, which is the crash-safety property that matters
here (a GPX/XML file kept open until the end would not have that property).
`write_gpx()` converts the CSV into a real GPX 1.1 document on demand.
"""

from __future__ import annotations

import csv
import threading
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from . import gps_client

TRACK_FILENAME = "track.csv"
_FIELDS = ["timestamp", "latitude", "longitude", "altitude_m", "speed_kmh"]

_stop_event: threading.Event | None = None
_thread: threading.Thread | None = None


def _sample_loop(output_dir: Path, sample_interval_seconds: float, stop_event: threading.Event) -> None:
    track_path = output_dir / TRACK_FILENAME
    is_new = not track_path.exists()
    with open(track_path, "a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if is_new:
            writer.writerow(_FIELDS)
            handle.flush()
        while not stop_event.wait(sample_interval_seconds):
            fix = gps_client.get_gps()
            if fix.get("fix") in (None, "none"):
                continue
            latitude = fix.get("latitude")
            longitude = fix.get("longitude")
            if latitude is None or longitude is None:
                continue
            writer.writerow([
                datetime.now(timezone.utc).isoformat(),
                latitude,
                longitude,
                fix.get("altitude_m"),
                fix.get("speed_kmh"),
            ])
            handle.flush()


def start(output_dir: Path, sample_interval_seconds: float = 2.0) -> None:
    global _stop_event, _thread
    output_dir.mkdir(parents=True, exist_ok=True)
    _stop_event = threading.Event()
    _thread = threading.Thread(
        target=_sample_loop,
        args=(output_dir, sample_interval_seconds, _stop_event),
        daemon=True,
        name="gpx-recorder",
    )
    _thread.start()


def stop() -> None:
    global _stop_event, _thread
    if _stop_event is not None:
        _stop_event.set()
    if _thread is not None:
        _thread.join(timeout=5)
    _stop_event = None
    _thread = None


def point_count(output_dir: Path) -> int:
    track_path = output_dir / TRACK_FILENAME
    if not track_path.exists():
        return 0
    with open(track_path, encoding="utf-8") as handle:
        return max(0, sum(1 for _ in handle) - 1)


def write_gpx(output_dir: Path) -> str:
    track_path = output_dir / TRACK_FILENAME
    gpx = ET.Element("gpx", {
        "version": "1.1",
        "creator": "CityGuard Edge Monitor",
        "xmlns": "http://www.topografix.com/GPX/1/1",
    })
    trk = ET.SubElement(gpx, "trk")
    ET.SubElement(trk, "name").text = output_dir.name
    trkseg = ET.SubElement(trk, "trkseg")

    if track_path.exists():
        with open(track_path, encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                lat, lon = row.get("latitude"), row.get("longitude")
                if not lat or not lon:
                    continue
                trkpt = ET.SubElement(trkseg, "trkpt", {"lat": lat, "lon": lon})
                altitude = row.get("altitude_m")
                if altitude:
                    ET.SubElement(trkpt, "ele").text = altitude
                timestamp = row.get("timestamp")
                if timestamp:
                    ET.SubElement(trkpt, "time").text = timestamp
                speed = row.get("speed_kmh")
                if speed:
                    extensions = ET.SubElement(trkpt, "extensions")
                    ET.SubElement(extensions, "speed").text = speed

    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(gpx, encoding="unicode")
