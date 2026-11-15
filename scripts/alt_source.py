# -*- coding: utf-8 -*-
"""
winticket が使えないとき(11/15〜 クラウドからのアクセスが「アクセス制限」)の代わりのデータ元。

wt_picks.py(穴レース・ルールW など)は winticket のレース情報(R)とオッズ(O)の形で書かれているので、
同じ形のデータを
  出走表・予想印・並び予想 … 楽天Kドリームス(scraper.fetch_all_todays_races。run_daily.py も使っている)
  オッズ(3連単・ワイド)     … netkeirin の API(nk_api.odds)
  結果・払戻               … netkeirin の結果ページ(nk_api.result)
から作る。レースのURLは "nk:<netkeirinのrace_id>:<場のslug>" の形にして、結果の取得(settle)でも使う。

注意: 予想印は winticket のものではなく Kドリームスの印。ルールは winticket の印で検証したので、成績は見直しが必要。
"""
import datetime
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nk_api  # noqa: E402

MARK_INT = {"◎": 1, "○": 2, "〇": 2, "▲": 3, "△": 4, "×": 5, "注": 5}


def winticket_ok():
    """winticket が読めるか(読めるなら今までどおり winticket を使う)"""
    import requests
    try:
        r = requests.get("https://www.winticket.jp/keirin/", timeout=15,
                         headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"})
        return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False


def _lines_from_text(text):
    lines = []
    for part in (text or "").split(","):
        nums = [int(x) for x in re.findall(r"\d+", part)]
        if nums:
            lines.append({"entries": [{"numbers": [n]} for n in nums]})
    return {"lines": lines}


def _lines_from_nk(race_id):
    try:
        d = nk_api.call("AplNarabiYoso", race_id=race_id)
        f = (d.get(f"nkrace_line::{race_id}") or {}).get("lineForecast") or []
    except Exception:  # noqa: BLE001
        return {"lines": []}
    lines, cur = [], []
    for x in (f[0] if f else []):
        if str(x) == "0":
            if cur:
                lines.append(cur)
            cur = []
        else:
            cur.append(int(x))
    if cur:
        lines.append(cur)
    return {"lines": [{"entries": [{"numbers": [n]} for n in L]} for L in lines]}


def to_R(kd, nkr):
    """Kドリームスのレース + netkeirin のレース一覧の行 -> winticket の FETCH_KEIRIN_RACE と同じ形"""
    racers = kd["racers"]
    info = kd["race_info"]
    lp = _lines_from_text(kd.get("line_prediction_text"))
    if not lp["lines"] and nkr:
        lp = _lines_from_nk(nkr["race_id"])
    return {
        "race": {"class": info.get("title") or (nkr or {}).get("name", ""), "raceType3": info.get("title") or "",
                 "closeAt": (nkr or {}).get("close_ts") or 0, "startAt": (nkr or {}).get("start_ts") or 0, "cancel": False},
        "entries": [{"number": int(r["car"]), "playerId": int(r["car"]), "absent": False, "bracketNumber": r.get("waku")} for r in racers],
        "players": [{"id": int(r["car"]), "name": r.get("name"), "prefecture": r.get("pref"), "age": r.get("age")} for r in racers],
        "records": [{"playerId": int(r["car"]), "predictionMark": MARK_INT.get((r.get("mark") or "").strip()),
                     "racePoint": r.get("score"), "comment": r.get("comment") or "", "style": r.get("tactic")} for r in racers],
        "linePrediction": lp,
    }


def to_O(o):
    """nk_api.odds(types=("9","7")) -> winticket の FETCH_KEIRIN_RACE_ODDS と同じ形(trifecta / quinellaPlace)"""
    tri = [{"id": k, "key": [int(x) for x in k.split("-")], "odds": v} for k, v in (o.get("3連単") or {}).items()]
    qp = [{"id": k, "key": [int(x) for x in k.split("-")], "minOdds": lo, "maxOdds": hi}
          for k, (lo, hi) in (o.get("ワイド") or {}).items()]
    return {"trifecta": tri, "quinellaPlace": qp}


def kd_code(url):
    m = re.search(r"/racedetail/(\d{2})", url or "")
    return m.group(1) if m else None


def todays_races(today):
    """-> [(c, n, url, R, O)]。c は wt_picks の開催情報(venue, name, grade, slug)と同じキー"""
    import scraper
    kd = scraper.fetch_all_todays_races(today)
    nk = {}
    try:
        for r in nk_api.race_list(today.strftime("%Y%m%d")):
            nk[(str(r["jyo_cd"]).zfill(2), r["race_no"])] = r
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] netkeirin のレース一覧に失敗: {e}")
    out = []
    for race in kd:
        info = race["race_info"]
        n = int(info["race_no"])
        code = kd_code(race.get("url"))
        nkr = nk.get((code, n)) if code else None
        if not nkr:
            continue
        try:
            O = to_O(nk_api.odds(nkr["race_id"], types=("9", "7")))
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] {nkr['venue']}{n}R オッズ失敗: {e}")
            O = {"trifecta": [], "quinellaPlace": []}
        R = to_R(race, nkr)
        slug = info["venue"]
        c = dict(venue=nkr["venue"], name=nkr.get("name") or "", grade=None, slug=slug, cup=nkr["race_id"][:10])
        out.append((c, n, f"nk:{nkr['race_id']}:{slug}", R, O))
    print(f"[INFO] 代わりのデータ元(Kドリームス+netkeirin)で {len(out)} レース")
    return out


def race_for_settle(url):
    """結果確定後の R(results・的中組のid)と O(最終オッズ・払戻)を作る。未確定なら results は空"""
    rid = url.split(":")[1]
    o = nk_api.odds(rid, types=("9", "7"))
    O = to_O(o)
    R = {"race": {"cancel": False}, "results": [], "trifectaWinningOddsIds": [], "quinellaPlaceWinningOddsIds": []}
    res = nk_api.result(rid)
    if not res:
        return R, O
    tri_pay = dict(res.get("3連単") or [])
    wide_pay = {"-".join(map(str, sorted(int(x) for x in k.split("-")))): v for k, v in (res.get("ワイド") or [])}
    for x in O["trifecta"]:
        if x["id"] in tri_pay:
            x["payoffUnitPrice"] = tri_pay[x["id"]]
            R["trifectaWinningOddsIds"].append(x["id"])
    for x in O["quinellaPlace"]:
        k = "-".join(map(str, sorted(x["key"])))
        if k in wide_pay:
            x["payoffUnitPrice"] = wide_pay[k]
            R["quinellaPlaceWinningOddsIds"].append(x["id"])
    first = next(iter(tri_pay), None)
    if first:
        R["results"] = [{"playerId": int(c), "order": i + 1} for i, c in enumerate(first.split("-"))]
    return R, O


def fetch_odds_map(races, today):
    """run_daily.py の予想の補正用: Kドリームスのレースに netkeirin の3連単オッズを付ける。
    戻り値 {(場, レース番号): {(1着,2着,3着): 倍率}}(winticket_source.fetch_odds_map と同じ形)"""
    nk = {}
    for r in nk_api.race_list(today.strftime("%Y%m%d")):
        nk[(str(r["jyo_cd"]).zfill(2), r["race_no"])] = r
    out = {}
    for race in races:
        info = race["race_info"]
        code = kd_code(race.get("url"))
        nkr = nk.get((code, int(info["race_no"]))) if code else None
        if not nkr or (nkr.get("close_ts") or 0) < datetime.datetime.now().timestamp() - 600:
            continue
        try:
            o = nk_api.odds(nkr["race_id"])
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] {nkr['venue']}{info['race_no']}R オッズ失敗: {e}")
            continue
        m = {tuple(int(x) for x in k.split("-")): v for k, v in (o.get("3連単") or {}).items() if v < 9000}
        if m:
            out[(info["venue"], int(info["race_no"]))] = m
    print(f"[INFO] netkeirin から {len(out)} レース分の3連単オッズを取得(予想の補正用)")
    return out
