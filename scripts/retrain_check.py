# -*- coding: utf-8 -*-
"""
モデルの自動再学習トリガー。

現在の予測モデル（model.py の MODEL 辞書）は、2020〜2025年のデータでオフライン
学習した係数をハードコードしたもので、このリポジトリ自体には再学習パイプライン
（特徴量抽出〜ロジスティック回帰フィット〜係数書き出し）はまだ組み込まれていない。
本モジュールはその再学習パイプラインそのものではなく、「そろそろ再学習した方が
良いタイミングかどうか」を自動検知して知らせる入口（トリガー）を提供する。

判定基準は2つ：
  1. 自前集計（当地成績・対戦履歴・直近の調子）で新たに取り込んだレース結果数が
     一定件数（RACE_COUNT_THRESHOLD）貯まったとき
     → モデルが学習した頃と比べて選手層・脚質傾向が変化してきた可能性がある
  2. 前回フラグを立ててから一定日数（DAYS_THRESHOLD）が経過したとき
     → データ量に関わらず、季節・年度が変わる節目では見直す価値がある

条件を満たすと docs/_retrain_flag.json にフラグを書き出す（この時点ではまだ
何も再学習しない）。運用者はこのフラグを見て、race_x.pkl/race_y.pkl 相当の
最新データで再学習スクリプトを走らせ、完了したら acknowledge_retrain() を呼んで
カウンタをリセットする、という運用を想定している。
"""

import os
import json
import datetime

RACE_COUNT_THRESHOLD = 300  # 新規に取り込んだレース結果数がこれを超えたらフラグ
DAYS_THRESHOLD = 60  # 前回フラグ（または初回運用開始）からの経過日数がこれを超えたらフラグ


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


def _days_between(date_str_a, date_str_b):
    a = datetime.date.fromisoformat(date_str_a)
    b = datetime.date.fromisoformat(date_str_b)
    return abs((b - a).days)


def check_retrain_trigger(docs_dir, newly_processed_race_count, today_str,
                           race_threshold=RACE_COUNT_THRESHOLD, days_threshold=DAYS_THRESHOLD):
    """
    newly_processed_race_count: 今回の実行で course_records（または同等の自前集計）が
      新たに取り込んだレース結果数（update_course_records の戻り値の newly_processed）
    today_str: 実行日（"YYYY-MM-DD"）
    戻り値: (status_dict, flagged: bool)
      flagged=True の場合、docs/_retrain_flag.json が書き出されている。
    """
    status_path = os.path.join(docs_dir, "_retrain_status.json")
    flag_path = os.path.join(docs_dir, "_retrain_flag.json")

    status = _load_json(status_path, {
        "cumulative_new_races": 0,
        "last_baseline_date": today_str,  # カウント開始／前回フラグの起点日
        "last_flagged_at": None,
    })

    status["cumulative_new_races"] += newly_processed_race_count

    days_elapsed = _days_between(status["last_baseline_date"], today_str)
    reasons = []
    if status["cumulative_new_races"] >= race_threshold:
        reasons.append(f"新規レース結果が{status['cumulative_new_races']}件蓄積（閾値{race_threshold}件）")
    if days_elapsed >= days_threshold:
        reasons.append(f"前回の基準日から{days_elapsed}日経過（閾値{days_threshold}日）")

    flagged = bool(reasons)
    if flagged:
        flag_data = {
            "flagged_at": today_str,
            "reasons": reasons,
            "cumulative_new_races": status["cumulative_new_races"],
            "days_elapsed": days_elapsed,
            "message": (
                "モデル（model.py のハードコード係数）の再学習を検討する時期です。"
                "最新の race_x.pkl/race_y.pkl 相当のデータで再フィットし、"
                "係数を更新したら acknowledge_retrain() でこのフラグをリセットしてください。"
            ),
        }
        _save_json(flag_path, flag_data)
        status["last_flagged_at"] = today_str
        status["last_baseline_date"] = today_str
        status["cumulative_new_races"] = 0
        print(f"[INFO] 再学習トリガー: 条件を満たしたためフラグを立てました（{', '.join(reasons)}）。")

    _save_json(status_path, status)
    return status, flagged


def acknowledge_retrain(docs_dir):
    """
    再学習を実施した後に呼び出し、docs/_retrain_flag.json を削除してフラグを解消する。
    このリポジトリの自動実行フローからは呼ばれない（運用者が手動で実施した後に使う想定）。
    """
    flag_path = os.path.join(docs_dir, "_retrain_flag.json")
    if os.path.exists(flag_path):
        os.remove(flag_path)
        return True
    return False
