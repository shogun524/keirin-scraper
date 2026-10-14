# -*- coding: utf-8 -*-
import os, sys, tempfile, datetime, json, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.dirname(__file__))
import calibration as C
from fixtures import synth_log


class TestGate(unittest.TestCase):
    def run_update(self, log):
        d = tempfile.mkdtemp()
        return C.update_params(d, log, datetime.date(2026, 10, 12)), d

    def test_below_min_races_is_inactive(self):
        p, _ = self.run_update(synth_log(2, 30, beta_true=1.0))
        self.assertFalse(p["active"]); self.assertFalse(p["buff"]["active"])

    def test_no_effect_world_stays_at_default(self):
        p, d = self.run_update(synth_log(12, 40, beta_true=0.0))
        self.assertFalse(p["buff"]["active"])                     # 効果なし → バフ0のまま
        self.assertEqual(p["sharpness_first"], C._default_gamma())
        self.assertNotIn("formula_buff", C.get_overrides(d))

    def test_real_formula_effect_is_adopted(self):
        p, d = self.run_update(synth_log(12, 40, beta_true=0.6))
        self.assertTrue(p["buff"]["active"])
        self.assertGreater(p["buff"]["lr"], C.LR_CRIT_1)
        self.assertGreater(C.get_overrides(d)["formula_buff"], 0.2)

    def test_late_entries_not_used_for_learning(self):
        log = synth_log(12, 40, beta_true=0.6)
        for e in log.values():
            e["late"] = True
        p, _ = self.run_update(log)
        self.assertEqual(p["buff"]["n"], 0)
        self.assertFalse(p["active"])

    def test_p0_is_preferred_over_final_probs(self):
        log = synth_log(2, 10)
        for e in log.values():
            e["p0"] = [[c, 100.0 / 7] for c in range(1, 8)]
        s = C._samples(log, datetime.date(2026, 10, 12))
        self.assertAlmostEqual(list(s[0][0].values())[0], 100.0 / 7)

    def test_params_updated_once_per_day(self):
        log = synth_log(12, 40, beta_true=0.6)
        d = tempfile.mkdtemp()
        p1 = C.update_params(d, log, datetime.date(2026, 10, 12))
        log2 = synth_log(12, 40, beta_true=0.0, seed=5)
        p2 = C.update_params(d, log2, datetime.date(2026, 10, 12))
        self.assertEqual(p1, p2)


if __name__ == "__main__":
    unittest.main()
