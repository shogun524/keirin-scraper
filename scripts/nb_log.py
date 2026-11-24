"""
AIの買い目(3連単「1着は全員」の回収率重視・的中重視)の記録と成績(11/24)。

- log(all_race_data, today): 締切前のレースの買い目(合成オッズ・買い/見送り・買い目の一覧)を docs/_nb_log.json に上書き保存。
  締切を過ぎたら上書きしない(=締切前の最後の判定が残る)。
- tally(): 締切から5分以上たって結果がまだのレースの3連単の結果と払戻を netkeiba から取って採点。
- section_html(): 成績ページに出す「AIの買い目の成績(回収率)」の欄。
"""
import datetime
import json
import os
import time
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "docs")
LOG = os.path.join(DOCS, "_nb_log.json")
JST = ZoneInfo("Asia/Tokyo")


def _load():
    try:
        with open(LOG, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(d):
    with open(LOG, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, separators=(",", ":"))


def _board(today):
    try:
        with open(os.path.join(DOCS, "_race_board.json"), encoding="utf-8") as f:
            b = json.load(f)
    except (OSError, ValueError):
        return {}
    if b.get("date") != today.isoformat():
        return {}
    out = {}
    for r in b.get("races", []):
        u = str(r.get("url", ""))
        if u.startswith("nk:"):
            out[(r.get("slug"), int(r["race_no"]))] = (u.split(":")[1], r.get("close_at"))
    return out


def log(all_race_data, today):
    from report import new_bets
    d = _load()
    bd = _board(today)
    now = time.time()
    n = 0
    for rd in all_race_data:
        info, res = rd.get("race_info") or {}, rd.get("prediction")
        if not res:
            continue
        no = int(info["race_no"])
        rid, close_at = bd.get((info["venue"], no), (None, None))
        if close_at is None:
            hm = info.get("deadline") or ""
            try:
                h, m = map(int, hm.split(":"))
                close_at = datetime.datetime(today.year, today.month, today.day, h, m, tzinfo=JST).timestamp()
            except ValueError:
                continue
        if now >= close_at:
            continue
        bets = new_bets(info, res)
        if not bets or all(b["comp"] is None for b in bets):
            continue
        key = f"{today.isoformat()}_{info['venue']}_{no}"
        old = d.get(key) or {}
        d[key] = dict(date=today.isoformat(), venue=info["venue"], race_no=no, rid=rid or old.get("rid"), close_at=close_at,
                      n_cars=len(res["rows"]), logged_at=int(now),
                      rules={b["key"]: dict(name=b["name"], buy=b["buy"], comp=round(b["comp"], 2) if b["comp"] else None,
                                            n=b["n"], verified=b["verified"],
                                            tickets=["-".join(map(str, t)) for t in b["tickets"]]) for b in bets})
        n += 1
    _save(d)
    print(f"[INFO] AIの買い目を記録しました({n}レース)")


def tally(max_fetch=150):
    import nk_api
    d = _load()
    now = time.time()
    k = 0
    for key, e in sorted(d.items()):
        if e.get("res") or not e.get("rid") or now < (e.get("close_at") or 0) + 300:
            continue
        if now > (e.get("close_at") or 0) + 3 * 86400:   # 3日たっても取れないものはあきらめる
            e["res"] = {"none": True}
            continue
        if k >= max_fetch:
            break
        k += 1
        try:
            pay = nk_api.result(e["rid"])
        except Exception as ex:  # noqa: BLE001
            print(f"[WARN] 結果の取得に失敗 {key}: {ex}")
            continue
        if not pay or not pay.get("3連単"):
            continue
        combo, yen = pay["3連単"][0]
        e["res"] = {"combo": combo, "pay": int(yen)}
    _save(d)
    print(f"[INFO] AIの買い目の結果を{k}レース確認しました")


def _stats(rows):
    R = len(rows)
    pts = sum(e["rules"][r]["n"] for e, r in rows)
    hit = [(e, r) for e, r in rows if e["res"]["combo"] in e["rules"][r]["tickets"]]
    ret = sum(e["res"]["pay"] * 1 for e, r in hit)  # 100円ずつ買ったときの払戻
    return R, pts, len(hit), ret


def section_html():
    d = _load()
    done = [e for e in d.values() if e.get("res") and e["res"].get("combo")]
    if not done:
        return ('<section><h2 class="section">AIの買い目の成績（回収率）</h2>'
                '<p>まだ結果の出たレースがありません。11/24から記録を始めました。</p></section>')

    def row(label, rows):
        R, pts, h, ret = _stats(rows)
        inv = pts * 100
        roi = f"{ret / inv:.0%}" if inv else "—"
        hr = f"{h / R:.0%}" if R else "—"
        return (f'<tr><td class="l">{label}</td><td>{R}</td><td>{pts}</td><td>{inv:,}円</td><td>{h}</td><td>{hr}</td>'
                f'<td>{ret:,}円</td><td><b>{roi}</b></td></tr>')
    head = ('<thead><tr><th class="l">買い方</th><th>レース</th><th>点数</th><th>投資(100円ずつ)</th><th>的中</th><th>的中率</th>'
            '<th>払戻</th><th>回収率</th></tr></thead>')
    trs = ""
    for rk, name, cond in (("kai", "回収率重視", "合成4倍以上"), ("teki", "的中重視", "合成3倍以上")):
        buy = [(e, rk) for e in done if e["rules"].get(rk, {}).get("buy")]
        trs += row(f'<b>{name}</b>（{cond}で買い）・7車立て', [x for x in buy if x[0]["rules"][rk]["verified"]])
        trs += row(f'{name}・それ以外(参考)', [x for x in buy if not x[0]["rules"][rk]["verified"]])
        allv = [(e, rk) for e in done if rk in e["rules"] and e["rules"][rk]["verified"] and e["rules"][rk]["comp"]]
        trs += row(f'<small>{name}・条件を無視して7車立てを全部買ったら</small>', allv)
    # 日別(7車立て・条件どおり)
    days = sorted({e["date"] for e in done}, reverse=True)[:14]
    dtr = ""
    for dd in days:
        cells = ""
        for rk in ("kai", "teki"):
            rows = [(e, rk) for e in done if e["date"] == dd and e["rules"].get(rk, {}).get("buy") and e["rules"][rk]["verified"]]
            R, pts, h, ret = _stats(rows)
            cells += f'<td>{R}R {h}的中 <b>{(ret / (pts * 100)):.0%}</b></td>' if pts else '<td>—</td>'
        dtr += f'<tr><td class="l">{dd}</td>{cells}</tr>'
    first = min(e["date"] for e in done)
    return (f'<section><h2 class="section">AIの買い目の成績（回収率）</h2>'
            f'<p style="font-size:13px;">3連単「1着は全員」。回収率重視＝全員→AI1〜2位→3着内率1〜4位(30点)、的中重視＝全員→AI1〜2位→人気1〜5位(40点)。'
            f'締切前の最後の判定で「買い」だったレースを、1点100円で買ったとして計算（{first}〜、結果確定 {len(done)}レース）。'
            f'過去の検証(7車立て)は 回収率重視 104〜115%・的中17〜19%、的中重視 94〜96%・的中22〜23%。</p>'
            f'<div class="table-scroll"><table class="ov">{head}<tbody>{trs}</tbody></table></div>'
            f'<h3 style="font-size:14px;margin:10px 0 4px;">日別（7車立て・条件どおり）</h3>'
            f'<div class="table-scroll"><table class="ov"><thead><tr><th class="l">日付</th><th>回収率重視</th><th>的中重視</th></tr></thead>'
            f'<tbody>{dtr}</tbody></table></div></section>')
