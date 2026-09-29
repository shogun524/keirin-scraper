# -*- coding: utf-8 -*-
"""
展開シミュレーション（モンテカルロ）。

【設計方針・改訂履歴】
当初は「本命が1着にならない確率（波乱度）」もこのモジュールの独自シミュレーション
（決まり手をランダムに再サンプリングし、展開に応じたボーナス/ペナルティを掛けて
架空レースを繰り返す）から算出していたが、これは
  ・adjusted（model.py の予測1着率）から 100 − adjusted[0] を計算しているだけで、
    情報量がゼロ（誰でも暗算できる引き算）
という指摘を受けて廃止した。「予測1着率が高い選手が当たらない確率」という
自明な数字ではなく、予測1着率だけでは見えてこない「展開次第でどの選手が浮上
しやすいか」を示すことが、このモジュールの本来の存在意義である。

そのため本モジュールは、決まり手の実現パターン（先行逃げ切り／先行争いの乱戦／
捲り決着／差し決着）ごとに
  1. そのパターンがどれくらいの確率で起こりそうか（share）
  2. そのパターンが起きた場合、条件付きで誰が1着になりやすいか（conditional_win_rates）
という、adjusted の単純な変換では絶対に出てこない情報を提供する。
「乱戦になったら本命よりこの選手」というような、展開読みでの狙い目探しに直結する
数字になるよう設計している。
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


# 決まり手ごとの「レース進行に対する位置取りの伸び方」。0%〜100%地点の5チェックポイント
# における、最終到達距離に対する到達割合（0〜1）。逃げは早く仕掛けて逃げ切りを図る
# ため序盤から伸び、差しは終盤まで脚を溜めて最後に伸びる、という一般的な脚質の
# イメージをアニメーションの動きとして表現するための簡易カーブ（実データからの
# 回帰ではなく、決まり手の定義から素直に作った目安の形）。
# straight_category（venue_data.straight_tendency 由来）で、みなし直線が短い場（
# 「逃げ・捲り有利」）ほど仕掛けが早く終盤の伸びが小さく、長い場（「差し有利」）
# ほど終盤の伸びを大きく取るようにカーブ自体を変える＝実際のコース特性を反映する。
POSITION_CURVES_BY_STRAIGHT = {
    "short": {  # みなし直線45m以下：逃げ・捲り有利
        "逃": [0.45, 0.72, 0.87, 0.95, 1.0],
        "捲": [0.22, 0.48, 0.75, 0.92, 1.0],
        "差": [0.15, 0.30, 0.50, 0.75, 1.0],
        "マ": [0.30, 0.55, 0.76, 0.92, 1.0],
    },
    "standard": {
        "逃": [0.35, 0.62, 0.80, 0.92, 1.0],
        "捲": [0.15, 0.35, 0.65, 0.88, 1.0],
        "差": [0.10, 0.22, 0.40, 0.68, 1.0],
        "マ": [0.25, 0.50, 0.72, 0.90, 1.0],
    },
    "long": {  # みなし直線58m以上：差し有利
        "逃": [0.30, 0.52, 0.68, 0.82, 1.0],
        "捲": [0.10, 0.25, 0.52, 0.80, 1.0],
        "差": [0.06, 0.14, 0.28, 0.55, 1.0],
        "マ": [0.18, 0.40, 0.62, 0.85, 1.0],
    },
}
ANIMATION_CHECKPOINTS = 5

# 決まり手ごとの「進路（コース取り）」。0=最内（誘導員の後ろ、ポジション固定）、
# 1=最外（大きく外を回る）で表す横方向の位置。
#   逃  : 最内を維持したまま逃げ切りを図る
#   マ  : 先頭の直後（内）に張り付いたまま追走し、ゴール寸前だけわずかに動く
#   捲  : 向正面〜コーナーで大きく外に膨らんで一気に交わし、直線でやや内に戻す
#   差  : 直線に入るまでは内で脚を溜め、最後の2区間だけ外へ出して差す
# これにより「捲り＝外から一気に」「差し＝直線でだけ動く」という脚質の違いを
# トラック上の横位置の動きとして再現する。
LANE_CURVES_BY_KIMARITE = {
    "逃": [0.12, 0.12, 0.13, 0.14, 0.15],
    "マ": [0.16, 0.18, 0.20, 0.17, 0.14],
    "捲": [0.15, 0.32, 0.62, 0.52, 0.30],
    "差": [0.15, 0.18, 0.24, 0.42, 0.28],
}

# 実際のバンク形状（ホームストレッチ＋バックストレッチ＋2つのコーナー）を、1周を
# 0.0〜1.0のトラック位置（fraction）で表した区間表。フィニッシュライン＝0.0（＝1.0）、
# 向正面（バックストレッチ）入口＝0.5（フィニッシュのちょうど半周先＝対岸）とする
# ことで、「向正面から残り1周半」を fraction 0.5 → 2.0（=0.5+1.5周）の単純な直線的な
# 加算で表現できる。フロントエンド（report.py の JS）はこの区間表を使って実際に
# ホームストレッチ／コーナー／バックストレッチの形にトラックを描画し、各車の
# position（0〜100の進行度）と lane（0〜1の横位置）から (x, y) 座標を計算する。
TRACK_SEGMENTS = {
    "home_straight": [0.0, 0.2],   # フィニッシュライン(0.0)を含むホームストレッチ
    "turn1": [0.2, 0.5],           # 1コーナー〜2コーナー
    "back_straight": [0.5, 0.8],   # 向正面（バックストレッチ）
    "turn2": [0.8, 1.0],           # 3コーナー〜4コーナー
}
ANIMATION_START_FRACTION = 0.5  # 向正面入口（アニメーションの開始地点）
ANIMATION_TOTAL_LAPS = 1.5      # 向正面から数えてゴールまでの周回数（残り1周半）


def _finalize_positions(positions, target):
    """
    どんな合成（ライン追従など）を経ても、アニメーションのチェックポイント列が
    ・途中で最終到達距離(target)を超えない（最後の点だけがtargetちょうど）
    ・値が前方に対して単調非減少（車が後退して見えることがない）
    という2条件を必ず満たすように後処理する。
    """
    capped = [min(p, target * 0.995) for p in positions[:-1]] + [target]
    for i in range(1, len(capped)):
        capped[i] = max(capped[i], capped[i - 1])
    return [round(p, 1) for p in capped]


def _line_following_series(car, own_series, leader_series, info, lag_per_position, divergent_from=3):
    """
    ラインの番手・三番手（position>=2）は、序盤（チェックポイント0〜divergent_from-1）は
    先頭の直後にぴったりついて進み、終盤（divergent_from以降）だけ自分自身の値に
    分岐する、という「番手取り」の動きを position/lane 共通のロジックとして作る。
    """
    if not (info and info.get("line_size", 1) > 1 and info.get("position", 1) >= 2):
        return list(own_series)
    lag = lag_per_position(info["position"])
    out = [leader_series[i] * lag for i in range(divergent_from)]
    out += [own_series[i] for i in range(divergent_from, len(own_series))]
    return out


def build_animation(rows, sample_run, straight_category="standard"):
    """
    1回分の試行（sample_run: {"realized":{car:決まり手}, "order":[car,...]（着順）}）から、
    レース展開を再生するためのチェックポイントごとの位置・進路データを作る。

    実際のライン構成（rows[i]["line_info"]）とコース特性（straight_category）を反映する：
      ・ラインの先頭（position=1）は自身の決まり手カーブ（進行度・進路とも）で進む。
      ・同ラインの番手・三番手（position>=2）は、序盤〜中盤は先頭の直後にぴったり
        ついて進み（進行度・進路の両方が差が開かない＝実際の「番手取り」の動き）、
        終盤2区間だけ自分の決まり手（差してさらに伸びる／マークのままゴールする等）
        で進行度・進路とも分岐する。
      ・単騎（ラインを組んでいない選手）は最初から自分の決まり手カーブのみで進む。
      ・向正面入口（チェックポイント0）は、全車まだ位置取り（ライン予想順）どおりに
        最内寄りで固まっている状態から始まる＝「バックをどのラインが取るか」は
        既にライン予想の並び順で決着している、という前提で表現している。

    戻り値: {
      "checkpoints": int,
      "track": {"segments":{...}, "start_fraction":0.5, "total_laps":1.5},
      "cars":[{"car","name","positions":[0-100の5点＝進行度],
               "lanes":[0-1の5点＝進路（0=最内/1=最外）],
               "line_index","line_position"}],
      "final_order":[car,...],
    }
    """
    if not rows or not sample_run:
        return None
    order = sample_run["order"]
    realized = sample_run["realized"]
    n = len(order)
    rank_of = {car: i for i, car in enumerate(order)}
    row_by_car = {r["car"]: r for r in rows}
    curves = POSITION_CURVES_BY_STRAIGHT.get(straight_category, POSITION_CURVES_BY_STRAIGHT["standard"])

    # 各車の目標到達距離（最終着順に基づく。1着ほど100%に近く、最下位でも55%までは進む）
    target_by_car = {}
    for car in order:
        rank = rank_of[car]
        target_by_car[car] = max(100 - rank * (30 / max(n - 1, 1)), 55)

    # 自分自身の決まり手カーブだけで進んだ場合の進行度・進路（ライン追従の土台として先に全員分計算）
    own_positions = {}
    own_lanes = {}
    for car in order:
        kimarite = realized.get(car)
        pos_curve = curves.get(kimarite, curves["マ"])
        lane_curve = LANE_CURVES_BY_KIMARITE.get(kimarite, LANE_CURVES_BY_KIMARITE["マ"])
        own_positions[car] = [round(target_by_car[car] * c, 1) for c in pos_curve]
        own_lanes[car] = list(lane_curve)

    # ラインの先頭車番を line_index ごとに特定する
    leader_of_line = {}
    for car, r in row_by_car.items():
        info = r.get("line_info")
        if info and info.get("line_size", 1) > 1 and info.get("position") == 1:
            leader_of_line[info["line_index"]] = car

    def lag_for_position(position):
        return 0.97 - 0.025 * (position - 2)  # 番手ほどわずかに車間を空けて追走

    cars_payload = []
    for car in order:
        info = row_by_car.get(car, {}).get("line_info")
        leader_car = leader_of_line.get(info["line_index"]) if info else None
        if leader_car is not None and leader_car != car:
            positions = _line_following_series(car, own_positions[car], own_positions[leader_car], info, lag_for_position)
            # 進路（lane）は番手ほどわずかに先頭より外側に張り付く（車間分の横ずれ）
            lane_offset = 0.02 * (info["position"] - 1)
            lanes = _line_following_series(
                car, own_lanes[car], [v + lane_offset for v in own_lanes[leader_car]], info, lambda p: 1.0)
        else:
            positions = own_positions[car]
            lanes = own_lanes[car]
        positions = _finalize_positions(positions, target_by_car[car])
        lanes = [round(min(max(v, 0.05), 0.95), 3) for v in lanes]
        cars_payload.append({
            "car": car, "name": row_by_car.get(car, {}).get("name", ""),
            "positions": positions,
            "lanes": lanes,
            "line_index": info["line_index"] if info else None,
            "line_position": info["position"] if info else 1,
        })

    # 表示順はライン構成が分かるよう「ライン順→ライン内の位置順」に並べる
    # （単騎・ライン情報無しは末尾に車番順でまとめる）
    cars_payload.sort(key=lambda c: (
        c["line_index"] if c["line_index"] is not None else 10**6,
        c["line_position"], c["car"],
    ))

    return {
        "checkpoints": ANIMATION_CHECKPOINTS,
        "track": {
            "segments": TRACK_SEGMENTS,
            "start_fraction": ANIMATION_START_FRACTION,
            "total_laps": ANIMATION_TOTAL_LAPS,
        },
        "cars": cars_payload,
        "final_order": order,
    }


def simulate_race_development(rows, trials=3000, seed=42, top_scenarios=4, top_picks_per_scenario=3,
                               straight_category="standard"):
    """
    rows: predict_race() が返す result["rows"]（各要素に 'car','name','adjusted',
          'kimarite_prediction':{'probs':{...}},'line_info' が必要）
    straight_category: venue_data.straight_tendency 由来の "short"/"standard"/"long"。
          アニメーションの決まり手カーブ（仕掛けのタイミング）に反映する。
    戻り値: {
      "trials": int,
      "scenarios": [
        {"key","label","share",
         "conditional_win_rates": [{"car","name","win_pct"}, ...]（そのパターン内で1着になった割合、上位のみ）},
        ...
      ],
    }
    決まり手の実現は各選手の予測分布（kimarite_prediction.probs）から都度サンプリング
    するため、この分布とライン構成以外の恣意的な仮定は「展開が有利に働いた場合の
    加点（決まり手が単独逃げか等）」のみで、スコアの相対順位づけにのみ使う
    （share自体には影響しない）。
    データが2人未満（レース不成立）なら None。
    """
    if not rows or len(rows) < 2:
        return None

    rng = random.Random(seed)
    cars = [r["car"] for r in rows]
    name_by_car = {r["car"]: r.get("name", "") for r in rows}
    probs_by_car = {r["car"]: r["kimarite_prediction"]["probs"] for r in rows}
    base_by_car = {r["car"]: max(r["adjusted"], 0.1) for r in rows}

    scenario_counts = {k: 0 for k in SCENARIO_LABELS}
    scenario_win_counts = {k: {c: 0 for c in cars} for k in SCENARIO_LABELS}
    scenario_sample_run = {}  # アニメーション再生用：パターンごとに直近の1試行を保存

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
        scenario_win_counts[scenario_key][order[0]] += 1
        scenario_sample_run[scenario_key] = {"realized": dict(realized), "order": order}

    # アニメーション再生用の代表試行：最も多く出たパターンから1つ選ぶ
    majority_key = max(scenario_counts, key=lambda k: scenario_counts[k])
    sample_run = scenario_sample_run.get(majority_key)

    scenarios = []
    for key, count in sorted(scenario_counts.items(), key=lambda x: -x[1]):
        if count == 0:
            continue
        win_counts = scenario_win_counts[key]
        conditional = sorted(
            ({"car": c, "name": name_by_car.get(c, ""), "win_pct": win_counts[c] / count * 100}
             for c in cars if win_counts[c] > 0),
            key=lambda x: -x["win_pct"],
        )[:top_picks_per_scenario]
        scenarios.append({
            "key": key,
            "label": SCENARIO_LABELS[key],
            "share": count / trials * 100,
            "conditional_win_rates": conditional,
        })

    return {
        "trials": trials,
        "scenarios": scenarios[:top_scenarios],
        "animation": build_animation(rows, sample_run, straight_category),
    }
