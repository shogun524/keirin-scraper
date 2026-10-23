import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import winticket_page as wp


class TestWinticketPage(unittest.TestCase):
    def test_rank_of(self):
        self.assertEqual(wp.rank_of(1, 1), "S1")
        self.assertEqual(wp.rank_of(2, 3), "A3")
        self.assertEqual(wp.rank_of(4, 1), "L1")

    def test_template_has_placeholder(self):
        path = os.path.join(os.path.dirname(wp.__file__), "winticket_template.html")
        self.assertIn("__DATA__", open(path, encoding="utf-8").read())

    def test_summary(self):
        venues = {"nara": [
            {"res": {"k": "2-4-1"}, "rows": [[1, "", "", "", 0, "", 0, 40.0], [2, "", "", "", 0, "", 0, 30.0]]},
            {"res": None, "rows": [[1, "", "", "", 0, "", 0, 40.0]]},
        ]}
        self.assertEqual(wp.summary(venues), {"n": 1, "ai_top_win": 0})


if __name__ == "__main__":
    unittest.main()


class TestWinticketSource(unittest.TestCase):
    COM = {
        "players": [{"id": "a", "name": "甲", "age": 30, "term": 100, "prefecture": "奈良"}],
        "records": [{"playerId": "a", "gearRatio": 3.92, "style": "逃", "racePoint": 90.5, "predictionMark": 1,
                     "standing": 1, "back": 5, "frontRunner": 3, "stalker": 1, "deepCloser": 2, "marker": 0,
                     "first": 4, "second": 3, "third": 2, "others": 10}],
        "entries": [{"number": 1, "playerId": "a", "bracketNumber": 1, "absent": False,
                     "playerCurrentTermClass": 1, "playerCurrentTermGroup": 2}],
        "linePrediction": {"lines": [{"entries": [{"numbers": [2]}, {"numbers": [5]}]}, {"entries": [{"numbers": [4]}]}]},
    }

    def test_racers_and_line(self):
        import winticket_source as ws
        r = ws._racers(self.COM)[0]
        self.assertEqual((r["car"], r["rank"], r["mark"], r["score"]), (1, "S2", "◎", 90.5))
        self.assertEqual(r["kimarite"], {"逃": 3, "捲": 2, "差": 1, "マ": 0})
        self.assertEqual(ws._line_text(self.COM), "2-5,4")
