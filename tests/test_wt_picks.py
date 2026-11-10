# -*- coding: utf-8 -*-
import datetime, os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import wt_picks as P


def race(n, lines, marks, points=None):
    """lines: [[車番...], ...] / marks: {車番: 印(1〜4)}"""
    points = points or {}
    return {
        "race": {"startAt": 0, "closeAt": 0},
        "entries": [{"number": c, "playerId": f"p{c}"} for c in range(1, n + 1)],
        "records": [{"playerId": f"p{c}", "predictionMark": marks.get(c, 0), "racePoint": points.get(c, 80)} for c in range(1, n + 1)],
        "linePrediction": {"lines": [{"entries": [{"numbers": [c]} for c in L]} for L in lines]},
    }


class TestPicks(unittest.TestCase):
    def test_nine_car_second_line_in_order(self):
        R = race(9, [[1, 4, 7], [2, 5, 8], [3, 6, 9]], {1: 1, 2: 2, 3: 3})   # 印: 1のライン>2のライン>3のライン
        hits, why = P.evaluate_race(R)
        self.assertEqual(why, "")
        self.assertIn(("A", "2-5-8", [2, 5, 8]), hits)
        self.assertIn(("B", "3-6-9", [3, 6, 9]), hits)

    def test_seven_car_third_line_needs_three_cars(self):
        R = race(7, [[1, 4], [2, 5], [3, 6, 7]], {1: 1, 2: 2, 3: 4})
        hits, _ = P.evaluate_race(R)
        self.assertEqual(hits, [("C", "3-6-7", [3, 6, 7])])
        R = race(7, [[1, 4, 7], [2, 5, 6], [3]], {1: 1, 2: 2})
        self.assertEqual(P.evaluate_race(R)[0], [])                          # 3番目のラインが単騎 → 対象外

    def test_absent_and_no_line(self):
        R = race(9, [], {1: 1})
        self.assertEqual(P.evaluate_race(R), ([], "並び予想なし"))
        R = race(9, [[1, 4, 7], [2, 5, 8], [3, 6, 9]], {1: 1, 2: 2, 3: 3})
        R["entries"][8]["absent"] = True                                     # 欠車で8車立て → 対象外
        self.assertEqual(P.evaluate_race(R)[0], [])

    def test_render_and_merge(self):
        now = datetime.datetime(2026, 11, 10, 12, 0, tzinfo=P.JST)
        p = dict(date="2026-11-10", rule="A", ticket="2-5-8", url="u", venue="立川", race_no=11, cup="記念", grade="G3",
                 start_at=0, close_at=0, cls="S級", race_type="決勝", line="2-5-8")
        log = P.merge([dict(p, settled=True, payout=12340)], [p])
        self.assertEqual(len(log), 1)
        self.assertIn("12,340円", P.render(log, now))


if __name__ == "__main__":
    unittest.main()
