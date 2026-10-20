# -*- coding: utf-8 -*-
import os, sys, math, random, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import stage_cal as S
import model
import scraper
from validity import finish_order_ok
from prediction_log import exclusion_reason

TYPES = ["逃", "捲", "差", "マ"]


def sample(rng, w):
    r, acc = rng.random() * sum(w), 0.0
    for i, v in enumerate(w):
        acc += v
        if r <= acc:
            return i
    return len(w) - 1


def make_log(n_days, per_day, tilt=None, place_cal=None, seed=1):
    """合成ログ。tilt/place_cal があればその世界で勝者・2着・3着を引く（なければ補正なしの世界）。"""
    rng = random.Random(seed)
    out = []
    venues = [f"v{i}" for i in range(8)]
    for d in range(n_days):
        for k in range(per_day):
            n = 7
            cars = list(range(1, n + 1))
            sc = [rng.uniform(1, 3) for _ in cars]
            dom = [rng.choice(TYPES) for _ in cars]
            lines = [[0, 0, 3], [0, 1, 3], [0, 2, 3], [1, 0, 2], [1, 1, 2], None, None]
            rng.shuffle(lines)
            p0 = [x ** 2 for x in sc]
            t = sum(p0)
            p0 = [x / t * 100 for x in p0]
            cond = {"scores": sc, "dom": dom, "line": lines, "cars": cars, "adv_bonus": 10, "adv_penalty": 10,
                    "line_follow_bonus": 45, "sharp23": 1.3}
            true1 = model.apply_first_place_tilt(p0, [{"type": x} for x in dom], tilt) if tilt else p0
            y = sample(rng, true1)
            racers = [{"car": c, "name": ""} for c in cars]
            dm = [{"type": x} for x in dom]
            lm = {c: {"line_index": l[0], "position": l[1], "line_size": l[2]} for c, l in zip(cars, lines) if l}
            a = (sc, dm, lm, 10, 10, 45, 1.3)
            c2 = model.compute_second_place_candidates(racers, y, *a, cal=place_cal)
            z = c2[sample(rng, [c["prob"] for c in c2])]["idx"]
            c3 = model.compute_third_place_candidates(racers, y, z, *a, cal=place_cal)
            w = c3[sample(rng, [c["prob"] for c in c3])]["idx"]
            e = {"date": f"2026-10-{1 + d:02d}", "venue": venues[(d + k) % 8], "p0": [[c, p] for c, p in zip(cars, p0)],
                 "cond": cond, "result": {"finish_order": [cars[y], cars[z], cars[w]]}, "order": cars}
            out.append((e["date"], e["venue"], e))
    return out


class TestStageCal(unittest.TestCase):
    def test_null_world_is_not_adopted(self):
        r = S.fit_all(make_log(8, 40), None)["7"]
        for k in ("s1", "s2", "s3"):
            self.assertFalse(r[k]["active"], k)

    def test_real_tilt_is_found(self):
        tilt = {"a": 1.0, "捲": 0.0, "差": -0.7, "マ": -1.0}
        r = S.fit_all(make_log(8, 40, tilt=tilt), None)["7"]
        self.assertTrue(r["s1"]["active"])
        self.assertLess(r["s1"]["coef"]["差"], -0.3)
        self.assertLess(r["s1"]["coef"]["マ"], -0.3)

    def test_place_effect_is_found(self):
        cal = {"slope": 0.7, "same": 0.4, "adj": 0.9}
        r = S.fit_all(make_log(8, 40, place_cal=cal), None)["7"]
        self.assertTrue(r["s2"]["active"])
        self.assertGreater(r["s2"]["coef"]["adj"], 0.3)

    def test_too_few_races_not_adopted(self):
        r = S.fit_all(make_log(3, 20, tilt={"a": 1.0, "差": -1.0, "マ": -1.0}), None)["7"]
        self.assertFalse(r["s1"]["active"])

    def test_nine_car_group_needs_more_data(self):
        r = S.fit_all(make_log(8, 40, tilt={"a": 1.0, "差": -1.0}), None)
        self.assertEqual(r["9"]["s1"]["n"], 0)
        self.assertFalse(r["9"]["s1"]["active"])
        # 9車の合成データ: 件数・開催場とも足りなければ見送り
        log = [(d, v, dict(e, cond=dict(e["cond"], cars=list(range(1, 9)) + [9], dom=e["cond"]["dom"] + ["逃"] * 2,
                                         scores=e["cond"]["scores"] + [1.0] * 2, line=e["cond"]["line"] + [None] * 2),
                          p0=e["p0"] + [[8, 1.0], [9, 1.0]]))
               for d, v, e in make_log(3, 20)]
        self.assertFalse(S.fit_all(log, None)["9"]["s1"]["active"])

    def test_first_activation_is_shrunk_toward_default(self):
        tilt = {"a": 1.0, "捲": 0.0, "差": -0.7, "マ": -1.0}
        r = S.fit_all(make_log(8, 40, tilt=tilt), None)["7"]["s1"]
        self.assertAlmostEqual(r["coef"]["差"], 0.5 * r["fit_raw"][2], delta=0.01)

    def test_broken_cond_does_not_stop_learning(self):
        log = make_log(8, 40, place_cal={"slope": 0.7, "same": 0.4, "adj": 0.9})
        log[0][2]["cond"]["dom"] = log[0][2]["cond"]["dom"][:3]
        del log[1][2]["cond"]["sharp23"]
        d2, _d3 = S.stage23_data(log)
        self.assertGreaterEqual(len(d2), len(log) - 1)

    def test_overrides_only_active(self):
        o = S.overrides({"7": {"s1": {"active": True, "coef": {"a": 0.9}}, "s2": {"active": False, "coef": {"slope": 1}}}})
        self.assertEqual(o, {"7": {"s1": {"a": 0.9}}})

    def test_coefficients_are_clipped(self):
        v = S._clip([5.0, -9.0], ["a", "dom"])
        self.assertEqual(v, [S.CLIP["a"][1], S.CLIP["dom"][0]])


class TestModelApplication(unittest.TestCase):
    def test_none_cal_changes_nothing(self):
        racers = [{"car": c, "name": ""} for c in range(1, 6)]
        lm = {1: {"line_index": 0, "position": 0, "line_size": 2}, 2: {"line_index": 0, "position": 1, "line_size": 2}}
        dom = [{"type": "逃"}] * 5
        a = (racers, 0, [1, 2, 3, 2, 1], dom, lm, 10, 10, 45, 1.3)
        base = [c["prob"] for c in model.compute_second_place_candidates(*a)]
        same = [c["prob"] for c in model.compute_second_place_candidates(*a, cal=None)]
        self.assertEqual(base, same)
        tuned = model.compute_second_place_candidates(*a, cal={"slope": 1.0, "adj": 1.0, "same": 0.0})
        self.assertAlmostEqual(sum(c["prob"] for c in tuned), 100.0, places=6)
        self.assertGreater(next(c["prob"] for c in tuned if c["car"] == 2), next(c["prob"] for c in
                           model.compute_second_place_candidates(*a) if c["car"] == 2))

    def test_tilt_sums_to_100_and_moves_the_right_way(self):
        out = model.apply_first_place_tilt([40, 30, 30], [{"type": "逃"}, {"type": "差"}, {"type": "マ"}],
                                          {"a": 1.0, "差": -0.7, "マ": -1.0})
        self.assertAlmostEqual(sum(out), 100.0, places=6)
        self.assertGreater(out[0], 40); self.assertLess(out[2], 30)
        self.assertEqual(model.apply_first_place_tilt([60, 40], [{"type": "逃"}] * 2, None), [60, 40])


class TestFavoriteCorrection(unittest.TestCase):
    def test_hinge_shrinks_only_favorites_and_pos2_lifts_third_in_line(self):
        dom = [{"type": "逃"}] * 3
        base = model.apply_first_place_tilt([60, 25, 15], dom, {"a": 1.0})
        hin = model.apply_first_place_tilt([60, 25, 15], dom, {"a": 1.0, "hinge": -0.5})
        self.assertLess(hin[0], base[0]); self.assertAlmostEqual(sum(hin), 100.0, places=6)
        q = model.apply_first_place_tilt([40, 30, 30], dom, {"a": 1.0, "pos2": 0.5}, [0, 1, 2])
        self.assertGreater(q[2], 30); self.assertLess(q[0], 40)
        # hinge の起点(30%)以下だけなら変化なし
        flat = model.apply_first_place_tilt([25, 25, 25, 25], dom + [{"type": "逃"}], {"a": 1.0, "hinge": -0.5})
        self.assertAlmostEqual(flat[0], 25.0, places=6)


class TestResultIntegrity(unittest.TestCase):
    def test_broken_order_detected(self):
        e = {"result": {"finish_order": [6, 2, 7, 3, 4]}, "order": list(range(1, 8))}
        self.assertFalse(finish_order_ok(e)); self.assertEqual(exclusion_reason(e), "bad_order")

    def test_normal_and_dnf_ok(self):
        self.assertTrue(finish_order_ok({"result": {"finish_order": [2, 1, 5, 3, 4, 6, 7]}, "order": list(range(1, 8))}))
        self.assertTrue(finish_order_ok({"result": {"finish_order": [2, 1, 5, 3, 4]}, "order": list(range(1, 8))}))
        self.assertTrue(finish_order_ok({"result": None}))

    def test_duplicates_and_foreign_cars_rejected(self):
        self.assertFalse(finish_order_ok({"result": {"finish_order": [1, 1, 2]}, "order": [1, 2, 3]}))
        self.assertFalse(finish_order_ok({"result": {"finish_order": [1, 2, 9]}, "order": [1, 2, 3]}))

    def test_parser_reads_header_dnf_page(self):
        orig = scraper._clean_text
        scraper._clean_text = lambda h: h
        self.addCleanup(setattr, scraper, "_clean_text", orig)
        head = ["1R", "Ａ級一般", "出走表詳細", "確定オッズ", "結果・払戻金詳細", "ダイジェスト映像", "投票", "1着", "2着", "3着"]
        tail = ["2", "枠", "連", "複", "1,230円"]
        names = ["工藤 文彦", "高橋 幸司", "井上 将志", "中武 優", "山田 太郎", "鈴木 一郎", "佐藤 二郎"]
        order = [2, 7, 4, 1, 6, 3, 5]
        toks = head + ["4", "5", "6", "7"] + [x for c, n in zip(order, names) for x in (str(c), n)] + tail
        res = scraper.parse_day_results(toks)
        self.assertEqual([r["car"] for r in res[1]], order)          # 払戻の「2 枠」を着順と読まない
        self.assertEqual(len(res[1]), 7)


if __name__ == "__main__":
    unittest.main()
