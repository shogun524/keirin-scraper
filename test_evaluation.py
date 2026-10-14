# -*- coding: utf-8 -*-
import os, sys, math, copy, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.dirname(__file__))
import evaluation as E
import prediction_log as P
from fixtures import synth_log


class TestStats(unittest.TestCase):
    def test_wilson_known_values(self):
        lo, hi = E.wilson(50, 100)
        self.assertAlmostEqual(lo, 40.38, delta=0.1)
        self.assertAlmostEqual(hi, 59.62, delta=0.1)
        self.assertEqual(E.wilson(0, 0), (None, None))
        lo, hi = E.wilson(0, 10)
        self.assertEqual(round(lo, 6), 0.0)
        self.assertGreater(hi, 0)

    def test_race_loss_uniform_and_perfect(self):
        ll, br = E.race_loss({1: 1, 2: 1, 3: 1, 4: 1}, 2)
        self.assertAlmostEqual(ll, math.log(4))
        self.assertAlmostEqual(br, 0.75)                       # (0.25-1)^2 + 3*(0.25)^2 = 0.75
        ll, br = E.race_loss({1: 1e-12, 2: 1.0, 3: 1e-12}, 2)
        self.assertAlmostEqual(br, 0.0, places=6)

    def test_probabilities_are_normalised_before_scoring(self):
        a = E.race_loss({1: 20, 2: 30, 3: 50}, 3)
        b = E.race_loss({1: 0.2, 2: 0.3, 3: 0.5}, 3)
        self.assertAlmostEqual(a[0], b[0]); self.assertAlmostEqual(a[1], b[1])

    def test_calibration_counts_all_riders_once(self):
        samples = E.race_samples(synth_log(3, 20))
        cal = E.calibration_all(samples)
        self.assertEqual(sum(r["n"] for r in cal), sum(len(s["p"]) for s in samples))
        self.assertEqual(sum(round(r["actual"] / 100 * r["n"]) for r in cal), len(samples))   # 勝者は1レース1人

    def test_isotonic_is_monotone_and_renormalised(self):
        samples = E.race_samples(synth_log(5, 40))
        pts = [(v, 1 if c == s["winner"] else 0) for s in samples for c, v in E._norm(s["p0"]).items()]
        fit = E.fit_isotonic(pts)
        ys = [y for _, y in fit]
        self.assertTrue(all(ys[i] <= ys[i + 1] + 1e-12 for i in range(len(ys) - 1)))
        q = E.isotonic_probs(fit, samples[0]["p0"])
        self.assertAlmostEqual(sum(q.values()), 1.0)


class TestWalkForward(unittest.TestCase):
    def test_no_future_information_in_walk_forward(self):
        """評価日の結果を書き換えても、その日に付ける確率は変わらない（学習に評価日・それ以降を使っていない）。"""
        log = synth_log(8, 30, beta_true=0.4)
        last = max(e["date"] for e in log.values())
        log2 = copy.deepcopy(log)
        for e in log2.values():
            if e["date"] == last:
                e["result"]["finish_order"] = e["result"]["finish_order"][::-1]   # 最終日の勝者を入れ替える
        w1 = E.walk_forward(E.race_samples(log), min_train=60, return_per=True)["_pred"]
        w2 = E.walk_forward(E.race_samples(log2), min_train=60, return_per=True)["_pred"]
        for k in ("gamma_refit", "gamma+formula", "isotonic"):
            a = [p for d, p in w1[k] if d == last]
            b = [p for d, p in w2[k] if d == last]
            self.assertTrue(a)
            self.assertEqual(a, b, f"{k}: 評価日の結果が学習に漏れている")

    def test_first_test_day_has_enough_history(self):
        s = E.race_samples(synth_log(6, 30))
        wf = E.walk_forward(s, min_train=60)
        self.assertGreaterEqual(sum(1 for x in s if x["date"] < wf["first_test_day"]), 60)

    def test_verdict_is_not_improvement_without_effect(self):
        wf = E.walk_forward(E.race_samples(synth_log(12, 40, beta_true=0.0)), min_train=60)
        v = wf["models"]["gamma+formula"]["verdict"]
        self.assertNotIn("改善（", v)

    def test_detects_true_formula_effect(self):
        wf = E.walk_forward(E.race_samples(synth_log(12, 40, beta_true=0.6)), min_train=60)
        m = wf["models"]["gamma+formula"]
        self.assertLess(m["logloss_diff_vs_current"], 0)
        self.assertLess(m["diff_ci"][1], 0)

    def test_small_sample_is_not_judged(self):
        wf = E.walk_forward(E.race_samples(synth_log(3, 30)), min_train=60)
        for k, v in wf["models"].items():
            if k not in ("current(p0)", "uniform"):
                self.assertIn("評価不能", v["verdict"])


class TestReport(unittest.TestCase):
    def test_late_entries_excluded_from_evaluation(self):
        log = synth_log(2, 10)
        n0 = len(E.race_samples(log))
        for e in list(log.values())[:5]:
            e["late"] = True
        self.assertEqual(len(E.race_samples(log)), n0 - 5)

    def test_report_marks_payout_not_evaluable(self):
        rep = E.build_report(synth_log(2, 10), __import__("datetime").date(2026, 9, 3))
        self.assertIn("評価不能", rep["payout"])
        self.assertNotIn("roi", rep)

    def test_empty_log(self):
        rep = E.build_report({}, __import__("datetime").date(2026, 9, 3))
        self.assertEqual(rep["n_races"], 0)


if __name__ == "__main__":
    unittest.main()
