"""
競輪の過去レースのバックフィル(winticket)。

終わったレースのページには、レース前の出走表(競走得点・脚質・ギア・印・コメント・勝敗数)、並び予想、
着順・決まり手、そして全券種の確定オッズ(2車複・2車単・ワイド・3連複・3連単の全組)と的中組の払戻が入っている
(2026-11 の診断で確認)。1レース1回のアクセスで全部取れる。

出力(--out-dir、追記):
  wt_races.csv    : 1レース1行(日付・場・グレード・クラス・種別・距離・周回・頭数・並びの形 など)
  wt_entries.csv  : 1選手1行(レース前の情報 + 着順・決まり手・並びの位置)
  wt_odds.jsonl.gz: 1レース1行。全組の確定オッズと人気、的中組と払戻
  wt_progress.json / wt_days_done.json: 再開用

使い方(scripts/ の親ディレクトリで):
  python scripts/wt_backfill.py 2025-01-01 2026-11-08 --out-dir data --workers 3 --max-minutes 300
終了コード: 0=期間をすべて処理 / 3=途中で打ち切り(再実行で続きから)
"""
import argparse
import csv
import datetime
import gzip
import json
import os
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

BASE = "https://www.winticket.jp/keirin"
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148")
GRADE = {1: "F2", 2: "F1", 3: "G3", 4: "G2", 5: "G1", 6: "GP"}
ODDS_TYPES = {"quinella": "2車複", "exacta": "2車単", "quinellaPlace": "ワイド", "trio": "3連複", "trifecta": "3連単"}
FAIL_STREAK_LIMIT = 30
NO_RESULT_LIMIT = 2  # ページは開けたのに結果が無い過去レース(中止など)は、別々の実行で2回そうなら諦める


class NoResult(Exception):
    """ページは取れたが結果が無い(中止・未確定)。アクセス失敗とは区別する"""

RACE_COLS = ["race_id", "cup_id", "date", "venue_id", "venue_slug", "venue", "cup_name", "grade", "day", "index",
             "duration", "race_no", "class", "race_type", "distance", "lap", "entries", "start_at", "close_at",
             "weather", "wind", "line_type", "line_text", "girls"]
ENTRY_COLS = ["race_id", "car", "bracket", "player_id", "name", "gender", "age", "term", "pref", "cls", "grp",
              "prev_cls", "prev_grp", "gear", "style", "race_point", "mark", "standing", "back", "front_runner",
              "stalker", "deep_closer", "marker", "first", "second", "third", "others", "first_rate", "second_rate",
              "third_rate", "comment", "absent", "line_no", "line_pos", "line_size", "finish", "factor", "accident"]

_local = threading.local()


def session():
    if not hasattr(_local, "s"):
        s = requests.Session()
        s.headers["User-Agent"] = UA
        _local.s = s
    return _local.s


def get_state(url):
    r = session().get(url, timeout=30)
    r.raise_for_status()
    html = r.text
    i = html.find("window.__PRELOADED_STATE__")
    if i < 0:
        raise ValueError("PRELOADED_STATE が見つからない")
    j = html.find("=", i) + 1
    return json.JSONDecoder().raw_decode(html[j:].lstrip())[0], html


def queries(state):
    return {q["queryKey"][1]: q["state"].get("data") for q in state.get("tanStackQuery", {}).get("queries", [])}


def month_cups(ym: str):
    st, _ = get_state(f"{BASE}/schedules/{ym}")
    m = queries(st)["FETCH_KEIRIN_MONTHLY_SCHEDULE"]["month"]
    venues = {v["id"]: v for v in m["venues"]}
    out = []
    for c in m["cups"]:
        v = venues.get(c["venueId"], {})
        out.append(dict(cup=c["id"], slug=v.get("slug"), venue=v.get("name"), venue_id=c["venueId"], name=c.get("name"),
                        start=c["startDate"], end=c["endDate"], duration=c.get("duration"), grade=GRADE.get(c.get("grade"), ""),
                        girls=int(3 in (c.get("labels") or []))))
    return out


def race_numbers(c, index):
    _, html = get_state(f"{BASE}/{c['slug']}/racecard/{c['cup']}/races?index={index}")
    return sorted({int(n) for n in re.findall(rf"racecard/{c['cup']}/{index}/(\d+)", html)})


def _lines(race):
    lp = race.get("linePrediction") or {}
    pos, text = {}, []
    for li, L in enumerate(lp.get("lines", [])):
        nums = [n for en in L["entries"] for n in en["numbers"]]
        text.append("-".join(map(str, nums)))
        for pi, n in enumerate(nums):
            pos[n] = (li, pi, len(nums))
    return lp.get("lineType", ""), ",".join(text), pos


def parse_race(c, index, date, n, state):
    q = queries(state)
    R, O = q.get("FETCH_KEIRIN_RACE"), q.get("FETCH_KEIRIN_RACE_ODDS")
    if not R or not R.get("results"):
        raise NoResult("結果がまだ無い")
    race = R["race"]
    if race.get("cancel"):
        return None
    line_type, line_text, pos = _lines(R)
    rid = race["id"]
    race_row = dict(race_id=rid, cup_id=c["cup"], date=date, venue_id=c["venue_id"], venue_slug=c["slug"], venue=c["venue"],
                    cup_name=c["name"], grade=c["grade"], day=index, index=index, duration=c["duration"], race_no=n,
                    **{"class": race.get("class")}, race_type=race.get("raceType3"), distance=race.get("distance"),
                    lap=race.get("lap"), entries=race.get("entriesNumber"), start_at=race.get("startAt"),
                    close_at=race.get("closeAt"), weather=race.get("weather"), wind=race.get("windSpeed"),
                    line_type=line_type, line_text=line_text, girls=c["girls"])
    P = {p["id"]: p for p in R["players"]}
    REC = {r["playerId"]: r for r in R["records"]}
    RES = {r["playerId"]: r for r in R["results"]}
    entries = []
    for e in R["entries"]:
        p, r, res = P.get(e["playerId"], {}), REC.get(e["playerId"], {}), RES.get(e["playerId"], {})
        g = r.get("modifiedGearRatio") if r.get("hasModifiedGearRatio") else r.get("gearRatio")
        li = pos.get(e["number"], (None, None, None))
        entries.append(dict(
            race_id=rid, car=e["number"], bracket=e.get("bracketNumber"), player_id=e["playerId"], name=p.get("name"),
            gender=p.get("gender"), age=p.get("age"), term=p.get("term"), pref=p.get("prefecture"),
            cls=e.get("playerCurrentTermClass"), grp=e.get("playerCurrentTermGroup"),
            prev_cls=e.get("playerPreviousTermClass"), prev_grp=e.get("playerPreviousTermGroup"),
            gear=g, style=r.get("style"), race_point=r.get("racePoint"), mark=r.get("predictionMark"),
            standing=r.get("standing"), back=r.get("back"), front_runner=r.get("frontRunner"), stalker=r.get("stalker"),
            deep_closer=r.get("deepCloser"), marker=r.get("marker"), first=r.get("first"), second=r.get("second"),
            third=r.get("third"), others=r.get("others"), first_rate=r.get("firstRate"), second_rate=r.get("secondRate"),
            third_rate=r.get("thirdRate"), comment=(r.get("comment") or "").replace("\n", " "), absent=int(bool(e.get("absent"))),
            line_no=li[0], line_pos=li[1], line_size=li[2], finish=res.get("order"), factor=res.get("factor"),
            accident=res.get("accidentName") or res.get("accident")))
    odds = {"race_id": rid, "final": bool(O and O.get("finalOdds")), "odds": {}, "win": {}, "payoff": {}}
    if O:
        for t, name in ODDS_TYPES.items():
            L = O.get(t) or []
            if t == "quinellaPlace":
                odds["odds"][name] = [[".".join(map(str, x["key"])), x.get("minOdds"), x.get("maxOdds"), x.get("popularityOrder")]
                                      for x in L if not x.get("absent")]
            else:
                odds["odds"][name] = [[".".join(map(str, x["key"])), x.get("odds"), x.get("popularityOrder")]
                                      for x in L if not x.get("absent")]
            wins = set(R.get(t + "WinningOddsIds") or [])
            m = {x["id"]: x for x in L}
            odds["win"][name] = [".".join(map(str, m[i]["key"])) if i in m else i.split(":")[-1] for i in wins]
            odds["payoff"][name] = {".".join(map(str, m[i]["key"])): m[i].get("payoffUnitPrice") for i in wins if i in m}
    return race_row, entries, odds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("start")
    ap.add_argument("end")
    ap.add_argument("--out-dir", default="data")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--max-minutes", type=float, default=None)
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    P = lambda f: os.path.join(a.out_dir, f)  # noqa: E731
    done = set(json.load(open(P("wt_progress.json"))) if os.path.exists(P("wt_progress.json")) else [])
    days_done = set(json.load(open(P("wt_days_done.json"))) if os.path.exists(P("wt_days_done.json")) else [])
    noresult = json.load(open(P("wt_noresult.json"))) if os.path.exists(P("wt_noresult.json")) else {}
    fr = open(P("wt_races.csv"), "a", newline="", encoding="utf-8")
    fe = open(P("wt_entries.csv"), "a", newline="", encoding="utf-8")
    fo = gzip.open(P("wt_odds.jsonl.gz"), "at", encoding="utf-8")
    wr = csv.DictWriter(fr, RACE_COLS, extrasaction="ignore")
    we = csv.DictWriter(fe, ENTRY_COLS, extrasaction="ignore")
    if fr.tell() == 0:
        wr.writeheader()
    if fe.tell() == 0:
        we.writeheader()
    lock = threading.Lock()
    t0 = time.time()
    st = {"ok": 0, "err": 0, "streak": 0}
    finished = True

    d0, d1 = datetime.date.fromisoformat(a.start), datetime.date.fromisoformat(a.end)
    today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).date()
    d1 = min(d1, today)
    months = sorted({(d0 + datetime.timedelta(days=i)).strftime("%Y%m") for i in range((d1 - d0).days + 1)})

    def work(job):
        c, index, date, n = job
        for attempt in range(3):
            try:
                state, _ = get_state(f"{BASE}/{c['slug']}/racecard/{c['cup']}/{index}/{n}")
                parsed = parse_race(c, index, date, n, state)
                with lock:
                    if parsed:
                        rr, ee, oo = parsed
                        wr.writerow(rr)
                        for e in ee:
                            we.writerow(e)
                        fo.write(json.dumps(oo, ensure_ascii=False, separators=(",", ":")) + "\n")
                    done.add(f"{c['cup']}:{index}:{n}")
                    st["ok"] += 1
                    st["streak"] = 0
                time.sleep(random.uniform(0.4, 0.9))
                return True
            except NoResult as e:
                key = f"{c['cup']}:{index}:{n}"
                with lock:
                    # 当日のレースは未確定なだけなので数えない。過去のレースで2回続けて結果なし → 中止とみなす
                    if date < today.strftime("%Y%m%d"):
                        noresult[key] = noresult.get(key, 0) + 1
                        if noresult[key] >= NO_RESULT_LIMIT:
                            done.add(key)
                            print(f"  [{c['slug']} {c['cup']} {index}日目 {n}R] 結果なしが{NO_RESULT_LIMIT}回 → 中止レースとして飛ばします", flush=True)
                            return True
                    print(f"  [{c['slug']} {c['cup']} {index}日目 {n}R] {e}", flush=True)
                time.sleep(random.uniform(0.4, 0.9))
                return False
            except Exception as e:
                if attempt == 2:
                    with lock:
                        st["err"] += 1
                        st["streak"] += 1
                    print(f"  [{c['slug']} {c['cup']} {index}日目 {n}R] 失敗: {e}", flush=True)
                    return False
                time.sleep(2 * (attempt + 1))

    def save_progress():
        json.dump(sorted(done), open(P("wt_progress.json"), "w"))
        json.dump(sorted(days_done), open(P("wt_days_done.json"), "w"))
        json.dump(noresult, open(P("wt_noresult.json"), "w"))
        fr.flush()
        fe.flush()
        fo.flush()

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for ym in months:
            if not finished and st["streak"] >= FAIL_STREAK_LIMIT:
                break
            try:
                cups = month_cups(ym)
            except Exception as e:
                print(f"[{ym}] 開催一覧の取得失敗: {e}", flush=True)
                finished = False
                continue
            days = []
            for c in cups:
                if not c["slug"]:
                    continue
                cd0 = datetime.datetime.strptime(c["start"], "%Y%m%d").date()
                for i in range(1, (c["duration"] or 1) + 1):
                    d = cd0 + datetime.timedelta(days=i - 1)
                    if d0 <= d <= d1 and d.strftime("%Y%m") == ym:
                        days.append((d, c, i))
            days.sort(key=lambda x: x[0])
            for d, c, i in days:
                key = f"{c['cup']}:{i}"
                if key in days_done:
                    continue
                if a.max_minutes and (time.time() - t0) / 60 > a.max_minutes:
                    print(f"!! 制限時間({a.max_minutes:.0f}分)に達したので中断", flush=True)
                    finished = False
                    break
                if st["streak"] >= FAIL_STREAK_LIMIT:
                    print("!! 失敗が続いたので中断(次の実行で続きから)", flush=True)
                    finished = False
                    break
                try:
                    nums = race_numbers(c, i)
                except Exception as e:
                    print(f"[{d} {c['slug']}] レース一覧の取得失敗: {e}", flush=True)
                    finished = False
                    st["streak"] += 1
                    continue
                todo = [(c, i, d.strftime("%Y%m%d"), n) for n in nums if f"{c['cup']}:{i}:{n}" not in done]
                if todo:
                    list(ex.map(work, todo))
                if nums and all(f"{c['cup']}:{i}:{n}" in done for n in nums):
                    days_done.add(key)
                elif not nums and d < today:
                    # レースが1つも無い過去の開催日(開催中止)。別々の実行で2回そうなら終わったことにする
                    noresult[key] = noresult.get(key, 0) + 1
                    if noresult[key] >= NO_RESULT_LIMIT:
                        days_done.add(key)
                        print(f"[{d} {c['venue']}{i}日目] レースなしが{NO_RESULT_LIMIT}回 → 開催中止として飛ばします", flush=True)
                    else:
                        finished = False
                else:
                    finished = False
                save_progress()
                print(f"[{d} {c['venue']}{i}日目] {len(nums)}R(新規{len(todo)}) 累計 成功={st['ok']} 失敗={st['err']} "
                      f"{(time.time() - t0) / 60:.0f}分", flush=True)
            if not finished and (st["streak"] >= FAIL_STREAK_LIMIT or (a.max_minutes and (time.time() - t0) / 60 > a.max_minutes)):
                break
    save_progress()
    fr.close()
    fe.close()
    fo.close()
    if st["err"]:
        finished = False
    print(f"{'完了' if finished else '途中終了'}。成功={st['ok']} 失敗={st['err']}", flush=True)
    sys.exit(0 if finished else 3)


if __name__ == "__main__":
    main()
