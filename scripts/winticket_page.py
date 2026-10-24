"""
winticket から当日の全開催の出走表・並び予想・オッズ・結果を取得し、
AIモデルで予想して docs/winticket.html（と日付別アーカイブ）を作る。
kドリームズが使えない日でも予想ページが出るようにするための別系統。

使い方（scripts/ で実行）:
  python winticket_page.py            # 今日（日本時間）
  python winticket_page.py 20261024   # 日付指定
"""
import datetime
import json
import math
import os
import re
import shutil
import sys
import tempfile
import time

import requests

import calibration
import formula
import model

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "docs")
BASE = "https://www.winticket.jp/keirin"
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148")
JST = datetime.timezone(datetime.timedelta(hours=9))
SLUG_TO_MODEL = {"iwakidaira": "iwakitaira"}  # winticket と本システムで綴りが違う場
MARK = {1: "◎", 2: "○", 3: "▲", 4: "△"}
GRADE = {1: "F2", 2: "F1", 3: "G3", 4: "G2", 5: "G1", 6: "GP"}
# 修正版: オッズ確率^B × AI確率^A を正規化（10/23・10/24の66レースで、AIを混ぜない方が当たったため A=0）
A_AI, B_MKT = 0.0, 1.15
SLEEP = 0.7

session = requests.Session()
session.headers["User-Agent"] = UA


def get_state(url):
    r = session.get(url, timeout=30)
    r.raise_for_status()
    html = r.text
    i = html.find("window.__PRELOADED_STATE__")
    if i < 0:
        raise ValueError("PRELOADED_STATE が見つからない: " + url)
    j = html.find("=", i) + 1
    return json.JSONDecoder().raw_decode(html[j:].lstrip())[0], html


def queries(state):
    return {q["queryKey"][1]: q["state"].get("data")
            for q in state.get("tanStackQuery", {}).get("queries", [])}


def cups_for(date):
    st, _ = get_state(f"{BASE}/schedules")
    m = queries(st)["FETCH_KEIRIN_MONTHLY_SCHEDULE"]["month"]
    venues = {v["id"]: v for v in m["venues"]}
    out = []
    for c in m["cups"]:
        if c["startDate"] <= date <= c["endDate"]:
            v = venues[c["venueId"]]
            d0 = datetime.datetime.strptime(c["startDate"], "%Y%m%d")
            idx = (datetime.datetime.strptime(date, "%Y%m%d") - d0).days + 1
            out.append(dict(cup=c["id"], slug=v["slug"], name=v["name"], index=idx,
                            days=c.get("duration"), grade=GRADE.get(c.get("grade"), "")))
    return out


def fetch_races(c):
    _, html = get_state(f"{BASE}/{c['slug']}/racecard/{c['cup']}/races?index={c['index']}")
    nums = sorted({int(n) for n in re.findall(rf"racecard/{c['cup']}/{c['index']}/(\d+)", html)})
    races = []
    for n in nums:
        time.sleep(SLEEP)
        try:
            st, _ = get_state(f"{BASE}/{c['slug']}/racecard/{c['cup']}/{c['index']}/{n}")
        except Exception as e:  # 1レース失敗しても他は続ける
            print("  取得失敗", c["slug"], n, e)
            continue
        q = queries(st)
        races.append(dict(race=n, common=q.get("FETCH_KEIRIN_RACE"), odds=q.get("FETCH_KEIRIN_RACE_ODDS")))
    return races


def rank_of(cls, grp):
    if cls == 4:
        return "L1"
    if cls == 0:
        return "SS"
    return ("S" if cls == 1 else "A") + str(grp)


def predict(c, R, ov):
    com = R["common"]
    race = com["race"]
    P = {p["id"]: p for p in com["players"]}
    REC = {r["playerId"]: r for r in com["records"]}
    racers = []
    for e in com["entries"]:
        if e.get("absent"):
            continue
        p, r = P[e["playerId"]], REC[e["playerId"]]
        g = r["modifiedGearRatio"] if r.get("hasModifiedGearRatio") else r["gearRatio"]
        racers.append(dict(
            car=e["number"], name=p["name"], mark=MARK.get(r.get("predictionMark"), ""),
            rank=rank_of(e["playerCurrentTermClass"], e["playerCurrentTermGroup"]),
            tactic=r["style"], souhyou=0, waku=e["bracketNumber"], gear=g, score=r["racePoint"],
            age=p["age"], period=p["term"],
            kimarite={"逃": r["frontRunner"], "捲": r["deepCloser"], "差": r["stalker"], "マ": r["marker"]},
            finishes={"f1": r["first"], "f2": r["second"], "f3": r["third"], "fo": r["others"]},
            pref=p["prefecture"], b_count=r["back"], s_count=r["standing"], comment=r.get("comment") or ""))
    lp = com.get("linePrediction") or {}
    line = ",".join("-".join(str(n) for en in L["entries"] for n in en["numbers"]) for L in lp.get("lines", []))
    slug = SLUG_TO_MODEL.get(c["slug"], c["slug"])
    title = f"{race['class']}{race['raceType3']}"
    res = model.predict_race(racers, line, settings={**ov, "trifecta_max_combos": 600},
                             venue_slug=slug, race_title=title)
    tmp = [{**r, "line_info": res["line_map"].get(r["car"]), "rivalry_summary": None} for r in res["rows"]]
    girls = formula.is_girls(tmp, title)
    fm = {x["car"]: x for x in formula.compute_formula(tmp, slug, title)}

    odds = {tuple(o["key"]): o["odds"] for o in (R["odds"] or {}).get("trifecta") or []
            if o.get("odds") and o["odds"] < 9000}
    combos = [((x["first"], x["second"], x["third"]), x["prob"]) for x in res["trifecta"]["combos"]]

    def row(k, p):
        o = odds.get(k)
        return ["-".join(map(str, k)), round(p, 2), round(100 / p, 1), o, round(p * o / 100, 2) if o else None]

    result = None
    wids = set(com.get("trifectaWinningOddsIds") or [])
    for o in (R["odds"] or {}).get("trifecta") or []:
        if o["id"] in wids:
            k = tuple(o["key"])
            rk = next((i + 1 for i, (kk, _) in enumerate(combos) if kk == k), None)
            pr = next((p for kk, p in combos if kk == k), None)
            result = dict(k="-".join(map(str, k)), pay=round(o["odds"] * 100), rank=rk, p=pr)

    cc = cw = None
    if not result and odds and len(odds) >= len(combos) * 0.7:
        s = sum(1 / v for v in odds.values())
        q = {k: (1 / v) / s for k, v in odds.items()}
        m = {k: p / 100 for k, p in combos}
        z = {k: math.exp(A_AI * math.log(max(m.get(k, 0), 1e-4)) + B_MKT * math.log(max(q.get(k, 0), 1e-4)))
             for k in set(m) | set(q)}
        t = sum(z.values())
        z = {k: v / t for k, v in z.items()}
        cc = [row(k, p * 100) for k, p in sorted(z.items(), key=lambda kv: -kv[1]) if p * 100 >= 0.2]
        w = {}
        for k, p in z.items():
            w[k[0]] = w.get(k[0], 0) + p * 100
        cw = {str(k): round(v, 1) for k, v in w.items()}

    byc = {r["car"]: r for r in racers}
    rows = []
    for r in sorted(res["rows"], key=lambda r: r["car"]):
        b = byc[r["car"]]
        rows.append([r["car"], r["name"], b["rank"], b["tactic"], b["score"], b["pref"], b["age"],
                     round(r["adjusted"], 1), round(r["place_rate"], 1), round(fm[r["car"]]["total"], 1),
                     fm[r["car"]]["rank"], b["mark"], b["comment"], r["dominant_type"]])
    fml = [[f["rank"], f["car"], f["name"], f["score"], f["b"] or 0, f["kim3"], f["age_pen"],
            round(f["ability"], 2), f["line_size"], f["L"], f["m"], "・".join(f["m_why"]), round(f["total"], 2)]
           for f in sorted(fm.values(), key=lambda f: f["rank"])]
    return dict(r=R["race"], t=title, s=datetime.datetime.fromtimestamp(race["startAt"], JST).strftime("%H:%M"),
                line=line, lsrc="公式並び予想" if line else ("ガールズ(全員単騎)" if girls else "並び未発表"),
                lt=lp.get("lineType") or "", rows=rows,
                combos=[row(k, p) for k, p in combos if p >= 0.2],
                girls=girls, fm=fml, res=result, cc=cc, cw=cw)


def summary(venues):
    """終わったレースの集計（AI本命の勝ち数、1番人気の勝ち数）"""
    n = ai = 0
    for races in venues.values():
        for r in races:
            if not r["res"]:
                continue
            n += 1
            top = max(r["rows"], key=lambda x: x[7])[0]
            ai += int(r["res"]["k"].split("-")[0]) == top
    return dict(n=n, ai_top_win=ai)


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.datetime.now(JST).strftime("%Y%m%d")
    d = tempfile.mkdtemp()
    shutil.copy(os.path.join(DOCS, "_model_params.json"), os.path.join(d, "_model_params.json"))
    ov = calibration.get_overrides(d)
    cups = cups_for(date)
    print(date, "開催", [(c["name"], c["index"]) for c in cups])
    venues, names, day, order = {}, {}, {}, []
    for c in sorted(cups, key=lambda c: c["slug"]):
        try:
            races = fetch_races(c)
        except Exception as e:
            print("場の取得失敗", c["slug"], e)
            continue
        out = []
        for R in races:
            try:
                out.append(predict(c, R, ov))
            except Exception as e:
                print("  予想失敗", c["slug"], R["race"], e)
        if not out:
            continue
        out.sort(key=lambda r: r["r"])
        venues[c["slug"]] = out
        names[c["slug"]] = c["name"]
        last = "最終日" if c["days"] and c["index"] == c["days"] else f"{c['index']}日目"
        day[c["slug"]] = f"{'初日' if c['index'] == 1 else last} {c['grade']}"
        order.append(c["slug"])
    order.sort(key=lambda s: venues[s][0]["s"])  # 発走の早い場から
    now = datetime.datetime.now(JST)
    data = dict(order=order, names=names, day=day, fetched=now.strftime("%H:%M"),
                date=f"{int(date[4:6])}/{int(date[6:])}", venues=venues, summary=summary(venues))
    tpl = open(os.path.join(HERE, "winticket_template.html"), encoding="utf-8").read()
    html = tpl.replace("__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    for name in ("winticket.html", f"winticket_{date}.html"):
        with open(os.path.join(DOCS, name), "w", encoding="utf-8") as f:
            f.write(html)
    print("出力", len(venues), "場", sum(len(v) for v in venues.values()), "レース")


if __name__ == "__main__":
    main()
