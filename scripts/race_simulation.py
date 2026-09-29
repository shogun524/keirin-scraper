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
    "逃": [0.10, 0.10, 0.11, 0.12, 0.13],
    "マ": [0.18, 0.20, 0.23, 0.19, 0.15],
    "捲": [0.16, 0.38, 0.72, 0.58, 0.32],
    "差": [0.16, 0.20, 0.28, 0.52, 0.30],
}

# 実際のバンク形状（ホームストレッチ＋バックストレッチ＋2つのコーナー）を、1周を
# 0.0〜1.0のトラック位置（fraction）で表した区間表（4区間とも均等の0.25ずつ）。
# フィニッシュライン＝1.0（＝0.0、ホームストレッチがコーナーへ入る直前）、
# 向正面（バックストレッチ）はフィニッシュのちょうど半周先（対岸）の fraction 0.25〜0.5
# とする。これにより「向正面から残り1周半」を fraction 0.5 → 2.0（=0.5+1.5周）の
# 単純な直線的な加算で表現できる。実際のトラック座標（形・周回方向）への変換は
# フロントエンド（report.py の JS の devTrackXY）側で行う。
TRACK_SEGMENTS = {
    "turn_to_back": [0.0, 0.25],    # ゴール側コーナー〜向正面入口
    "back_straight": [0.25, 0.5],   # 向正面（バックストレッチ）
    "turn_to_home": [0.5, 0.75],    # 向正面側コーナー〜ホームストレッチ入口
    "home_straight": [0.75, 1.0],   # ゴール（ホームストレッチ）。フィニッシュは末尾(=1.0=0.0)
}
ANIMATION_START_FRACTION = 0.5  # 向正面あたり（アニメーションの開始地点）
ANIMATION_TOTAL_LAPS = 1.5      # 向正面から数えてゴールまでの周回数（残り1周半）

# 【重要】"positions" は 0〜100 の抽象的な「進み具合」ではなく、実際の周回距離
# （単位：周）そのものを表す。全車は同じ 1.5周 を同じ時間で走るので、まず
# 「集団全体が今どこまで進んでいるか」という共通の基準線（baseline）を先に決め、
# 各車の差（着差）はその基準線からの「ごくわずかな遅れ」として上乗せする。
# こうしないと、着順に応じて 0〜100 の異なるスケールを 1.5周分の弧長にそのまま
# 換算してしまい、ある車だけ実際には1周以上も先にワープしたように見える
# （チェックポイント0の時点で選手ごとにトラック上のバラバラな場所に飛んでしまう）
# という致命的なバグになる。
#
# 【改訂：個別着順ベース＋ライン内は「表示上の車間」を分離】
# 以前は「ライン代表着順（ラインの最上位選手の着順）」だけで遅れ幅を決め、番手・
# 三番手は常に「先頭の位置−追加の車間」として先頭より後ろにしか描けなかった。
# これだと、番手選手が実際に差し切って1着になるケース（差し・捲り）でも、
# アニメーション上は先頭の後ろに描かれてしまい、着順と矛盾する上に「集団が
# 一塊すぎて誰が動いているか分からない」問題も起きていた。
# そこで、進み具合そのもの（own_positions）は各車「個別の」最終着順で決め、
# ライン内の並び順（1-2-3のような車間）は、それとは別に「表示上の一定の間隔
# （ANIMATION_LINE_QUEUE_GAP）」として常時上乗せするだけにする。これにより
#   ・実際の着順が正しくそのままアニメーションの前後関係に反映される
#     （番手が差し切れば、番手が先頭を追い抜く動きとして描かれる）
#   ・かつ、着順差が小さい序盤〜中盤は「ライン順に連なって進む」見た目になる
# の両立ができる。ゴール（最終チェックポイント）だけは車間を0に戻し、必ず
# 実際の着順どおりの前後関係でフィニッシュするようにする。
ANIMATION_MAX_FIELD_GAP_LAPS = 0.18    # 最下位が1着から遅れる最大幅（周）。集団の塊具合と
                                        # 視認性のバランスを取った、実際の着差よりやや誇張した値。
ANIMATION_LINE_QUEUE_GAP = 0.015       # ライン内の車間（周相当、着順に関係なく常時一定）。
                                        # 「1-2-3」のような並び順を序盤から視覚的に示すための間隔。


def _finalize_positions(positions, target):
    """
    どんな合成（ライン追従など）を経ても、アニメーションのチェックポイント列が
    ・途中で最終到達距離(target)を超えない（最後の点だけがtargetちょうど）
    ・値が前方に対して単調非減少（車が後退して見えることがない）
    という2条件を必ず満たすように後処理する。
    """
    capped = [min(p, target - 0.0005) for p in positions[:-1]] + [target]
    for i in range(1, len(capped)):
        capped[i] = max(capped[i], capped[i - 1])
    return [round(p, 5) for p in capped]


def build_animation(rows, sample_run, straight_category="standard"):
    """
    1回分の試行（sample_run: {"realized":{car:決まり手}, "order":[car,...]（着順）}）から、
    レース展開を再生するためのチェックポイントごとの位置・進路データを作る。

    【重要：positions の単位について】
    以前のバージョンでは positions を「0〜100の抽象的な進み具合（着順ベースの
    目標値×決まり手カーブ）」として計算し、それをトラック上の弧長（1.5周分）に
    そのまま比例変換していた。しかしこれは、着順によって異なる0〜100のスケールを
    1.5周という「全車共通の周回距離」に無理やり当てはめてしまうことになり、
    チェックポイント0（アニメーション開始直後）の時点で選手によってはトラック上
    1周以上先の全く違う場所にいるかのような、物理的にありえない結果を生んでいた
    （実際に描画して発覚した致命的なバグ）。
    そこで本バージョンでは positions を最初から「実際の周回距離（単位：周）」
    として計算し直す：まず全車共通の基準線 baseline（0〜1.5周、チェックポイントの
    時間経過に比例）を作り、着順による差は、そこからの「ごくわずかな遅れ」
    （ANIMATION_MAX_GROUP_GAP_LAPS・ANIMATION_MAX_LINE_GAP_LAPS で上限を設定）
    として上乗せする。これにより、全車が常に同じ集団としてトラック上のほぼ
    同じ場所を一緒に進み、着順による違いはゴール前のごく僅かな差としてのみ
    現れるようになる。

    【実際の競輪の集団の動きに合わせた設計】
    実際のレースでは、決着がつく最後の直線までは基本的に集団がほぼ一塊のまま進み、
    ライン同士・ライン内の選手同士が大きく離れることはない。そして、一度どこかで
    差がついたら、その差が再び縮まることは無い（＝一度千切れたら追いつけない）。
    ただし「番手・三番手が実際に差し切って1着になる」ような決まり手（差し・捲り）
    はきちんと追い抜きの動きとして見えなければならない。この3点を以下で両立する。

    1. 進み具合（own_positions）は「個々の選手の実際の着順」で決める。1着は遅れ0、
       最下位でも ANIMATION_MAX_FIELD_GAP_LAPS（既定0.18周）までしか遅れない＝
       集団が大きく千切れないことを表現しつつ、着順が正しくそのまま前後関係になる
       （番手が差し切れば、番手が先頭より前に出る動きとして描かれる）。
       遅れが表面化するタイミングは自分の決まり手カーブ（0→1に単調増加のramp）に
       従うので、一度ついた遅れが縮まることもない。
    2. ライン内の並び順（「1-2-3」のような車間）は、着順による本当の差とは別に
       ANIMATION_LINE_QUEUE_GAP（常時一定の表示上の間隔）として番手・三番手に
       追加で上乗せする。これにより着順差が小さい序盤〜中盤は「ライン順に連なって
       進む」見た目になる。ただし最終チェックポイント（ゴール）だけはこの間隔を
       0に戻し、必ず実際の着順どおりの前後関係でフィニッシュするようにする
       （着順とアニメーションの矛盾を防ぐ）。
    3. 進路（lane）は、決まり手ごとの横位置カーブ（LANE_CURVES_BY_KIMARITE）を
       そのまま使う。捲り＝向正面〜コーナーで大きく外に膨らむ、差し＝直線でだけ
       外に出る、という動きが個々の車にそのまま表れるので、着順が良い捲り・差しは
       「外に膨らんで前に出る」動きとしてはっきり視認できる。ライン内の番手・
       三番手は、見た目の一体感のため先頭のレーンを基準に横ずれを乗せる。

    戻り値: {
      "checkpoints": int,
      "track": {"segments":{...}, "start_fraction":0.5, "total_laps":1.5},
      "cars":[{"car","name","positions":[実際の周回距離（周）の5点＝進行度],
               "lanes":[0-1の5点＝進路（0=最内/1=最外）],
               "line_index","line_position"}],
      "final_order":[car,...],
    }
    """
    if not rows or not sample_run:
        return None
    order = sample_run["order"]
    realized = sample_run["realized"]
    n_checkpoints = ANIMATION_CHECKPOINTS
    rank_of = {car: i for i, car in enumerate(order)}
    row_by_car = {r["car"]: r for r in rows}
    curves = POSITION_CURVES_BY_STRAIGHT.get(straight_category, POSITION_CURVES_BY_STRAIGHT["standard"])

    # 集団全体が共通で進む基準線（周単位）。全車がこの同じペースで一緒に進み、
    # 着順による差は、この基準線からの「ごくわずかな遅れ」として later 上乗せする。
    baseline = [ANIMATION_TOTAL_LAPS * i / (n_checkpoints - 1) for i in range(n_checkpoints)]
    n_cars = len(order)

    def _ramp_for(kimarite):
        # 決まり手カーブ（0〜1に単調増加）を「0（まだ遅れていない）→1（最終的な遅れが
        # 出切った）」の比率カーブに変換する。決まり手ごとに遅れが表面化するタイミング
        # （逃げは終盤まで粘る、差しは終盤だけ一気に、等）を反映しつつ、単調増加が
        # 保証されるので「一度遅れたら縮まらない」という条件も自動的に満たす。
        curve = curves.get(kimarite, curves["マ"])
        span = curve[-1] - curve[0]
        if span <= 1e-9:
            return [0.0] * n_checkpoints
        return [(c - curve[0]) / span for c in curve]

    # 各車「個別の」実際の着順から、進行度（基準線 − 遅れ）を計算する。ライン代表
    # 着順ではなく個別着順を使うことで、番手が差し切って1着になるケースでも矛盾なく
    # 「番手が先頭を追い抜く」動きとして描かれる。
    own_positions = {}
    own_lanes = {}
    for car in order:
        kimarite = realized.get(car)
        ramp = _ramp_for(kimarite)
        deficit_final = ANIMATION_MAX_FIELD_GAP_LAPS * (rank_of[car] / max(n_cars - 1, 1))
        own_positions[car] = [baseline[i] - deficit_final * ramp[i] for i in range(n_checkpoints)]
        lane_curve = LANE_CURVES_BY_KIMARITE.get(kimarite, LANE_CURVES_BY_KIMARITE["マ"])
        own_lanes[car] = list(lane_curve)

    # ラインの先頭車番を line_index ごとに特定する
    leader_of_line = {}
    for car, r in row_by_car.items():
        info = r.get("line_info")
        if info and info.get("line_size", 1) > 1 and info.get("position") == 1:
            leader_of_line[info["line_index"]] = car

    cars_payload = []
    for car in order:
        info = row_by_car.get(car, {}).get("line_info")
        line_position = info["position"] if info else 1
        leader_car = leader_of_line.get(info["line_index"]) if info else None
        is_follower = leader_car is not None and leader_car != car

        # 進み具合＝自分の実際の着順で決まる own_positions が主。ライン内の並び順を
        # 見せるための「表示上の車間」は、それとは別に一定量（着順に関係なく常時
        # ANIMATION_LINE_QUEUE_GAP×(番手-1)）だけ追加で引く。ただし最終チェック
        # ポイント（ゴール）だけは車間を0に戻し、必ず own_positions（＝実際の着順）
        # どおりの前後関係でフィニッシュするようにする。これにより、番手が実際に
        # 差し切って1着になった場合はゴール前でその追い抜きが見える一方、
        # 着順の前後関係そのものが車間表示によって崩れることはない。
        if is_follower:
            queue_gap = ANIMATION_LINE_QUEUE_GAP * (line_position - 1)
            positions = list(own_positions[car])
            for i in range(n_checkpoints - 1):
                positions[i] -= queue_gap
            # 進路（lane）は先頭のレーンを基準に、決まり手カーブの分だけ外側へ
            # 張り出す＝捲り・差しは大きく外に出る動きがそのまま見た目に表れる。
            leader_lane = own_lanes[leader_car]
            own_lane_curve = own_lanes[car]
            lanes = []
            lane_gap = 0.05 * (line_position - 1)  # 番手ほど基礎的にわずかに外側（見た目で判別できる幅）
            base_lane_gap = lane_gap
            for i in range(n_checkpoints):
                outward = max(own_lane_curve[i] - leader_lane[i], 0.0) * 0.5
                lane_gap = max(lane_gap, base_lane_gap + outward)
                lanes.append(leader_lane[i] + lane_gap)
        else:
            positions = own_positions[car]
            lanes = own_lanes[car]
        positions = _finalize_positions(positions, positions[-1])
        lanes = [round(min(max(v, 0.05), 0.95), 3) for v in lanes]
        cars_payload.append({
            "car": car, "name": row_by_car.get(car, {}).get("name", ""),
            "positions": positions,
            "lanes": lanes,
            "line_index": info["line_index"] if info else None,
            "line_position": line_position,
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
    # アニメーション再生用：パターンごとに「1着になった選手の予測1着率(adjusted)が
    # 最も高い」1試行を保存する（＝そのパターンの中でも、他で表示している予測1着率
    # と矛盾しにくい試行を選ぶ）。単に「直近の1試行」を使うと、たまたま予測1着率の
    # 低い選手が1着になった回だけが残ってしまい、「予測1着率と展開アニメーションの
    # 着順が全く違う」という不整合が無用に大きくなるため。
    # ただし、それでもアニメーションは数ある試行のうちの「1つの具体例」であり、
    # 予測1着率はシナリオを跨いだ全試行の加重平均であるため、両者が完全に一致する
    # 保証はない（この差は仕様であり、report.py 側の説明文で明示する）。
    scenario_sample_run = {}
    scenario_sample_score = {}

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
        winner_score = base_by_car[order[0]]
        if winner_score > scenario_sample_score.get(scenario_key, -1.0):
            scenario_sample_score[scenario_key] = winner_score
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
