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
2着・3着の確率（3連単の出目の元になる条件付き確率）も、同じ考え方で車立て別（7車以下／8車以上）に
補正する。ログに残した入力（各選手の力・予測戦法・ライン位置）から「1着が○番のとき2着は△番、
3着は□番」の確率を、2着・3着側の絞り込み（sharp23）とライン追走ボーナス（line_follow_bonus）を変えて
再計算し、実際の2着・3着に付けていた確率の対数の合計が最大になる組み合わせを探す。
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

# --- 2着・3着の補正 ---
MIN_RACES_23 = 100          # 車立てグループごとに必要なレース数（9車は件数が少ないので別に数える）
S23_MIN, S23_MAX = 1.0, 3.5
LFB_MIN, LFB_MAX = 0.0, 120.0
S23_SCALE, LFB_SCALE = 0.4, 30.0     # 事前分布の幅（この幅ぶん基準値からずれると、PRIOR_K_23件ぶんの罰則）
PRIOR_K_23 = 12.0
LFB_DEFAULT = 45.0

# --- 勝利の方程式バフ（1着率に exp(β×z) を掛ける） ---
MIN_RACES_B = 80            # 方程式を記録したレースがこの件数たまるまで適用しない
BETA_MIN, BETA_MAX = 0.0, 1.0   # 負にはしない（方程式が高い選手を下げることはしない）
PRIOR_B = 20.0              # β=0 への引き戻し（β=0.3 で対数尤度 -0.9 ぶんの罰則）


def _default_gamma():
    from model import DEFAULT_SETTINGS
    return float(DEFAULT_SETTINGS["sharpness_first"])


def _sharp():
    from model import DEFAULT_SETTINGS
    return float(DEFAULT_SETTINGS["sharpness"])


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
    out = {}
    if p.get("active") and GAMMA_MIN <= p.get("sharpness_first", 0) <= GAMMA_MAX:
        out["sharpness_first"] = float(p["sharpness_first"])
    bp = p.get("buff") or {}
    if bp.get("active") and BETA_MIN < bp.get("beta", 0) <= BETA_MAX:
        out["formula_buff"] = float(bp["beta"])
    go = {}
    for g, gp in (p.get("groups") or {}).items():
        if gp.get("active") and S23_MIN <= gp.get("sharp23_mult", 0) * _sharp() <= S23_MAX + 1e-6 \
                and LFB_MIN <= gp.get("line_follow_bonus", -1) <= LFB_MAX:
            go[g] = {"sharp23_mult": float(gp["sharp23_mult"]), "line_follow_bonus": float(gp["line_follow_bonus"])}
    if go:
        out["group_overrides"] = go
    return out


def _samples(log, today):
    cutoff = (today - datetime.timedelta(days=WINDOW_DAYS)).isoformat()
    out = []
    for e in log.values():
        res = e.get("result")
        probs = e.get("p0") or e.get("probs")   # バフ前の値で学習する（バフ自身を学習に混ぜない）
        if not res or not probs or e.get("date", "") < cutoff or not res.get("finish_order"):
            continue
        winner = res["finish_order"][0]
        pm = {int(c): float(p1) for c, p1, *_ in probs if p1 and p1 > 0}
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


def _z_from_ev(ev):
    vals = [float(t) for _, t in ev]
    n = len(vals)
    if n < 3:
        return None
    m = sum(vals) / n
    sd = math.sqrt(sum((v - m) ** 2 for v in vals) / n)
    if sd <= 0:
        return None
    return {int(c): (float(t) - m) / sd for c, t in ev}


def _buff_samples(log, today):
    """バフの学習に使えるレース: バフ前の1着率・方程式の記録・結果がそろっているもの。"""
    cutoff = (today - datetime.timedelta(days=WINDOW_DAYS)).isoformat()
    out = []
    for e in log.values():
        res, ev = e.get("result"), e.get("ev")
        probs = e.get("p0") or e.get("probs")
        if not res or not ev or not probs or e.get("date", "") < cutoff or not res.get("finish_order"):
            continue
        z = _z_from_ev(ev)
        winner = res["finish_order"][0]
        pm = {int(c): float(p1) for c, p1, *_ in probs if p1 and p1 > 0}
        if not z or winner not in pm or len(pm) < 3 or any(c not in z for c in pm):
            continue
        out.append((pm, float(e.get("sf") or _default_gamma()), winner, z))
    return out


def _loglik_buff(samples, gamma, beta):
    total = 0.0
    for pm, sf, winner, z in samples:
        e = gamma / sf
        w = {c: (p ** e) * math.exp(beta * z[c]) for c, p in pm.items()}
        total += math.log(max(w[winner] / sum(w.values()), 1e-9))
    return total


def fit_beta(samples, gamma):
    best, best_obj = 0.0, -1e18
    b = BETA_MIN
    while b <= BETA_MAX + 1e-9:
        obj = _loglik_buff(samples, gamma, b) - 0.5 * PRIOR_B * b * b
        if obj > best_obj:
            best, best_obj = b, obj
        b += 0.025
    return best


def _group_of(n_cars):
    return "9" if n_cars >= 8 else "7"


def _cond_samples(log, today):
    """2着・3着の補正に使えるレース（入力と上位3着の結果がそろっているもの）を、車立てグループ別に返す。"""
    cutoff = (today - datetime.timedelta(days=WINDOW_DAYS)).isoformat()
    groups = {"7": [], "9": []}
    for e in log.values():
        res, cond = e.get("result"), e.get("cond")
        if not res or not cond or e.get("date", "") < cutoff:
            continue
        fin = res.get("finish_order") or []
        cars = cond.get("cars") or []
        if len(fin) < 3 or not cars or not set(fin[:3]) <= set(cars):
            continue
        line_map = {}
        for c, ln in zip(cars, cond.get("line") or []):
            if ln:
                line_map[c] = {"line_index": ln[0], "position": ln[1], "line_size": ln[2]}
        groups[_group_of(len(cars))].append({
            "cars": cars, "scores": cond["scores"], "dom": cond["dom"], "line_map": line_map,
            "adv_bonus": cond["adv_bonus"], "adv_penalty": cond["adv_penalty"], "fin": fin[:3],
        })
    return groups


def _ll23_one(sm, s23, lfb):
    import model
    racers = [{"car": c, "name": ""} for c in sm["cars"]]
    idx = {c: i for i, c in enumerate(sm["cars"])}
    dominant = [{"type": t} for t in sm["dom"]]
    y, z, w = sm["fin"]
    sec = model.compute_second_place_candidates(
        racers, idx[y], sm["scores"], dominant, sm["line_map"], sm["adv_bonus"], sm["adv_penalty"], lfb, s23)
    p2 = next((c["prob"] for c in sec if c["car"] == z), 0.0) / 100
    thr = model.compute_third_place_candidates(
        racers, idx[y], idx[z], sm["scores"], dominant, sm["line_map"], sm["adv_bonus"], sm["adv_penalty"], lfb, s23)
    p3 = next((c["prob"] for c in thr if c["car"] == w), 0.0) / 100
    return math.log(max(p2, 1e-6)) + math.log(max(p3, 1e-6))


def _ll23(samples, s23, lfb):
    return sum(_ll23_one(sm, s23, lfb) for sm in samples)


def fit_23(samples, s23_0, lfb_0=LFB_DEFAULT, rounds=3):
    """sharp23 と line_follow_bonus を交互に1次元探索して、事前分布つきの対数尤度を最大化する。"""
    def obj(s23, lfb):
        return (_ll23(samples, s23, lfb)
                - 0.5 * PRIOR_K_23 * ((s23 - s23_0) / S23_SCALE) ** 2
                - 0.5 * PRIOR_K_23 * ((lfb - lfb_0) / LFB_SCALE) ** 2)
    s23, lfb = s23_0, lfb_0
    for _ in range(rounds):
        best, best_o = s23, obj(s23, lfb)
        v = S23_MIN
        while v <= S23_MAX + 1e-9:
            o = obj(v, lfb)
            if o > best_o:
                best, best_o = v, o
            v += 0.1
        s23 = best
        best, best_o = lfb, obj(s23, lfb)
        v = LFB_MIN
        while v <= LFB_MAX + 1e-9:
            o = obj(s23, v)
            if o > best_o:
                best, best_o = v, o
            v += 5.0
        lfb = best
    return s23, lfb


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
    # ---- 勝利の方程式バフ（1着率への上乗せ） ----
    bsamples = _buff_samples(log, today)
    pb = prev.get("buff") or {}
    bp = {"n": len(bsamples), "min_races": MIN_RACES_B, "active": False, "beta": 0.0}
    if len(bsamples) >= MIN_RACES_B:
        g_used = params["sharpness_first"]
        b_prev = pb.get("beta", 0.0) if pb.get("active") else 0.0
        b_fit = fit_beta(bsamples, g_used)
        b_new = max(BETA_MIN, min(BETA_MAX, round(SMOOTH * b_prev + (1 - SMOOTH) * b_fit, 3)))
        nb = len(bsamples)
        bp.update({
            "active": b_new > 0.01, "beta": b_new, "fit_raw": round(b_fit, 3),
            "ll_per_race_default": round(_loglik_buff(bsamples, g_used, 0.0) / nb, 4),
            "ll_per_race_new": round(_loglik_buff(bsamples, g_used, b_new) / nb, 4),
        })
        print(f"[INFO] 方程式バフ: {nb}レースで β={b_new:.3f}（学習値{b_fit:.3f}）に更新。")
    else:
        print(f"[INFO] 方程式バフ: 学習に使えるレースが{len(bsamples)}件（{MIN_RACES_B}件以上で適用開始）。")
    params["buff"] = bp
    # ---- 2着・3着（車立て別） ----
    from model import DEFAULT_SETTINGS
    sharp = float(DEFAULT_SETTINGS["sharpness"])
    prev_groups = prev.get("groups") or {}
    params["groups"] = {}
    for g, samples23 in _cond_samples(log, today).items():
        n_typ = 9 if g == "9" else 7
        s23_0 = sharp * max(1.0, (n_typ - 1) / 6)
        gp = {"n": len(samples23), "min_races": MIN_RACES_23, "active": False,
              "sharp23_mult": round(s23_0 / sharp, 3), "line_follow_bonus": LFB_DEFAULT,
              "default_sharp23": round(s23_0, 3), "default_line_follow_bonus": LFB_DEFAULT}
        if len(samples23) >= MIN_RACES_23:
            pg = prev_groups.get(g) or {}
            s23_prev = pg.get("sharp23_mult", s23_0 / sharp) * sharp if pg.get("active") else s23_0
            lfb_prev = pg.get("line_follow_bonus", LFB_DEFAULT) if pg.get("active") else LFB_DEFAULT
            s23_fit, lfb_fit = fit_23(samples23, s23_0)
            s23_new = max(S23_MIN, min(S23_MAX, SMOOTH * s23_prev + (1 - SMOOTH) * s23_fit))
            lfb_new = max(LFB_MIN, min(LFB_MAX, SMOOTH * lfb_prev + (1 - SMOOTH) * lfb_fit))
            n_s = len(samples23)
            gp.update({
                "active": True, "sharp23_mult": round(s23_new / sharp, 3), "line_follow_bonus": round(lfb_new, 1),
                "fit_raw": [round(s23_fit, 2), round(lfb_fit, 1)],
                "ll_per_race_default": round(_ll23(samples23, s23_0, LFB_DEFAULT) / n_s, 4),
                "ll_per_race_new": round(_ll23(samples23, s23_new, lfb_new) / n_s, 4),
            })
            print(f"[INFO] モデル自動補正({g}車立て): {n_s}レースで2着・3着側を sharp23={s23_new:.2f}、ライン追走={lfb_new:.0f} に更新。")
        else:
            print(f"[INFO] モデル自動補正({g}車立て): 2着・3着の補正に使えるレースが{len(samples23)}件（{MIN_RACES_23}件以上で適用開始）。")
        params["groups"][g] = gp
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
