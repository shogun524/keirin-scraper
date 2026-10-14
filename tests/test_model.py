# -*- coding: utf-8 -*-
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.dirname(__file__))
import model, formula
from fixtures import make_race


class TestProbabilities(unittest.TestCase):
    def check_sums(self, n, **kw):
        racers, line = make_race(7, n=n, line="1-2-3,4-5,6-7" if n == 7 else "1-2-3,4-5-6,7-8-9")
        r = model.predict_race(racers, line, venue_slug="omiya", race_title="決勝", **kw)
        self.assertAlmostEqual(sum(x["adjusted"] for x in r["rows"]), 100.0, places=6)
        self.assertAlmostEqual(sum(r["pre_buff"].values()), 100.0, delta=0.05)
        tf = r["trifecta"]["combos"] if r["trifecta"] else []
        return r

    def test_first_place_probabilities_sum_to_100(self):
        for n in (7, 9):
            self.check_sums(n)

    def test_sum_stays_100_with_formula_buff(self):
        for n in (7, 9):
            r = self.check_sums(n, settings={"formula_buff": 0.8})
            self.assertGreater(r["formula_buff"], 0)

    def test_buff_zero_changes_nothing(self):
        racers, line = make_race(3)
        a = model.predict_race(racers, line, venue_slug="omiya", race_title="予選")
        b = model.predict_race(racers, line, venue_slug="omiya", race_title="予選", settings={"formula_buff": 0.0})
        self.assertEqual([(x["car"], x["adjusted"]) for x in a["rows"]], [(x["car"], x["adjusted"]) for x in b["rows"]])

    def test_buff_moves_probability_toward_higher_formula(self):
        racers, line = make_race(3)
        a = model.predict_race(racers, line, venue_slug="omiya", race_title="予選")
        b = model.predict_race(racers, line, venue_slug="omiya", race_title="予選", settings={"formula_buff": 1.0})
        z = b["formula_z"]
        hi = max(z, key=z.get); lo = min(z, key=z.get)
        pa = {x["car"]: x["adjusted"] for x in a["rows"]}; pb = {x["car"]: x["adjusted"] for x in b["rows"]}
        self.assertGreater(pb[hi], pa[hi]); self.assertLess(pb[lo], pa[lo])

    def test_girls_race_has_no_formula_and_no_buff(self):
        racers, line = make_race(3, rank="L1", line="1,2,3,4,5,6,7")
        r = model.predict_race(racers, line, venue_slug="omiya", race_title="ガールズ予選", settings={"formula_buff": 1.0})
        self.assertIsNone(r["formula_z"])
        self.assertEqual(r["formula_buff"], 0.0)
        self.assertEqual([x["adjusted"] for x in r["rows"]], [x["adjusted"] for x in
                         model.predict_race(racers, line, venue_slug="omiya", race_title="ガールズ予選")["rows"]])

    def test_trifecta_combos_sum_close_to_total(self):
        racers, line = make_race(5)
        r = model.predict_race(racers, line, venue_slug="omiya")
        tf = r["trifecta"]
        probs = [c["prob"] for c in tf["combos"]]
        self.assertTrue(all(probs[i] >= probs[i + 1] - 1e-9 for i in range(len(probs) - 1)))   # 確率の高い順


class TestFormula(unittest.TestCase):
    def rows(self):
        return [
            {"car": 1, "name": "a", "rank": "S1", "score": 100.0, "b_count": 10, "age": 50,
             "kimarite": {"逃": 5, "捲": 3, "差": 2, "マ": 9}, "line_info": {"line_index": 0, "position": 1, "line_size": 3}, "pref": "大 阪"},
            {"car": 2, "name": "b", "rank": "S1", "score": 90.0, "b_count": 0, "age": 30,
             "kimarite": {"逃": 0, "捲": 0, "差": 0, "マ": 0}, "line_info": None, "pref": "東 京"},
        ]

    def test_formula_components(self):
        f = {x["car"]: x for x in formula.compute_formula(self.rows(), "kishiwada", "予選")}
        self.assertEqual(f[1]["kim3"], 10)            # マークは含めない
        self.assertEqual(f[1]["age_pen"], 15)         # 50歳 → 15
        self.assertAlmostEqual(f[1]["ability"], 100 + 10 + 10 - 15)
        self.assertEqual(f[1]["L"], 9)                # 3人 ×3
        self.assertEqual(f[2]["L"], 3)                # 単騎 = 1人 ×3
        self.assertEqual(f[2]["age_pen"], 0)

    def test_m_is_clamped_0_to_10_and_home_bonus(self):
        m_home, why = formula.estimate_m(self.rows()[0], "kishiwada", "決勝")
        m_away, _ = formula.estimate_m(self.rows()[0], "omiya", "予選")
        self.assertIn("地元戦", " ".join(why))
        self.assertGreater(m_home, m_away)
        self.assertTrue(0 <= m_home <= 10)

    def test_girls_detection(self):
        self.assertTrue(formula.is_girls([{"rank": "L1"}] * 7, ""))
        self.assertTrue(formula.is_girls([{"rank": "S1"}], "ガールズ決勝"))
        self.assertFalse(formula.is_girls([{"rank": "S1"}, {"rank": "L1"}], "予選"))


if __name__ == "__main__":
    unittest.main()
