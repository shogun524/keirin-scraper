# -*- coding: utf-8 -*-
"""
賭け金の配分と資金管理。

  equal_payout_stakes : 買い目ごとの金額。どれが当たっても払戻が同じになる（1/オッズに比例）。
                        同額ずつ買うより、当たった買い目による払戻のブレが小さい。
  wilson_lower        : 的中率の下側信頼限界（少ない件数の的中率を割り引く）。
  plan_kelly          : 1レースに資金の何%まで賭けてよいか（ケリー基準の1/4、上限つき）。
                        的中率には『下側の限界』を使うので、優位性が確認できていなければ 0 になる。
  recommend           : 検証ゲートを通っていなければ賭け金は 0（見送り）。通ったときだけ金額を返す。

重要: 回収率が100%を超えると確認できていない買い方には、賭け金を出さない。
ケリー基準は『本当の的中率』が分かっているときの式で、推定が甘いと過大に賭けて資金を減らす。
"""
import math

UNIT = 100  # 100円単位


def wilson_lower(hits, n, z=1.645):
    """的中率の下側（片側95%）のウィルソン限界。n=0 なら 0。"""
    if n <= 0:
        return 0.0
    p = hits / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (c - m) / d)


def synth_odds(odds):
    inv = sum(1.0 / o for o in odds if o)
    return 1.0 / inv if inv else None


def equal_payout_stakes(odds, budget, unit=UNIT):
    """odds: 買い目のオッズ（確率の高い順）。budget: 総額（円）。
    戻り値: 各買い目の金額（unit の倍数、合計は budget 以下で最大）。予算が点数×unit に満たないときは、
    先頭（確率の高い買い目）から unit ずつ。"""
    odds = [o for o in odds if o and o > 0]
    units = int(budget // unit)
    n = len(odds)
    if not n or units <= 0:
        return [0] * n
    if units < n:
        return [unit if i < units else 0 for i in range(n)]
    inv = [1.0 / o for o in odds]
    tot = sum(inv)
    raw = [units * x / tot for x in inv]
    q = [max(1, int(r)) for r in raw]
    # 合計を units に合わせる（端数の大きい順に足し、超えていれば払戻の小さい（=投下の大きい）ものから引く）
    while sum(q) < units:
        i = max(range(n), key=lambda j: raw[j] - q[j])
        q[i] += 1
    while sum(q) > units:
        i = max((j for j in range(n) if q[j] > 1), key=lambda j: q[j] - raw[j], default=None)
        if i is None:
            break
        q[i] -= 1
    return [x * unit for x in q]


def kelly_fraction(hit_prob, synth):
    """当たれば投下の synth 倍（合成オッズ）が返る賭けのケリー比率。優位性が無ければ 0。"""
    if not synth or synth <= 1 or hit_prob <= 0:
        return 0.0
    return max(0.0, (hit_prob * synth - 1.0) / (synth - 1.0))


def plan_kelly(hits, races, synth, frac=0.25, cap=0.02):
    """的中率は下側限界で見積もる。frac=ケリーの何分の1か、cap=1レースの上限（資金比）。"""
    f = kelly_fraction(wilson_lower(hits, races), synth)
    return min(cap, f * frac)


def recommend(odds, bankroll, hits, races, gate_ok, frac=0.25, cap=0.02, unit=UNIT):
    """1レースの賭け金の提案。
    戻り値 {"budget":円, "stakes":[円...], "fraction":資金比, "reason":文}"""
    s = synth_odds(odds)
    if not gate_ok:
        return {"budget": 0, "stakes": [0] * len(odds), "fraction": 0.0,
                "reason": "検証で回収率100%超えを確認できていないため見送り"}
    f = plan_kelly(hits, races, s, frac, cap)
    budget = int(bankroll * f // unit * unit)
    if budget <= 0:
        return {"budget": 0, "stakes": [0] * len(odds), "fraction": round(f, 4),
                "reason": "的中率の下側限界で見ると優位性がないため見送り"}
    return {"budget": budget, "stakes": equal_payout_stakes(odds, budget, unit), "fraction": round(f, 4),
            "reason": f"ケリー1/{round(1 / frac)}（上限{cap * 100:.0f}%）"}
