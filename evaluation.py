# -*- coding: utf-8 -*-
"""
予想の評価（統計的に正しく測る）。表示用の集計(prediction_log.py)とは別に、確率の質を測る。

  ・全選手ベースの校正表（予測確率の帯 / 件数 / 平均予測 / 実際の1着率 / 95%信頼区間）
  ・Log Loss と Brier スコア（ランダム＝車数分の1 を基準にして比べる）
  ・日付順のウォークフォワード検証：評価する日より前の日のデータだけで補正器を学習し、その日を評価する
     （同じレース・同じ日が学習側と評価側に分かれない）。比較するのは同じ評価レース。
  ・校正器の候補（γの再推定／方程式バフ／等調回帰 isotonic）を本番とは独立に評価する。
     本番へ自動適用されるのは calibration.py の有意性ゲートを通ったものだけ。ここは「測るだけ」。
  ・結果は docs/_eval_report.json に保存し、予想成績ページから参照する（表示と計算根拠を一致させる）。
  ・回収率：払戻・オッズをログに持っていないため「評価不能」。架空の値は出さない。

評価に使うレース：結果が3着ぶん揃っていて、締切前に予想を記録したもの（prediction_log.exclusion_reason が None）。
"""

import os
import json
import math
import random
import datetime

import calibration as C
from prediction_log import exclusion_reason

REPORT_FILENAME = "_eval_report.json"
MIN_TRAIN = 60              # ウォークフォワードで学習側に最低限必要なレース数
MIN_TEST = 80               # 前向きの評価レース数がこれ未満なら結論を出さない
BOOT = 1000
CAL_BINS = [(0, 5), (5, 10), (10, 15), (15, 20), (20, 30), (30, 40), (40, 50), (50, 101)]
FAV_BINS = [(0, 20), (20, 30), (30, 40), (40, 50), (50, 101)]


def wilson(k, n, z=1.96):
    """二項比率の Wilson 95%信頼区間（%）。"""
    if n <= 0:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    a = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - a) / d * 100, (c + a) / d * 100)


def race_samples(log):
    """評価対象レースを、日付順の標本リストにして返す。確率は%。"""
    out = []
    for e in log.values():
        if exclusion_reason(e) is not None:
            continue
        probs = e.get("probs")
        fin = e["result"]["finish_order"]
        if not probs or fin[0] is None:
            continue
        p_final = {int(c): float(p1) for c, p1, *_ in probs if p1 and p1 > 0}
        p0 = {int(c): float(p1) for c, p1, *_ in (e.get("p0") or probs) if p1 and p1 > 0}
        if fin[0] not in p_final or len(p_final) < 3 or fin[0] not in p0:
            continue
        z = C._z_from_ev(e["ev"]) if e.get("ev") else None
        out.append({"date": e["date"], "venue": e.get("venue"), "n": len(p_final), "winner": fin[0], "fin": fin,
                    "p": p_final, "p0": p0, "z": z, "sf": float(e.get("sf") or C._default_gamma())})
    out.sort(key=lambda s: s["date"])
    return out


def _norm(pm):
    t = sum(pm.values()) or 1.0
    return {c: v / t for c, v in pm.items()}


def race_loss(pm, winner):
    """1レースの (Log Loss, Brier)。pm は合計1に正規化して使う。"""
    q = _norm(pm)
    ll = -math.log(max(q.get(winner, 0.0), 1e-9))
    br = sum((v - (1.0 if c == winner else 0.0)) ** 2 for c, v in q.items())
    return ll, br


def metrics(samples, key="p"):
    n = len(samples)
    if not n:
        return {"n": 0}
    ll = br = 0.0
    acc = 0
    for s in samples:
        a, b = race_loss(s[key], s["winner"])
        ll += a; br += b
        acc += max(s[key], key=s[key].get) == s["winner"]
    return {"n": n, "logloss": ll / n, "brier": br / n, "accuracy": acc / n * 100,
            "uniform_logloss": sum(math.log(s["n"]) for s in samples) / n}


def calibration_all(samples, key="p"):
    """全選手ベースの校正表（本命だけの帯別表より選択バイアスが小さい）。"""
    rows = []
    for lo, hi in CAL_BINS:
        n = k = 0
        sp = 0.0
        for s in samples:
            q = _norm(s[key])
            for c, v in q.items():
                if lo <= v * 100 < hi:
                    n += 1; sp += v * 100; k += (c == s["winner"])
        if n:
            ci = wilson(k, n)
            rows.append({"lo": lo, "hi": min(hi, 100), "n": n, "pred": sp / n, "actual": k / n * 100,
                         "ci_lo": ci[0], "ci_hi": ci[1], "diff": k / n * 100 - sp / n,
                         "ci_contains_pred": ci[0] <= sp / n <= ci[1]})
    return rows


def favorite_bands(samples, key="p"):
    """本命（予測1着率が最大の選手）の予測確率帯ごと。"""
    rows = []
    for lo, hi in FAV_BINS:
        n = k = 0
        sp = 0.0
        for s in samples:
            q = _norm(s[key])
            fav = max(q, key=q.get)
            v = q[fav] * 100
            if lo <= v < hi:
                n += 1; sp += v; k += (fav == s["winner"])
        if n:
            ci = wilson(k, n)
            rows.append({"lo": lo, "hi": min(hi, 100), "n": n, "pred": sp / n, "actual": k / n * 100,
                         "ci_lo": ci[0], "ci_hi": ci[1], "diff": k / n * 100 - sp / n,
                         "ci_contains_pred": ci[0] <= sp / n <= ci[1]})
    return rows


# ---------------- 等調回帰（校正器の候補。本番には使わない） ----------------
def fit_isotonic(points):
    """points: [(予測確率(0-1), 1着=1/0)]。PAV で単調増加の階段関数を学習し、(境界x, 値y) のリストを返す。"""
    pts = sorted(points)
    blocks = [[x, y, 1.0, x] for x, y in pts]   # [x_min, 和, 重み, x_max] 和=ysum
    # ブロックは (x_max, 平均, 重み) で管理
    stack = []
    for x, y in pts:
        stack.append([x, x, y, 1.0])           # [x_min, x_max, ysum, w]
        while len(stack) >= 2 and stack[-2][2] / stack[-2][3] >= stack[-1][2] / stack[-1][3]:
            b = stack.pop()
            a = stack.pop()
            stack.append([a[0], b[1], a[2] + b[2], a[3] + b[3]])
    return [(b[1], b[2] / b[3]) for b in stack]


def apply_isotonic(fit, p, floor=1e-4):
    for xmax, y in fit:
        if p <= xmax:
            return max(y, floor)
    return max(fit[-1][1], floor) if fit else p


def isotonic_probs(fit, pm):
    q = _norm(pm)
    out = {c: apply_isotonic(fit, v) for c, v in q.items()}
    return _norm(out)          # レース内で合計1に戻す


# ---------------- ウォークフォワード ----------------
def _gamma_pm(pm0, sf, gamma, beta=0.0, z=None):
    e = gamma / sf
    w = {c: (v ** e) * (math.exp(beta * z[c]) if (beta and z and c in z) else 1.0) for c, v in pm0.items()}
    return _norm(w)


def walk_forward(samples, min_train=MIN_TRAIN, return_per=False):
    """
    評価日ごとに「その日より前の日」だけで学習し、その日のレースを評価する。
    戻り値: {"n_test","first_test_day","models":{名前:{logloss,brier,per_race:[...]}}, ...}
    """
    days = sorted({s["date"] for s in samples})
    g0 = C._default_gamma()
    names = ["uniform", "current(p0)", "gamma_refit", "gamma+formula", "isotonic"]
    per = {k: [] for k in names}      # [(date, ll, brier)]
    pred_log = {k: [] for k in names}  # テスト用：各評価レースに付けた確率
    first = None
    for d in days:
        train = [s for s in samples if s["date"] < d]
        test = [s for s in samples if s["date"] == d]
        if len(train) < min_train:
            continue
        first = first or d
        g_samples = [(s["p0"], s["sf"], s["winner"]) for s in train]
        g = C.fit_gamma(g_samples, g0)
        b_samples = [(s["p0"], s["sf"], s["winner"], s["z"]) for s in train if s["z"]]
        beta = C.fit_beta(b_samples, g) if len(b_samples) >= C.MIN_RACES_B else 0.0
        pts = [(v, 1 if c == s["winner"] else 0) for s in train for c, v in _norm(s["p0"]).items()]
        iso = fit_isotonic(pts)
        for s in test:
            cands = {
                "uniform": {c: 1.0 for c in s["p0"]},
                "current(p0)": s["p0"],
                "gamma_refit": _gamma_pm(s["p0"], s["sf"], g),
                "gamma+formula": _gamma_pm(s["p0"], s["sf"], g, beta, s["z"]),
                "isotonic": isotonic_probs(iso, s["p0"]),
            }
            for k, pm in cands.items():
                ll, br = race_loss(pm, s["winner"])
                per[k].append((d, ll, br))
                pred_log[k].append((d, _norm(pm)))
    n = len(per["current(p0)"])
    res = {"n_test": n, "first_test_day": first, "models": {}}
    if return_per:
        res["_per"] = per         # テスト用：各評価レースの損失（日付, LogLoss, Brier）
        res["_pred"] = pred_log   # テスト用：各評価レースに付けた確率
    if not n:
        return res
    for k, rows in per.items():
        res["models"][k] = {"logloss": sum(r[1] for r in rows) / n, "brier": sum(r[2] for r in rows) / n}
    # 現行(p0)との差を、日単位のブートストラップで区間つきにする（同じ日のレースは相関するため）
    rnd = random.Random(0)
    byday = {}
    for i, r in enumerate(per["current(p0)"]):
        byday.setdefault(r[0], []).append(i)
    keys = list(byday)
    for k in ("gamma_refit", "gamma+formula", "isotonic", "uniform"):
        d_all = [per[k][i][1] - per["current(p0)"][i][1] for i in range(n)]   # 損失の差（負=改善）
        boots = []
        for _ in range(BOOT):
            idx = [i for kk in (rnd.choice(keys) for _ in keys) for i in byday[kk]]
            boots.append(sum(d_all[i] for i in idx) / len(idx))
        boots.sort()
        mean = sum(d_all) / n
        lo, hi = boots[int(BOOT * 0.025)], boots[int(BOOT * 0.975)]
        res["models"][k]["logloss_diff_vs_current"] = mean
        res["models"][k]["diff_ci"] = [lo, hi]
        if k == "uniform":
            res["models"][k]["verdict"] = "基準（ランダム）"
        elif n < MIN_TEST:
            res["models"][k]["verdict"] = f"評価不能（前向きの評価レースが{n}件＜{MIN_TEST}件）"
        elif hi < 0:
            res["models"][k]["verdict"] = "改善（区間が0を下回る）"
        elif lo > 0:
            res["models"][k]["verdict"] = "悪化"
        else:
            res["models"][k]["verdict"] = "改善とは言えない（区間が0をまたぐ）→ 採用しない"
    return res


def build_report(log, today):
    samples = race_samples(log)
    rep = {
        "generated": datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M"),  # JST
        "n_races": len(samples),
        "period": [samples[0]["date"], samples[-1]["date"]] if samples else None,
        "exclusion": "結果が3着ぶん未取得・着順不足、締切後に予想を記録したレースを除く",
        "payout": "評価不能（払戻・オッズをログに保存していないため回収率・収支は算出しない）",
    }
    if not samples:
        return rep
    rep["metrics_final"] = metrics(samples, "p")        # 実際に公開した確率（バフ込み）
    rep["metrics_pre_buff"] = metrics(samples, "p0")    # バフ前
    rep["calibration_all"] = calibration_all(samples, "p")
    rep["favorite_bands"] = favorite_bands(samples, "p")
    rep["walk_forward"] = walk_forward(samples)
    return rep


def save_report(docs_dir, rep):
    with open(os.path.join(docs_dir, REPORT_FILENAME), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)


def load_report(docs_dir):
    path = os.path.join(docs_dir, REPORT_FILENAME)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
