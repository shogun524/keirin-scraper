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
from course_records import update_course_records, get_course_record

JST = ZoneInfo("Asia/Tokyo")
DOCS_DIR = os.path.join(os.path.dirname(__file__), "..", "docs")


ODDS_HISTORY_PATH = os.path.join(DOCS_DIR, "_odds_history.json")
ODDS_HISTORY_MAX_SNAPSHOTS = 30  # 1レースあたり保持するスナップショット数の上限（1時間おき実行なら約1.25日分）


def update_odds_history(all_race_data, today, now_str):
    """
    投票の盛り上がり具合（発売票数）を毎時記録し、時系列データとして蓄積する。
    完全な3連単オッズの組み合わせ表はまだ取得できていないが（scraper.extract_betting_volume
    のdocstring参照）、発売票数の推移だけでも「投票が伸びているレース＝注目度が高い
    レース」の簡易な指標として使える。将来的にオッズの完全な組み合わせ表が取得できる
    ようになった際、同じ仕組みでそちらも時系列蓄積できるよう汎用的な構造にしてある。
    戻り値: {race_key: {"venue":,"race_no":,"venue_name":,"trend":{...}}, ...}（当日分のみ）
    """
    history = {}
    if os.path.exists(ODDS_HISTORY_PATH):
        try:
            with open(ODDS_HISTORY_PATH, "r", encoding="utf-8") as f:
                history = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[WARN] docs/_odds_history.json の読み込みに失敗したため初期化します: {e}")
            history = {}

    today_str = today.isoformat()
    updated_count = 0
    for rd in all_race_data:
        info = rd["race_info"]
        vol = info.get("betting_volume")
        if not vol:
            continue
        race_key = f"{info['venue']}_{info['race_no']}_{today_str}"
        entry = history.setdefault(race_key, {
            "venue": info["venue"], "race_no": info["race_no"], "date": today_str, "snapshots": [],
        })
        snapshots = entry["snapshots"]
        # 直近のスナップショットと票数が同じ（サイト側オッズがまだ更新されていない）場合は
        # 記録を増やさない（1時間おき実行なので、変化が無い間は無駄にファイルを太らせない）
        if not snapshots or snapshots[-1]["ticket_total"] != vol["ticket_total"]:
            snapshots.append({"ts": now_str, "ticket_total": vol["ticket_total"], "as_of": vol.get("as_of")})
            updated_count += 1
        if len(snapshots) > ODDS_HISTORY_MAX_SNAPSHOTS:
            entry["snapshots"] = snapshots[-ODDS_HISTORY_MAX_SNAPSHOTS:]

    # 当日分以外（前日以前）のレースは削除し、ファイルサイズが際限なく増えないようにする
    history = {k: v for k, v in history.items() if v.get("date") == today_str}

    with open(ODDS_HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    print(f"[INFO] docs/_odds_history.json を更新しました（新規スナップショット{updated_count}件、当日{len(history)}レース分）。")

    # 各レースの投票トレンド（本日の最初のスナップショット比でどれだけ伸びたか）を返す
    trends = {}
    for race_key, entry in history.items():
        snaps = entry["snapshots"]
        if len(snaps) < 2:
            continue
        first, latest = snaps[0]["ticket_total"], snaps[-1]["ticket_total"]
        if first > 0:
            trends[race_key] = {
                "first": first, "latest": latest,
                "growth_pct": (latest - first) / first * 100,
                "snapshot_count": len(snaps),
            }
    return trends


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
            result = predict_race(race["racers"], race["line_prediction_text"], venue_slug=race["race_info"]["venue"])
        except Exception as e:
            print(f"[WARN] {race['race_info']['venue']} {race['race_info']['race_no']}R の計算に失敗: {e}")
            result = None
        all_race_data.append({"race_info": race["race_info"], "prediction": result})

    os.makedirs(DOCS_DIR, exist_ok=True)

    try:
        odds_trends = update_odds_history(all_race_data, today, now_str)
    except Exception as e:
        print(f"[WARN] オッズ履歴（発売票数）の記録に失敗しました: {e}")
        odds_trends = {}
    for rd in all_race_data:
        info = rd["race_info"]
        race_key = f"{info['venue']}_{info['race_no']}_{today.isoformat()}"
        info["odds_trend"] = odds_trends.get(race_key)

    # 当地成績の自前集計：締切を過ぎている（＝結果が出ている可能性が高い）レースだけ
    # 結果ページの取得を試みる。締切前のレースに毎回アクセスするのを避けるための判定。
    now_hm = datetime.datetime.now(JST).strftime("%H:%M")
    finished_candidates = [
        {"venue": race["race_info"]["venue"], "race_no": race["race_info"]["race_no"], "url": race["url"]}
        for race in races
        if race["race_info"].get("deadline") and race["race_info"]["deadline"] < now_hm
    ]
    try:
        course_records, _ = update_course_records(DOCS_DIR, finished_candidates, now_str)
    except Exception as e:
        print(f"[WARN] 当地成績（自前集計）の更新に失敗しました: {e}")
        course_records = {}

    for rd in all_race_data:
        if not rd["prediction"]:
            continue
        venue = rd["race_info"]["venue"]
        for row in rd["prediction"]["rows"]:
            row["course_record"] = get_course_record(course_records, row["name"], venue)

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
