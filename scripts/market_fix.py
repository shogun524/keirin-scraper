"""
winticket で取ったレースの予想を、実績に合わせて直す後処理。

10/23・10/24 の66レースで確かめたこと:
  - 3連単のオッズ（人気）は、AIよりはっきり当たる（1レースあたり対数尤度で約0.8〜1.0の差）。
    人気とAIを混ぜても、AIの比重を上げるほど悪くなった。人気をやや強める（1.15乗）と少し良くなる。
  - オッズが無いときは、AIの1着率を「人気の1着率」に近づける補正（下の COEF）で、
    日をまたいだ検証でも1着の当たり方が改善した（-1.80→-1.50、-1.73→-1.61）。

そこで:
  1) オッズが出ているレース → 3連単の確率 = オッズの確率を累乗して正規化（本命寄りは1.1乗、30倍以上の穴は1.0乗）
  2) オッズが無いレース     → AIの1着率を COEF で補正し、3連単は1着ごとに比率を掛け直す
いずれも、1着率・3着内率・2着/3着の表・3連単の一覧を、直した同時確率から作り直す。
元のAIの1着率は row["ai_raw"] に残す。
"""
import math

# オッズ→確率の累乗。10/24〜10/26の確定181レースで、勝った出目に付けた確率の対数を比べて決めた。
#   30倍未満は1.1乗、30倍以上は1.0乗（以前は全体1.15乗）。1レースあたり約0.016良くなり、
#   10/24で決めて10/25-26で試す／その逆、のどちらでも改善した（差は小さいので過信しない）。
MKT_POWER_LOW = 1.1
MKT_POWER_HIGH = 1.0
MKT_KNEE = 30.0
# 人気の1着率を教師にして学習した係数（特徴量の順は _features と同じ）
COEF = {
    "logAI": 0.39, "得点z": 0.37, "ライン先頭": -0.18, "番手": 0.17, "3番手以降": -0.17,
    "単騎": 0.17, "印◎": 0.43, "印○": 0.22, "印▲": 0.26, "自力型": 0.43,
}
MIN_ODDS_COVERAGE = 0.7

# 買い目の目安（10/24〜10/26の確定181レース=保存済みwinticketページの分析から。10/23分はアーカイブ無し）
#   人気ベースの確率順: 1〜5位で34%、1〜10位で59%が的中（6〜10位だけで26%）
#   元のAIの確率順   : 1〜10位で35%。AIの1位の出目は14%（kドリームズ期942レースでは7.7%）
HONSEN_N, OSAE_N = 5, 10
HIST = {"odds": {"honsen": 39, "osae": 52, "n": 181}, "ai_fix": {"honsen": 26, "osae": 35, "n": 86}}  # ai_fix は旧集計(86レース)のまま


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
    def w(o):
        # 30倍で折れ曲がっても値が飛ばないよう、折れ点で連続させる
        return o ** -MKT_POWER_LOW if o < MKT_KNEE else MKT_KNEE ** -MKT_POWER_LOW * (o / MKT_KNEE) ** -MKT_POWER_HIGH
    q = {k: w(v) for k, v in odds.items() if v and v > 0}
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


# レースの型ごとの自動おすすめ。成績は buy_stats が毎日の自動記録（docs/_buy_log.json）から集計して差し替える（LIVE_HIST）。
#
# 10/24〜10/26の確定181レースでの検証（オッズは保存ページの約8割の組を使った近似、回収率は的中時の払戻で計算）:
#   堅い(99R): 合成1.5倍まで 的中58%・回収93%（90%区間74〜116）。押さえまで10点は的中65%・回収88%、本線5点は80%。
#              （点数が少なすぎるとき10点に戻す処理を入れた実装での数字。処理なしだと99%）
#   中間(56R): 5点が71%で最良。ほかは44〜69%で、全部、控除率25%の控除後の水準(75%)を下回る → 見送り目安
#   混戦(26R): 買い方で回収が8〜142%とブレが極端で、件数も少ない → 見送り目安
# 注意: 40通り（4型×10買い方）を試して良いものを選んでいるので、堅い×合成1.5倍の高さは「選び方の偏り」で
#       高く見えている可能性がある。今日以降の自動記録（live）で前向きに検証し直す。
AUTO = {
    "堅い": {"plan": "合成オッズ1.5倍まで", "id": "syn1.5", "target": 1.5, "skip": False,
             "hist": "10/24〜10/26の99レースで的中58%・回収率93%（前向き検証はこれから）"},
    "中間": {"plan": "見送り目安（買うなら5点）", "id": "top5", "target": None, "skip": True,
             "hist": "10/24〜10/26の56レースで5点の回収率71%（どの買い方も控除後の75%以下）"},
    "混戦": {"plan": "見送り目安（買うなら5点）", "id": "top5", "target": None, "skip": True,
             "hist": "10/24〜10/26の26レース。買い方で回収が大きくブレて判断できない"},
}
LIVE_HIST = {}  # {型: 成績の文章}。buy_stats.publish_hist が毎回セットする


def race_type(rows):
    top = max(r["adjusted"] for r in rows)
    return "堅い" if top >= 45 else ("混戦" if top < 30 else "中間")


def pick_synth(items, target):
    """items: [(キー, オッズ)] を確率の高い順に並べたもの。合成オッズが target を下回る手前まで取る。"""
    sel, inv = [], 0.0
    for k, o in items:
        if not o:
            continue
        if 1 / (inv + 1 / o) < target:
            break
        sel.append(k)
        inv += 1 / o
    return sel


def pick_plan(items, plan_id):
    """items: [(キー, オッズ)]（確率の高い順）。plan_id: 'syn1.5' / 'syn2' / 'topN'。選んだキーの一覧を返す。"""
    if plan_id.startswith("syn"):
        sel = pick_synth(items, float(plan_id[3:]))
        return sel if len(sel) >= 3 else [k for k, _ in items[:OSAE_N]]  # 点数が少なすぎるときは10点
    return [k for k, _ in items[:int(plan_id[3:])]]


def auto_plan(result, odds):
    """レースの型を判定して、買い目を自動で選ぶ。trifecta["auto"] に入れる。"""
    combos = (result.get("trifecta") or {}).get("combos") or []
    if not combos:
        return None
    rtype = race_type(result["rows"])
    cfg = AUTO[rtype]
    keyed = [((c["first"], c["second"], c["third"]), c) for c in combos]
    plan = cfg["plan"]
    if odds and cfg["target"]:
        chosen = pick_plan([(k, odds.get(k)) for k, _ in keyed], cfg["id"])
        cmap = dict(keyed)
        sel = [(k, cmap[k]) for k in chosen]
        if len(chosen) == OSAE_N and cfg["id"].startswith("syn"):
            pts = pick_synth([(k, odds.get(k)) for k, _ in keyed], cfg["target"])
            if len(pts) < 3:
                plan = f"押さえまで10点（合成{cfg['target']}倍では点数が少なすぎるため）"
    else:
        n = 5 if cfg["skip"] else OSAE_N
        sel = keyed[:n]
        if not cfg["skip"]:
            plan = "押さえまで10点（オッズ発売前のため仮）"
    ol = [odds.get(k) for k, _ in sel] if odds else []
    auto = {
        "type": rtype, "plan": plan, "hist": LIVE_HIST.get(rtype) or cfg["hist"], "skip": cfg["skip"],
        "keys": ["-".join(map(str, k)) for k, _ in sel],
        "probs": [round(c["prob"], 2) for _, c in sel],
        "odds": ol,
        "p": round(sum(c["prob"] for _, c in sel), 1),
        "synth": _synth(ol) if ol and all(ol) else None,
        "mode": result.get("fix_mode"),
    }
    if not cfg["skip"]:
        for _, c in sel:
            c.setdefault("badges", []).append("おすすめ")
    result["trifecta"]["auto"] = auto
    return auto


# ---- 穴目予想（万車券＝3連単が1万円以上＝100倍以上）----
# 10/24〜10/26の確定181レースの分析（万車券は49レース=27%）:
#   本命の1着率(補正後)別の万車券率: 30%未満38%(10/26) / 30〜45%39%(24/62) / 45〜60%21%(11/53) / 60%以上10%(4/40)
#   ガールズは1/14=7%と少ない。→ 「本命が弱いレースほど出やすい」をレース単位の目安として表示する。
#   買い目は、確率が高い順に50倍以上から5点を選ぶ形が一番マシだった（的中6%・回収70%）。
#   100倍以上だけに絞ると的中2〜5%・回収40〜55%と悪かった。どれも控除後の水準(75%)を超えていないので、
#   「万車券を狙う穴目の参考」であって、儲かる買い方としては出さない。
#   オッズから出した万車率（100倍以上の組の確率の合計）は、予測が高いほど実際も高く並びが合っていた。
#   予測12%→実際12%（33R）、20%→22%（88R）、29%→40%（47R）、41%→60%（10R）。平均は予測23%・実際27%で、やや低め。
#   注意: 保存ページのオッズは約8割の組だけで、万車券49件のうち勝ち出目が入っていたのは29件(59%)。検証は甘め。
MAN_ODDS = 100.0
ANA_MIN_ODDS = 50.0
ANA_N = 5
MAN_RATE = [(30.0, 38), (45.0, 39), (60.0, 21), (1e9, 10)]  # (本命1着率の上限, 万車券率%)
MAN_RATE_GIRLS = 7


def man_chance(top, girls=False):
    """本命の1着率(%)から、このレースが万車券になる目安(%)を返す（過去181レースの実績率）。"""
    if girls:
        return MAN_RATE_GIRLS
    for lim, rate in MAN_RATE:
        if top < lim:
            return rate
    return MAN_RATE[-1][1]


def ana_plan(result, odds, girls=False):
    """穴目予想を trifecta["ana"] に入れる。オッズが無いときは万車券の出やすさだけ。"""
    if not result or not result.get("trifecta") or not result.get("rows"):
        return None
    top = max(r["adjusted"] for r in result["rows"])
    ana = {"man_chance": man_chance(top, girls), "top": round(top, 1), "girls": bool(girls),
           "keys": [], "probs": [], "odds": [], "mode": result.get("fix_mode"),
           "hist": "10/24〜10/26の181レース: 万車券は27%。穴目5点（50倍以上）は的中6%・回収70%"}
    if odds and result.get("fix_mode") == "odds":
        joint = market_joint(odds)
        cand = sorted(((k, p) for k, p in joint.items() if odds.get(k, 0) >= ANA_MIN_ODDS), key=lambda kv: -kv[1])[:ANA_N]
        ana["keys"] = ["-".join(map(str, k)) for k, _ in cand]
        ana["probs"] = [round(p * 100, 2) for _, p in cand]
        ana["odds"] = [odds[k] for k, _ in cand]
        ana["p"] = round(sum(ana["probs"]), 1)
        # 万車率：オッズから見た「100倍以上の出目が来る確率」（全組の確率の合計。過去181レースでは実際より2〜4pt低め）
        ana["man_odds"] = round(sum(p for k, p in joint.items() if odds.get(k, 0) >= MAN_ODDS) * 100, 1)
    result["trifecta"]["ana"] = ana
    return ana


def mark_buys(result, odds, ai_top, ai_probs=None):
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
        if ai_probs is not None:
            c["ai"] = round(ai_probs.get(k, 0.0) * 100, 3)   # 補正前のAIの確率（%）
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
    auto_plan(result, odds)
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
        return mark_buys(result, odds, ai_top, aj0)
    w = corrected_win(result["rows"], racers, result.get("line_map") or {})
    aj = ai_joint(result)
    head = {}
    for (a, _, _), p in aj.items():
        head[a] = head.get(a, 0.0) + p
    joint = {k: p * w.get(k[0], 0) / head[k[0]] for k, p in aj.items() if head.get(k[0])}
    s = sum(joint.values()) or 1
    rebuild(result, {k: v / s for k, v in joint.items()})
    result["fix_mode"] = "ai_fix"
    return mark_buys(result, odds, ai_top, aj0)
