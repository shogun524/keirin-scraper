# -*- coding: utf-8 -*-
"""
毎朝実行するメインスクリプト。
1. 本日開催のレースを全てスクレイピング
2. 各レースをAIモデルで計算
3. docs/index.html にレポートを書き出す（GitHub Pagesで公開される）
"""

import sys
import datetime
import traceback
from zoneinfo import ZoneInfo

from scraper import fetch_all_todays_races
from model import predict_race
from report import render_report

JST = ZoneInfo("Asia/Tokyo")

import os
def main():
    # GitHub Actionsのランナーは基本的にUTCで動くため、日本時間の「今日」を明示的に計算する
    today = datetime.datetime.now(JST).date()
    print(f"[INFO] {today} (JST) のレースを取得します...")

    try:
        races = fetch_all_todays_races(today)
    except Exception as e:
        print(f"[ERROR] レース取得中にエラーが発生しました: {e}")
        traceback.print_exc()
        races = []

    print(f"[INFO] {len(races)} レース分のデータを取得しました。")

    all_race_data = []
    for race in races:
        try:
            result = predict_race(race["racers"], race["line_prediction_text"])
        except Exception as e:
            print(f"[WARN] {race['race_info']['venue']} {race['race_info']['race_no']}R の計算に失敗: {e}")
            result = None
        all_race_data.append({"race_info": race["race_info"], "prediction": result})

    html = render_report(all_race_data, today)

   docs_path = os.path.join(os.path.dirname(__file__), "..", "docs", "index.html")
   with open(docs_path, "w", encoding="utf-8") as f:

    print("[INFO] docs/index.html を書き出しました。")

    if len(races) == 0:
        print("[WARN] 取得できたレースが0件でした。サイト構造が変わっている可能性があります。")
        # 0件でもワークフロー自体は失敗させない（毎日の通知を止めないため）


if __name__ == "__main__":
    main()
