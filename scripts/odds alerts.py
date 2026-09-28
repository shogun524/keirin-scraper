# -*- coding: utf-8 -*-
"""
オッズ妙味アラート（票数トレンド活用・簡易プロキシ版）。

【重要な制約】
このサイトでは車券ごと（選手ごと）のオッズ内訳を安定して取得できておらず、
scraper.extract_betting_volume() で取得できているのは「レース全体の発売票数
（＝そのレースにどれだけ投票が集まっているか）」のみ。そのため「モデルが強気
なこの選手は、実際のオッズに対して過小評価されている」という単勝オッズ対比の
狭義の妙味判定はできない。

その代わりここでは、「モデルが高い確信度を持って本命を示しているのに、
同じ時間帯の他レースと比べて投票の伸びが鈍い（＝まだ注目度が低い）レース」を
検出し、"投票が本格化する前に注目しておきたいレース候補" として参考表示する。
あくまで観測できる範囲でのプロキシ指標であり、車券の的中や払い戻しの良し悪しを
保証するものではないことをUI上でも明記すること。
"""

MIN_CONFIDENCE_FOR_ALERT = 45  # is_high_prob と同じ閾値目安（モデルが強気なレースのみ対象）
MIN_SNAPSHOTS_FOR_BASELINE = 2  # growth_pctが算出されている（=2回以上観測された）レースのみ基準値の計算に使う
GROWTH_GAP_THRESHOLD = 8.0  # 基準値よりこの割合（pt）以上伸びが鈍ければ「注目度が低い」と判定


def compute_odds_value_alerts(all_race_data, min_confidence=MIN_CONFIDENCE_FOR_ALERT,
                               growth_gap_threshold=GROWTH_GAP_THRESHOLD):
    """
    all_race_data: run_daily.py の all_race_data（各要素に "race_info"（odds_trend含む）と
                   "prediction" を持つ）
    戻り値: [{"venue","race_no","venue_name","top_car","top_name","top_adjusted",
              "growth_pct","baseline_growth_pct","gap"}, ...]（gapが大きい順）
    候補が無ければ空リスト。基準値を算出できるレースが無い場合も空リストを返す。
    """
    growth_values = []
    for rd in all_race_data:
        trend = rd["race_info"].get("odds_trend")
        if trend and trend.get("snapshot_count", 0) >= MIN_SNAPSHOTS_FOR_BASELINE:
            growth_values.append(trend["growth_pct"])

    if not growth_values:
        return []  # まだどのレースも十分な観測回数が無い（運用開始直後など）

    baseline = sum(growth_values) / len(growth_values)

    alerts = []
    for rd in all_race_data:
        prediction = rd.get("prediction")
        if not prediction:
            continue
        top = prediction.get("top")
        if not top or top["adjusted"] < min_confidence:
            continue

        trend = rd["race_info"].get("odds_trend")
        # 観測不足（まだ票数の伸びを2回以上観測できていない）レースも、
        # 「そもそも投票自体がまだ盛り上がっていない」とみなして候補に含める
        growth_pct = trend["growth_pct"] if trend else 0.0
        gap = baseline - growth_pct
        if gap < growth_gap_threshold:
            continue

        info = rd["race_info"]
        alerts.append({
            "venue": info["venue"],
            "race_no": info["race_no"],
            "top_car": top["car"],
            "top_name": top["name"],
            "top_adjusted": top["adjusted"],
            "growth_pct": growth_pct,
            "baseline_growth_pct": baseline,
            "gap": gap,
        })

    alerts.sort(key=lambda a: -a["gap"])
    return alerts
