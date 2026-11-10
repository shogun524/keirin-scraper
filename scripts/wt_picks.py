# -*- coding: utf-8 -*-
"""
競輪「買うべきレース」(docs/picks.html)。ライン並び通りの3連単ルールに当てはまるレースだけを出す。

ルール(2025-01〜2026-11 の winticket 確定データで検証。scripts/wt_trifecta_search.py):
  ラインの強さ = ライン内の予想印(◎4 ○3 ▲2 △1)の合計(同点は競走得点の平均で決める)。出走表だけで分かる(オッズ不要)。
  A 9車立て → 印で2番目のラインを並び通り(先頭→番手→3番手)  … 2196点 回収率131%(2025年129%・2026年133%)
  B 9車立て → 印で3番目のラインを並び通り                      … 1420点 回収率110%
  C 7車立て → 印で3番目のラインを並び通り                      … 2462点 回収率122%
  (どれも3人以上のラインのときだけ。A+B+C 合計 6078点・的中84回・回収率122%、上位5本の的中を除くと93%)

記録: docs/_picks_log.json に買い目を残し、レースが終わったら結果(的中・払戻)を書き足す → ページ下部に通算成績。

使い方(scripts/ で): python wt_picks.py   ※ daily.yml(1時間おき)から呼ぶ
"""
import datetime
import html
import json
import os
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wt_backfill import BASE, get_state, month_cups, queries, race_numbers  # noqa: E402

JST = ZoneInfo("Asia/Tokyo")
DOCS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs")
LOG = os.path.join(DOCS, "_picks_log.json")
MARK_PT = {1: 4, 2: 3, 3: 2, 4: 1}
RULES = [
    ("A", 9, 2, "9車立て・印2番目のライン 並び通り", "検証 2196点 回収率131%(2025年129%・2026年133%)"),
    ("B", 9, 3, "9車立て・印3番目のライン 並び通り", "検証 1420点 回収率110%"),
    ("C", 7, 3, "7車立て・印3番目のライン 並び通り", "検証 2462点 回収率122%"),
]


def line_rank(lines, mark, point):
    def score(L):
        return sum(MARK_PT.get(int(mark.get(c) or 0), 0) for c in L) + 0.001 * sum(point.get(c, 0) or 0 for c in L) / len(L)
    return sorted(range(len(lines)), key=lambda i: -score(lines[i]))


def evaluate_race(R):
    """FETCH_KEIRIN_RACE のデータ -> 当てはまるルールのリスト [(rule, ticket, line)]"""
    race = R.get("race") or {}
    if race.get("cancel"):
        return [], "中止"
    entries = [e for e in R.get("entries", []) if not e.get("absent")]
    cars = {int(e["number"]) for e in entries}
    lp = R.get("linePrediction") or {}
    lines = [[n for en in L.get("entries", []) for n in en.get("numbers", []) if n in cars] for L in lp.get("lines", [])]
    lines = [L for L in lines if L]
    if len(lines) < 2:
        return [], "並び予想なし"
    rec = {r["playerId"]: r for r in R.get("records", [])}
    mark = {int(e["number"]): (rec.get(e["playerId"]) or {}).get("predictionMark") for e in entries}
    point = {int(e["number"]): (rec.get(e["playerId"]) or {}).get("racePoint") or 0 for e in entries}
    if not any(mark.values()):
        return [], "予想印なし"
    order = line_rank(lines, mark, point)
    out = []
    for key, n, rank, *_ in RULES:
        if len(cars) == n and len(order) >= rank:
            L = lines[order[rank - 1]]
            if len(L) >= 3:
                out.append((key, f"{L[0]}-{L[1]}-{L[2]}", L))
    return out, ""


def load_log():
    try:
        with open(LOG, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def save_log(log):
    with open(LOG, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=0)


def settle(log, now):
    """終わったレースの結果(3連単の的中組と払戻)を書き足す"""
    for p in log:
        if p.get("settled") or p["start_at"] > now.timestamp() - 15 * 60:
            continue
        try:
            st, _ = get_state(p["url"])
            q = queries(st)
            R, O = q.get("FETCH_KEIRIN_RACE") or {}, q.get("FETCH_KEIRIN_RACE_ODDS") or {}
            if (R.get("race") or {}).get("cancel"):
                p.update(settled=True, result="中止", payout=0, refund=True)
                continue
            if not R.get("results"):
                continue
            m = {x["id"]: x for x in O.get("trifecta") or []}
            wins = ["-".join(map(str, m[i]["key"])) for i in (R.get("trifectaWinningOddsIds") or []) if i in m]
            pay = {"-".join(map(str, m[i]["key"])): m[i].get("payoffUnitPrice") or 0
                   for i in (R.get("trifectaWinningOddsIds") or []) if i in m}
            final = {"-".join(map(str, x["key"])): x.get("odds") for x in O.get("trifecta") or []}
            p.update(settled=True, result="・".join(wins), payout=int(pay.get(p["ticket"], 0)),
                     final_odds=final.get(p["ticket"]))
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] 結果の取得に失敗 {p['url']}: {e}")


def collect(today):
    ym = today.strftime("%Y%m")
    picks, checked, skipped = [], 0, {}
    for c in month_cups(ym):
        if not c["slug"]:
            continue
        d0 = datetime.datetime.strptime(c["start"], "%Y%m%d").date()
        idx = (today - d0).days + 1
        if not 1 <= idx <= (c["duration"] or 1):
            continue
        try:
            nums = race_numbers(c, idx)
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] {c['venue']} のレース一覧に失敗: {e}")
            continue
        for n in nums:
            url = f"{BASE}/{c['slug']}/racecard/{c['cup']}/{idx}/{n}"
            try:
                st, _ = get_state(url)
                R = queries(st).get("FETCH_KEIRIN_RACE") or {}
            except Exception as e:  # noqa: BLE001
                print(f"[WARN] {url}: {e}")
                continue
            checked += 1
            hits, why = evaluate_race(R)
            if why:
                skipped[why] = skipped.get(why, 0) + 1
            race = R.get("race") or {}
            for key, ticket, L in hits:
                picks.append(dict(date=today.isoformat(), rule=key, ticket=ticket, url=url, venue=c["venue"], race_no=n,
                                  cup=c["name"], grade=c["grade"], start_at=race.get("startAt") or 0,
                                  close_at=race.get("closeAt") or 0, cls=race.get("class"), race_type=race.get("raceType3"),
                                  line="-".join(map(str, L))))
    print(f"[INFO] {today} : {checked}レースを確認、買い目 {len(picks)}件、対象外の理由 {skipped}")
    return picks


def merge(log, picks):
    """同じレース・同じルールは最新の判定で置き換える(並びや印が後から変わることがあるため)。結果確定済みは触らない"""
    keyf = lambda p: (p["url"], p["rule"])  # noqa: E731
    settled = {keyf(p) for p in log if p.get("settled")}
    today = {p["date"] for p in picks}
    keep = [p for p in log if p["date"] not in today or p.get("settled")]
    keep += [p for p in picks if keyf(p) not in settled]
    return sorted(keep, key=lambda p: (p["date"], p["start_at"], p["rule"]))


def render(log, now):
    today = now.date().isoformat()
    rule_desc = {k: (d, b) for k, _, _, d, b in RULES}

    def hm(ts):
        return datetime.datetime.fromtimestamp(ts, JST).strftime("%H:%M") if ts else "--:--"

    todays = [p for p in log if p["date"] == today]
    cards = []
    for p in todays:
        passed = p["start_at"] and p["start_at"] < now.timestamp()
        res = ""
        if p.get("settled"):
            res = (f'<span class="hit">的中 {p["payout"]:,}円</span>' if p.get("payout") else
                   f'<span class="miss">{"中止(返還)" if p.get("refund") else "はずれ " + html.escape(p.get("result") or "")}</span>')
        cards.append(f"""<article class="pick{' passed' if passed else ''}">
  <div class="top"><span class="time">{hm(p['start_at'])}</span><span class="race">{html.escape(p['venue'])}{p['race_no']}R</span>
  <span class="tag">{p['rule']}</span>{res}</div>
  <div class="sub">{html.escape(p.get('cup') or '')} {html.escape(p.get('grade') or '')} {html.escape(p.get('race_type') or '')}</div>
  <div class="bet">3連単 <b>{html.escape(p['ticket'])}</b> 100円</div>
  <div class="why">{html.escape(rule_desc[p['rule']][0])}(並び {html.escape(p['line'])})</div>
</article>""")
    body = "".join(cards) or '<p class="none">今日の対象レースはまだありません(並び予想が出ると1時間おきに追加されます)。</p>'

    done = [p for p in log if p.get("settled") and not p.get("refund")]
    stat = ""
    if done:
        rows = []
        for key in ["A", "B", "C", "全体"]:
            s = done if key == "全体" else [p for p in done if p["rule"] == key]
            if s:
                pay = sum(p["payout"] for p in s)
                rows.append(f"<tr><td>{key}</td><td>{len(s)}</td><td>{sum(1 for p in s if p['payout'])}</td>"
                            f"<td>{pay:,}円</td><td>{pay / (len(s) * 100):.0%}</td></tr>")
        stat = ("<h2>このページの通算成績(本番)</h2><table><tr><th>ルール</th><th>点数</th><th>的中</th><th>払戻</th><th>回収率</th></tr>"
                + "".join(rows) + "</table>")
    notes = "".join(f"<li><b>{k}</b>: {html.escape(d)}。{html.escape(b)}。</li>" for k, _, _, d, b in RULES)
    return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>買うべきレース</title>
<style>
  :root {{ --navy:#1B2A4A; --paper:#F5F6F8; --line:#DDE1E8; --ink:#1E2430; --soft:#5F6878; --accent:#C8402A; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--paper); color:var(--ink); font-family:"Noto Sans JP",system-ui,sans-serif; font-size:15px; line-height:1.6; }}
  header {{ background:var(--navy); color:#fff; padding:18px 16px; }}
  header h1 {{ margin:0; font-size:1.4rem; }} header p {{ margin:4px 0 0; font-size:.8rem; opacity:.9; }} header a {{ color:#FFD58A; }}
  main, footer {{ max-width:720px; margin:0 auto; padding:12px 16px; }}
  .pick {{ background:#fff; border:1px solid var(--line); border-left:5px solid var(--accent); border-radius:8px; padding:12px 14px; margin:0 0 12px; }}
  .pick.passed {{ opacity:.55; }}
  .top {{ display:flex; gap:8px; align-items:baseline; flex-wrap:wrap; }}
  .time {{ font-weight:700; font-size:1.2rem; font-variant-numeric:tabular-nums; }}
  .race {{ font-weight:700; font-size:1.1rem; color:var(--navy); }}
  .tag {{ background:var(--accent); color:#fff; font-size:.72rem; font-weight:700; padding:2px 8px; border-radius:999px; }}
  .hit {{ color:#0A7A3B; font-weight:700; }} .miss {{ color:var(--soft); font-size:.85rem; }}
  .sub, .why {{ font-size:.78rem; color:var(--soft); }}
  .bet {{ margin-top:6px; font-size:1.05rem; }} .bet b {{ font-size:1.25rem; letter-spacing:.04em; font-variant-numeric:tabular-nums; }}
  .none {{ background:#fff; border:1px solid var(--line); border-radius:8px; padding:20px; text-align:center; }}
  h2 {{ font-size:1rem; margin:20px 0 8px; }}
  table {{ border-collapse:collapse; width:100%; background:#fff; font-size:.88rem; }}
  th, td {{ border:1px solid var(--line); padding:6px 8px; text-align:right; }} th:first-child, td:first-child {{ text-align:left; }}
  footer {{ font-size:.75rem; color:var(--soft); }} footer ul {{ padding-left:18px; }}
</style></head><body>
<header><h1>買うべきレース(競輪)</h1>
<p>{html.escape(today)} ・ 更新 {now.strftime('%H:%M')}(1時間おき) ・ <a href="index.html">全レースの予想</a></p></header>
<main>{body}{stat}</main>
<footer><ul>{notes}</ul>
<p>ラインの強さは「予想印の合計」で決めるので、オッズを見なくても判定できます。並び予想や印が変わると買い目も変わるので、
買う直前にもう一度開いてください。各ルールとも1レース1点(100円)。過去の確定データでの検証結果で、
大きい配当に頼った成績(上位5本の的中を除くと回収率93%)なので、プラスを保証するものではありません。</p></footer>
</body></html>"""


def main():
    now = datetime.datetime.now(JST)
    log = load_log()
    try:
        log = merge(log, collect(now.date()))
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] 今日の判定に失敗: {e}")
    settle(log, now)
    save_log(log)
    with open(os.path.join(DOCS, "picks.html"), "w", encoding="utf-8") as f:
        f.write(render(log, now))
    print("[INFO] docs/picks.html を書き出しました。")


if __name__ == "__main__":
    main()
