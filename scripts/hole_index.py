# -*- coding: utf-8 -*-
"""
穴目指数（Sleeper Index）。

「予測1着率が高い選手が1着にならない確率」＝ 100 − 予測1着率 は、見た目の数字が
新しいだけで情報量がゼロ（引き算しているだけ）という指摘の通りで、狙い目探しの
役には立たない。ここでは、model.py が既に計算している別々の材料を組み合わせて、
「新聞・大方の評価（＝mark、記者印）では目立たないが、データ上は評価が高い選手」
を探すための指数を作る。

使う材料は2つ、どちらも既存計算の副産物であり、新しい仮定を追加していない：

1. 印乖離（mark_gap）
   選手には ×▲△○◎注★ の記者印（mark）が付いており、これは MODEL["weights"] で
   実際に学習済みモデルの特徴量として使われている（＝mark が強いほど基礎スコアが
   上がるよう学習されている）。つまり mark はそれ自体が「大方の下馬評」を表す
   数値化可能な情報源であり、予測1着率（adjusted）とは独立に「印だけで並べた
   順位」を作れる。
   この「印だけの順位」と「モデル総合の順位（adjusted降順）」を比較し、
   モデルの方が高く評価している（背番号が良くなっている）選手を抽出する。
   → 「記者の目線では目立たないが、ライン構成・決まり手適性・当地成績・対戦相性・
     直近の調子まで総合すると評価が上がる」選手を見つけられる。

2. 展開補正倍率（adj、row["adj"]）
   model.py の compute_adjusted_rates() が返す effective_mult は「基礎スコアが、
   決まり手構成・ライン補正・バンク相性・対戦相性・調子補正でトータル何倍に
   なったか」を表す。1.0より大きいほど「地力以上に、今回のレース特有の要因
   （展開・バンク・相手・調子）で浮上しやすい」選手ということになる。

この2つを組み合わせた hole_score が高い選手ほど、「表面的な評価は低いが、
データを総合すると浮上の芽がある」候補として提示する。あくまで参考指標であり、
的中を保証するものではない。
"""

MARK_ORDER_WEIGHTS = None  # model.py から MODEL["weights"] を渡してもらう想定


def _mark_strength(mark, mark_weights):
    if not mark:
        return 0.0  # 印なし＝基準（平均的な下馬評）とみなす
    return mark_weights.get(mark, 0.0)


def compute_hole_candidates(rows, mark_weights, top_n=3,
                             mark_gap_weight=1.0, adj_weight=10.0, min_score=1.5):
    """
    rows: predict_race() の result["rows"]（adjusted降順にソート済みであること。
          各要素に 'car','name','mark','adjusted','adj' が必要）
    mark_weights: MODEL["weights"]（記者印ごとの学習済み重み）
    戻り値: [{"car","name","model_rank","mark_rank","mark_gap","adj_mult",
              "hole_score","reasons":[...]}, ...]（hole_score降順、上位top_n件）
    候補が無ければ空リスト。
    """
    if not rows or len(rows) < 3:
        return []

    n = len(rows)
    # 印だけで並べた順位（強い印ほど上位。同じ強さなら車番の若い順で安定させる）
    by_mark = sorted(rows, key=lambda r: (-_mark_strength(r.get("mark"), mark_weights), r["car"]))
    mark_rank_of = {r["car"]: i + 1 for i, r in enumerate(by_mark)}

    candidates = []
    for model_rank, r in enumerate(rows, start=1):
        mark_rank = mark_rank_of[r["car"]]
        mark_gap = mark_rank - model_rank  # 正の値＝印の評価より、モデルの方が高く評価している
        adj_mult = r.get("adj", 1.0)

        hole_score = max(mark_gap, 0) * mark_gap_weight + max(adj_mult - 1.0, 0) * adj_weight
        if hole_score < min_score:
            continue

        reasons = []
        if mark_gap >= 2:
            reasons.append(f"記者印の評価（{mark_rank}番手評価）よりモデル総合評価が{mark_gap}ランク高い")
        if adj_mult >= 1.15:
            reasons.append(f"ライン・バンク相性・対戦相性・調子などの補正で基礎の{adj_mult:.2f}倍に浮上")
        if not reasons:
            continue

        candidates.append({
            "car": r["car"], "name": r["name"],
            "model_rank": model_rank, "mark_rank": mark_rank, "mark_gap": mark_gap,
            "adj_mult": adj_mult, "adjusted": r["adjusted"],
            "hole_score": hole_score, "reasons": reasons,
        })

    candidates.sort(key=lambda c: -c["hole_score"])
    return candidates[:top_n]
