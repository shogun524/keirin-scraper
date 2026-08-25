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
    "intercept": -2.2616982157477947,
    "field_size_weight": -0.14499,
    "weights": {
        "総評": -0.96958, "枠番": -0.13012, "ギヤ倍数": 0.62829,
        "競走得点": 0.49021, "年齢": -0.53961, "期別": 0.28119,
        "×": 1.76224, "▲": 0.43882, "△": 1.22149,
        "○": 2.10183, "◎": 3.21779, "注": 0.90767, "★": -0.05684,
        "両": -0.6957, "追": -0.89212, "逃": -0.62603,
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


OLD_MODEL = {
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


def compute_old_model_place_rates(racers):
    """
    旧モデル（Ridge回帰・複数着順を含む実績ベース）による「予測3着内率」の参考値。
    新モデル（ロジスティック回帰）が純粋な勝率であるのに対し、旧モデルは総合的な
    実績の強さを反映した値に近いため、3着以内（複勝圏）に来る強さの目安として使う。
    毎レース必ず3人が3着以内に入るため、100%ではなく min(3,頭数)×100% を
    合計値として正規化する。
    """
    cols = {}
    field_map = {"総評": "souhyou", "枠番": "waku", "ギヤ倍数": "gear", "競走得点": "score", "年齢": "age", "期別": "period"}
    for c in RANK_NORM_COLS:
        cols[c] = rank_normalize([r[field_map[c]] for r in racers])
    field_size = len(racers)

    raw = []
    for i, r in enumerate(racers):
        s = OLD_MODEL["intercept"]
        for c in RANK_NORM_COLS:
            s += OLD_MODEL["weights"][c] * cols[c][i]
        s += OLD_MODEL["field_size_weight"] * field_size
        if r.get("mark") in MARKS:
            s += OLD_MODEL["weights"][r["mark"]]
        if r.get("tactic") in TACTICS:
            s += OLD_MODEL["weights"][r["tactic"]]
        if r.get("rank") in RANKS:
            s += OLD_MODEL["weights"][r["rank"]]
        raw.append(max(s, 0.005))

    slots = min(3, len(racers))
    total = sum(raw) or 1.0
    return [min((v / total) * 100 * slots, 99) for v in raw]


def compute_base_scores(racers):
    """racers: list of dict with souhyou, waku, gear, score, age, period, mark, tactic, rank"""
    cols = {}
    field_map = {"総評": "souhyou", "枠番": "waku", "ギヤ倍数": "gear", "競走得点": "score", "年齢": "age", "期別": "period"}
    for c in RANK_NORM_COLS:
        cols[c] = rank_normalize([r[field_map[c]] for r in racers])

    field_size = len(racers)
    scores = []
    for i, r in enumerate(racers):
        z = MODEL["intercept"]
        for c in RANK_NORM_COLS:
            z += MODEL["weights"][c] * cols[c][i]
        z += MODEL["field_size_weight"] * field_size
        if r.get("mark") in MARKS:
            z += MODEL["weights"][r["mark"]]
        if r.get("tactic") in TACTICS:
            z += MODEL["weights"][r["tactic"]]
        # 級班（RANKS）は競走得点との相関が強く学習を不安定にするため、
        # 新モデルでは特徴量から除外している（表示・他の補正では引き続き使用）
        # ロジスティック回帰なのでシグモイド関数で0〜1の確率に変換する
        p = 1 / (1 + math.exp(-z))
        scores.append(max(p, 0.001))
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
            personal_weight = 0.55 + 0.35 * sample_weight  # 実績厚いほど本人傾向重視（0.55〜0.9。以前は0.3〜0.8）
            probs = {t: personal_weight * personal[t] + (1 - personal_weight) * context[t] for t in KIMARITE}

        s = sum(probs.values()) or 1.0
        probs = {t: v / s for t, v in probs.items()}
        best_type = max(KIMARITE, key=lambda t: probs[t])
        results.append({"type": best_type, "ratio": probs[best_type], "total": total, "probs": probs})
    return results


def compute_kimarite_adjustment(racers, dominant, kimarite_ratio):
    front_weight = [d["probs"]["逃"] + d["probs"]["捲"] * 0.6 for d in dominant]
    total_front = sum(front_weight)
    pace_index = (total_front / len(racers)) if racers else 0.0
    nige_count = sum(1 for d in dominant if d["type"] == "逃")

    dev_scores = []
    for i, r in enumerate(racers):
        d = dominant[i]
        confidence_factor = max(0.0, min(1.0, (d["ratio"] - 0.25) / 0.75))
        # レース全体の決まり手構成の中で、自分の予測決まり手がどれだけ主流か（0〜1）。
        # これが無いと「独走できそうか」だけを見てしまい、レース全体では滅多に決まらない
        # 決まり手（構成比が最も低いもの）を予測された選手まで高く評価してしまう。
        composition_share = (kimarite_ratio.get(d["type"], 25.0) / 100) if kimarite_ratio else 0.25

        situational = 0.25
        if d["type"] in ("逃", "捲"):
            situational = (front_weight[i] / total_front) if total_front > 0 else 1.0 / len(racers)
        elif d["type"] in ("差", "マ"):
            situational = pace_index

        dev_scores.append(confidence_factor * composition_share * (0.5 + 0.5 * situational))

    return dev_scores, nige_count, pace_index


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


def compute_adjusted_rates(base_scores, line_adj_mults, dev_scores, development_weight, sharpness=1):
    w = max(0.0, min(0.8, development_weight / 100))  # 0〜0.8にクリップ（基礎スコアの重みを完全にゼロにはしない）
    raw = []
    for i, s in enumerate(base_scores):
        base_term = max(s, 0.0005) ** (1 - w)
        dev_term = (max(dev_scores[i] if dev_scores else 0, 0.01) + 0.02) ** w
        raw.append(max(base_term * dev_term * line_adj_mults[i], 0))
    # 表示用：基礎スコア単体に対して最終的に何倍になったか（展開補正の目安として使う）
    effective_mult = [raw[i] / max(base_scores[i], 0.0005) for i in range(len(base_scores))]
    total = sum(raw) or 1.0
    rates = [(v / total) * 100 for v in raw]
    if sharpness and sharpness != 1:
        powered = [max(v, 0.001) ** sharpness for v in rates]
        psum = sum(powered) or 1.0
        rates = [(p / psum) * 100 for p in powered]
    return rates, effective_mult, raw


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


def apply_confidence_shrinkage(base_scores, confidence, shrink_strength):
    """
    信頼度シュリンケージ：信頼度が低い（サンプルが薄い・不安定な）選手の
    基礎スコアを、レース平均側へ引き寄せる。これにより「信頼度」が単なる
    表示用の別指標ではなく、実際に1着率の計算に反映されるようになる。
    """
    avg = sum(base_scores) / len(base_scores) if base_scores else 0
    s = max(0.0, min(1.0, shrink_strength / 100))
    result = []
    for score, conf in zip(base_scores, confidence):
        conf_weight = max(0.0, min(1.0, conf["score"] / 100))
        shrink_amount = s * (1 - conf_weight)
        result.append(score * (1 - shrink_amount) + avg * shrink_amount)
    return result


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
# 3連単フォーメーション
# 1着・2着・3着それぞれに複数の候補をまとめて提示する（フォーメーション買い）。
# ・1着軸：予測1着率が高い上位n1車
# ・2着候補：各1着軸から見た2着候補の上位n2車を統合（重複除去）
# ・3着候補：各(1着軸,2着候補)の組み合わせから見た3着候補の上位n3車を統合
# 実際に成立する組み合わせと、その合計確率（カバー率）・点数を算出する。
# ============================================================
def compute_formation_bet(racers, base_scores, dominant, line_map, final_rates,
                           adv_bonus, adv_penalty, line_follow_bonus, sharpness, n1, n2, n3):
    n = len(racers)
    if n < 3:
        return None

    sorted_by_rate = sorted(
        [{"car": r["car"], "name": r["name"], "idx": i, "rate": final_rates[i]} for i, r in enumerate(racers)],
        key=lambda x: -x["rate"])
    first_candidates = [x["car"] for x in sorted_by_rate[:n1]]

    second_pool = []
    second_cache = {}
    for fc in first_candidates:
        wi = next(i for i, r in enumerate(racers) if r["car"] == fc)
        cands = compute_second_place_candidates(
            racers, wi, base_scores, dominant, line_map, adv_bonus, adv_penalty, line_follow_bonus, sharpness)
        second_cache[fc] = cands
        for c in cands[:n2]:
            if c["car"] not in second_pool:
                second_pool.append(c["car"])

    third_pool = []
    third_cache = {}
    for fc in first_candidates:
        wi = next(i for i, r in enumerate(racers) if r["car"] == fc)
        for sc in second_pool:
            if sc == fc:
                continue
            si = next(i for i, r in enumerate(racers) if r["car"] == sc)
            cands = compute_third_place_candidates(
                racers, wi, si, base_scores, dominant, line_map, adv_bonus, adv_penalty, line_follow_bonus, sharpness)
            third_cache[(fc, sc)] = cands
            for c in cands[:n3]:
                if c["car"] not in third_pool:
                    third_pool.append(c["car"])

    combos = []
    for fc in first_candidates:
        wi = next(i for i, r in enumerate(racers) if r["car"] == fc)
        first_prob = final_rates[wi] / 100
        if first_prob <= 0:
            continue
        second_by_car = {c["car"]: c for c in second_cache.get(fc, [])}
        for sc in second_pool:
            if sc == fc or sc not in second_by_car:
                continue
            second_prob = second_by_car[sc]["prob"] / 100
            if second_prob <= 0:
                continue
            third_by_car = {c["car"]: c for c in third_cache.get((fc, sc), [])}
            for tc in third_pool:
                if tc in (fc, sc) or tc not in third_by_car:
                    continue
                third_prob = third_by_car[tc]["prob"] / 100
                if third_prob <= 0:
                    continue
                fc_name = next(r["name"] for r in racers if r["car"] == fc)
                sc_name = next(r["name"] for r in racers if r["car"] == sc)
                tc_name = next(r["name"] for r in racers if r["car"] == tc)
                combos.append({
                    "first": fc, "first_name": fc_name,
                    "second": sc, "second_name": sc_name,
                    "third": tc, "third_name": tc_name,
                    "prob": first_prob * second_prob * third_prob * 100,
                })
    combos.sort(key=lambda x: -x["prob"])
    total_prob = sum(c["prob"] for c in combos)

    return {
        "first_candidates": first_candidates,
        "second_candidates": second_pool,
        "third_candidates": third_pool,
        "combos": combos,
        "total_combos": len(combos),
        "total_prob": total_prob,
    }


# ============================================================
# ライン予想テキストの解析（並び予想: "← 4先行 1追込 6押え先 2追込 7押え先 3追込 5追込"）
# 「追込」だけが同じラインの継続を表し、それ以外の役割語（先行・押え先・自在・追い上げ等）は
# 新しいラインの先頭を表す、という競輪の並び予想表記の慣例に基づいて解析する。
# ============================================================
def parse_line_prediction_text(text):
    """
    並び予想テキストの解析。以下の2つの形式に対応する。
    1. スクレイピングしたサイトのテキスト形式（例："4先行1追込6押え先2追込"）
       スペース区切りの有無に依存せず、「数字＋役割語」の並びを正規表現で
       直接抜き出す方式。全角数字にも対応するため、事前に半角へ正規化する。
       「(4競り5競り)(3競り7競り)」のように括弧で競り合いペアを示す表記にも対応する
       （括弧の開始は新しいラインの区切りとして扱い、括弧内の「競り」は「追込」と
       同様に同じラインへの継続とみなす）。
    2. 手動入力のハイフン・カンマ記法（例："5-1,4,6-2,3-7"）
       keirin_predictor_v2.html（スタンドアロン版）と同じ書式。
       同じラインは先頭→後方をハイフンでつなぎ、ライン同士はカンマで区切る。
       役割語が1つも見つからなかった場合にこちらの形式として解釈する。
    """
    if not text:
        return {}
    import re as _re
    # 全角数字→半角数字に正規化
    zen = "０１２３４５６７８９"
    han = "0123456789"
    text = text.translate(str.maketrans(zen, han))
    text = text.replace("←", " ").replace("→", " ")

    ROLE_WORDS = "先行|追込|押え先|自在|追い上げ|追上|競り|カマシ|捲|差|逃"
    pairs = _re.findall(rf"([（(]?)\s*(\d+)\s*({ROLE_WORDS})", text)

    if not pairs:
        # 役割語が見つからない場合は、ハイフン・カンマ記法として解釈する
        return _parse_line_hyphen_notation(text)

    lines = []
    current = []
    for paren, car_str, role in pairs:
        car = int(car_str)
        if paren in ("(", "（"):
            # 括弧の開始＝新しい競り合いグループの先頭
            if current:
                lines.append(current)
            current = [car]
        elif role in ("追込", "競り") and current:
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


def _parse_line_hyphen_notation(text):
    """"5-1,4,6-2,3-7" のようなハイフン・カンマ記法を解析する。"""
    import re as _re
    line_map = {}
    groups = [g.strip() for g in _re.split(r"[,、，\n]", text) if g.strip()]
    for gi, g in enumerate(groups):
        cars_str = [s for s in _re.split(r"[-－―ー\s]+", g) if s]
        cars = []
        for s in cars_str:
            try:
                n = int(s)
                if n > 0:
                    cars.append(n)
            except ValueError:
                continue
        for pos, car in enumerate(cars):
            line_map[car] = {"line_index": gi, "position": pos + 1, "line_size": len(cars)}
    return line_map


# ============================================================
# レース全体の予測を計算するメイン関数
# ============================================================
DEFAULT_SETTINGS = {
    "th_high": 45, "th_list": 10, "close_threshold": 8,
    "development_weight": 55,
    "line_strength": 30, "line_support": 8, "solo_penalty": 6,
    "line_follow_bonus": 45, "adv_bonus": 10, "adv_penalty": 15,
    "sharpness": 1.3, "confidence_shrink": 20,
    "formation_n1": 2, "formation_n2": 4, "formation_n3": 5,
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
    base_scores_raw = compute_base_scores(racers)
    confidence = compute_confidence(racers)
    base_scores = apply_confidence_shrinkage(base_scores_raw, confidence, s["confidence_shrink"])
    dominant = compute_kimarite_prediction(racers, line_map)
    kimarite_ratio = compute_kimarite_ratio(dominant)
    dev_scores, nige_count, pace_index = compute_kimarite_adjustment(racers, dominant, kimarite_ratio)
    line_adj = compute_line_adjustment(
        racers, line_map, kimarite_ratio, s["line_strength"], s["line_support"], s["solo_penalty"])
    final_rates, effective_mult, combined_scores = compute_adjusted_rates(
        base_scores, line_adj, dev_scores, s["development_weight"], s["sharpness"])
    old_model_place_rates = compute_old_model_place_rates(racers)

    rows = []
    for i, r in enumerate(racers):
        rows.append({
            **r, "base": base_scores[i], "adj": effective_mult[i], "adjusted": final_rates[i],
            "dominant_type": dominant[i]["type"], "kimarite_prediction": dominant[i],
            "line_info": line_map.get(r["car"]), "confidence": confidence[i],
            "old_model_place_rate": old_model_place_rates[i], "idx": i,
        })
    rows.sort(key=lambda x: -x["adjusted"])

    top = rows[0]
    second_candidates = compute_second_place_candidates(
        racers, top["idx"], combined_scores, dominant, line_map,
        s["adv_bonus"], s["adv_penalty"], s["line_follow_bonus"], s["sharpness"])

    third_candidates = []
    if second_candidates and len(racers) > 2:
        second_idx = second_candidates[0]["idx"]
        third_candidates = compute_third_place_candidates(
            racers, top["idx"], second_idx, combined_scores, dominant, line_map,
            s["adv_bonus"], s["adv_penalty"], s["line_follow_bonus"], s["sharpness"])

    close_group = [r for r in rows if top["adjusted"] - r["adjusted"] <= s["close_threshold"]]
    most_reliable = max(close_group, key=lambda r: r["confidence"]["score"]) if len(close_group) >= 2 else None

    second_place_matrix = compute_second_place_matrix(
        racers, combined_scores, dominant, line_map, s["adv_bonus"], s["adv_penalty"], s["line_follow_bonus"], s["sharpness"])
    third_place_matrix = compute_third_place_matrix(
        racers, combined_scores, dominant, line_map, s["adv_bonus"], s["adv_penalty"], s["line_follow_bonus"], s["sharpness"],
        second_place_matrix=second_place_matrix)

    formation = compute_formation_bet(
        racers, combined_scores, dominant, line_map, final_rates,
        s["adv_bonus"], s["adv_penalty"], s["line_follow_bonus"], s["sharpness"],
        s["formation_n1"], s["formation_n2"], s["formation_n3"])

    return {
        "rows": rows,
        "top": top,
        "second_candidates": second_candidates[:5],
        "third_candidates": third_candidates[:5],
        "second_place_matrix": second_place_matrix,
        "third_place_matrix": third_place_matrix,
        "formation": formation,
        "kimarite_ratio": kimarite_ratio,
        "pace_index": pace_index,
        "line_map": line_map,
        "line_prediction_text": line_prediction_text,
        "close_group": close_group,
        "most_reliable": most_reliable,
        "is_high_prob": top["adjusted"] >= s["th_high"],
        "settings": s,
    }
