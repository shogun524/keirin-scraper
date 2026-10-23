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
