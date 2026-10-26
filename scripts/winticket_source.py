"""
kドリームズが取れない日の代わりのデータ元（winticket）。
scraper.fetch_all_todays_races と同じ形式でレースを返すので、
run_daily.py の後段（予想・各ページ・予想成績ログ）をそのまま使える。
結果は fetch_result(url) で winticket のレースページから取る。
"""
import datetime

from winticket_page import (BASE, JST, MARK, SLUG_TO_MODEL, cups_for, fetch_races,
                            get_state, queries, rank_of)


def _racers(com):
    P = {p["id"]: p for p in com["players"]}
    REC = {r["playerId"]: r for r in com["records"]}
    out = []
    for e in com["entries"]:
        if e.get("absent"):
            continue
        p, r = P[e["playerId"]], REC[e["playerId"]]
        g = r["modifiedGearRatio"] if r.get("hasModifiedGearRatio") else r["gearRatio"]
        out.append({
            "car": e["number"], "name": p["name"], "mark": MARK.get(r.get("predictionMark"), ""),
            "rank": rank_of(e["playerCurrentTermClass"], e["playerCurrentTermGroup"]),
            "tactic": r["style"], "souhyou": 0, "waku": e["bracketNumber"], "gear": g,
            "score": r["racePoint"], "age": p["age"], "period": p["term"],
            "kimarite": {"逃": r["frontRunner"], "捲": r["deepCloser"], "差": r["stalker"], "マ": r["marker"]},
            "finishes": {"f1": r["first"], "f2": r["second"], "f3": r["third"], "fo": r["others"]},
            "pref": p["prefecture"], "s_count": r["standing"], "b_count": r["back"],
            "win_rate": r.get("firstRateStr"), "rentai2": r.get("secondRateStr"), "rentai3": r.get("thirdRateStr"),
        })
    return out


def _line_text(com):
    lp = com.get("linePrediction") or {}
    return ",".join("-".join(str(n) for en in L["entries"] for n in en["numbers"])
                    for L in lp.get("lines", []))


def fetch_all_todays_races(date):
    """date: datetime.date（日本時間の今日）。戻り値は scraper.fetch_all_todays_races と同じ形式。"""
    ds = date.strftime("%Y%m%d")
    out = []
    for c in cups_for(ds):
        try:
            races = fetch_races(c)
        except Exception as e:
            print(f"[WARN] winticket {c['slug']} のレース一覧取得に失敗: {e}")
            continue
        venue = SLUG_TO_MODEL.get(c["slug"], c["slug"])
        for R in races:
            com = R.get("common")
            if not com:
                continue
            race = com["race"]
            racers = _racers(com)
            if len(racers) < 5:
                continue
            out.append({
                "race_info": {
                    "venue": venue, "race_no": R["race"],
                    "title": f"{race['class']}{race['raceType3']}",
                    "deadline": datetime.datetime.fromtimestamp(race["closeAt"], JST).strftime("%H:%M"),
                    "source": "winticket",
                },
                "racers": racers,
                "line_prediction_text": _line_text(com),
                "url": f"{BASE}/{c['slug']}/racecard/{c['cup']}/{c['index']}/{R['race']}",
                # 3連単オッズ {(1着,2着,3着): 倍率}（market_fix で予想の補正に使う。未発売は除く）
                "wt_odds": {tuple(o["key"]): o["odds"] for o in (R.get("odds") or {}).get("trifecta") or []
                            if o.get("odds") and o["odds"] < 9000},
            })
        print(f"[INFO] winticket {c['name']}: {len([r for r in out if r['race_info']['venue'] == venue])} レース")
    return out


def fetch_odds_map(date):
    """kドリームズで取ったレースにも「おすすめ予想」を付けるため、winticketから3連単オッズだけ集める。
    戻り値 {(場slug, レース番号): {(1着,2着,3着): 倍率}}。取れない場・レースは含めない（その場合は補正AIで代用）。"""
    ds = date.strftime("%Y%m%d")
    out = {}
    for c in cups_for(ds):
        try:
            races = fetch_races(c)
        except Exception as e:
            print(f"[WARN] winticket {c['slug']} のオッズ取得に失敗: {e}")
            continue
        venue = SLUG_TO_MODEL.get(c["slug"], c["slug"])
        for R in races:
            odds = {tuple(o["key"]): o["odds"] for o in (R.get("odds") or {}).get("trifecta") or []
                    if o.get("odds") and o["odds"] < 9000}
            if odds:
                out[(venue, R["race"])] = odds
    print(f"[INFO] winticketから {len(out)} レース分のオッズを取得しました（kドリームズ用おすすめ予想）。")
    return out


def fetch_result(url):
    """winticket のレースURLから着順を取る。戻り値 [{"car":車番, "finish":着順}, ...]（未確定なら None）"""
    st, _ = get_state(url)
    com = queries(st).get("FETCH_KEIRIN_RACE") or {}
    res = com.get("results") or []
    if not res:
        return None
    car_of = {e["playerId"]: e["number"] for e in com.get("entries", [])}
    out = [{"car": car_of[r["playerId"]], "finish": r["order"]}
           for r in res if r.get("order") and r.get("playerId") in car_of]
    return out or None
