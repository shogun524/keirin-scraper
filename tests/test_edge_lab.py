# -*- coding: utf-8 -*-
import datetime
import json
import math
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import buy_stats
import closing_odds
import edge_lab as E
import staking as S


def entry(date, winner, odds=(2.0, 4.0, 8.0, 16.0, 32.0), typ="中間", venue="v", no=1, first=None, deadline="12:00"):
    keys = [f"1-{i + 2}-{i + 3}" for i in range(len(odds))]
    e = {"date": date, "venue": venue, "race_no": no, "deadline": deadline, "type": typ, "top": 40.0,
         "items": [[k, o, 10.0] for k, o in zip(keys, odds)], "winner": winner, "src": "live"}
    if first:
        e["first"] = first
    return e


class TestOutcome(unittest.TestCase):
    def test_equal_hit_and_miss(self):
        e = entry("2026-11-01", "1-2-3")                    # 1点目(2.0倍)が当たり
        s, r, hit, _ = E.outcome(e, "top3")
        self.assertEqual((s, r, hit), (3.0, 2.0, True))
        s, r, hit, _ = E.outcome(entry("2026-11-01", "9-9-9"), "top3")
        self.assertEqual((s, r, hit), (3.0, 0.0, False))

    def test_payout_alloc_returns_synth(self):
        e = entry("2026-11-01", "1-3-4")                    # 2点目(4.0倍)が当たり
        s, r, hit, synth = E.outcome(e, "top3", "payout")
        self.assertAlmostEqual(synth, 1 / (1 / 2 + 1 / 4 + 1 / 8))
        self.assertEqual((s, hit), (1.0, True))
        self.assertAlmostEqual(r, synth)

    def test_roi_matches_buy_stats(self):
        es = [entry(f"2026-11-0{1 + i % 3}", w, no=i) for i, w in enumerate(["1-2-3", "1-3-4", "x", "1-2-3", "y", "1-4-5"])]
        races, hits, pts, ret = buy_stats.evaluate(es, "top5")
        st = E.roi_stats(es, "top5", n_boot=50)
        self.assertEqual((st["races"], st["hits"]), (races, hits))
        self.assertAlmostEqual(st["roi"], round(ret / pts * 100, 1))


class TestBootstrap(unittest.TestCase):
    def test_interval_contains_point_and_is_deterministic(self):
        es = [entry("2026-11-01", "1-2-3" if i % 3 == 0 else "z", no=i) for i in range(60)]
        a = E.roi_stats(es, "top5", n_boot=300)
        b = E.roi_stats(es, "top5", n_boot=300)
        self.assertEqual(a, b)
        self.assertLessEqual(a["lo"], a["roi"])
        self.assertGreaterEqual(a["hi"], a["roi"])

    def test_p_gt_extremes(self):
        always = [entry("2026-11-01", "1-2-3", no=i) for i in range(30)]    # 毎回2倍が当たる（5点→回収率40%）
        self.assertEqual(E.roi_stats(always, "top5", n_boot=100)["p_gt"], 0.0)
        big = [entry("2026-11-01", "1-2-3", odds=(60, 70, 80, 90, 100), no=i) for i in range(30)]
        self.assertEqual(E.roi_stats(big, "top5", n_boot=100)["p_gt"], 1.0)


class TestBands(unittest.TestCase):
    def test_band_counts(self):
        es = [entry("2026-11-01", "1-2-3", no=0), entry("2026-11-01", "1-3-4", no=1)]
        rows = {(b["lo"], b["hi"]): b for b in E.band_table(es, n_boot=50)}
        self.assertEqual(rows[(0, 10)]["tickets"], 6)          # 2,4,8 が各レース
        self.assertEqual(rows[(0, 10)]["hits"], 2)
        self.assertAlmostEqual(rows[(0, 10)]["roi"], round((2.0 + 4.0) / 6 * 100, 1))
        self.assertEqual(rows[(10, 20)]["tickets"], 2)
        self.assertIsNone(rows[(150, None)]["hit_pct"] if rows[(150, None)]["tickets"] == 0 else None)


class TestWalkForward(unittest.TestCase):
    def test_uses_only_past_days(self):
        # 過去2日は top3 が儲かる世界（2倍が当たる）。最終日は何も当たらない。
        # 最終日の選択が最終日の結果を見ていれば、見送りになるはず。見ていなければ top3 系を選ぶ。
        es = []
        for d in ("2026-11-01", "2026-11-02"):
            for i in range(40):
                es.append(entry(d, "1-2-3", odds=(4.0, 9, 20, 30, 40), no=i))
        for i in range(40):
            es.append(entry("2026-11-03", "none", odds=(4.0, 9, 20, 30, 40), no=i))
        wf = E.walk_forward(es, plans=("top3",), min_past=40, by_type=False, n_boot=50)
        last = [p for p in wf["picks"] if p["date"] == "2026-11-03"][0]
        self.assertEqual(last["plan"], "top3")                  # 先読みしていない
        self.assertGreaterEqual(last["past_roi"], 100.0)

    def test_skips_when_past_is_losing(self):
        es = [entry("2026-11-01", "none", no=i) for i in range(40)] + [entry("2026-11-02", "1-2-3", no=i) for i in range(10)]
        wf = E.walk_forward(es, plans=("top3",), min_past=40, by_type=False, n_boot=50)
        self.assertEqual(wf["bet_races"], 0)
        self.assertEqual(wf["skipped_races"], 50)
        self.assertIsNone([p for p in wf["picks"] if p["date"] == "2026-11-02"][0]["plan"])


class TestCLV(unittest.TestCase):
    def _e(self, first_o, last_o, ts_first="10:00", last_ts="11:30"):
        e = entry("2026-11-01", "none", odds=last_o)
        e["first"] = {"ts": ts_first, "items": [[k, o] for (k, _, _), o in zip(e["items"], first_o)]}
        e["last_ts"] = last_ts
        return e

    def test_positive_when_odds_shorten(self):
        es = [self._e((10, 20, 30, 40, 50), (8, 16, 24, 32, 40), ) for _ in range(5)]
        c = E.clv_stats(es, None, "top5", n_boot=50)
        self.assertEqual(c["races"], 5)
        self.assertAlmostEqual(c["mean_pct"], round(math.log(10 / 8) * 100, 2), places=1)
        self.assertEqual(c["pos_share"], 100.0)
        self.assertEqual(c["sources"], {"last": 5})
        self.assertEqual(c["median_lead_min"], 120)

    def test_prefers_close_odds_and_negative_sign(self):
        e = self._e((10, 20, 30, 40, 50), (10, 20, 30, 40, 50))
        close = {E.race_key(e): {"ts": "11:55", "odds": {k: o * 1.25 for k, o, _ in e["items"]}}}
        c = E.clv_stats([e, e], close, "top5", n_boot=50)
        self.assertEqual(c["sources"], {"close": 2})
        self.assertLess(c["mean_pct"], 0)                      # 締切までにオッズが上がった

    def test_single_snapshot_is_skipped(self):
        e = self._e((10, 20, 30, 40, 50), (10, 20, 30, 40, 50), ts_first="11:30", last_ts="11:30")
        self.assertEqual(E.clv_stats([e], None, "top5", n_boot=20)["races"], 0)

    def test_max_lead_filter(self):
        e = self._e((10, 20, 30, 40, 50), (8, 16, 24, 32, 40), ts_first="06:30")
        self.assertEqual(E.clv_stats([e], None, "top5", max_lead_min=120, n_boot=20)["races"], 0)


class TestGate(unittest.TestCase):
    def test_all_conditions_needed(self):
        good = {"races": 300, "lo": 101.0}
        wf = {"bet_races": 150, "roi": 104.0}
        self.assertTrue(E.evidence_gate(good, wf, {"races": 80, "mean_pct": 1.0})[0])
        self.assertFalse(E.evidence_gate({"races": 100, "lo": 105.0}, wf)[0])             # 件数不足
        self.assertFalse(E.evidence_gate({"races": 300, "lo": 99.0}, wf)[0])              # 下側が100%未満
        self.assertFalse(E.evidence_gate(good, {"bet_races": 150, "roi": 98.0})[0])       # 前向き検証が負け
        self.assertFalse(E.evidence_gate(good, wf, {"races": 80, "mean_pct": -2.0})[0])   # CLVがマイナス
        self.assertTrue(E.evidence_gate(good, wf, {"races": 10, "mean_pct": -2.0})[0])    # CLVは件数が少なければ判定に使わない

    def test_empty(self):
        ok, why = E.evidence_gate({"races": 0})
        self.assertFalse(ok)
        self.assertTrue(why)


class TestPaperTrade(unittest.TestCase):
    def test_drawdown_and_profit(self):
        win = lambda d, i: entry(d, "1-2-3", odds=(5, 50, 50, 50, 50), no=i)     # top3: 当たれば合成が約4.1倍
        lose = lambda d, i: entry(d, "none", no=i)
        es = [win("2026-11-01", 0), lose("2026-11-02", 0), lose("2026-11-03", 0)]
        pt = E.paper_trade(es, E.fixed_picker("top3"), alloc="payout", unit=1000)
        self.assertEqual([d["date"] for d in pt["days"]], ["2026-11-01", "2026-11-02", "2026-11-03"])
        self.assertEqual(pt["bets"], 3)
        self.assertEqual(pt["days"][1]["profit"], -1000)
        self.assertEqual(pt["max_dd"], 2000)
        self.assertEqual(pt["stake"], 3000)

    def test_skip_picker(self):
        es = [entry("2026-11-01", "1-2-3")]
        pt = E.paper_trade(es, lambda v: None)
        self.assertEqual((pt["bets"], pt["profit"], pt["days"]), (0, 0, []))


class TestStaking(unittest.TestCase):
    def test_equal_payout(self):
        odds = [5.0, 10.0, 20.0, 40.0]
        st = S.equal_payout_stakes(odds, 10000)
        self.assertEqual(sum(st), 10000)
        pays = [s * o for s, o in zip(st, odds)]
        self.assertLess(max(pays) / min(pays), 1.1)
        self.assertTrue(all(s % 100 == 0 and s >= 100 for s in st))

    def test_small_budget_and_empty(self):
        self.assertEqual(S.equal_payout_stakes([5, 10, 20], 200), [100, 100, 0])
        self.assertEqual(S.equal_payout_stakes([5, 10], 0), [0, 0])
        self.assertEqual(S.equal_payout_stakes([], 1000), [])

    def test_kelly_zero_without_edge(self):
        self.assertEqual(S.kelly_fraction(0.2, 4.0), 0.0)                # 0.2×4=0.8 <1
        self.assertAlmostEqual(S.kelly_fraction(0.5, 3.0), (1.5 - 1) / 2)
        self.assertEqual(S.plan_kelly(40, 100, 2.5), 0.0)               # 的中率40%でも下側限界では優位性なし

    def test_wilson_is_below_point_estimate(self):
        self.assertLess(S.wilson_lower(60, 100), 0.6)
        self.assertGreater(S.wilson_lower(600, 1000), S.wilson_lower(60, 100))
        self.assertEqual(S.wilson_lower(0, 0), 0.0)

    def test_recommend_gated(self):
        r = S.recommend([5, 10, 20], 100000, 60, 100, gate_ok=False)
        self.assertEqual((r["budget"], r["stakes"]), (0, [0, 0, 0]))
        r = S.recommend([2.0, 4.0, 8.0], 100000, 800, 1000, gate_ok=True)     # 合成約1.14倍・的中80%→下側限界で優位性なし
        self.assertEqual(r["budget"], 0)
        r = S.recommend([6.0, 12.0, 24.0], 100000, 900, 1000, gate_ok=True)   # 合成約3.4倍・的中90%（仮定）
        self.assertGreater(r["budget"], 0)
        self.assertLessEqual(r["budget"], 2000)                                # 上限2%
        self.assertEqual(sum(r["stakes"]), r["budget"])


class TestClosingOdds(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.today = datetime.date(2026, 11, 8)
        log = {buy_stats._key("2026-11-08", "v", 1): entry("2026-11-08", None, odds=tuple(range(2, 52)) and (3.0,) * 12, no=1)}
        log[buy_stats._key("2026-11-08", "v", 1)].update(venue="v", race_no=1, winner=None)
        buy_stats.save(self.d, log)
        with open(os.path.join(self.d, "_deadlines.json"), "w", encoding="utf-8") as f:
            json.dump({"date": "2026-11-08", "races": [{"venue": "v", "race_no": 1, "deadline": "12:00"},
                                                       {"venue": "v", "race_no": 2, "deadline": "12:05"}]}, f)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _now(self, hm):
        h, m = map(int, hm.split(":"))
        return datetime.datetime(2026, 11, 8, h, m)

    def test_due_window(self):
        dl = [{"deadline": "12:00"}, {"deadline": "12:30"}, {"deadline": None}]
        self.assertEqual(len(closing_odds.due_races(dl, self._now("11:55"))), 1)
        self.assertEqual(len(closing_odds.due_races(dl, self._now("12:00"))), 0)    # 締切ちょうど以降は対象外
        self.assertEqual(len(closing_odds.due_races(dl, self._now("11:40"))), 0)

    def test_records_only_before_deadline_and_logged_races(self):
        odds = {(1, i + 2, i + 3): 2.5 + i for i in range(12)}
        calls = []
        fetch = lambda today: calls.append(1) or {("v", 1): odds, ("v", 2): odds}
        self.assertEqual(closing_odds.update(self.d, self.today, self._now("11:55"), fetch), 1)  # race2 は買い目の記録なし
        data = closing_odds.load(self.d)
        k = buy_stats._key("2026-11-08", "v", 1)
        self.assertEqual(list(data), [k])
        self.assertEqual(data[k]["ts"], "11:55")
        self.assertEqual(data[k]["odds"]["1-2-3"], 2.5)
        # 締切後は取りに行かない
        calls.clear()
        self.assertEqual(closing_odds.update(self.d, self.today, self._now("12:01"), fetch), 0)
        self.assertEqual(calls, [])

    def test_later_snapshot_overwrites_and_other_day_ignored(self):
        odds = {(1, i + 2, i + 3): 2.5 for i in range(12)}
        odds2 = {k: 2.0 for k in odds}
        closing_odds.update(self.d, self.today, self._now("11:50"), lambda t: {("v", 1): odds})
        closing_odds.update(self.d, self.today, self._now("11:58"), lambda t: {("v", 1): odds2})
        k = buy_stats._key("2026-11-08", "v", 1)
        self.assertEqual(closing_odds.load(self.d)[k]["odds"]["1-2-3"], 2.0)
        self.assertEqual(closing_odds.update(self.d, datetime.date(2026, 11, 9), self._now("11:58"), lambda t: {}), 0)


class TestBuyStatsRecordKeepsFirst(unittest.TestCase):
    def _rd(self, odds_scale):
        combos = [{"first": 1, "second": i + 2, "third": i + 3, "odds": (3.0 + i) * odds_scale, "prob": 10 - i * 0.1}
                  for i in range(12)]
        rows = [{"adjusted": 40.0}, {"adjusted": 20.0}]
        return {"race_info": {"venue": "v", "race_no": 1, "deadline": "12:00"},
                "prediction": {"fix_mode": "odds", "trifecta": {"combos": combos}, "rows": rows}}

    def test_first_is_kept_last_is_updated(self):
        log = {}
        today = datetime.date(2026, 11, 8)
        buy_stats.record(log, [self._rd(1.0)], today, "09:00")
        buy_stats.record(log, [self._rd(0.5)], today, "10:00")
        v = next(iter(log.values()))
        self.assertEqual(v["first"]["ts"], "09:00")
        self.assertEqual(v["first"]["items"][0][1], 3.0)
        self.assertEqual(v["items"][0][1], 1.5)
        self.assertEqual(v["last_ts"], "10:00")
        # 締切後は上書きしない
        buy_stats.record(log, [self._rd(0.1)], today, "12:30")
        self.assertEqual(next(iter(log.values()))["items"][0][1], 1.5)

    def test_build_report_runs_on_live_like_log(self):
        log = {}
        for i in range(30):
            e = entry(f"2026-11-0{1 + i % 3}", "1-2-3" if i % 4 == 0 else "z", no=i, typ=["堅い", "中間", "混戦"][i % 3])
            e["first"] = {"ts": "09:00", "items": [[k, o * 1.1] for k, o, _ in e["items"]]}
            e["last_ts"] = "11:00"
            log[f"k{i}"] = e
        rep = E.build_report(log, {}, n_boot=50)
        self.assertEqual(rep["races"], 30)
        self.assertTrue(all(not x["pass"] for g in rep["gates"].values() for x in g.values()))
        self.assertGreater(rep["clv"]["top5"]["races"], 0)
        json.dumps(rep)                                     # JSONにできる


if __name__ == "__main__":
    unittest.main()
