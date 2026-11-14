# -*- coding: utf-8 -*-
"""
競輪「オッズ急落」(docs/drops.html): 締切が近いレースで、オッズが大きく下がった(=直前に大きく買われた)組だけを出す。

締切前オッズの記録(wt_odds_snapshot.py が5分おきに追記する wt_live_YYYYMMDD.jsonl.gz)から、
  基準 = 締切10分以上前で、一番締切に近い記録のオッズ(11/14: 30分前→10分前に。直前の動きを見るため。
         11/11〜13の178レースでは、どちらの基準でも急落組は直前オッズどおりの当たり方で、差ははっきりしなかった)
  今   = 一番新しい記録のオッズ
  下落率 = 今 ÷ 基準 − 1
を組ごとに出し、3連単で 下落率 −25% 以下(−40%以下は赤で強調) の組を、オッズの帯ごとに下落の大きい順に並べる。
  2桁台(今10〜99.9倍)を最大6組 + 万車(100〜300倍)を最大2組。
  (11/13: 下落率だけで並べると、オッズが大きく動きやすい万車ばかりが上に来て2桁台が出なかったので帯を分けた。2車単はやめた)
※ 直前に下がった組は当たりやすいが、オッズが下がった分だけ回収率は下がるという話もある。記録がたまったら
   「急落した組を買った回収率」を検証する(scripts/wt_drops.py --evaluate)。

使い方: python wt_drops.py --live ../live/wt_live_20261112.jsonl.gz   (docs/drops.html と docs/_drops.json を書く)
"""
import argparse
import datetime
import gzip
import html
import json
import os
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
DOCS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs")
BET_TYPES = ("3連単",)
BASE_MIN = 10          # 基準にする記録: 締切10分以上前
DROP_TH = -0.25        # これ以下の下落を出す(11/13に -40% から広げた: 11/12の81レースで、出した組が当たったレースが 6→14)
STRONG_TH = -0.40      # これ以下は「大きく下落」として強調
ODDS_RANGE = (10.0, 300.0)
BANDS = (("2桁台", 10.0, 99.95, 6), ("万車", 99.95, 300.0, 2))   # (名前, 下限, 上限, 1レースに出す数)
SHOW_PER_RACE = sum(b[3] for b in BANDS)


def load_live(path):
    recs = {}
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                recs.setdefault(r["url"], []).append(r)
    except (OSError, EOFError):
        pass
    for v in recs.values():
        v.sort(key=lambda r: r["ts"])
    return recs


def race_drops(snaps):
    """1レースの記録の列 -> {券種: [(組, 基準オッズ, 今のオッズ, 下落率), ...]}(急落した組だけ)、基準と今の記録"""
    base = [s for s in snaps if s.get("mins") is not None and s["mins"] >= BASE_MIN]
    if not base or len(snaps) < 2:
        return {}, None, None
    b, c = base[-1], snaps[-1]   # 基準は締切10分前に一番近い記録
    if c["ts"] <= b["ts"]:
        return {}, b, c
    out = {}
    for bt in BET_TYPES:
        bo = {x[0]: x[1] for x in b["odds"].get(bt, []) if x[1]}
        lst = []
        for x in c["odds"].get(bt, []):
            k, o = x[0], x[1]
            if not o or k not in bo or bo[k] >= 2000 or not (ODDS_RANGE[0] <= o <= ODDS_RANGE[1]):
                continue
            d = o / bo[k] - 1
            if d <= DROP_TH:
                lst.append((k, bo[k], o, d))
        lst.sort(key=lambda t: t[3])
        for name, lo, hi, _ in BANDS:
            band = [t for t in lst if lo <= t[2] < hi]
            if band:
                out[name] = band
    return out, b, c


def build(path, now):
    recs = load_live(path)
    races = []
    for url, snaps in recs.items():
        drops, b, c = race_drops(snaps)
        last = snaps[-1]
        races.append(dict(url=url, venue=last["venue"], race_no=last["race_no"], close_at=last.get("close_at") or last.get("start_at"),
                          base_mins=b["mins"] if b else None, cur_mins=c["mins"] if c else None, cur_ts=c["ts"] if c else None,
                          drops={k: [list(t) for t in v] for k, v in drops.items()}))
    races.sort(key=lambda r: r["close_at"] or 0)
    return races


def render(races, now):
    ts = now.timestamp()
    upcoming = [r for r in races if r["close_at"] and r["close_at"] > ts - 60]
    closed = [r for r in races if r["close_at"] and r["close_at"] <= ts - 60 and any(r["drops"].values())]

    def card(r, passed):
        hm = datetime.datetime.fromtimestamp(r["close_at"], JST).strftime("%H:%M")
        mins = (r["close_at"] - ts) / 60
        rows = ""
        limit = {b[0]: b[3] for b in BANDS}
        for bt, lst in r["drops"].items():
            for k, bo, o, d in lst[:limit.get(bt, SHOW_PER_RACE)]:
                rows += (f'<tr class="{"strong" if d <= STRONG_TH else ""}"><td>{bt}</td><td><b>{html.escape(k)}</b></td><td>{bo:.1f}</td><td>→ <b>{o:.1f}</b></td>'
                         f'<td class="d">{d:.0%}</td></tr>')
        body = (f'<table><tr><th>3連単</th><th>組</th><th>基準</th><th>今</th><th>下落</th></tr>{rows}</table>' if rows
                else '<p class="dim">急落した組はありません</p>')
        when = "締切済み" if passed else f"締切 {hm}(あと{max(mins, 0):.0f}分)"
        basis = (f'基準=締切{r["base_mins"]:.0f}分前 → 今=締切{r["cur_mins"]:.0f}分前の記録' if r.get("base_mins") is not None
                 and r.get("cur_mins") is not None else "比べる記録がまだありません")
        return (f'<article class="race{" passed" if passed else ""}"><div class="top"><span class="race-name">{html.escape(r["venue"])}'
                f'{r["race_no"]}R</span><span class="when">{when}</span></div><div class="basis">{basis}</div>{body}</article>')

    soon = [r for r in upcoming if (r["close_at"] - ts) <= 30 * 60]
    later = [r for r in upcoming if (r["close_at"] - ts) > 30 * 60]
    main = "".join(card(r, False) for r in soon) or '<p class="none">締切30分以内のレースはありません。</p>'
    later_html = "".join(card(r, False) for r in later)
    closed_html = "".join(card(r, True) for r in closed[-12:][::-1])
    return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="60"><title>オッズ急落</title>
<style>
  :root {{ --navy:#1B2A4A; --paper:#F5F6F8; --line:#DDE1E8; --ink:#1E2430; --soft:#5F6878; --red:#C8402A; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--paper); color:var(--ink); font-family:"Noto Sans JP",system-ui,sans-serif; font-size:15px; line-height:1.6; }}
  header {{ background:var(--navy); color:#fff; padding:16px; }} header h1 {{ margin:0; font-size:1.3rem; }}
  header p {{ margin:4px 0 0; font-size:.8rem; opacity:.9; }} header a {{ color:#FFD58A; }}
  main {{ max-width:720px; margin:0 auto; padding:12px 16px 32px; }}
  .race {{ background:#fff; border:1px solid var(--line); border-left:5px solid var(--red); border-radius:8px; padding:10px 12px; margin:0 0 12px; }}
  .race.passed {{ opacity:.55; }}
  .top {{ display:flex; justify-content:space-between; gap:8px; }} .race-name {{ font-weight:800; font-size:1.1rem; }}
  .when {{ font-weight:700; color:var(--red); }} .basis, .dim {{ font-size:.75rem; color:var(--soft); }}
  table {{ width:100%; border-collapse:collapse; margin-top:6px; font-size:.9rem; font-variant-numeric:tabular-nums; }}
  th, td {{ border-bottom:1px solid var(--line); padding:4px 6px; text-align:left; }} td.d {{ color:var(--soft); font-weight:700; }}
  tr.strong td {{ background:#FDECEA; }} tr.strong td.d {{ color:var(--red); font-weight:800; }}
  h2 {{ font-size:1rem; margin:20px 0 8px; }} .none {{ background:#fff; border:1px solid var(--line); border-radius:8px; padding:16px; text-align:center; }}
  details {{ margin-top:12px; }} summary {{ cursor:pointer; font-weight:700; color:var(--soft); }}
</style></head><body>
<header><h1>オッズ急落(競輪)</h1>
<p>{now:%m/%d %H:%M} 時点(5分おきに記録・1分おきに再読み込み) ・ <a href="picks.html">穴レース</a> ・ <a href="index.html">予想</a></p></header>
<main>
<p class="dim">締切10分前(に一番近い記録)のオッズから{abs(DROP_TH):.0%}以上下がった3連単の組。2桁台(今10〜99.9倍)を最大6組、万車(100〜300倍)を最大2組。
赤い行は{abs(STRONG_TH):.0%}以上の大きな下落。
直前に大きく買われた組です。当たりやすくなる一方、オッズが下がった分だけ割安さは減ります(回収率は記録がたまり次第検証)。</p>
<h2>締切30分以内</h2>{main}
{f'<details><summary>このあとのレース({len(later)})</summary>{later_html}</details>' if later else ''}
{f'<details><summary>締切済みで急落があったレース</summary>{closed_html}</details>' if closed_html else ''}
</main></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", required=True)
    a = ap.parse_args()
    now = datetime.datetime.now(JST)
    races = build(a.live, now)
    with open(os.path.join(DOCS, "_drops.json"), "w", encoding="utf-8") as f:
        json.dump(dict(date=now.date().isoformat(), generated=int(now.timestamp()), races=races), f, ensure_ascii=False)
    with open(os.path.join(DOCS, "drops.html"), "w", encoding="utf-8") as f:
        f.write(render(races, now))
    n = sum(1 for r in races if any(r["drops"].values()))
    print(f"[INFO] オッズ急落: {len(races)}レース中 {n}レースに急落あり → docs/drops.html")


if __name__ == "__main__":
    main()
