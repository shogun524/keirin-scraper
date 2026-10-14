# -*- coding: utf-8 -*-
import os, sys, datetime, unittest, unittest.mock as mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.dirname(__file__))
import prediction_log as P
import model
from fixtures import make_race, synth_log


def race_data(venue="omiya", no=1, deadline="12:00", seed=1, n=7):
    racers, line = make_race(seed, n=n)
    pred = model.predict_race(racers, line, venue_slug=venue, race_title="予選")
    return {"race_info": {"venue": venue, "race_no": no, "title": "予選", "deadline": deadline},
            "prediction": pred, "url": f"https://keirin.kdreams.jp/{venue}/racedetail/2026101200000{no:02d}01/"}


class TestRecord(unittest.TestCase):
    def test_dedupe_and_first_prediction_kept(self):
        log = {}
        rd = race_data()
        self.assertEqual(P.record_predictions(log, [rd], "2026-10-12", "2026-10-12 08:00"), 1)
        first = dict(log["2026-10-12_omiya_1"])
        rd2 = race_data(seed=99)                                  # 同じレースを別の予測で再度渡しても
        self.assertEqual(P.record_predictions(log, [rd2], "2026-10-12", "2026-10-12 09:00"), 0)
        self.assertEqual(log["2026-10-12_omiya_1"]["order"], first["order"])
        self.assertEqual(log["2026-10-12_omiya_1"]["rec_at"], "2026-10-12 08:00")
        self.assertEqual(len(log), 1)

    def test_late_flag(self):
        log = {}
        P.record_predictions(log, [race_data(deadline="12:00")], "2026-10-12", "2026-10-12 11:59")
        P.record_predictions(log, [race_data(no=2, deadline="12:00")], "2026-10-12", "2026-10-12 12:00")
        P.record_predictions(log, [race_data(no=3, deadline="12:00")], "2026-10-12", "2026-10-12 13:30")
        self.assertFalse(log["2026-10-12_omiya_1"]["late"])
        self.assertTrue(log["2026-10-12_omiya_2"]["late"])
        self.assertTrue(log["2026-10-12_omiya_3"]["late"])

    def test_record_keeps_pre_buff_probs_and_ev(self):
        log = {}
        P.record_predictions(log, [race_data()], "2026-10-12", "2026-10-12 08:00")
        e = log["2026-10-12_omiya_1"]
        self.assertAlmostEqual(sum(p for _, p, *_ in e["probs"]), 100, delta=0.2)
        self.assertAlmostEqual(sum(p for _, p in e["p0"]), 100, delta=0.2)
        self.assertEqual(e["n_cars"], 7)


class TestExclusionAndStats(unittest.TestCase):
    def test_exclusion_reason(self):
        self.assertEqual(P.exclusion_reason({}), "pending")
        self.assertEqual(P.exclusion_reason({"result": {"finish_order": [1, 2]}}), "short")
        self.assertEqual(P.exclusion_reason({"result": {"finish_order": [1, 2, 3]}, "late": True}), "late")
        self.assertIsNone(P.exclusion_reason({"result": {"finish_order": [1, 2, 3]}}))

    def entry(self, order, fin, tri, **kw):
        e = {"date": "2026-10-01", "venue": "omiya", "race_no": 1, "order": order, "top_adj": 40.0, "is_high": False,
             "is_close": False, "trifecta": tri, "result": {"finish_order": fin}}
        e.update(kw)
        return e

    def test_hit_judgement(self):
        e = self.entry([3, 1, 2, 4, 5, 6, 7], [3, 1, 2, 4, 5, 6, 7], [[3, 1, 2], [3, 2, 1]])
        ev = P._evaluate(e)
        self.assertTrue(ev["top1"] and ev["top2"] and ev["top3"] and ev["box3"] and ev["tri1"] and ev["tri5"])
        e = self.entry([3, 1, 2, 4, 5, 6, 7], [1, 2, 3, 4, 5, 6, 7], [[3, 1, 2], [1, 2, 3]])
        ev = P._evaluate(e)
        self.assertFalse(ev["top1"]); self.assertFalse(ev["top2"]); self.assertTrue(ev["top3"])
        self.assertTrue(ev["box3"]); self.assertFalse(ev["tri1"]); self.assertTrue(ev["tri5"])
        e = self.entry([7, 1, 2, 4, 5, 6, 3], [1, 2, 3, 4, 5, 6, 7], [[7, 1, 2]])
        ev = P._evaluate(e)
        self.assertFalse(ev["top3"]); self.assertFalse(ev["box3"]); self.assertFalse(ev["tri5"])

    def test_denominator_excludes_pending_short_late(self):
        log = {
            "a": self.entry([1, 2, 3, 4, 5, 6, 7], [1, 2, 3, 4, 5, 6, 7], [[1, 2, 3]], rec_at="x"),
            "b": self.entry([1, 2, 3, 4, 5, 6, 7], [1, 2], [[1, 2, 3]], rec_at="x"),               # 着順不足
            "c": self.entry([1, 2, 3, 4, 5, 6, 7], [2, 1, 3, 4, 5, 6, 7], [[1, 2, 3]], late=True, rec_at="x"),
            "d": {**self.entry([1, 2, 3, 4, 5, 6, 7], [1, 2, 3], [[1, 2, 3]]), "result": None, "attempts": 0},
            "e": self.entry([1, 2, 3, 4, 5, 6, 7], [2, 1, 3, 4, 5, 6, 7], [[1, 2, 3]]),            # 旧ログ(記録時刻なし)
        }
        st = P.compute_prediction_stats(log)
        self.assertEqual(st["overall"]["n"], 2)                 # a と e だけが分母
        self.assertEqual(st["excluded"], {"late": 1, "short": 1, "no_time": 1})
        self.assertEqual(st["pending_count"], 1)
        self.assertAlmostEqual(st["overall"]["top1"], 50.0)


class TestIndependentRecount(unittest.TestCase):
    def test_page_stats_match_an_independent_count(self):
        """prediction_log の集計と、analyze_log.recount（別実装）の数え直しが一致する。"""
        import io, contextlib, random, analyze_log
        log = synth_log(5, 30, seed=11)
        rnd = random.Random(2)
        for e in log.values():
            if rnd.random() < 0.15:
                e["late"] = True
            if rnd.random() < 0.05:
                e["result"]["finish_order"] = e["result"]["finish_order"][:2]
        st = P.compute_prediction_stats(log)["overall"]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            analyze_log.recount(log)
        out = buf.getvalue()
        self.assertIn(f"評価対象{st['n']}レース", out)
        self.assertIn(f"本命1着{st['top1']:.1f}%", out)
        self.assertIn(f"3着内{st['top3']:.1f}%", out)
        self.assertIn(f"3連複BOX{st['box3']:.1f}%", out)
        self.assertIn(f"5点{st['tri5']:.1f}%", out)


class TestUpdateResults(unittest.TestCase):
    def base_log(self):
        log = {}
        P.record_predictions(log, [race_data()], "2026-10-12", "2026-10-12 08:00")
        return log

    def test_success_records_ranks_and_time(self):
        log = self.base_log()
        res = [{"finish": i + 1, "car": c, "name": "x", "kimarite": ""} for i, c in enumerate([3, 1, 2, 4, 5, 6, 7])]
        with mock.patch.object(P, "fetch_race_result", return_value=res):
            n = P.update_results(log, datetime.date(2026, 10, 12), "13:00")
        e = log["2026-10-12_omiya_1"]
        self.assertEqual(n, 1)
        self.assertEqual(e["result"]["finish_order"], [3, 1, 2, 4, 5, 6, 7])
        self.assertEqual(e["result"]["ranks"], [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(e["res_at"], "2026-10-12 13:00")

    def test_not_fetched_before_deadline(self):
        log = self.base_log()
        with mock.patch.object(P, "fetch_race_result", side_effect=AssertionError("締切前に取得してはいけない")):
            self.assertEqual(P.update_results(log, datetime.date(2026, 10, 12), "11:00"), 0)

    def test_unconfirmed_and_mismatched_results_are_not_recorded(self):
        log = self.base_log()
        with mock.patch.object(P, "fetch_race_result", return_value=None):
            P.update_results(log, datetime.date(2026, 10, 12), "13:00")
        self.assertIsNone(log["2026-10-12_omiya_1"]["result"]); self.assertEqual(log["2026-10-12_omiya_1"]["attempts"], 1)
        bad = [{"finish": 1, "car": 99, "name": "x", "kimarite": ""}, {"finish": 2, "car": 1, "name": "x", "kimarite": ""},
               {"finish": 3, "car": 2, "name": "x", "kimarite": ""}]
        with mock.patch.object(P, "fetch_race_result", return_value=bad):
            P.update_results(log, datetime.date(2026, 10, 12), "14:00")
        self.assertIsNone(log["2026-10-12_omiya_1"]["result"])          # 出走車番にない車 → 取り違えとして不採用

    def test_gives_up_after_max_attempts(self):
        log = self.base_log()
        with mock.patch.object(P, "fetch_race_result", return_value=None) as m:
            for h in range(10, 20):
                P.update_results(log, datetime.date(2026, 10, 12), f"{h}:00")
        self.assertEqual(m.call_count, P.MAX_ATTEMPTS)


if __name__ == "__main__":
    unittest.main()
