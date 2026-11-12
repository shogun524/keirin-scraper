# -*- coding: utf-8 -*-
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import report


class TestKeshi(unittest.TestCase):
    def test_collect(self):
        res = {"trifecta": {"buy": {"honsen": ["1-2-3", "1-3-2"], "osae": ["2-1-3"], "ai_top": "1-2-3"},
                            "auto": {"keys": ["1-2-3", "3-1-2"]}, "ana": {"keys": ["7-5-6"]}}}
        self.assertEqual(report.ai_keshi(res), ["1-2-3", "1-3-2", "2-1-3", "3-1-2", "7-5-6"])
        self.assertEqual(report.ai_keshi({}), [])

    def test_box_removes_keshi_from_recommend(self):
        info = {"manshaken": {"man": 0.45, "q25": 2000, "q50": 6000, "q75": 9000},
                "recommend": [("ana", "穴", ["2-5-8"]), ("win", "D", ["1-4-7"])], "ai_keshi": ["2-5-8", "1-2-3"]}
        h = report.render_manshaken_box(info)
        self.assertIn("1-4-7", h)
        self.assertIn("<s>2-5-8</s>", h)               # 推奨からは外れ、消し目に出る
        self.assertNotIn("<b>2-5-8</b>", h)
        self.assertIn("消し目", h)


if __name__ == "__main__":
    unittest.main()
