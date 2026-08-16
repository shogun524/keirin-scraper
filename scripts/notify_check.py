# -*- coding: utf-8 -*-
"""
締切が近づいているレースを検出し、ntfy.sh経由でスマホにプッシュ通知を送るスクリプト。

仕組み：
- run_daily.py が書き出した docs/_deadlines.json（今日のレース一覧・締切時刻）を読む
  （毎回スクレイピングし直すと負荷が大きいため、軽量なキャッシュファイルだけを見る）
- 現在時刻（JST）から見て、締切が「あと8〜13分」のレースを探す
- 該当レースがあれば ntfy.sh にHTTP POSTして通知を送る
- 同じレースに何度も通知しないよう、送信済みレースIDを docs/_notified.json に記録する

事前準備：
- スマホに ntfy アプリ（iOS/Android、無料）をインストール
- .github/workflows/notify.yml の NTFY_TOPIC を、他人に推測されにくいランダムな文字列に変更する
  （例: "keirin-alert-8f3ac2b1"）
- ntfyアプリで、同じトピック名を「購読（Subscribe to topic）」する
"""

import os
import json
import datetime
import urllib.request
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
DOCS_DIR = os.path.join(os.path.dirname(__file__), "..", "docs")
DEADLINES_PATH = os.path.join(DOCS_DIR, "_deadlines.json")
NOTIFIED_PATH = os.path.join(DOCS_DIR, "_notified.json")

# 締切のこの分数前から通知対象にする（窓を広めに取り、5分間隔チェックの取りこぼしを防ぐ）
NOTIFY_WINDOW_MIN = 8
NOTIFY_WINDOW_MAX = 13

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}" if NTFY_TOPIC else None

PAGES_BASE_URL = os.environ.get("PAGES_BASE_URL", "")  # 例: https://shogun524.github.io/keirin-scraper


def minutes_until(deadline_str, now):
    try:
        h, m = map(int, deadline_str.split(":"))
    except (ValueError, AttributeError):
        return None
    deadline_minutes = h * 60 + m
    now_minutes = now.hour * 60 + now.minute
    return deadline_minutes - now_minutes


def send_notification(race):
    if not NTFY_URL:
        print("[WARN] NTFY_TOPIC が設定されていないため通知をスキップします。")
        return False
    # ntfyのHTTPヘッダーはASCII前提のため、Titleは半角英数字に留め、
    # 日本語の詳細はリクエストボディ（UTF-8）側に入れる
    title_ascii = f"{race['venue']} {race['race_no']}R deadline soon"
    body = f"{race['venue_name']}競輪 {race['race_no']}R\n締切 {race['deadline']}（あと約{race['mins']}分）"
    link = f"{PAGES_BASE_URL.rstrip('/')}/{race['venue']}/index.html" if PAGES_BASE_URL else None

    headers = {
        "Title": title_ascii,
        "Priority": "high",
        "Tags": "rotating_light",
    }
    if link:
        headers["Click"] = link

    req = urllib.request.Request(
        NTFY_URL,
        data=body.encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"[INFO] 通知送信: {title_ascii} / {body} (status={resp.status})")
        return True
    except Exception as e:
        print(f"[WARN] 通知送信に失敗しました: {e}")
        return False


def main():
    now = datetime.datetime.now(JST)
    today_str = now.date().isoformat()

    if not os.path.exists(DEADLINES_PATH):
        print("[INFO] docs/_deadlines.json がまだ存在しません（本日分の生成前）。スキップします。")
        return

    with open(DEADLINES_PATH, "r", encoding="utf-8") as f:
        cache = json.load(f)

    if cache.get("date") != today_str:
        print(f"[INFO] キャッシュの日付({cache.get('date')})が今日({today_str})と異なるためスキップします。")
        return

    notified = {}
    if os.path.exists(NOTIFIED_PATH):
        try:
            with open(NOTIFIED_PATH, "r", encoding="utf-8") as f:
                notified = json.load(f)
        except (json.JSONDecodeError, OSError):
            notified = {}
    if notified.get("date") != today_str:
        notified = {"date": today_str, "sent": []}
    sent_set = set(notified.get("sent", []))

    targets = []
    for r in cache.get("races", []):
        mins = minutes_until(r.get("deadline"), now)
        if mins is None:
            continue
        race_key = f"{r['venue']}_{r['race_no']}"
        if NOTIFY_WINDOW_MIN <= mins <= NOTIFY_WINDOW_MAX and race_key not in sent_set:
            r["mins"] = mins
            r["key"] = race_key
            targets.append(r)

    print(f"[INFO] 現在時刻 {now.strftime('%H:%M')} JST / 通知対象レース {len(targets)} 件")

    any_sent = False
    for r in targets:
        if send_notification(r):
            sent_set.add(r["key"])
            any_sent = True

    if any_sent:
        notified["sent"] = sorted(sent_set)
        with open(NOTIFIED_PATH, "w", encoding="utf-8") as f:
            json.dump(notified, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
