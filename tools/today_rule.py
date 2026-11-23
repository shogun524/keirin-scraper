"""今日の競輪で「頭=AI1着率10%以上・軸=3着内率1位(必ず入る)・3着内率20%未満は切り・合成2倍まで」を3連単で買った成績。
予想(AIの1着率・3着内率)は docs/_prediction_log.json、確定オッズと払戻は netkeiba。結果は /tmp/today_rule.json"""
import datetime, json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import nk_api

JST = datetime.timezone(datetime.timedelta(hours=9))
day = sys.argv[1] if len(sys.argv) > 1 else datetime.datetime.now(JST).strftime("%Y-%m-%d")
D = os.path.join(os.path.dirname(__file__), "..", "docs")
log = json.load(open(os.path.join(D, "_prediction_log.json")))
board = json.load(open(os.path.join(D, "_race_board.json")))
slug_of = {}
for r in board.get("races", []):
    u = str(r.get("url", ""))
    if u.startswith("nk:"):
        _, rid, slug = u.split(":")
        slug_of[rid] = slug
out = []
for rid, slug in sorted(slug_of.items()):
    if not rid.startswith(day.replace("-", "")):
        continue
    rno = int(rid[-2:])
    L = log.get(f"{day}_{slug}_{rno}")
    if not L or not L.get("probs"):
        continue
    try:
        pay = nk_api.result(rid)
    except Exception as e:  # noqa: BLE001
        pay = None
    if not pay:
        continue
    o = nk_api.odds(rid).get("3連単") or {}
    p1 = {int(c): a / 100 for c, a, b in L["probs"]}
    p3 = {int(c): b / 100 for c, a, b in L["probs"]}
    H = [c for c in p1 if p1[c] >= .10]
    # 頭ごとに軸を決める(11/23): 軸=その頭以外で3着内率が一番高い選手(頭が3着内率1位なら2位が軸)。軸は2着か3着、残りは3着内率20%以上
    K = [c for c in p3 if p3[c] >= .20]
    AX = {a: max((c for c in p3 if c != a), key=p3.get) for a in H}
    A = max(p3, key=p3.get)
    tk = sorted({(a, b, c) for a in H for b in K + [AX[a]] for c in K + [AX[a]]
                 if len({a, b, c}) == 3 and AX[a] in (b, c) and f"{a}-{b}-{c}" in o})

    def hv(k):
        a, b, c = k
        return p1[a] * p1[b] / max(1e-9, 1 - p1[a]) * p1[c] / max(1e-9, 1 - p1[a] - p1[b])
    tk.sort(key=lambda k: -hv(k))
    # 全部買う。全部の合成が2倍を切るなら見送り(11/23)
    inv = sum(1 / o[f"{a}-{b}-{c}"] for a, b, c in tk)
    sel = tk if inv and 1 / inv >= 2 else []
    allcomp = round(1 / inv, 2) if inv else None
    win, wpay = pay["3連単"][0]
    hit = any(f"{a}-{b}-{c}" == win for a, b, c in sel)
    out.append(dict(rid=rid, venue=slug, race_no=rno, heads=H, axis={str(a): AX[a] for a in H}, cut=[c for c in p3 if p3[c] < .2],
                    n=len(sel), comp=allcomp, ntk=len(tk), tickets=["-".join(map(str, k)) for k in sel],
                    win=win, pay=wpay, hit=hit))
json.dump(out, open("/tmp/today_rule.json", "w"), ensure_ascii=False)
b = [r for r in out if r["n"]]
inv = sum(r["n"] for r in b) * 100
ret = sum(r["pay"] for r in b if r["hit"])
print(f"{day} 確定{len(out)}レース 買う{len(b)} 点数{inv // 100} 的中{sum(r['hit'] for r in b)} 投資{inv} 払戻{ret} 回収率{ret / inv:.1%}" if inv else "対象なし")
