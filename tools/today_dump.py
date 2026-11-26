"""診断: 今日(または指定日)の競輪の、締切前の買い目の記録(_nb_log.json)に、確定の3連単オッズと結果を付けて /tmp/today_dump.json に書く(11/26)"""
import datetime, gzip, json, os, pickle, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import nk_api
from model import parse_line_prediction_text
JST = datetime.timezone(datetime.timedelta(hours=9))
day = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else datetime.datetime.now(JST).strftime("%Y-%m-%d")
R = os.path.join(os.path.dirname(__file__), "..")
nb = json.load(open(os.path.join(R, "docs", "_nb_log.json")))
lines = {}
try:
    d0, races = pickle.load(gzip.open(os.path.join(R, "cache", "races_today.pkl.gz")))
    if d0 == day:
        for x in races:
            lm = parse_line_prediction_text(x.get("line_prediction_text") or "")
            L = {}
            for c, li in lm.items():
                L.setdefault(li["line_index"], []).append((li["position"], c))
            lines[(x["race_info"]["venue"], int(x["race_info"]["race_no"]))] = [[c for _, c in sorted(v)] for v in L.values()]
except Exception as e:  # noqa: BLE001
    print("lines NG", e)
out = []
for k, e in nb.items():
    if e.get("date") != day or not e.get("rid"):
        continue
    try:
        pay = nk_api.result(e["rid"])
    except Exception:  # noqa: BLE001
        pay = None
    if not pay or not pay.get("3連単"):
        continue
    o = nk_api.odds(e["rid"]).get("3連単") or {}
    out.append(dict(e, lines=lines.get((e["venue"], e["race_no"])), final_tri=o, result=pay))
json.dump(out, open("/tmp/today_dump.json", "w"), ensure_ascii=False)
print(len(out))
