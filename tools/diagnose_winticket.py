"""
winticket の過去レースで取れる情報の診断(過去データのバックフィルの下調べ)。
- 過去月のスケジュール(開催一覧)のURLの形
- 終わったレースのページに、出走表・選手成績・結果・払戻・オッズが入っているか(クエリのキーと中身の形)
結果は diag/ に保存。
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
from winticket_page import BASE, get_state, queries  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else "diag"
os.makedirs(OUT, exist_ok=True)
log = []


def say(s):
    print(s, flush=True)
    log.append(str(s))


def shape(x, depth=0, maxd=4):
    if depth > maxd:
        return "…"
    if isinstance(x, dict):
        return {k: shape(v, depth + 1, maxd) for k, v in list(x.items())[:40]}
    if isinstance(x, list):
        return [shape(x[0], depth + 1, maxd), f"len={len(x)}"] if x else []
    return x if not isinstance(x, str) else x[:60]


st, html = get_state(f"{BASE}/schedules")
q = queries(st)
say(f"schedules keys: {list(q)}")
m = q["FETCH_KEIRIN_MONTHLY_SCHEDULE"]["month"]
say(f"month keys: {list(m)}  cups={len(m['cups'])}")
links = sorted(set(re.findall(r'href="(/keirin/schedules[^"]*)"', html)))[:20]
say(f"schedule links: {links}")
for cand in ["/schedules/2025/01", "/schedules?year=2025&month=1", "/schedules/202501", "/schedules/2024/06"]:
    try:
        s2, _ = get_state(BASE + cand)
        m2 = queries(s2).get("FETCH_KEIRIN_MONTHLY_SCHEDULE", {}).get("month", {})
        cups = m2.get("cups", [])
        say(f"[{cand}] cups={len(cups)} first={cups[0]['startDate'] if cups else None} last={cups[-1]['startDate'] if cups else None}")
    except Exception as e:
        say(f"[{cand}] ERROR {e}")

venues = {v["id"]: v for v in m["venues"]}
past = [c for c in m["cups"] if c["endDate"] < "20261109"][:2]
for c in past:
    slug = venues[c["venueId"]]["slug"]
    url = f"{BASE}/{slug}/racecard/{c['id']}/1/7"
    try:
        s3, h3 = get_state(url)
        q3 = queries(s3)
        say(f"[race {slug} {c['id']} 1日目7R] keys={list(q3)}")
        json.dump({k: shape(v) for k, v in q3.items()}, open(f"{OUT}/race_shape_{slug}.json", "w"), ensure_ascii=False, indent=1)
        json.dump(q3, open(f"{OUT}/race_full_{slug}.json", "w"), ensure_ascii=False)
        res_links = sorted(set(re.findall(r'href="([^"]*(?:result|payout|refund)[^"]*)"', h3)))[:10]
        say(f"  result-like links: {res_links}")
        for sub in ["/result", "?tab=result", "/payout"]:
            try:
                s4, _ = get_state(url + sub)
                say(f"  [{sub}] keys={list(queries(s4))}")
                json.dump({k: shape(v) for k, v in queries(s4).items()}, open(f"{OUT}/race_shape_{slug}_{sub.strip('/?=')}.json", "w"), ensure_ascii=False, indent=1)
            except Exception as e:
                say(f"  [{sub}] ERROR {e}")
    except Exception as e:
        say(f"[race {slug}] ERROR {e}")
open(f"{OUT}/summary.txt", "w").write("\n".join(log) + "\n")
