# -*- coding: utf-8 -*-
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import wt_drops as W


def snap(mins, ts, tri, ex=None):
    return dict(mins=mins, ts=ts, odds={"3連単": [[k, v, 1] for k, v in tri.items()], "2車単": [[k, v, 1] for k, v in (ex or {}).items()]})


class TestDrops(unittest.TestCase):
    def test_drop_from_30min_base(self):
        s = [snap(60, 0, {"1-2-3": 9999.9, "2-5-8": 80.0}), snap(32, 100, {"1-2-3": 100.0, "2-5-8": 50.0, "3-1-2": 20.0}),
             snap(4, 200, {"1-2-3": 40.0, "2-5-8": 45.0, "3-1-2": 5.0})]
        d, b, c = W.race_drops(s)
        self.assertEqual(b["mins"], 32)                               # 60分前(売れていない)ではなく30分前に一番近い記録
        self.assertEqual([x[0] for x in d["2桁台"]], ["1-2-3"])        # 2-5-8 は-10%、3-1-2 は10倍未満
        self.assertAlmostEqual(d["2桁台"][0][3], -0.6)
        self.assertNotIn("2車単", d)

    def test_bands_split(self):
        s = [snap(35, 0, {"1-2-3": 80.0, "4-5-6": 900.0, "7-8-9": 400.0}, {"1-2": 30.0}),
             snap(3, 10, {"1-2-3": 55.0, "4-5-6": 150.0, "7-8-9": 200.0}, {"1-2": 10.0})]
        d, _, _ = W.race_drops(s)
        self.assertEqual([x[0] for x in d["2桁台"]], ["1-2-3"])         # −31%でも万車の−83%に埋もれない
        self.assertEqual([x[0] for x in d["万車"]], ["4-5-6", "7-8-9"])

    def test_no_base(self):
        self.assertEqual(W.race_drops([snap(8, 0, {"1-2-3": 50.0}), snap(3, 1, {"1-2-3": 10.0})])[0], {})


if __name__ == "__main__":
    unittest.main()
