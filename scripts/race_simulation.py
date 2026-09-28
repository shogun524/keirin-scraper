# -*- coding: utf-8 -*-
"""
展開シミュレーション（モンテカルロ）。

model.py の予測1着率（adjusted）や決まり手予測分布は、あくまで「期待値としての
強さ」を示す静的な数値。実際のレースは「その日その瞬間にどの決まり手が実現するか」
という一回性の展開に左右されるため、ここでは各選手の決まり手予測分布から
決まり手を都度サンプリングし、レース展開（先行争いの激しさ・捲りの有無など）に
応じたボーナス/ペナルティを load させた上で、多数回（デフォルト3000回）の
架空レースを繰り返して集計する。

目的は「予測1着率を上書きする新しい確率」を作ることではなく、
・本命が飛ぶ確率（波乱度）
・レースがどんな展開パターンになりやすいか（先行決着／捲り決着／差し決着 など）
を、既存の予測とは違う角度から示す参考情報を提供すること。そのため既存の
adjusted（真の同時確率ベースの1着率）はそのまま残し、本モジュールの結果は
別枠の「展開シミュレーション」として表示する。
"""

import math
import random

KIMARITE = ["逃", "捲", "差", "マ"]

SCENARIO_LABELS = {
    "solo_nige": "先行逃げ切り濃厚",
    "nige_war": "先行争いで共倒れ含みの乱戦",
    "makuri": "捲り決着",
    "sashi": "差し・展開待ち決着",
}


def _gumbel_noise(rng):
    u = rng.random()
    u = min(max(u, 1e-12), 1 - 1e-12)
    return -math.log(-math.log(u))


def _classify_scenario(nige_realized, makuri_realized):
    if len(nige_realized) == 1 and not makuri_realized:
        return "solo_nige"
    if len(nige_realized) >= 2:
        return "nige_war"
    if makuri_realized:
        return "makuri"
    return "sashi"


def simulate_race_development(rows, trials=3000, seed=42, top_scenarios=4):
    """
    rows: predict_race() が返す result["rows"]（各要素に 'car','adjusted',
          'kimarite_prediction':{'probs':{...}} が必要）
    戻り値: {
      "trials": int,
      "top_pick": car,
      "win_freq": {car: %},          # シミュレーション上の1着率（サニティチェック用にも使える）
      "upset_probability": %,         # 本命（adjusted最大の選手）が1着にならない確率
      "scenarios": [ {"key","label","share","example_top3":[car,car,car]}, ... ],
    }
    データが2人未満（レース不成立）なら None。
    """
    if not rows or len(rows) < 2:
        return None

    rng = random.Random(seed)
    cars = [r["car"] for r in rows]
    probs_by_car = {r["car"]: r["kimarite_prediction"]["probs"] for r in rows}
    base_by_car = {r["car"]: max(r["adjusted"], 0.1) for r in rows}
    top_pick = max(rows, key=lambda r: r["adjusted"])["car"]

    win_counts = {c: 0 for c in cars}
    scenario_counts = {k: 0 for k in SCENARIO_LABELS}
    scenario_example = {}

    for _ in range(trials):
        realized = {}
        for c in cars:
            probs = probs_by_car[c]
            types = list(probs.keys())
            weights = [probs[t] for t in types]
            realized[c] = rng.choices(types, weights=weights, k=1)[0]

        nige_realized = [c for c in cars if realized[c] == "逃"]
        makuri_realized = [c for c in cars if realized[c] == "捲"]
        scenario_key = _classify_scenario(nige_realized, makuri_realized)
        scenario_counts[scenario_key] += 1

        scores = {}
        for c in cars:
            base = base_by_car[c]
            rt = realized[c]
            bonus = 1.0
            if rt == "逃":
                bonus = 1.35 if len(nige_realized) == 1 else 0.75
            elif rt == "捲":
                bonus = 1.25 if len(makuri_realized) <= 1 else 1.0
                bonus *= 1.15 if len(nige_realized) <= 1 else 0.9
            elif rt == "差":
                bonus = 1.15 if (nige_realized or makuri_realized) else 0.9
            else:  # マーク
                bonus = 1.05 if (nige_realized or makuri_realized) else 0.85
            scores[c] = base * bonus

        order = sorted(cars, key=lambda c: math.log(scores[c]) + _gumbel_noise(rng), reverse=True)
        win_counts[order[0]] += 1
        if scenario_key not in scenario_example:
            scenario_example[scenario_key] = order[:3]

    win_freq = {c: win_counts[c] / trials * 100 for c in cars}
    upset_probability = 100.0 - win_freq.get(top_pick, 0.0)

    scenarios = []
    for key, count in sorted(scenario_counts.items(), key=lambda x: -x[1]):
        if count == 0:
            continue
        scenarios.append({
            "key": key,
            "label": SCENARIO_LABELS[key],
            "share": count / trials * 100,
            "example_top3": scenario_example.get(key, []),
        })

    return {
        "trials": trials,
        "top_pick": top_pick,
        "win_freq": win_freq,
        "upset_probability": upset_probability,
        "scenarios": scenarios[:top_scenarios],
    }
