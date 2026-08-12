# -*- coding: utf-8 -*-
"""
競輪AI予想モデル（keirin_predictor_v2.html のロジックをPythonに移植したもの）
学習済みRidge回帰の重み、決まり手のAI予測、ライン補正、2着・3着予測などを
すべて含む。scraper.py が収集したレースデータをこのモジュールに渡して計算する。
"""

import math

# ============================================================
# 学習済みモデル（2020〜2025年・43,650レース／出走306,577人分のデータで学習）
# ============================================================
MODEL = {
    "intercept": 0.08025409628633257,
    "field_size_weight": 0.00853568299742552,
    "weights": {
        "総評": -0.17441777667716216, "枠番": 0.0030596892764230155, "ギヤ倍数": 0.043544445460426275,
        "競走得点": -0.006948280966864034, "年齢": 0.0011073490366931872, "期別": -0.006020843473665809,
        "×": 0.0112119209187471, "▲": 0.0010803586778149069, "△": 0.005733939297667219,
        "○": 0.010015564675994619, "◎": 0.037199070221735596, "注": 0.004132824493750195, "★": 0.025401795838274687,
        "両": 0.0047269896598747165, "追": -0.02957627880837295, "逃": 0.024849289147551967,
        "A1": -0.016776242355594165, "A2": -0.02402381564712001, "A3": -0.032634468028605916,
        "L1": -0.009585017758308476, "S1": 0.02608815611052486, "S2": -0.004735058188392152, "SS": 0.06166644587262267,
    },
}
RANK_NORM_COLS = ["総評", "枠番", "ギヤ倍数", "競走得点", "年齢", "期別"]
MARKS = ["×", "▲", "△", "○", "◎", "注", "★"]
TACTICS = ["逃", "追", "両"]
RANKS = ["SS", "S1", "S2", "A1", "A2", "A3", "L1"]
KIMARITE = ["逃", "捲", "差", "マ"]
KIMARITE_LABELS = {"逃": "逃げ", "捲": "捲り", "差": "差し", "マ": "マーク"}

TACTIC_KIMARITE_PRIOR = {
    "逃": {"逃": 0.50, "捲": 0.25, "差": 0.15, "マ": 0.10},
    "追": {"逃": 0.05, "捲": 0.15, "差": 0.40, "マ": 0.40},
    "両": {"逃": 0.25, "捲": 0.25, "差": 0.25, "マ": 0.25},
}
LINE_CONTEXT_KIMARITE_PRIOR = {
    1: {"逃": 0.45, "捲": 0.30, "差": 0.15, "マ": 0.10},
    2: {"逃": 0.05, "捲": 0.15, "差": 0.55, "マ": 0.25},
    3: {"逃": 0.03, "捲": 0.10, "差": 0.25, "マ": 0.62},
}
KIMARITE_SAMPLE_CAP = 15
LINE_POSITION_KIMARITE = {1: ["逃", "捲"], 2: ["差"], 3: ["マ"]}


def rank_normalize(values):
    n = len(values)
    if n <= 1:
        return [0.0] * n
    sorted_vals = sorted(values)
    return [sorted_vals.index(v) / (n - 1) for v in values]


def compute_base_scores(racers):
    """racers: list of dict with souhyou, waku, gear, score, age, period, mark, tactic, rank"""
    cols = {}
    field_map = {"総評": "souhyou", "枠番": "waku", "ギヤ倍数": "gear", "競走得点": "score", "年齢": "age", "期別": "period"}
    for c in RANK_NORM_COLS:
        cols[c] = rank_normalize([r[field_map[c]] for r in racers])

    field_size = len(racers)
    scores = []
    for i, r in enumerate(racers):
        s = MODEL["intercept"]
        for c in RANK_NORM_COLS:
            s += MODEL["weights"][c] * cols[c][i]
        s += MODEL["field_size_weight"] * field_size
        if r.get("mark") in MARKS:
            s += MODEL["weights"][r["mark"]]
        if r.get("tactic") in TACTICS:
            s += MODEL["weights"][r["tactic"]]
        if r.get("rank") in RANKS:
            s += MODEL["weights"][r["rank"]]
        scores.append(max(s, 0.005))
    return scores


def compute_kimarite_prediction(racers, line_map):
    """line_map: dict car -> {"line_index":int, "position":int, "line_size":int}"""
    results = []
    for r in racers:
        total = sum(r["kimarite"].get(t, 0) for t in KIMARITE)
        if total > 0:
            personal = {t: r["kimarite"].get(t, 0) / total for t in KIMARITE}
            sample_weight = min(total, KIMARITE_SAMPLE_CAP) / KIMARITE_SAMPLE_CAP
        else:
            personal = TACTIC_KIMARITE_PRIOR.get(r.get("tactic"), TACTIC_KIMARITE_PRIOR["両"])
            sample_weight = 0.0

        info = line_map.get(r["car"])
        probs = dict(personal)
        if info and info["line_size"] > 1:
            pos_key = min(info["position"], 3)
            context = LINE_CONTEXT_KIMARITE_PRIOR[pos_key]
            personal_weight = 0.3 + 0.5 * sample_weight
            probs = {t: personal_weight * personal[t] + (1 - personal_weight) * context[t] for t in KIMARITE}

        s = sum(probs.values()) or 1.0
        probs = {t: v / s for t, v in probs.items()}
        best_type = max(KIMARITE, key=lambda t: probs[t])
        results.append({"type": best_type, "ratio": probs[best_type], "total": total, "probs": probs})
    return results


def compute_kimarite_adjustment(racers, dominant, solo_bonus, cong_penalty, chase_bonus):
    front_weight = [d["probs"]["逃"] + d["probs"]["捲"] * 0.6 for d in dominant]
    total_front = sum(front_weight)
    pace_index = (total_front / len(racers)) if racers else 0.0
    nige_count = sum(1 for d in dominant if d["type"] == "逃")

    adj = []
    for i, r in enumerate(racers):
        d = dominant[i]
        mult = 1.0
        confidence_factor = max(0.0, min(1.0, (d["ratio"] - 0.25) / 0.75))
        if d["type"] in ("逃", "捲"):
            share = (front_weight[i] / total_front) if total_front > 0 else 1.0
            mult *= 1 + (solo_bonus / 100 * share - cong_penalty / 100 * (1 - share)) * confidence_factor
        elif d["type"] in ("差", "マ"):
            mult *= 1 + chase_bonus / 100 * pace_index * 2 * confidence_factor
        adj.append(max(mult, 0.3))
    return adj, nige_count, pace_index


def compute_kimarite_ratio(dominant):
    scores = {t: 0.0 for t in KIMARITE}
    for d in dominant:
        for t in KIMARITE:
            scores[t] += d["probs"][t]
    total = sum(scores.values()) or 1.0
    return {t: (v / total) * 100 for t, v in scores.items()}


def compute_line_adjustment(racers, line_map, kimarite_ratio, position_strength, support_strength, solo_penalty):
    adj = []
    for r in racers:
        info = line_map.get(r["car"])
        if not info or info["line_size"] <= 1:
            adj.append(max(1 - solo_penalty / 100, 0.5))
            continue
        pos_key = min(info["position"], 3)
        relevant_types = LINE_POSITION_KIMARITE.get(pos_key, ["マ"])
        relevant_ratio = sum(kimarite_ratio.get(t, 0) for t in relevant_types)
        diff = (relevant_ratio - 25) / 100
        position_match_mult = 1 + diff * (position_strength / 100) * 2

        teammates = info["line_size"] - 1
        pos_weight = 1.0 if info["position"] == 1 else 0.4 / info["position"]
        support_mult = 1 + (support_strength / 100) * math.sqrt(min(teammates, 4)) * pos_weight

        adj.append(max(position_match_mult * support_mult, 0.4))
    return adj


def compute_adjusted_rates(base_scores, adj_mults):
    raw = [max(s * a, 0) for s, a in zip(base_scores, adj_mults)]
    total = sum(raw) or 1.0
    return [(v / total) * 100 for v in raw]


def compute_confidence(racers):
    SAMPLE_CAP = 25
    results = []
    for r in racers:
        f = r["finishes"]
        total = f["f1"] + f["f2"] + f["f3"] + f["fo"]
        if total <= 0:
            results.append({"total": 0, "rentai_rate": 0.0, "score": 0.0})
            continue
        rentai_rate = (f["f1"] + f["f2"]) / total
        sample_factor = min(total, SAMPLE_CAP) / SAMPLE_CAP
        score = (sample_factor * 0.6 + rentai_rate * 0.4) * 100
        results.append({"total": total, "rentai_rate": rentai_rate, "score": score})
    return results


def sharpen_probabilities(scored, exponent):
    powered = [max(r["prob"], 0.001) ** exponent for r in scored]
    total = sum(powered) or 1.0
    for r, p in zip(scored, powered):
        r["prob"] = (p / total) * 100
    return scored


def compute_second_place_candidates(racers, winner_idx, base_scores, dominant, line_map,
                                     adv_bonus, adv_penalty, line_follow_bonus, sharpness):
    winner_type = dominant[winner_idx]["type"]
    winner_car = racers[winner_idx]["car"]
    winner_info = line_map.get(winner_car)

    scored = []
    for i, r in enumerate(racers):
        if i == winner_idx:
            continue
        score = base_scores[i]
        o_info = line_map.get(r["car"])
        same_line = bool(winner_info and o_info and winner_info["line_index"] == o_info["line_index"]
                          and winner_info["line_size"] > 1)
        if same_line:
            distance = abs(o_info["position"] - winner_info["position"])
            proximity_weight = 1.0 if distance <= 1 else 1 / (distance + 1)
            score *= 1 + line_follow_bonus / 100 * proximity_weight
        else:
            same_type = winner_type and dominant[i]["type"] == winner_type
            score *= (1 - adv_penalty / 100) if same_type else (1 + adv_bonus / 100)
        scored.append({**r, "score": max(score, 0), "same_line": same_line, "idx": i})

    total = sum(x["score"] for x in scored) or 1.0
    for x in scored:
        x["prob"] = (x["score"] / total) * 100
    sharpen_probabilities(scored, sharpness)
    scored.sort(key=lambda x: -x["prob"])
    return scored


def compute_third_place_candidates(racers, winner_idx, second_idx, base_scores, dominant, line_map,
                                    adv_bonus, adv_penalty, line_follow_bonus, sharpness):
    ref_types = [dominant[winner_idx]["type"], dominant[second_idx]["type"]]
    ref_infos = [
        {"car": racers[winner_idx]["car"], "info": line_map.get(racers[winner_idx]["car"])},
        {"car": racers[second_idx]["car"], "info": line_map.get(racers[second_idx]["car"])},
    ]
    excluded = {winner_idx, second_idx}
    scored = []
    for i, r in enumerate(racers):
        if i in excluded:
            continue
        score = base_scores[i]
        o_info = line_map.get(r["car"])
        best_same_line = None
        for ref in ref_infos:
            if not ref["info"] or not o_info:
                continue
            if ref["info"]["line_index"] == o_info["line_index"] and ref["info"]["line_size"] > 1:
                distance = abs(o_info["position"] - ref["info"]["position"])
                if best_same_line is None or distance < best_same_line:
                    best_same_line = distance

        if best_same_line is not None:
            proximity_weight = 1.0 if best_same_line <= 1 else 1 / (best_same_line + 1)
            score *= 1 + line_follow_bonus / 100 * 0.7 * proximity_weight
        else:
            same_type_count = sum(1 for t in ref_types if t == dominant[i]["type"])
            if same_type_count > 0:
                score *= (1 - adv_penalty / 100) ** same_type_count
            else:
                score *= 1 + adv_bonus / 100
        scored.append({**r, "score": max(score, 0), "same_line": best_same_line is not None, "idx": i})

    total = sum(x["score"] for x in scored) or 1.0
    for x in scored:
        x["prob"] = (x["score"] / total) * 100
    sharpen_probabilities(scored, sharpness)
    scored.sort(key=lambda x: -x["prob"])
    return scored


# ============================================================
# 全号車マトリクス（表4：各号車が仮に1着だった場合の2着確率／
#                  表5：さらに2着も確定したうえでの3着確率）
# ============================================================
def compute_second_place_matrix(racers, base_scores, dominant, line_map,
                                 adv_bonus, adv_penalty, line_follow_bonus, sharpness):
    """
    戻り値: {winner_car: [{"car":.., "name":.., "prob":.., "same_line":..}, ...]}
    """
    matrix = {}
    for i, r in enumerate(racers):
        candidates = compute_second_place_candidates(
            racers, i, base_scores, dominant, line_map, adv_bonus, adv_penalty, line_follow_bonus, sharpness)
        matrix[r["car"]] = candidates
    return matrix


def compute_third_place_matrix(racers, base_scores, dominant, line_map,
                                adv_bonus, adv_penalty, line_follow_bonus, sharpness,
                                second_place_matrix=None):
    """
    各号車が仮に1着だった場合、その号車における最有力2着候補を自動選定した上で、
    3着候補の確率を算出する。
    戻り値: {winner_car: {"second_car": int, "candidates": [...]}}
    """
    if second_place_matrix is None:
        second_place_matrix = compute_second_place_matrix(
            racers, base_scores, dominant, line_map, adv_bonus, adv_penalty, line_follow_bonus, sharpness)

    matrix = {}
    if len(racers) <= 2:
        return matrix
    for i, r in enumerate(racers):
        second_candidates = second_place_matrix.get(r["car"], [])
        if not second_candidates:
            continue
        second_car = second_candidates[0]["car"]
        second_idx = next((j for j, rr in enumerate(racers) if rr["car"] == second_car), None)
        if second_idx is None:
            continue
        third_candidates = compute_third_place_candidates(
            racers, i, second_idx, base_scores, dominant, line_map,
            adv_bonus, adv_penalty, line_follow_bonus, sharpness)
        matrix[r["car"]] = {"second_car": second_car, "candidates": third_candidates}
    return matrix


# ============================================================
# ライン予想テキストの解析（並び予想: "← 4先行 1追込 6押え先 2追込 7押え先 3追込 5追込"）
# 「追込」だけが同じラインの継続を表し、それ以外の役割語（先行・押え先・自在・追い上げ等）は
# 新しいラインの先頭を表す、という競輪の並び予想表記の慣例に基づいて解析する。
# ============================================================
def parse_line_prediction_text(text):
    """
    並び予想テキストの解析。スペース区切りの有無に依存せず、
    「数字＋役割語」の並びを正規表現で直接抜き出す方式（例：
    "4先行1追込6押え先2追込" のようにスペースが無い場合にも対応）。
    全角数字にも対応するため、事前に半角へ正規化する。
    """
    if not text:
        return {}
    import re as _re
    # 全角数字→半角数字に正規化
    zen = "０１２３４５６７８９"
    han = "0123456789"
    text = text.translate(str.maketrans(zen, han))
    text = text.replace("←", " ").replace("→", " ")

    pairs = _re.findall(r"(\d+)\s*(先行|追込|押え先|自在|追い上げ|捲|差|逃)", text)

    lines = []
    current = []
    for car_str, role in pairs:
        car = int(car_str)
        if role == "追込" and current:
            current.append(car)
        else:
            if current:
                lines.append(current)
            current = [car]
    if current:
        lines.append(current)

    line_map = {}
    for li, members in enumerate(lines):
        for pos, car in enumerate(members):
            line_map[car] = {"line_index": li, "position": pos + 1, "line_size": len(members)}
    return line_map


# ============================================================
# レース全体の予測を計算するメイン関数
# ============================================================
DEFAULT_SETTINGS = {
    "th_high": 45, "th_list": 10, "close_threshold": 8,
    "solo_bonus": 18, "cong_penalty": 18, "chase_bonus": 10,
    "line_strength": 30, "line_support": 8, "solo_penalty": 6,
    "line_follow_bonus": 45, "adv_bonus": 10, "adv_penalty": 15,
    "sharpness": 3.5,
}


def predict_race(racers, line_prediction_text, settings=None):
    """
    racers: list of dict, each with:
      car, name, mark, rank, tactic, souhyou, waku, gear, score, age, period,
      kimarite: {"逃":n,"捲":n,"差":n,"マ":n}, finishes: {"f1":n,"f2":n,"f3":n,"fo":n}
    line_prediction_text: raw "並び予想" string from the site
    Returns a dict with full prediction results.
    """
    s = {**DEFAULT_SETTINGS, **(settings or {})}
    if not racers:
        return None

    line_map = parse_line_prediction_text(line_prediction_text)
    base_scores = compute_base_scores(racers)
    confidence = compute_confidence(racers)
    dominant = compute_kimarite_prediction(racers, line_map)
    kimarite_ratio = compute_kimarite_ratio(dominant)
    kimarite_adj, nige_count, pace_index = compute_kimarite_adjustment(
        racers, dominant, s["solo_bonus"], s["cong_penalty"], s["chase_bonus"])
    line_adj = compute_line_adjustment(
        racers, line_map, kimarite_ratio, s["line_strength"], s["line_support"], s["solo_penalty"])
    adj = [k * l for k, l in zip(kimarite_adj, line_adj)]
    final_rates = compute_adjusted_rates(base_scores, adj)

    rows = []
    for i, r in enumerate(racers):
        rows.append({
            **r, "base": base_scores[i], "adj": adj[i], "adjusted": final_rates[i],
            "dominant_type": dominant[i]["type"], "kimarite_prediction": dominant[i],
            "line_info": line_map.get(r["car"]), "confidence": confidence[i], "idx": i,
        })
    rows.sort(key=lambda x: -x["adjusted"])

    top = rows[0]
    second_candidates = compute_second_place_candidates(
        racers, top["idx"], base_scores, dominant, line_map,
        s["adv_bonus"], s["adv_penalty"], s["line_follow_bonus"], s["sharpness"])

    third_candidates = []
    if second_candidates and len(racers) > 2:
        second_idx = second_candidates[0]["idx"]
        third_candidates = compute_third_place_candidates(
            racers, top["idx"], second_idx, base_scores, dominant, line_map,
            s["adv_bonus"], s["adv_penalty"], s["line_follow_bonus"], s["sharpness"])

    close_group = [r for r in rows if top["adjusted"] - r["adjusted"] <= s["close_threshold"]]
    most_reliable = max(close_group, key=lambda r: r["confidence"]["score"]) if len(close_group) >= 2 else None

    second_place_matrix = compute_second_place_matrix(
        racers, base_scores, dominant, line_map, s["adv_bonus"], s["adv_penalty"], s["line_follow_bonus"], s["sharpness"])
    third_place_matrix = compute_third_place_matrix(
        racers, base_scores, dominant, line_map, s["adv_bonus"], s["adv_penalty"], s["line_follow_bonus"], s["sharpness"],
        second_place_matrix=second_place_matrix)

    return {
        "rows": rows,
        "top": top,
        "second_candidates": second_candidates[:5],
        "third_candidates": third_candidates[:5],
        "second_place_matrix": second_place_matrix,
        "third_place_matrix": third_place_matrix,
        "kimarite_ratio": kimarite_ratio,
        "pace_index": pace_index,
        "line_map": line_map,
        "line_prediction_text": line_prediction_text,
        "close_group": close_group,
        "most_reliable": most_reliable,
        "is_high_prob": top["adjusted"] >= s["th_high"],
        "settings": s,
    }
