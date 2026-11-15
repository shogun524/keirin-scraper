# -*- coding: utf-8 -*-
"""
競輪 3連単の出目確率(11/15)。3連単オッズ(市場)に、市場が織り込み切れていない「ラインの決まり方」を足した条件付きロジット:
    p(1着a,2着b,3着c) ∝ exp( Σ w_k · 要素_k )
要素: log(市場の確率)・その2乗(大穴の買われすぎの補正)・AIの出目確率(Harville)・
      1-2着が同じラインの先頭→番手(並び)/番手→先頭(差し)/その他・2-3着/1-3着が同じライン・3人並び通り・
      1着の位置(先頭/番手/3番手以降/単騎)・1着が印1〜3番目のライン・2着/3着の位置
学習: winticket 2025〜2026年 1万6千レース(確定オッズ)。重みは tri_model.json。
検証(2025年で学習→2026年 2万4千レース): 1レースあたりの対数損失 市場 3.9819 → 3.9778。
  市場がとくに低く見ている(=来やすい)形: 同じラインの先頭→番手の1-2着(+15%)。
  市場が高く見ている(=来にくい)形: 印で強いライン(1〜3番目)の選手の1着(-12〜-16%)、大穴。
"""
import json
import math
import os

_W = None
MP = {"◎": 4, "○": 3, "〇": 3, "▲": 2, "△": 1}


def weights():
    global _W
    if _W is None:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "tri_model.json"), encoding="utf-8") as f:
            _W = json.load(f)["w"]
    return _W


def _lines(line_map, racers):
    """line_map(car -> line_index, position(1始まり), line_size) -> car -> (印の強さ順のライン順位, 0始まりの位置, 人数)"""
    mk = {r["car"]: MP.get((r.get("mark") or "").strip(), 0) for r in racers}
    sc = {r["car"]: float(r.get("score") or 0) for r in racers}
    by = {}
    for car, v in (line_map or {}).items():
        by.setdefault(v["line_index"], []).append((v["position"], car))
    lines = [[c for _, c in sorted(m)] for m in by.values()]
    lines.sort(key=lambda l: (-sum(mk.get(c, 0) for c in l), -sum(sc.get(c, 0) for c in l) / len(l)))
    out = {}
    for i, l in enumerate(lines):
        for j, c in enumerate(l):
            out[c] = (i, j, len(l))
    return out


def joint(odds, racers, line_map, ai_p1):
    """odds {(a,b,c): 倍率}・racers・line_map・ai_p1 {car: AIの1着率(0〜1)} -> {(a,b,c): 確率}(合計1)"""
    w = weights()
    li = _lines(line_map, racers)
    inv = {k: 1 / v for k, v in odds.items() if v and v > 0}
    tot = sum(inv.values()) or 1
    sa = sum(ai_p1.values()) or 1
    s = {}
    for k, iv in inv.items():
        a, b, c = k
        A, B, C = li.get(a, (-1, 0, 1)), li.get(b, (-1, 0, 1)), li.get(c, (-1, 0, 1))
        lq = math.log(iv / tot)
        pa, pb, pc = (max(ai_p1.get(x, 1e-4), 1e-4) / sa for x in (a, b, c))
        h = pa * pb / max(1 - pa, 1e-6) * pc / max(1 - pa - pb, 1e-6)
        s12 = A[0] == B[0] and A[2] > 1
        s23 = B[0] == C[0] and B[2] > 1
        s13 = A[0] == C[0] and A[2] > 1
        x = [lq, lq * lq, math.log(max(h, 1e-9)),
             s12 and A[1] == 0 and B[1] == 1, s12 and A[1] == 1 and B[1] == 0, s12 and (A[1], B[1]) not in ((0, 1), (1, 0)),
             s23, s13, s12 and s23 and A[1] == 0 and B[1] == 1 and C[1] == 2,
             A[1] == 0 and A[2] > 1, A[1] == 1, A[1] >= 2, A[2] == 1, A[0] == 0, A[0] == 1, A[0] == 2,
             B[1] == 0 and B[2] > 1, B[1] == 1, C[1] == 1, C[2] == 1]
        s[k] = sum(wi * float(xi) for wi, xi in zip(w, x))
    m = max(s.values()) if s else 0
    e = {k: math.exp(v - m) for k, v in s.items()}
    z = sum(e.values()) or 1
    return {k: v / z for k, v in e.items()}
