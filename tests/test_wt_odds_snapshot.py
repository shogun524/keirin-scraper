# -*- coding: utf-8 -*-
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import wt_odds_snapshot as S


class TestSnapshot(unittest.TestCase):
    def test_due(self):
        now = 1_000_000
        board = [dict(url="a", close_at=now + 30 * 60), dict(url="b", close_at=now + 90 * 60),
                 dict(url="c", close_at=now - 60), dict(url="d", close_at=0, start_at=now + 5 * 60)]
        self.assertEqual([b["url"] for b in S.due(board, now)], ["a", "d"])

    def test_extract(self):
        O = {"trifecta": [{"key": [1, 2, 3], "odds": 12.3, "popularityOrder": 4}, {"key": [1, 3, 2], "absent": True}],
             "quinellaPlace": [{"key": [1, 2], "minOdds": 1.5, "maxOdds": 2.0, "popularityOrder": 1}]}
        od = S.extract(O)
        self.assertEqual(od["3連単"], [["1-2-3", 12.3, 4]])
        self.assertEqual(od["ワイド"], [["1-2", 1.5, 2.0, 1]])
        self.assertEqual(od["2車単"], [])


if __name__ == "__main__":
    unittest.main()
