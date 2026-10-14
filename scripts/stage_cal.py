# -*- coding: utf-8 -*-
"""
段階別の追加補正（毎日の再学習）。予想成績ログの「補正前の確率」と実際の着順から、次の3つを別々に学習する。

  s1（1着）: 確率 ∝ p^a × exp(θ[予測決まり手])    … 逃が基準。実績では逃・捲りが過小、差し・マークが過大だった
  s2（2着）: 確率 ∝ p^slope × exp(same + adj)    … 1着と同じライン／そのうち隣の位置、の上乗せ
  s3（3着）: 同上（1着・2着のどちらかと同じライン）

どれも「レース内で1人を選ぶ」条件付きロジット（softmax）で、基準値（a=slope=1, θ=0）に引き戻す
L2 事前分布つき。適用するのは、次のゲートを全部通ったときだけ（通らなければ補正なし＝従来どおり）。
  ・件数: 車立てグループ別に MIN_RACES 以上（8車以上は件数・開催場数とも多めに要求）
  ・尤度比検定: 基準値からの改善が p<0.01（自由度=係数の数）
  ・日単位の1日抜き交差検証: 全体で損失が改善し、改善した日が過半数
係数には上限・下限をかけ、前回値と平均して1日の変化を小さくする。
※ 第三者レビューでの指摘: 8車以上は検証データが1開催場（弥彦）だけで一般化の根拠が弱いので、
  開催場4つ・150レースがそろうまで適用しない。
"""
import math
import collections

DOMS = ("捲", "差", "マ")
MIN_RACES = {"7": 200, "9": 150}
MIN_VENUES = {"7": 6, "9": 4}
LAMBDA = 3.0
SMOOTH = 0.5
CHI2_99 = {2: 9.21, 3: 11.34, 4: 13.28}
CLIP = {"a": (0.6, 1.1), "slope": (0.6, 1.15), "dom": (-1.2, 0.6), "adj": (-0.5, 1.5), "same": (-0.5, 1.5)}
MIN_DAYS = 5
LFB_DEFAULT = 45.0


def _solve(A, b):
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[p] = M[p], M[c]
        d = M[c][c] or 1e-12
        for r in range(n):
            if r != c:
                f = M[r][c] / d
                for k in range(c, n + 1):
                    M[r][k] -= f * M[c][k]
    return [M[i][n] / (M[i][i] or 1e-12) for i in range(n)]


def _race_terms(F, theta):
    s = [sum(f * t for f, t in zip(row, theta)) for row in F]
    m = max(s)
    e = [math.exp(v - m) for v in s]
    z = sum(e)
    return s, [v / z for v in e], m + math.log(z)


def loglik(data, theta):
    """data: [(F, chosen_index, meta)]。chosen の対数確率の合計。"""
    tot = 0.0
    for F, w, _ in data:
        s, _p, lse = _race_terms(F, theta)
        tot += s[w] - lse
    return tot


def fit(data, prior, lam=LAMBDA, iters=12):
    k = len(prior)
    th = list(prior)
    for _ in range(iters):
        g = [lam * (th[i] - prior[i]) for i in range(k)]
        H = [[lam if i == j else 0.0 for j in range(k)] for i in range(k)]
        for F, w, _ in data:
            _s, P, _l = _race_terms(F, th)
            mu = [sum(P[r] * F[r][i] for r in range(len(F))) for i in range(k)]
            for i in range(k):
                g[i] -= F[w][i] - mu[i]
            for r in range(len(F)):
                for i in range(k):
                    for j in range(k):
                        H[i][j] += P[r] * F[r][i] * F[r][j]
            for i in range(k):
                for j in range(k):
                    H[i][j] -= mu[i] * mu[j]
        step = _solve(H, g)
        th = [t - max(-1.5, min(1.5, d)) for t, d in zip(th, step)]
        if max(abs(d) for d in step) < 1e-6:
            break
    return th


# ---------------- データ作り ----------------
def _norm_pct(pm):
    t = sum(pm.values()) or 1.0
    return {c: v / t for c, v in pm.items()}


def _gamma0():
    from model import DEFAULT_SETTINGS
    return float(DEFAULT_SETTINGS["sharpness_first"])


def stage1_data(entries):
    """entries: [(date, venue, log_entry)] → 1着段階。特徴量 [log p, 捲, 差, マ]。"""
    out = []
    for date, venue, e in entries:
        cond = e.get("cond") or {}
        cars, doms = cond.get("cars"), cond.get("dom")
        probs = e.get("p0") or e.get("probs")
        fin = (e.get("result") or {}).get("finish_order") or []
        if not cars or not doms or not probs or not fin or len(cars) != len(doms):
            continue
        if fin[0] not in cars:
            continue
        pm = {int(c): float(p1) for c, p1, *_ in probs if p1 and p1 > 0}
        if set(pm) != set(cars) or fin[0] not in pm:
            continue
        # 記録時の絞り込み(sf)がまちまちなので、既定の絞り込みにそろえた確率で学習する（推論側も既定の絞り込みを使う）
        sf = float(e.get("sf") or 0) or _gamma0()
        pn = _norm_pct({c: v ** (_gamma0() / sf) for c, v in pm.items()})
        F = [[math.log(max(pn[c], 1e-9))] + [1.0 if d == k else 0.0 for k in DOMS] for c, d in zip(cars, doms)]
        out.append((F, cars.index(fin[0]), (date, venue)))
    return out


def _stage_feats(cands):
    return [[math.log(max(c["prob"] / 100, 1e-6)), 1.0 if c["same_line"] else 0.0,
             1.0 if (c["same_line"] and c.get("dist") is not None and c["dist"] <= 1) else 0.0] for c in cands]


def stage23_data(entries):
    """2着段階・3着段階。補正なし（cal=None）の確率を、ログの入力から本番の関数で再計算する。"""
    import model
    d2, d3 = [], []
    sharp = float(model.DEFAULT_SETTINGS["sharpness"])
    for date, venue, e in entries:
        try:
            cond = e.get("cond") or {}
            fin = (e.get("result") or {}).get("finish_order") or []
            cars = cond.get("cars")
            if not cars or len(fin) < 3 or not set(fin[:3]) <= set(cars):
                continue
            if not (len(cars) == len(cond["dom"]) == len(cond["scores"])):
                continue
            racers = [{"car": c, "name": ""} for c in cars]
            idx = {c: i for i, c in enumerate(cars)}
            dom = [{"type": t} for t in cond["dom"]]
            lm = {c: {"line_index": ln[0], "position": ln[1], "line_size": ln[2]}
                  for c, ln in zip(cars, cond.get("line") or []) if ln}
            y, z, w = fin[:3]
            # 2着・3着側は、記録時の(日々変わる)ライン追走・絞り込みではなく既定値で再計算する。
            # 推論側も、この補正が有効なときは既定値を使うので、二重に補正しない。
            s23 = sharp * max(1.0, (len(cars) - 1) / 6)
            args = (cond["scores"], dom, lm, cond["adv_bonus"], cond["adv_penalty"], LFB_DEFAULT, s23)
            c2 = model.compute_second_place_candidates(racers, idx[y], *args)
            r2 = (_stage_feats(c2), [c["car"] for c in c2].index(z), (date, venue))
            c3 = model.compute_third_place_candidates(racers, idx[y], idx[z], *args)
            r3 = (_stage_feats(c3), [c["car"] for c in c3].index(w), (date, venue))
        except (KeyError, IndexError, ValueError, TypeError):
            continue        # 壊れた1件で学習全体を止めない
        d2.append(r2)
        d3.append(r3)
    return d2, d3


# ---------------- 学習・ゲート ----------------
def _loo(data, prior):
    """日単位の1日抜き: (対数損失の改善の合計[正=改善], 改善した日数, 日数)。"""
    by = collections.defaultdict(list)
    for r in data:
        by[r[2][0]].append(r)
    gain, better = 0.0, 0
    for d, test in by.items():
        train = [r for r in data if r[2][0] != d]
        th = fit(train, prior)
        g = loglik(test, th) - loglik(test, prior)
        gain += g
        better += g > 0
    return gain, better, len(by)


def _clip(vals, kinds):
    return [max(CLIP[k][0], min(CLIP[k][1], v)) for v, k in zip(vals, kinds)]


def fit_stage(data, group, names, kinds, prior, prev=None, venues=None):
    """1段階ぶんの学習とゲート判定。戻り値: dict（active と係数・診断）。"""
    n = len(data)
    info = {"n": n, "min_races": MIN_RACES[group], "min_venues": MIN_VENUES[group], "active": False}
    nv = len(venues) if venues is not None else len({r[2][1] for r in data})
    info["venues"] = nv
    if n < MIN_RACES[group] or nv < MIN_VENUES[group]:
        info["reason"] = "件数不足"
        return info
    th = fit(data, prior)
    lr = 2 * (loglik(data, th) - loglik(data, prior))
    info.update({"lr": round(lr, 2), "fit_raw": [round(v, 3) for v in th],
                 "ll_per_race_default": round(-loglik(data, prior) / n, 4)})
    crit = CHI2_99[len(prior)]
    keep = bool(prev) and lr >= 0.6 * crit      # すでに適用中なら、少し下回っても急には外さない（ヒステリシス）
    if lr < 0.6 * crit:
        info["reason"] = "ゲート不通過（偶然の範囲）"
        return info
    gain, better, days = _loo(data, prior) if len({r[2][0] for r in data}) >= MIN_DAYS else (0.0, 0, 0)
    info.update({"loo_gain_per_race": round(gain / n, 4), "loo_days_better": better, "loo_days": days})
    strict = lr >= crit and days >= MIN_DAYS and gain > 0 and better * 2 > days
    keep = keep and gain > 0
    if not (strict or keep):
        info["reason"] = "ゲート不通過（偶然の範囲／日ごとに安定しない）"
        return info
    # 初回も前回値(なければ基準値)との平均で縮める。上振れ(勝者の呪い)を抑えるため
    pv = [(prev or {}).get(k, p) for k, p in zip(names, prior)]
    new = _clip([SMOOTH * a + (1 - SMOOTH) * b for a, b in zip(pv, _clip(th, kinds))], kinds)
    info["active"] = True
    info["coef"] = {k: round(v, 3) for k, v in zip(names, new)}
    info["ll_per_race_new"] = round(-loglik(data, new) / n, 4)
    info["min_venues"] = MIN_VENUES[group]
    return info


def fit_all(log_entries, prev_cal=None):
    """
    log_entries: [(date, venue, entry)]（結果が正常で late でないもの）をグループ別に分けて渡す想定。
    戻り値: {"7": {"s1":info,"s2":info,"s3":info}, "9": {...}}
    """
    prev_cal = prev_cal or {}
    out = {}
    for g in ("7", "9"):
        ent = [x for x in log_entries
               if (len((x[2].get("cond") or {}).get("cars") or []) >= 8) == (g == "9")]
        d1 = stage1_data(ent)
        d2, d3 = stage23_data(ent)
        pv = prev_cal.get(g) or {}
        def pc(k):
            i = pv.get(k) or {}
            return i.get("coef") if i.get("active") else None
        out[g] = {
            "s1": fit_stage(d1, g, ["a", "捲", "差", "マ"], ["a", "dom", "dom", "dom"], [1.0, 0.0, 0.0, 0.0], pc("s1")),
            "s2": fit_stage(d2, g, ["slope", "same", "adj"], ["slope", "same", "adj"], [1.0, 0.0, 0.0], pc("s2")),
            "s3": fit_stage(d3, g, ["slope", "same", "adj"], ["slope", "same", "adj"], [1.0, 0.0, 0.0], pc("s3")),
        }
    return out


def overrides(stage_cal):
    """predict_race の settings["stage_cal"] 用。ゲートを通った段階の係数だけ返す。"""
    res = {}
    for g, st in (stage_cal or {}).items():
        d = {}
        for k, info in st.items():
            if info.get("active") and info.get("coef"):
                d[k] = dict(info["coef"])
        if d:
            res[g] = d
    return res
