"""今日の競輪の成績(11/25): 今の買い目(全員→AI1〜2位→…)と、ライン買い(本命ライン 先頭⇄番手→3番手 など)を比べる。
本命ライン=3連単の確定オッズから出した1着率の合計が一番大きいライン(3人以上)。結果は /tmp/today_line.json"""
import datetime, gzip, json, os, pickle, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import nk_api
from model import parse_line_prediction_text

JST = datetime.timezone(datetime.timedelta(hours=9))
day = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else datetime.datetime.now(JST).strftime("%Y-%m-%d")
R = os.path.join(os.path.dirname(__file__), "..")
d0, races = pickle.load(gzip.open(os.path.join(R, "cache", "races_today.pkl.gz")))
assert d0 == day, d0
nb = json.load(open(os.path.join(R, "docs", "_nb_log.json")))
board = json.load(open(os.path.join(R, "docs", "_race_board.json")))
rid_of = {}
for r in board.get("races", []):
    u = str(r.get("url", ""))
    if u.startswith("nk:"):
        _, rid, slug = u.split(":")
        rid_of[(slug, int(r["race_no"]))] = (rid, r.get("grade"), r.get("cls"))
out = []
for x in races:
    info = x["race_info"]; key = (info["venue"], int(info["race_no"]))
    if key not in rid_of:
        continue
    rid, grade, cls = rid_of[key]
    try:
        pay = nk_api.result(rid)
    except Exception:  # noqa: BLE001
        pay = None
    if not pay or not pay.get("3連単"):
        continue
    combo, yen = pay["3連単"][0]
    o = nk_api.odds(rid).get("3連単") or {}
    if not o:
        continue
    tot = sum(1 / v for v in o.values() if v)
    hs = {}
    for k, v in o.items():
        if v:
            a = int(k.split("-")[0]); hs[a] = hs.get(a, 0) + 1 / v / tot
    lm = parse_line_prediction_text(x.get("line_prediction_text") or "")
    L = {}
    for c, li in lm.items():
        L.setdefault(li["line_index"], []).append((li["position"], c))
    L = [[c for _, c in sorted(v)] for v in L.values()]
    bets = {}
    if L:
        l1 = max(L, key=lambda l: sum(hs.get(c, 0) for c in l))
        if len(l1) >= 3:
            a, b, c = l1[:3]
            bets["先頭⇄番手→3番手(2点)"] = [f"{a}-{b}-{c}", f"{b}-{a}-{c}"]
            bets["先頭→番手→3番手(1点)"] = [f"{a}-{b}-{c}"]
            bets["ライン3人BOX(6点)"] = [f"{p}-{q}-{r}" for p in (a, b, c) for q in (a, b, c) for r in (a, b, c) if len({p, q, r}) == 3]
    e = nb.get(f"{day}_{info['venue']}_{info['race_no']}") or {}
    for rk, nm in (("kai", "今の回収率重視"), ("teki", "今の的中重視")):
        rr = (e.get("rules") or {}).get(rk)
        if rr and rr.get("buy"):
            bets[nm] = rr["tickets"]
    out.append(dict(venue=info["venue"], no=info["race_no"], n=len(x["racers"]), grade=grade, cls=cls, title=info.get("title"),
                    combo=combo, pay=int(yen), lines=L, bets=bets))
json.dump(out, open("/tmp/today_line.json", "w"), ensure_ascii=False)
print(len(out))
