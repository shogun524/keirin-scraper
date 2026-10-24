"""
winticket で取ったレースの予想を、実績に合わせて直す後処理。

10/23・10/24 の66レースで確かめたこと:
  - 3連単のオッズ（人気）は、AIよりはっきり当たる（1レースあたり対数尤度で約0.8〜1.0の差）。
    人気とAIを混ぜても、AIの比重を上げるほど悪くなった。人気をやや強める（1.15乗）と少し良くなる。
  - オッズが無いときは、AIの1着率を「人気の1着率」に近づける補正（下の COEF）で、
    日をまたいだ検証でも1着の当たり方が改善した（-1.80→-1.50、-1.73→-1.61）。

そこで:
  1) オッズが出ているレース → 3連単の確率 = オッズの確率^MKT_POWER（正規化）
  2) オッズが無いレース     → AIの1着率を COEF で補正し、3連単は1着ごとに比率を掛け直す
いずれも、1着率・3着内率・2着/3着の表・3連単の一覧を、直した同時確率から作り直す。
元のAIの1着率は row["ai_raw"] に残す。
"""
import math

MKT_POWER = 1.15
# 人気の1着率を教師にして学習した係数（特徴量の順は _features と同じ）
COEF = {
    "logAI": 0.39, "得点z": 0.37, "ライン先頭": -0.18, "番手": 0.17, "3番手以降": -0.17,
    "単騎": 0.17, "印◎": 0.43, "印○": 0.22, "印▲": 0.26, "自力型": 0.43,
}
MIN_ODDS_COVERAGE = 0.7

# 買い目の目安（10/23・10/24の確定86レースの分析から）
#   人気ベースの確率順: 1〜5位で34%、1〜10位で59%が的中（6〜10位だけで26%）
#   元のAIの確率順   : 1〜10位で35%。AIの1位の出目は14%（kドリームズ期942レースでは7.7%）
HONSEN_N, OSAE_N = 5, 10
HIST = {"odds": {"honsen": 34, "osae": 59, "n": 86}, "ai_fix": {"honsen": 26, "osae": 35, "n": 86}}


def _features(rows, racers, line_map):
    mk = {r["car"]: r for r in racers}
    sc = [float(mk[r["car"]].get("score") or 0) for r in rows]
    mu = sum(sc) / len(sc)
    sd = (sum((x - mu) ** 2 for x in sc) / len(sc)) ** 0.5 + 1e-6
    out = []
    for r, s in zip(rows, sc):
        rc = mk[r["car"]]
        li = line_map.get(r["car"]) or {}
        ps, ls = li.get("position", 1), li.get("line_size", 1)
        out.append({
            "logAI": math.log(max(r["adjusted"] / 100, 1e-3)), "得点z": (s - mu) / sd,
            "ライン先頭": float(ps == 1 and ls > 1), "番手": float(ps == 2), "3番手以降": float(ps >= 3),
            "単騎": float(ls <= 1), "印◎": float(rc.get("mark") == "◎"), "印○": float(rc.get("mark") == "○"),
            "印▲": float(rc.get("mark") == "▲"), "自力型": float(rc.get("tactic") in ("逃", "両")),
        })
    return out


def corrected_win(rows, racers, line_map):
    """AIの1着率を補正した値 {car: 確率(0-1)}"""
    z = [sum(COEF[k] * v for k, v in f.items()) for f in _features(rows, racers, line_map)]
    m = max(z)
    e = [math.exp(v - m) for v in z]
    s = sum(e)
    return {r["car"]: v / s for r, v in zip(rows, e)}


def ai_joint(result):
    """AIの3連単の同時確率 {(1着,2着,3着): p}（全組み合わせ、合計1）"""
    j = {}
    for c in (result.get("trifecta") or {}).get("combos", []):
        j[(c["first"], c["second"], c["third"])] = c["prob"] / 100
    s = sum(j.values()) or 1
    return {k: v / s for k, v in j.items()}


def market_joint(odds):
    """odds: {(1着,2着,3着): オッズ倍率}"""
    q = {k: (1 / v) ** MKT_POWER for k, v in odds.items() if v and v > 0}
    s = sum(q.values()) or 1
    return {k: v / s for k, v in q.items()}


def rebuild(result, joint, th_high=None, th_close=None):
    """同時確率 joint から、result の1着率・3着内率・2着/3着表・3連単一覧・判定を作り直す"""
    rows = result["rows"]
    cars = [r["car"] for r in rows]
    p1 = {c: 0.0 for c in cars}
    place = {c: 0.0 for c in cars}
    p12 = {}
    for (a, b, c), p in joint.items():
        if a not in p1 or b not in p1 or c not in p1:
            continue
        p1[a] += p
        p12[(a, b)] = p12.get((a, b), 0.0) + p
        for x in (a, b, c):
            place[x] += p
    for r in rows:
        r.setdefault("ai_raw", r["adjusted"])
        r["adjusted"] = p1[r["car"]] * 100
        r["place_rate"] = min(place[r["car"]], 1.0) * 100
    rows.sort(key=lambda r: -r["adjusted"])
    spm = result.get("second_place_matrix") or {}
    for a, cands in spm.items():
        for cd in cands:
            cd["prob"] = (p12.get((a, cd["car"]), 0.0) / p1[a] * 100) if p1.get(a) else 0.0
        cands.sort(key=lambda x: -x["prob"])
    ftd = result.get("full_third_place_data") or {}
    for a, by2 in ftd.items():
        for b, cands in by2.items():
            d = p12.get((a, b), 0.0)
            for cd in cands:
                cd["prob"] = (joint.get((a, b, cd["car"]), 0.0) / d * 100) if d else 0.0
            cands.sort(key=lambda x: -x["prob"])
    tpm = result.get("third_place_matrix") or {}
    for a, info in tpm.items():
        b = info.get("second_car")
        d = p12.get((a, b), 0.0)
        for cd in info.get("candidates", []):
            cd["prob"] = (joint.get((a, b, cd["car"]), 0.0) / d * 100) if d else 0.0
        info.get("candidates", []).sort(key=lambda x: -x["prob"])
    names = {r["car"]: r["name"] for r in rows}
    combos = [{"first": a, "first_name": names.get(a, ""), "second": b, "second_name": names.get(b, ""),
               "third": c, "third_name": names.get(c, ""), "prob": p * 100}
              for (a, b, c), p in joint.items() if a in names and b in names and c in names]
    combos.sort(key=lambda x: -x["prob"])
    tri = result.get("trifecta") or {}
    tri.update({"combos": combos, "coverage": sum(c["prob"] for c in combos),
                "total_prob_check": sum(c["prob"] for c in combos)})
    result["trifecta"] = tri
    s = result.get("settings") or {}
    th_high = th_high if th_high is not None else s.get("th_high", 50)
    th_close = th_close if th_close is not None else s.get("th_close_place", 60)
    result["top"] = rows[0]
    result["top_gap"] = rows[0]["adjusted"] - rows[1]["adjusted"] if len(rows) >= 2 else None
    result["is_high_prob"] = rows[0]["adjusted"] >= th_high
    result["max_place_rate"] = max(r["place_rate"] for r in rows)
    result["is_close_race"] = result["max_place_rate"] < th_close
    return result


def _synth(odds_list):
    """合成オッズ（この点数を同じ金額ずつ買ったとき、どれか当たった場合の平均払戻倍率）"""
    inv = sum(1 / o for o in odds_list if o)
    return round(1 / inv, 1) if inv else None


def mark_buys(result, odds, ai_top):
    """3連単一覧に「本線」「押さえ」「AI1位」のバッジを付け、買い目の目安を trifecta["buy"] に入れる"""
    tri = result.get("trifecta") or {}
    combos = tri.get("combos") or []
    mode = result.get("fix_mode", "ai_fix")
    for i, c in enumerate(combos):
        k = (c["first"], c["second"], c["third"])
        badges = []
        if i < HONSEN_N:
            badges.append("本線")
        elif i < OSAE_N:
            badges.append("押さえ")
        if ai_top and k == ai_top:
            badges.append("AI1位")
        c["badges"] = badges
        if odds and k in odds:
            c["odds"] = odds[k]
    top = combos[:OSAE_N]
    tri["buy"] = {
        "mode": mode,
        "honsen": ["-".join(map(str, (c["first"], c["second"], c["third"]))) for c in combos[:HONSEN_N]],
        "osae": ["-".join(map(str, (c["first"], c["second"], c["third"]))) for c in combos[HONSEN_N:OSAE_N]],
        "ai_top": "-".join(map(str, ai_top)) if ai_top else None,
        "p_honsen": round(sum(c["prob"] for c in combos[:HONSEN_N]), 1),
        "p_all": round(sum(c["prob"] for c in top), 1),
        "synth_honsen": _synth([c.get("odds") for c in combos[:HONSEN_N]]) if odds else None,
        "synth_all": _synth([c.get("odds") for c in top]) if odds else None,
        "hist": HIST[mode],
    }
    result["trifecta"] = tri
    return result


def apply(result, racers, odds=None):
    """result を直して返す。odds: {(1着,2着,3着): 倍率} または None。result["fix_mode"] に方式を記録。"""
    if not result or not result.get("trifecta"):
        return result
    n = len(result["rows"])
    total = n * (n - 1) * (n - 2)
    aj0 = ai_joint(result)
    ai_top = max(aj0, key=aj0.get) if aj0 else None
    if odds and len(odds) >= total * MIN_ODDS_COVERAGE:
        rebuild(result, market_joint(odds))
        result["fix_mode"] = "odds"
        return mark_buys(result, odds, ai_top)
    w = corrected_win(result["rows"], racers, result.get("line_map") or {})
    aj = ai_joint(result)
    head = {}
    for (a, _, _), p in aj.items():
        head[a] = head.get(a, 0.0) + p
    joint = {k: p * w.get(k[0], 0) / head[k[0]] for k, p in aj.items() if head.get(k[0])}
    s = sum(joint.values()) or 1
    rebuild(result, {k: v / s for k, v in joint.items()})
    result["fix_mode"] = "ai_fix"
    return mark_buys(result, odds, ai_top)
