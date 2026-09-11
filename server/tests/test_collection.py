import unittest
import csv
import io
import tempfile
from pathlib import Path

from app.collection import (
    CaptureMode,
    DEFAULT_CAPTURE_MODE,
    MODE_DETAILS,
    _metadata_row,
    _capture_one,
    _video_command,
)


class TestCollectionModes(unittest.TestCase):

    class _Request:
        def __init__(self, payload: bytes):
            self.payload = payload
            self.released = False

        def save(self, _stream, destination: str):
            Path(destination).write_bytes(self.payload)

        def get_metadata(self):
            return {"LensPosition": 4.0, "AfState": 2, "FocusFoM": 5000}

        def release(self):
            self.released = True

    class _Camera:
        def __init__(self, payload: bytes):
            self.request = TestCollectionModes._Request(payload)

        def capture_request(self):
            return self.request

    def test_continuous_autofocus_is_the_default_collection_mode(self):
        self.assertEqual(DEFAULT_CAPTURE_MODE, CaptureMode.CONTINUOUS_AF_STILL)

    def test_all_named_modes_have_a_display_contract(self):
        self.assertEqual(set(CaptureMode), set(MODE_DETAILS))
        self.assertEqual(MODE_DETAILS[CaptureMode.FIXED_STILL]["kind"], "still")
        self.assertEqual(MODE_DETAILS[CaptureMode.MJPEG_VIDEO_BASELINE]["kind"], "video")

    def test_still_metadata_keeps_focus_and_exposure_values(self):
        row = _metadata_row(
            "20260908_120000_123.jpg",
            "2026-09-08T12:00:00.123+00:00",
            CaptureMode.LOCKED_AF_STILL,
            {"LensPosition": 1.75, "AfState": "Focused", "FocusFoM": 321,
             "ExposureTime": 7000, "AnalogueGain": 1.2, "FrameDuration": 69669},
        )
        self.assertEqual(row["mode"], "locked-af-still")
        self.assertEqual(row["lens_position"], 1.75)
        self.assertEqual(row["focus_fom"], 321)
        self.assertEqual(row["exposure_time_us"], 7000)

    def test_capture_promotes_only_complete_nonempty_jpeg_before_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / ".partial"
            staging.mkdir()
            rows = io.StringIO()
            writer = csv.DictWriter(rows, fieldnames=["filename", "timestamp_utc", "mode", "lens_position", "af_state", "focus_fom", "exposure_time_us", "analogue_gain", "frame_duration_us"])
            writer.writeheader()
            camera = self._Camera(b"\xff\xd8payload\xff\xd9")
            size = _capture_one(camera, root, staging, CaptureMode.CONTINUOUS_AF_STILL, writer)
            self.assertEqual(size, 11)
            self.assertEqual(len(list(root.glob("*.jpg"))), 1)
            self.assertFalse(any(staging.iterdir()))
            self.assertIn("continuous-af-still", rows.getvalue())
            self.assertTrue(camera.request.released)

    def test_capture_rejects_zero_byte_save_without_metadata_row(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / ".partial"
            staging.mkdir()
            rows = io.StringIO()
            writer = csv.DictWriter(rows, fieldnames=["filename", "timestamp_utc", "mode", "lens_position", "af_state", "focus_fom", "exposure_time_us", "analogue_gain", "frame_duration_us"])
            writer.writeheader()
            camera = self._Camera(b"")
            with self.assertRaisesRegex(OSError, "empty JPEG"):
                _capture_one(camera, root, staging, CaptureMode.CONTINUOUS_AF_STILL, writer)
            self.assertFalse(list(root.glob("*.jpg")))
            self.assertEqual(rows.getvalue().count("\n"), 1)
            self.assertTrue(camera.request.released)

    def test_video_command_is_full_resolution_mjpeg_with_continuous_af(self):
        command = _video_command(Path("/tmp/capture.mjpeg"))
        self.assertEqual(command[:3], ["rpicam-vid", "--codec", "mjpeg"])
        self.assertIn("4608", command)
        self.assertIn("2592", command)
        self.assertIn("continuous", command)
        self.assertEqual(command[-1], str(Path("/tmp/capture.mjpeg")))

    def test_service_persists_the_field_camera_rotation(self):
        service_file = Path(__file__).resolve().parents[2] / "systemd" / "cityguard-edge-monitor.service"
        self.assertIn("Environment=CITYGUARD_CAMERA_ROTATION=0", service_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
