# -*- coding: utf-8 -*-
"""
モデルの毎日の自動補正（簡易な「再学習」）。

予想成績ログ（_prediction_log.json）に溜めた「各選手の予測1着率」と「実際の1着」から、
1着率の絞り込みの強さ（model.py の sharpness_first）を、毎日1回、最尤法で見直す。
   予測1着率 p を p^(γ/γ_記録時) の形で絞り直したとき、実際の1着になった選手に付けていた確率の
   対数（対数尤度）の合計が最大になる γ を探す。
過学習を避けるための安全策：
   ・補正に使えるレース（各選手の確率が記録されているもの）が MIN_RACES 件以上たまるまでは適用しない
   ・直近 WINDOW_DAYS 日分だけを使う
   ・基準値（既定値）に引き戻す事前分布（PRIOR_K）を付け、さらに前回値と平均して1日の変化を小さくする
   ・γ は GAMMA_MIN〜GAMMA_MAX の範囲に収める
結果は docs/_model_params.json に書き出し、次回以降の実行で predict_race() の設定に反映される。
※ 補正できるのは1着率の絞り込み1つだけで、モデルの係数そのもの（特徴量の重み）を学習し直す
  ものではない（ログに特徴量を残していないため）。
"""

import os
import json
import math
import datetime

PARAMS_FILENAME = "_model_params.json"
MIN_RACES = 120
WINDOW_DAYS = 60
GAMMA_MIN, GAMMA_MAX = 1.3, 2.3
PRIOR_K = 30.0      # 基準値に引き戻す強さ（「基準値のまわりのレース約30件ぶん」の重み）
SMOOTH = 0.5        # 前回値とのブレンド比（0.5=前回と今回の平均）
GRID_STEP = 0.025


def _default_gamma():
    from model import DEFAULT_SETTINGS
    return float(DEFAULT_SETTINGS["sharpness_first"])


def load_params(docs_dir):
    path = os.path.join(docs_dir, PARAMS_FILENAME)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def get_overrides(docs_dir):
    """predict_race(settings=...) に渡す補正値。適用条件を満たしていなければ空dict。"""
    p = load_params(docs_dir)
    if p.get("active") and GAMMA_MIN <= p.get("sharpness_first", 0) <= GAMMA_MAX:
        return {"sharpness_first": float(p["sharpness_first"])}
    return {}


def _samples(log, today):
    cutoff = (today - datetime.timedelta(days=WINDOW_DAYS)).isoformat()
    out = []
    for e in log.values():
        res, probs = e.get("result"), e.get("probs")
        if not res or not probs or e.get("date", "") < cutoff or not res.get("finish_order"):
            continue
        winner = res["finish_order"][0]
        pm = {int(c): float(p1) for c, p1, _ in probs if p1 and p1 > 0}
        if winner not in pm or len(pm) < 3:
            continue
        out.append((pm, float(e.get("sf") or _default_gamma()), winner))
    return out


def _loglik(samples, gamma):
    """γ に絞り直したときの、実際の勝者への対数尤度の合計。"""
    total = 0.0
    for pm, sf, winner in samples:
        e = gamma / sf
        powered = {c: p ** e for c, p in pm.items()}
        z = sum(powered.values())
        total += math.log(max(powered[winner] / z, 1e-9))
    return total


def fit_gamma(samples, gamma0):
    best, best_obj = gamma0, -1e18
    g = GAMMA_MIN
    while g <= GAMMA_MAX + 1e-9:
        obj = _loglik(samples, g) - 0.5 * PRIOR_K * (g - gamma0) ** 2
        if obj > best_obj:
            best, best_obj = g, obj
        g += GRID_STEP
    return best


def update_params(docs_dir, log, today):
    """毎日1回だけ補正値を見直して書き出す。戻り値: 書き出した params dict（今日すでに更新済みなら既存のもの）。"""
    prev = load_params(docs_dir)
    today_s = today.isoformat()
    if prev.get("updated") == today_s:
        return prev
    gamma0 = _default_gamma()
    samples = _samples(log, today)
    n = len(samples)
    params = {"updated": today_s, "n": n, "min_races": MIN_RACES, "default": gamma0,
              "active": False, "sharpness_first": gamma0, "history": (prev.get("history") or [])[-30:]}
    if n >= MIN_RACES:
        g_prev = prev.get("sharpness_first", gamma0) if prev.get("active") else gamma0
        g_fit = fit_gamma(samples, gamma0)
        g_new = SMOOTH * g_prev + (1 - SMOOTH) * g_fit
        g_new = max(GAMMA_MIN, min(GAMMA_MAX, round(g_new, 3)))
        params.update({
            "active": True, "sharpness_first": g_new, "fit_raw": round(g_fit, 3),
            "ll_per_race_default": round(_loglik(samples, gamma0) / n, 4),
            "ll_per_race_new": round(_loglik(samples, g_new) / n, 4),
        })
        params["history"].append({"date": today_s, "gamma": g_new, "n": n})
    try:
        with open(os.path.join(docs_dir, PARAMS_FILENAME), "w", encoding="utf-8") as f:
            json.dump(params, f, ensure_ascii=False, indent=1)
    except OSError as e:
        print(f"[WARN] モデル補正値の書き出しに失敗しました: {e}")
    if params["active"]:
        print(f"[INFO] モデル自動補正: {n}レースで sharpness_first を {params['sharpness_first']:.3f} に更新（基準{gamma0}）。")
    else:
        print(f"[INFO] モデル自動補正: 補正に使えるレースが{n}件（{MIN_RACES}件以上で適用開始）。")
    return params
