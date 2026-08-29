import os
import unittest
from unittest.mock import patch, MagicMock

from app.camera import _capture_now


class TestCamera(unittest.TestCase):
    @patch("subprocess.run")
    def test_capture_rotation_flag_passed(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = b"fake_jpeg_bytes"
        mock_proc.stderr = b""
        mock_run.return_value = mock_proc

        data, err = _capture_now()
        self.assertEqual(data, b"fake_jpeg_bytes")
        self.assertIsNone(err)

        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        self.assertIn("rpicam-still", args)
        self.assertIn("--rotation", args)
        self.assertIn("180", args)


if __name__ == "__main__":
    unittest.main()
