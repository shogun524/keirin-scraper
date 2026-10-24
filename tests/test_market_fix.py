import itertools
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import market_fix
import model


def _racers():
    base = [(1, "逃", 95.0, "◎"), (2, "追", 92.0, "○"), (3, "追", 88.0, ""), (4, "逃", 90.0, "▲"),
            (5, "追", 85.0, ""), (6, "両", 87.0, "△"), (7, "追", 80.0, "")]
    return [dict(car=c, name=f"選手{c}", mark=m, rank="A1", tactic=t, souhyou=0, waku=min(c, 6), gear=3.92,
                 score=s, age=35, period=100, kimarite={"逃": 3, "捲": 2, "差": 2, "マ": 1},
                 finishes={"f1": 3, "f2": 3, "f3": 3, "fo": 10}, pref="", b_count=2, s_count=1)
            for c, t, s, m in base]


class TestMarketFix(unittest.TestCase):
    def _check(self, r):
        self.assertAlmostEqual(sum(x["adjusted"] for x in r["rows"]), 100.0, places=4)
        self.assertAlmostEqual(sum(x["place_rate"] for x in r["rows"]), 300.0, places=3)
        self.assertEqual(r["top"]["car"], max(r["rows"], key=lambda x: x["adjusted"])["car"])
        for cands in r["second_place_matrix"].values():
            self.assertAlmostEqual(sum(c["prob"] for c in cands), 100.0, places=3)

    def test_ai_fix(self):
        rc = _racers()
        r = market_fix.apply(model.predict_race(rc, "1-2-3,4-5,6-7"), rc, None)
        self.assertEqual(r["fix_mode"], "ai_fix")
        self.assertTrue(all("ai_raw" in x for x in r["rows"]))
        self._check(r)

    def test_odds_mode_follows_market(self):
        rc = _racers()
        odds = {k: (5.0 if k[0] == 7 else 400.0) for k in itertools.permutations(range(1, 8), 3)}
        r = market_fix.apply(model.predict_race(rc, "1-2-3,4-5,6-7"), rc, odds)
        self.assertEqual(r["fix_mode"], "odds")
        self.assertEqual(r["top"]["car"], 7)
        self._check(r)

    def test_too_few_odds_falls_back(self):
        rc = _racers()
        r = market_fix.apply(model.predict_race(rc, "1-2-3,4-5,6-7"), rc, {(1, 2, 3): 5.0})
        self.assertEqual(r["fix_mode"], "ai_fix")


if __name__ == "__main__":
    unittest.main()
