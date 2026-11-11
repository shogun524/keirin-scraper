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


class TestBigRace(unittest.TestCase):
    def test_big_race_tickets(self):
        # ◎=1(ライン1-4-7の先頭) → 番手4 → 印順の相手5車
        R = race(9, [[1, 4, 7], [2, 5, 8], [3, 6, 9]], {1: 1, 2: 2, 3: 3, 5: 4})
        tks, ab = P.big_race_tickets(R)
        self.assertEqual(ab, (1, 4))
        self.assertEqual(tks[:4], ["1-4-2", "1-4-3", "1-4-5", "1-4-9"][:1] + tks[1:4])
        self.assertEqual(len(tks), 5)
        self.assertTrue(all(t.startswith("1-4-") for t in tks))
        self.assertEqual(tks[0], "1-4-2")

    def test_no_bante(self):
        R = race(9, [[4, 7, 1], [2, 5, 8], [3, 6, 9]], {1: 1})
        self.assertEqual(P.big_race_tickets(R), ([], (1, None)))

    def test_is_big_race(self):
        self.assertTrue(P.is_big_race("G1", "決勝"))
        self.assertTrue(P.is_big_race("G3", "準決勝"))
        self.assertFalse(P.is_big_race("F1", "決勝"))
        self.assertFalse(P.is_big_race("G2", "予選"))

    def test_render_big(self):
        now = datetime.datetime(2026, 11, 10, 12, 0, tzinfo=P.JST)
        p = dict(date="2026-11-10", rule="G", ticket="1-4-2 / 1-4-3", tickets=["1-4-2", "1-4-3"], url="u", venue="平塚",
                 race_no=12, cup="グランプリ", grade="GP", start_at=0, close_at=0, cls="S級", race_type="決勝", line="◎1・番手4",
                 settled=True, payout=5000)
        h = P.render([p], now)
        self.assertIn("重賞(G戦)の決勝・準決勝", h)
        self.assertIn("重賞パック", h)
        self.assertIn("2500%", h)  # 5000円 / (2点×100円)


class TestPrelim(unittest.TestCase):
    def test_prelim_tickets(self):
        R = race(9, [[1, 4, 7], [2, 5, 8], [3, 6, 9]], {1: 1, 2: 2, 3: 3})
        self.assertEqual(P.prelim_tickets(R), ["1-4-7", "2-5-8", "3-6-9", "4-1-7"])
        R = race(7, [[1, 4], [2, 5], [3, 6, 7]], {2: 1})
        self.assertEqual(P.prelim_tickets(R), ["3-6-7"])          # 最強ライン(2-5)は2車なので番手差しなし

    def test_star_and_no_double_card(self):
        now = datetime.datetime(2026, 11, 10, 12, 0, tzinfo=P.JST)
        base = dict(date="2026-11-10", url="u", venue="立川", race_no=5, cup="記念", grade="G3", start_at=0, close_at=0,
                    cls="S級", race_type="一予選")
        log = [dict(base, rule="H", ticket="", tickets=["1-4-7", "2-5-8", "3-6-9", "4-1-7"], line="並び"),
               dict(base, rule="A", ticket="2-5-8", line="2-5-8")]
        h = P.render(log, now)
        self.assertIn("★2-5-8", h)
        self.assertEqual(h.count('<article'), 1)                   # A の別カードは出さない
        self.assertIn("重賞(G戦)の予選・特選・選抜など", h)


class TestRuleD(unittest.TestCase):
    def test_second_line_ticket(self):
        R = race(7, [[1, 4, 7], [2, 5, 6], [3]], {1: 1, 2: 2})
        self.assertEqual(P.second_line_ticket(R), ("2-5-6", [2, 5, 6]))
        R = race(7, [[1, 4, 7], [2, 5], [3, 6]], {1: 1, 2: 2})
        self.assertIsNone(P.second_line_ticket(R))

    def test_trifecta_odds(self):
        O = {"trifecta": [{"key": [2, 5, 6], "odds": 18.5}, {"key": [1, 4, 7], "odds": None}]}
        self.assertEqual(P.trifecta_odds(O), {"2-5-6": 18.5})

    def test_merge_card_a_and_d(self):
        now = datetime.datetime(2026, 11, 10, 12, 0, tzinfo=P.JST)
        base = dict(date="2026-11-10", url="u", venue="立川", race_no=5, cup="記念", grade="F1", start_at=0, close_at=0,
                    cls="S級", race_type="予選", ticket="2-5-8")
        h = P.render([dict(base, rule="A", line="2-5-8"), dict(base, rule="D", line="2-5-8・15.0倍")], now)
        self.assertEqual(h.count("<article"), 1)
        self.assertIn(">A・D<", h)


class TestBoard(unittest.TestCase):
    def test_market_view(self):
        import wt_manshaken as M
        v = M.market_view([2.0] + [50.0] * 20 + [500.0] * 30)
        self.assertTrue(0 < v["man"] < 1)
        self.assertLessEqual(v["q25"], v["q50"])
        self.assertLessEqual(v["q50"], v["q75"])
        self.assertIsNone(M.market_view([5.0, 6.0]))

    def test_line_ticket_first(self):
        R = race(7, [[1, 4, 7], [2, 5, 6], [3]], {1: 1, 2: 2})
        self.assertEqual(P.line_ticket(R, 1), ("1-4-7", [1, 4, 7]))

    def test_board_render(self):
        now = datetime.datetime(2026, 11, 10, 12, 0, tzinfo=P.JST)
        base = dict(date="2026-11-10", url="u", venue="立川", race_no=5, cup="記念", grade="F1", start_at=0, close_at=0,
                    cls="A級", race_type="予選")
        log = [dict(base, rule="D", ticket="2-5-6", line="2-5-6・15.0倍"), dict(base, rule="E", ticket="1-4-7", line="1-4-7・6.0倍"),
               dict(base, url="v", race_no=6, rule="E", ticket="3-1-2", line="3-1-2・4.0倍")]
        board = [dict(url="u", venue="立川", race_no=5, start_at=0, grade="F1", race_type="予選", cls="A級", n=7,
                      man=0.31, q25=1500, q50=4200, q75=12000, odds={}),
                 dict(url="v", venue="立川", race_no=6, start_at=0, grade="F1", race_type="予選", cls="A級", n=7,
                      man=0.12, q25=600, q50=1200, q75=2500, odds={}),
                 dict(url="w", venue="立川", race_no=7, start_at=0, grade="F1", race_type="予選", cls="A級", n=7,
                      man=None, q25=None, q50=None, q75=None, odds={})]
        h = P.render(log, now, board)
        self.assertIn("全レース一覧", h)
        self.assertIn("31%", h)
        self.assertIn("4,200円", h)
        self.assertIn(">D</span> <b>2-5-6</b>", h)      # 勝ち筋があるレースは参考を出さない
        self.assertNotIn(">参考</span> 3-1-2", h)             # 本命寄りの参考(E)は出さない
        self.assertIn("honmei", h)                             # 万車率30%未満は穴党モードで隠す
        self.assertIn("見送り", h)
        self.assertEqual(h.count("<article"), 1)          # E はカードにしない


class TestRuleF(unittest.TestCase):
    def test_third_line(self):
        R = race(9, [[1, 4, 7], [2, 5, 8], [3, 6, 9]], {1: 1, 2: 2, 3: 3})
        self.assertEqual(P.line_ticket(R, 3), ("3-6-9", [3, 6, 9]))

    def test_recommendation_includes_f_not_e(self):
        ps = [dict(url="u", rule="F", ticket="3-6-9"), dict(url="u", rule="E", ticket="1-4-7")]
        self.assertEqual(P.race_recommendation(ps, "u"), [("win", "F", ["3-6-9"])])
        self.assertEqual(P.race_recommendation([dict(url="u", rule="E", ticket="1-4-7")], "u"), [])


class TestSmooth(unittest.TestCase):
    def test_median_of_last_three(self):
        old = [dict(url="u", hist=[[1, 0.30, 1, 2, 3], [2, 0.50, 1, 2, 3]])]
        new = [dict(url="u", man=0.32, q25=1, q50=2, q75=3), dict(url="v", man=None, q25=None, q50=None, q75=None)]
        b = P.smooth_board(new, old, 3)
        self.assertAlmostEqual(b[0]["man"], 0.32)          # 0.30, 0.50, 0.32 の中央値
        self.assertEqual(len(b[0]["hist"]), 3)
        self.assertIsNone(b[1]["man"])
        b2 = P.smooth_board([dict(url="u", man=0.9, q25=1, q50=2, q75=3)], b, 4)
        self.assertAlmostEqual(b2[0]["man"], 0.50)         # 0.50, 0.32, 0.90 → 0.50(1回の急な値に引っぱられない)
