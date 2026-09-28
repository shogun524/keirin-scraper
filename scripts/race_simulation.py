# -*- coding: utf-8 -*-
"""
展開シミュレーション（モンテカルロ）。

【設計方針・改訂履歴】
当初は「本命が1着にならない確率（波乱度）」もこのモジュールの独自シミュレーション
（決まり手をランダムに再サンプリングし、展開に応じたボーナス/ペナルティを掛けて
架空レースを繰り返す）から算出していたが、これは以下の理由で不正確だった：
  ・model.py の adjusted（1着率）は、各選手の2着・3着候補まで含めた真の同時確率
    計算から導かれ、かつ過去実績との calibration 検証済みの値である一方、
  ・本モジュールのボーナス係数（1.35や0.75など）は経験則的な仮の値で、キャリブ
    レーションされていない。そのため「本命が飛ぶ確率」を本モジュールのシミュレー
    ション結果（win_freq）から出すと、画面上部に表示される「予測1着率」と数字が
    食い違い、どちらが正しいのか分からなくなる（このプロジェクトでは以前から
    「1着率・決まり手・confidence が矛盾しないこと」を重視して confidence
    shrinkage 等を入れてきた経緯があり、それに反する）。

そこで現在の設計では、
  ・「波乱度」（本命が1着にならない確率）と「大波乱指数」（4着評価以下の選手が
    1着になる確率）は、model.py 側で adjusted 確率から直接・厳密に計算する
    （100 - adjusted[0] のような単純な引き算で求まり、シミュレーションのノイズが
    入り込まない）。
  ・本モジュールが担うのは「レースがどんな決まり手パターンで決着しやすいか」
    （先行逃げ切り／先行争いの乱戦／捲り決着／差し決着）という、model.py の
    数値からは直接読み取れない切り口の参考情報のみに限定する。この分類は各選手の
    決まり手予測分布（kimarite_prediction.probs）から実際に決まり手をサンプリング
    した結果だけで決まり、ボーナス係数の影響を受けないため、恣意性が入らない。
  ・ボーナス係数付きのスコアリングは、各シナリオの「代表的な上位3頭」という
    添え物（あくまでイメージを示す例示）の算出にのみ使う。
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
      "scenarios": [ {"key","label","share","example_top3":[car,car,car]}, ... ],
    }
    「本命が飛ぶ確率」等の1着率そのものはここでは返さない（model.py 側で
    adjusted から厳密に計算するため。上のdocstring参照）。
    データが2人未満（レース不成立）なら None。
    """
    if not rows or len(rows) < 2:
        return None

    rng = random.Random(seed)
    cars = [r["car"] for r in rows]
    probs_by_car = {r["car"]: r["kimarite_prediction"]["probs"] for r in rows}
    base_by_car = {r["car"]: max(r["adjusted"], 0.1) for r in rows}

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

        if scenario_key not in scenario_example:
            # このシナリオの「代表例」を1つだけ、展開ボーナスを加味したスコアで作る
            # （あくまでイメージ用の例示であり、確率の算出には使わない）
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
            scenario_example[scenario_key] = order[:3]

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
        "scenarios": scenarios[:top_scenarios],
    }
