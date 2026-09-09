import unittest
from pathlib import Path

from app.collection import (
    CaptureMode,
    MODE_DETAILS,
    _metadata_row,
    _video_command,
)


class TestCollectionModes(unittest.TestCase):
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
