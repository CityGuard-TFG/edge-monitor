import time
import unittest

from app.gps_client import (
    classify_gnss,
    parse_gsv_sentence,
    parse_gsa_sentence,
    _compile_satellites_summary,
    _sat_cache,
    _state,
    _apply_tpv,
    _apply_sky,
)


class TestGpsClient(unittest.TestCase):
    def setUp(self):
        _sat_cache.clear()
        _state["fix"] = "none"
        _state["satellites"] = []
        _state["satellites_visible"] = None
        _state["satellites_used"] = None

    def test_classify_gnss(self):
        self.assertEqual(classify_gnss(1), "GPS")
        self.assertEqual(classify_gnss(32), "GPS")
        self.assertEqual(classify_gnss(70), "GLONASS")
        self.assertEqual(classify_gnss(86), "GLONASS")
        self.assertEqual(classify_gnss(210), "BeiDou")
        self.assertEqual(classify_gnss(310), "Galileo")
        self.assertEqual(classify_gnss(40, prefix="GP"), "GPS")
        self.assertEqual(classify_gnss(70, prefix="GL"), "GLONASS")

    def test_parse_gsv_sentence(self):
        now = time.time()
        # GLONASS with 3 satellites
        glgsv = "$GLGSV,1,1,03,78,,,37,70,,,41,86,,,32,0*7C"
        parse_gsv_sentence(glgsv, now=now)
        
        # GPS with 2 satellites
        gpgsv = "$GPGSV,1,1,02,15,45,120,28,24,30,210,22,0*64"
        parse_gsv_sentence(gpgsv, now=now)

        _compile_satellites_summary(now=now)

        self.assertEqual(_state["satellites_visible"], 5)
        self.assertEqual(_state["constellations"]["GLONASS"], 3)
        self.assertEqual(_state["constellations"]["GPS"], 2)
        self.assertIsNotNone(_state["avg_snr_db"])
        self.assertIn(_state["signal_quality"], ("good", "moderate", "weak"))

        # Verify PRN 15 parsed elevation and azimuth
        sat_15 = next(s for s in _state["satellites"] if s["prn"] == 15)
        self.assertEqual(sat_15["elevation"], 45)
        self.assertEqual(sat_15["azimuth"], 120)
        self.assertEqual(sat_15["snr"], 28.0)

    def test_parse_gsa_sentence_marks_used(self):
        now = time.time()
        parse_gsv_sentence("$GLGSV,1,1,03,78,,,37,70,,,41,86,,,32,0*7C", now=now)
        parse_gsa_sentence("$GNGSA,A,3,70,78,86,,,,,,,,,,1.8,1.2,1.4,2*02")
        _compile_satellites_summary(now=now)

        self.assertEqual(_state["fix"], "3d")
        self.assertEqual(_state["hdop"], 1.2)
        self.assertEqual(_state["pdop"], 1.8)
        self.assertEqual(_state["vdop"], 1.4)
        self.assertEqual(_state["satellites_used"], 3)

    def test_apply_tpv(self):
        tpv = {
            "mode": 3,
            "lat": 41.3879,
            "lon": 2.1699,
            "altHAE": 125.4,
            "speed": 12.5,
            "track": 90.0,
            "epx": 3.5,
            "epy": 4.0,
            "epv": 6.2,
            "time": "2026-08-29T19:20:00.000Z",
        }
        _apply_tpv(tpv)

        self.assertEqual(_state["fix"], "3d")
        self.assertEqual(_state["latitude"], 41.3879)
        self.assertEqual(_state["longitude"], 2.1699)
        self.assertEqual(_state["altitude_m"], 125.4)
        self.assertEqual(_state["speed_kmh"], 45.0)
        self.assertEqual(_state["track_deg"], 90.0)
        self.assertEqual(_state["epx"], 3.5)
        self.assertEqual(_state["epy"], 4.0)
        self.assertEqual(_state["epv"], 6.2)


if __name__ == "__main__":
    unittest.main()
