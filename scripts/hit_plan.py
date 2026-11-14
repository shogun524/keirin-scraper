# -*- coding: utf-8 -*-
"""
競輪の的中率重視の買い目(回収率は見ない)。

2025年1月〜2026年11月の 51,075レースで、人気順の買い方ごとの的中率を数えた(docs/_hitrate.json)。
人気 = 3連単の確定オッズから出した各選手の1着率(q ∝ オッズ^-1.05 を1着の選手ごとに合計)の順。
1番人気の1着率と車立てで的中率が大きく変わるので、その表から今のオッズで見込みを出す。
  ワイド 1番人気→2〜4番人気(3点)    全体77.7% / 1番人気の1着率60%以上・7車なら93%
  2車複 1番人気→2〜4番人気(3点)     全体58.1%
  3連複 1番人気軸→2〜5番人気(6点)   全体55.4% / 同 70%
"""
import json
import os

DOCS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs")
_T = None


def table():
    global _T
    if _T is None:
        try:
            with open(os.path.join(DOCS, "_hitrate.json"), encoding="utf-8") as f:
                _T = json.load(f)
        except (OSError, ValueError):
            _T = {}
    return _T


def win_probs(tri_odds, beta=1.05):
    """{'1-2-3': オッズ} -> {車番: 1着率}"""
    acc = {}
    for k, v in (tri_odds or {}).items():
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        if v > 0:
            c = int(str(k).replace(".", "-").split("-")[0])
            acc[c] = acc.get(c, 0.0) + v ** -beta
    s = sum(acc.values())
    return {c: x / s for c, x in acc.items()} if s else {}


def plan(tri_odds, n_cars):
    t = table()
    p = win_probs(tri_odds)
    if len(p) < 5 or not t:
        return None
    order = sorted(p, key=lambda c: -p[c])
    pm = p[order[0]]
    b = "0-30" if pm < .3 else "30-40" if pm < .4 else "40-50" if pm < .5 else "50-60" if pm < .6 else "60-"
    nb = str(min(max(int(n_cars or len(p)), 5), 9))
    f = order[0]
    return dict(fav=f, fav_p=round(pm, 3), items=[
        ["ワイド", f"{f} → {'・'.join(map(str, order[1:4]))}(3点)", t["wide3"][b][nb]],
        ["2車複", f"{f} → {'・'.join(map(str, order[1:4]))}(3点)", t["quin3"][b][nb]],
        ["3連複", f"{f}軸 → {'・'.join(map(str, order[1:5]))}(6点)", t["trio6"][b][nb]]])
