# -*- coding: utf-8 -*-
"""
競輪の締切前オッズを定期的に記録する(10分おき、wt_odds_live.yml から呼ぶ)。

対象: 今日のレース(docs/_race_board.json、買うべきレースの生成時に作る)のうち、締切まで 0〜65分のもの。
     10分おきなので、1レースにつき締切の約60・50・40・30・20・10分前と直前の 最大7回 記録される。
記録: 全券種の全組のオッズ(2車複・2車単・ワイド・3連複・3連単)と人気順を、1回1行で
     wt_live_YYYYMMDD.jsonl.gz に追記する(リリース wt-odds-live に置く。リポジトリは太らせない)。
     行の中身: url, venue, race_no, close_at, start_at, ts(取得時刻), mins(締切まで何分), odds{券種: [[組, オッズ, 人気]...]}
使い道: 締切前オッズで ルールD(3連単10〜30倍)・万車率 を検証し直す、オッズの動きを見る。

使い方(scripts/ で): python wt_odds_snapshot.py --out-dir ../live
"""
import argparse
import datetime
import gzip
import json
import os
import sys
import time
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wt_backfill import ODDS_TYPES, get_state, queries  # noqa: E402

JST = ZoneInfo("Asia/Tokyo")
DOCS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs")
WINDOW_MIN = 65


def due(board, now_ts, window=WINDOW_MIN):
    out = []
    for b in board:
        ca = b.get("close_at") or b.get("start_at")
        if ca and 0 < ca - now_ts <= window * 60:
            out.append(b)
    return out


def extract(O):
    """FETCH_KEIRIN_RACE_ODDS -> {券種: [[組, オッズ, 人気], ...]}(ワイドは [組, 下限, 上限, 人気])"""
    out = {}
    for t, name in ODDS_TYPES.items():
        L = (O or {}).get(t) or []
        if t == "quinellaPlace":
            out[name] = [["-".join(map(str, x["key"])), x.get("minOdds"), x.get("maxOdds"), x.get("popularityOrder")]
                         for x in L if not x.get("absent")]
        else:
            out[name] = [["-".join(map(str, x["key"])), x.get("odds"), x.get("popularityOrder")] for x in L if not x.get("absent")]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=os.path.join(DOCS, "..", "live"))
    a = ap.parse_args()
    now = datetime.datetime.now(JST)
    try:
        with open(os.path.join(DOCS, "_race_board.json"), encoding="utf-8") as f:
            b = json.load(f)
    except (OSError, ValueError):
        print("[INFO] _race_board.json が無いので何もしません")
        return
    if b.get("date") != now.date().isoformat():
        print(f"[INFO] 今日の一覧がまだありません({b.get('date')})")
        return
    races = due(b.get("races") or [], now.timestamp())
    print(f"[INFO] 締切まで{WINDOW_MIN}分以内のレース: {len(races)}")
    if not races:
        return
    os.makedirs(a.out_dir, exist_ok=True)
    path = os.path.join(a.out_dir, f"wt_live_{now:%Y%m%d}.jsonl.gz")
    n_ok = 0
    with gzip.open(path, "at", encoding="utf-8") as f:   # 既存のファイルに追記(gzipは追記しても読める)
        for r in races:
            try:
                st, _ = get_state(r["url"])
                O = queries(st).get("FETCH_KEIRIN_RACE_ODDS") or {}
            except Exception as e:  # noqa: BLE001
                print(f"[WARN] {r['venue']}{r['race_no']}R: {e}")
                continue
            od = extract(O)
            if not od.get("3連単"):
                continue
            ts = time.time()
            ca = r.get("close_at") or r.get("start_at")
            f.write(json.dumps(dict(url=r["url"], venue=r["venue"], slug=r.get("slug"), race_no=r["race_no"],
                                    close_at=r.get("close_at"), start_at=r.get("start_at"), ts=int(ts),
                                    mins=round((ca - ts) / 60, 1), final=bool(O.get("finalOdds")), odds=od),
                               ensure_ascii=False) + "\n")
            n_ok += 1
            time.sleep(0.5)
    print(f"[INFO] {n_ok}レースのオッズを {path} に記録しました")


if __name__ == "__main__":
    main()
