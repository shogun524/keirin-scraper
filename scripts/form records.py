# -*- coding: utf-8 -*-
"""
直近の調子（フォーム）の自前集計。
course_records.py（当地成績）・rivalry_records.py（対戦履歴）と同じ考え方で、
毎時の自動実行のたびに終了済みレースの結果を取得し、選手ごとに直近の着順を
時系列で積み上げていく。級班や競走得点のような「実力の絶対値」ではなく、
「直近伸びているか / 落ちているか」という相対的なトレンドを見るための機能。

競輪場を問わず選手単位で記録する（当地成績とは別の切り口）。

データは docs/_form_records.json （選手ごとの直近着順履歴、最大MAX_RECENT件）と
docs/_form_records_processed.json （二重集計防止用の処理済みレースID一覧）
の2ファイルに保存する。
"""

import os
import json

from scraper import extract_race_id_from_url, fetch_race_result

MAX_RECENT = 10  # 選手ごとに保持する直近レース件数の上限
MIN_RACES_FOR_TREND = 6  # トレンド判定に必要な最低件数（直近3走 vs その前3走を比較するため）


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def _save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def update_form_records(docs_dir, races_with_deadline_passed, race_date_str, now_str):
    """
    races_with_deadline_passed: [{"venue":, "race_no":, "url":}, ...]
      （締切を過ぎている＝結果が出ている可能性が高いレースのみを渡すこと。
       course_records / rivalry_records に渡すものと同じリストでよい）
    race_date_str: そのレースの開催日（"YYYY-MM-DD"）。直近順を並べるために使う。
    戻り値: (records, newly_processed_count)
    """
    records_path = os.path.join(docs_dir, "_form_records.json")
    processed_path = os.path.join(docs_dir, "_form_records_processed.json")

    records = _load_json(records_path, {})
    processed = _load_json(processed_path, {"processed_race_ids": []})
    processed_set = set(processed.get("processed_race_ids", []))

    newly_processed = 0
    for race in races_with_deadline_passed:
        venue, url = race["venue"], race["url"]
        race_id = extract_race_id_from_url(url)
        if not race_id or race_id in processed_set:
            continue

        try:
            result = fetch_race_result(venue, race_id)
        except Exception as e:
            print(f"[WARN] {venue} {race['race_no']}R: 調子集計用の結果取得に失敗しました: {e}")
            continue

        if not result:
            continue  # まだ結果が確定していない（正常系。次回の実行で再挑戦する）

        for row in result:
            name = row["name"]
            entry = records.setdefault(name, {"name": name, "recent": []})
            entry["recent"].append({
                "date": race_date_str,
                "venue": venue,
                "finish": row["finish"],
                "kimarite": row.get("kimarite"),
            })
            # 日付順（古い→新しい）を保証してから、直近MAX_RECENT件だけ残す
            entry["recent"].sort(key=lambda r: r["date"])
            if len(entry["recent"]) > MAX_RECENT:
                entry["recent"] = entry["recent"][-MAX_RECENT:]

        processed_set.add(race_id)
        newly_processed += 1

    processed["processed_race_ids"] = sorted(processed_set)
    MAX_PROCESSED = 5000
    if len(processed["processed_race_ids"]) > MAX_PROCESSED:
        processed["processed_race_ids"] = processed["processed_race_ids"][-MAX_PROCESSED:]

    _save_json(records_path, records)
    _save_json(processed_path, processed)
    if newly_processed:
        print(f"[INFO] 直近の調子（自前集計）: 新たに{newly_processed}レース分を集計しました（累計{len(records)}選手）。")
    return records, newly_processed


def get_form_trend(records, name):
    """
    選手の直近の調子を判定する。データ不足（MIN_RACES_FOR_TREND未満）ならNone。
    直近3走の平均着順 と その前3走の平均着順 を比べて、上昇/下降/安定を判定する
    （着順は数字が小さいほど良いので、prev - last が正なら好転＝上昇）。
    戻り値: {"trend": "up"|"down"|"flat", "avg_last3":, "avg_prev3":, "races_tracked":}
    """
    entry = records.get(name)
    if not entry or len(entry["recent"]) < MIN_RACES_FOR_TREND:
        return None
    recent = entry["recent"]
    last3 = recent[-3:]
    prev3 = recent[-6:-3]
    avg_last = sum(r["finish"] for r in last3) / 3
    avg_prev = sum(r["finish"] for r in prev3) / 3
    diff = avg_prev - avg_last
    if diff >= 0.75:
        trend = "up"
    elif diff <= -0.75:
        trend = "down"
    else:
        trend = "flat"
    return {"trend": trend, "avg_last3": avg_last, "avg_prev3": avg_prev,
            "diff": diff, "races_tracked": len(recent)}


def form_multiplier(trend_info, strength=0.08):
    """
    get_form_trend() の結果から、1着率に掛ける倍率を計算する。
    着順の改善幅（diff、最大で概ね±4程度を想定）を正規化してstrengthの範囲で反映する。
    データが無ければ1.0（補正なし）。
    """
    if not trend_info:
        return 1.0
    normalized = max(-1.0, min(1.0, trend_info["diff"] / 4.0))
    return 1.0 + normalized * strength
