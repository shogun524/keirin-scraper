# -*- coding: utf-8 -*-
"""
選手間の相性（対戦履歴）の自前集計。
course_records.py（当地成績）と同じ考え方で、毎時の自動実行のたびに終了済み
レースの結果を取得し、「同じレースに出走した選手ペア」ごとに、どちらが前に
着順を取ったか（勝敗）を積み上げていく。

当地成績は「選手×競輪場」単位だが、こちらは「選手×選手」単位。同じライン
（師弟関係・地区）の選手同士は元々ライン予想である程度加味されているため、
ここでは特に「よく当たる決まり手を持つ相手に対して弱い／強い」といった、
ライン予想だけでは拾いきれない個体差の把握を主目的とする。

データは docs/_rivalry_records.json （選手ペアごとの対戦成績）と
docs/_rivalry_records_processed.json （二重集計防止用の処理済みレースID一覧）
の2ファイルに保存する。course_records.py とは別の処理済みIDリストを持つため、
同じ結果ページに対して2回HTTPリクエストが飛ぶが（course_records用・
rivalry_records用で1回ずつ）、両モジュールを疎結合に保ち、片方の不具合が
もう片方に波及しないようにするためのトレードオフとしている。
"""

import os
import json
import itertools

from scraper import extract_race_id_from_url, fetch_race_result

MIN_RACES_FOR_EDGE = 2  # このペアの対戦数がこれ未満なら、ノイズが大きいため補正に使わない
MAX_OPPONENT_HISTORY_USED = 20  # 1レースあたり参照する対戦相手数の上限（保険。通常は最大8）


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


def _pair_key(name_a, name_b):
    a, b = sorted([name_a, name_b])
    return f"{a}__{b}"


def update_rivalry_records(docs_dir, races_with_deadline_passed, now_str):
    """
    races_with_deadline_passed: [{"venue":, "race_no":, "url":}, ...]
      （締切を過ぎている＝結果が出ている可能性が高いレースのみを渡すこと。
       course_records.update_course_records に渡すものと同じリストでよい）
    戻り値: (records, newly_processed_count)
    """
    records_path = os.path.join(docs_dir, "_rivalry_records.json")
    processed_path = os.path.join(docs_dir, "_rivalry_records_processed.json")

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
            print(f"[WARN] {venue} {race['race_no']}R: 対戦履歴用の結果取得に失敗しました: {e}")
            continue

        if not result:
            continue  # まだ結果が確定していない（正常系。次回の実行で再挑戦する）

        # 同じレースに出走した全選手のペアについて、着順の前後関係を記録する
        for ra, rb in itertools.combinations(result, 2):
            if ra["finish"] == rb["finish"]:
                continue  # 同着など、順位が確定できないケースはスキップ
            winner, loser = (ra, rb) if ra["finish"] < rb["finish"] else (rb, ra)
            key = _pair_key(winner["name"], loser["name"])
            entry = records.setdefault(key, {
                "a": sorted([winner["name"], loser["name"]])[0],
                "b": sorted([winner["name"], loser["name"]])[1],
                "races": 0, "a_wins": 0, "b_wins": 0,
            })
            entry["races"] += 1
            if winner["name"] == entry["a"]:
                entry["a_wins"] += 1
            else:
                entry["b_wins"] += 1

        processed_set.add(race_id)
        newly_processed += 1

    processed["processed_race_ids"] = sorted(processed_set)
    MAX_PROCESSED = 5000
    if len(processed["processed_race_ids"]) > MAX_PROCESSED:
        processed["processed_race_ids"] = processed["processed_race_ids"][-MAX_PROCESSED:]

    _save_json(records_path, records)
    _save_json(processed_path, processed)
    if newly_processed:
        print(f"[INFO] 対戦履歴（自前集計）: 新たに{newly_processed}レース分を集計しました（累計{len(records)}ペア）。")
    return records, newly_processed


def _win_rate_of(records, name, opponent):
    """name から見た opponent への勝率。対戦数不足やデータ無しなら None。"""
    entry = records.get(_pair_key(name, opponent))
    if not entry or entry["races"] < MIN_RACES_FOR_EDGE:
        return None
    wins = entry["a_wins"] if entry["a"] == name else entry["b_wins"]
    return wins / entry["races"], entry["races"]


def get_rivalry_summary(records, name, opponent_names):
    """
    出走メンバー（opponent_names、自分自身は除く）に対する対戦成績のサマリーを返す。
    戻り値: None（対戦データが全く無い場合）か、
      {"avg_win_rate": 0-1, "matchups": [{"opponent":, "win_rate":, "races":}, ...]}
      matchups は対戦数が多い順。avg_win_rate はデータのある相手のみの単純平均。
    """
    matchups = []
    for opp in opponent_names[:MAX_OPPONENT_HISTORY_USED]:
        if opp == name:
            continue
        result = _win_rate_of(records, name, opp)
        if result is None:
            continue
        win_rate, races = result
        matchups.append({"opponent": opp, "win_rate": win_rate, "races": races})

    if not matchups:
        return None

    matchups.sort(key=lambda m: -m["races"])
    avg_win_rate = sum(m["win_rate"] for m in matchups) / len(matchups)
    return {"avg_win_rate": avg_win_rate, "matchups": matchups}


def rivalry_multiplier(summary, strength=0.12):
    """
    get_rivalry_summary() の結果から、1着率に掛ける倍率を計算する。
    平均勝率が50%からどれだけ離れているかに応じて ±strength の範囲で補正する
    （bank_tactic_affinity と同じ「基準からの乖離×強さ」の考え方）。
    データが無ければ1.0（補正なし）。
    """
    if not summary:
        return 1.0
    deviation = summary["avg_win_rate"] - 0.5  # -0.5〜+0.5
    return 1.0 + deviation * 2 * strength
