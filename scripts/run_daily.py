# -*- coding: utf-8 -*-
"""
1時間おきに実行されるメインスクリプト（並び予想が日中〜夕方にかけて随時
公開されるため、1回の朝実行だけでは間に合わないレースがある。1時間おきに
再実行することで、後から公開された分も次の実行で拾えるようにしている）。
1. 本日開催のレースを全てスクレイピング
2. 各レースをAIモデルで計算
3. 前日以前に生成された競輪場フォルダを削除し（古いデータが残らないように）、
   docs/index.html（競輪場一覧）と docs/{venue}/index.html（レース一覧・タブ切替）を書き出す
   （GitHub Pagesで公開される）
"""

import os
import sys
import json
import shutil
import datetime
import traceback
from zoneinfo import ZoneInfo

# ログ出力（GitHub Actionsのコンソール）が実行環境のロケール設定次第で
# UTF-8以外にフォールバックし、日本語が文字化けして見えることがある。
# ここで明示的にUTF-8へ固定し、print() の表示自体が原因で「文字化けしている
# ように見える」ケースを切り分けられるようにする。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass  # Python 3.6以前など reconfigure が無い環境では何もしない

from scraper import fetch_all_todays_races
from model import predict_race
from report import render_index, render_venue_page, render_venues_page, render_venue_bank_page, VENUE_NAMES

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

    # 全競輪場データページ（バンク情報。物理的な施設特性なので日々変わらない）
    venues_html = render_venues_page(today)
    with open(os.path.join(DOCS_DIR, "venues.html"), "w", encoding="utf-8") as f:
        f.write(venues_html)
    print("[INFO] docs/venues.html を書き出しました。")

    # 競輪場ごとのページ（レース一覧・タブ切替）
    for venue, races_for_venue in by_venue.items():
        venue_dir = os.path.join(DOCS_DIR, venue)
        os.makedirs(venue_dir, exist_ok=True)
        venue_html = render_venue_page(venue, races_for_venue, today)
        with open(os.path.join(venue_dir, "index.html"), "w", encoding="utf-8") as f:
            f.write(venue_html)
        print(f"[INFO] docs/{venue}/index.html を書き出しました。")

    # 全43競輪場のバンクデータページ（本日開催していない場も含め、常に全場分を書き出す。
    # clean_stale_venue_dirs で本日非開催の場のフォルダごと削除されるため、その後に
    # 改めて全場分を用意することでリンク切れを防ぐ）
    for venue in VENUE_NAMES:
        venue_dir = os.path.join(DOCS_DIR, venue)
        os.makedirs(venue_dir, exist_ok=True)
        bank_html = render_venue_bank_page(venue, today)
        with open(os.path.join(venue_dir, "bank.html"), "w", encoding="utf-8") as f:
            f.write(bank_html)
    print(f"[INFO] docs/{{venue}}/bank.html を全{len(VENUE_NAMES)}場分書き出しました。")

    # 通知チェック用の軽量な締切一覧キャッシュ（毎回スクレイピングし直さずに済むように）
    deadlines_cache = [
        {
            "venue": rd["race_info"]["venue"],
            "venue_name": VENUE_NAMES.get(rd["race_info"]["venue"], rd["race_info"]["venue"]),
            "race_no": rd["race_info"]["race_no"],
            "deadline": rd["race_info"].get("deadline"),
        }
        for rd in all_race_data if rd["race_info"].get("deadline")
    ]
    with open(os.path.join(DOCS_DIR, "_deadlines.json"), "w", encoding="utf-8") as f:
        json.dump({"date": today.isoformat(), "races": deadlines_cache}, f, ensure_ascii=False, indent=2)
    print(f"[INFO] docs/_deadlines.json を書き出しました（{len(deadlines_cache)}件）。")

    if len(races) == 0:
        print("[WARN] 取得できたレースが0件でした。サイト構造が変わっている可能性があります。")
        # 0件でもワークフロー自体は失敗させない（毎日の通知を止めないため）


if __name__ == "__main__":
    main()
