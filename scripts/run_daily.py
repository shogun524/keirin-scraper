# -*- coding: utf-8 -*-
"""
毎朝実行するメインスクリプト。
1. 本日開催のレースを全てスクレイピング
2. 各レースをAIモデルで計算
3. 前日以前に生成された競輪場フォルダを削除し（古いデータが残らないように）、
   docs/index.html（競輪場一覧）と docs/{venue}/index.html（レース一覧・タブ切替）を書き出す
   （GitHub Pagesで公開される）
"""

import os
import shutil
import datetime
import traceback
from zoneinfo import ZoneInfo

from scraper import fetch_all_todays_races
from model import predict_race
from report import render_index, render_venue_page, VENUE_NAMES

JST = ZoneInfo("Asia/Tokyo")
DOCS_DIR = os.path.join(os.path.dirname(__file__), "..", "docs")


def clean_stale_venue_dirs(active_venues):
    """
    docs/ 以下にある競輪場フォルダのうち、本日の開催に含まれないものを削除する。
    （前日以前のデータがそのまま残って古い予想が表示され続けるのを防ぐ）
    """
    if not os.path.isdir(DOCS_DIR):
        return
    all_known_slugs = set(VENUE_NAMES.keys())
    removed = []
    for name in os.listdir(DOCS_DIR):
        path = os.path.join(DOCS_DIR, name)
        if not os.path.isdir(path):
            continue
        if name in all_known_slugs and name not in active_venues:
            shutil.rmtree(path)
            removed.append(name)
    if removed:
        print(f"[INFO] 本日開催していない競輪場の古いフォルダを削除しました: {removed}")


def main():
    # GitHub Actionsのランナーは基本的にUTCで動くため、日本時間の「今日」を明示的に計算する
    today = datetime.datetime.now(JST).date()
    now_str = datetime.datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    print(f"[INFO] {today} (JST) のレースを取得します...（実行時刻: {now_str}）")

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

    os.makedirs(DOCS_DIR, exist_ok=True)

    by_venue = {}
    for rd in all_race_data:
        by_venue.setdefault(rd["race_info"]["venue"], []).append(rd)

    # 本日開催していない競輪場の古いフォルダ（前日以前のデータ）を先に削除
    clean_stale_venue_dirs(set(by_venue.keys()))

    # トップページ（競輪場一覧）
    index_html = render_index(all_race_data, today)
    with open(os.path.join(DOCS_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_html)
    print("[INFO] docs/index.html を書き出しました。")

    # 競輪場ごとのページ（レース一覧・タブ切替）
    for venue, races_for_venue in by_venue.items():
        venue_dir = os.path.join(DOCS_DIR, venue)
        os.makedirs(venue_dir, exist_ok=True)
        venue_html = render_venue_page(venue, races_for_venue, today)
        with open(os.path.join(venue_dir, "index.html"), "w", encoding="utf-8") as f:
            f.write(venue_html)
        print(f"[INFO] docs/{venue}/index.html を書き出しました。")

    if len(races) == 0:
        print("[WARN] 取得できたレースが0件でした。サイト構造が変わっている可能性があります。")
        # 0件でもワークフロー自体は失敗させない（毎日の通知を止めないため）


if __name__ == "__main__":
    main()
