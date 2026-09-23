# -*- coding: utf-8 -*-
"""
当地成績の自前集計（過去成績×当地）
サイト側には「この選手がこの競輪場で過去どのくらいの成績を残しているか」という
データが無いため、毎時の自動実行のたびに終了済みレースの結果（着順・決まり手）を
取得し、選手名×競輪場ごとに自前で積み上げていく。

十分な件数が貯まるまでは（運用開始からしばらくの間）ほぼ空のデータになるため、
すぐには予測モデルには組み込まず、まずは記録の仕組みを用意し、貯まったデータを
参考情報として表示することから始める。

データは docs/_course_records.json （選手×競輪場ごとの集計）と
docs/_course_records_processed.json （二重集計防止用の処理済みレースID一覧）
の2ファイルに保存する。
"""

import os
import json

from scraper import extract_race_id_from_url, fetch_race_result

KIMARITE_KEYS = ["逃", "捲", "差", "マ"]


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


def _record_key(name, venue):
    return f"{name}__{venue}"


def update_course_records(docs_dir, races_with_deadline_passed, now_str):
    """
    races_with_deadline_passed: [{"venue":, "race_no":, "url":}, ...]
      （締切を過ぎている＝結果が出ている可能性が高いレースのみを渡すこと）
    戻り値: (records, newly_processed_count)
    """
    records_path = os.path.join(docs_dir, "_course_records.json")
    processed_path = os.path.join(docs_dir, "_course_records_processed.json")

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
            print(f"[WARN] {venue} {race['race_no']}R: 結果の取得に失敗しました: {e}")
            continue

        if not result:
            continue  # まだ結果が確定していない（正常系。次回の実行で再挑戦する）

        for row in result:
            name = row["name"]
            key = _record_key(name, venue)
            entry = records.setdefault(key, {
                "name": name, "venue": venue, "races": 0, "wins": 0, "top3": 0,
                "kimarite": {k: 0 for k in KIMARITE_KEYS},
            })
            entry["races"] += 1
            if row["finish"] == 1:
                entry["wins"] += 1
            if row["finish"] <= 3:
                entry["top3"] += 1
            if row.get("kimarite") in KIMARITE_KEYS:
                entry["kimarite"][row["kimarite"]] += 1

        processed_set.add(race_id)
        newly_processed += 1

    processed["processed_race_ids"] = sorted(processed_set)
    # 処理済みIDリストが際限なく増えないよう、直近の一定件数だけ保持する
    MAX_PROCESSED = 5000
    if len(processed["processed_race_ids"]) > MAX_PROCESSED:
        processed["processed_race_ids"] = processed["processed_race_ids"][-MAX_PROCESSED:]

    _save_json(records_path, records)
    _save_json(processed_path, processed)
    if newly_processed:
        print(f"[INFO] 当地成績（自前集計）: 新たに{newly_processed}レース分を集計しました（累計{len(records)}選手×場）。")
    return records, newly_processed


def get_course_record(records, name, venue):
    """特定の選手×競輪場の当地成績を取得する。データが無ければNone。"""
    entry = records.get(_record_key(name, venue))
    if not entry or entry["races"] < 3:
        # サンプル数が少なすぎる（3走未満）場合は、参考情報としても不安定なため表示しない
        return None
    return entry
