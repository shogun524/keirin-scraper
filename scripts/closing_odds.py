# -*- coding: utf-8 -*-
"""
締切の直前オッズを記録する（CLVの比較先）。10分おきの別ワークフロー（closing.yml）から呼ぶ。

流れ
  1) docs/_deadlines.json から「締切まであと1〜12分」のレースを探す（無ければ何もしない＝サイトに取りに行かない）
  2) winticket から3連単オッズを取得（run_daily と同じ winticket_source.fetch_odds_map）
  3) docs/_buy_log.json に記録のあるレースだけ、記録済みの買い目（最初に見た40点＋最新の40点）のオッズを
     docs/_close_odds.json に保存。締切より前に取れた値だけを使い、次の実行でさらに締切に近い値で上書きする

注意: 締切のあと（minutes_until < 1）は記録しない。結果が確定したあとのオッズを混ぜないため。
"""
import datetime
import json
import os
from zoneinfo import ZoneInfo

import buy_stats

JST = ZoneInfo("Asia/Tokyo")
HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "docs")
CLOSE_NAME = "_close_odds.json"
WINDOW_MIN, WINDOW_MAX = 1, 12   # 締切の何分前〜何分前を対象にするか
KEEP_DAYS = 60


def load(docs=DOCS):
    try:
        with open(os.path.join(docs, CLOSE_NAME), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save(docs, data):
    with open(os.path.join(docs, CLOSE_NAME), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))


def minutes_until(deadline, now):
    try:
        h, m = map(int, deadline.split(":"))
    except (ValueError, AttributeError):
        return None
    return h * 60 + m - (now.hour * 60 + now.minute)


def due_races(deadlines, now, lo=WINDOW_MIN, hi=WINDOW_MAX):
    """deadlines: _deadlines.json の races。締切が lo〜hi 分先のレースだけ返す。"""
    out = []
    for r in deadlines or []:
        m = minutes_until(r.get("deadline"), now)
        if m is not None and lo <= m <= hi:
            out.append(r)
    return out


def snapshot(entry, odds):
    """entry の買い目（最初＋最新）について、odds {(a,b,c): 倍率} から {"a-b-c": 倍率} を作る。"""
    keys = [k for k, *_ in entry.get("items", [])]
    keys += [k for k, *_ in (entry.get("first") or {}).get("items", [])]
    out = {}
    for k in dict.fromkeys(keys):
        try:
            t = tuple(int(x) for x in k.split("-"))
        except ValueError:
            continue
        if odds.get(t):
            out[k] = odds[t]
    return out


def update(docs, today, now, fetch=None):
    """戻り値: 記録・更新したレース数。fetch は odds 取得関数（テスト用に差し替え可）。"""
    try:
        with open(os.path.join(docs, "_deadlines.json"), encoding="utf-8") as f:
            dl = json.load(f)
    except (OSError, ValueError):
        return 0
    if dl.get("date") != today.isoformat():
        return 0
    due = due_races(dl.get("races"), now)
    if not due:
        return 0
    log = buy_stats.load(docs)
    targets = []
    for r in due:
        k = buy_stats._key(today.isoformat(), r["venue"], r["race_no"])
        if k in log:
            targets.append((r, k))
    if not targets:
        return 0
    if fetch is None:
        import winticket_source
        fetch = winticket_source.fetch_odds_map
    odds_map = fetch(today)
    data = load(docs)
    n = 0
    hm = f"{now.hour:02d}:{now.minute:02d}"
    for r, k in targets:
        od = odds_map.get((r["venue"], r["race_no"]))
        if not od:
            continue
        snap = snapshot(log[k], od)
        if len(snap) < 10:
            continue
        data[k] = {"ts": hm, "deadline": r["deadline"], "odds": snap}
        n += 1
    cutoff = (today - datetime.timedelta(days=KEEP_DAYS)).isoformat()
    for k in [k for k in data if k[:10] < cutoff]:
        del data[k]
    save(docs, data)
    print(f"[INFO] 締切直前オッズを{n}レース分記録しました（対象{len(targets)}レース）。")
    return n


def main():
    now = datetime.datetime.now(JST)
    update(DOCS, now.date(), now)


if __name__ == "__main__":
    main()
