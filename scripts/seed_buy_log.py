# -*- coding: utf-8 -*-
"""保存済みの winticket ページ（docs/winticket_YYYYMMDD.html）から、買い方の成績ログ（docs/_buy_log.json）の
初期データ（seed）を作る。1回だけ実行すればよい（再実行しても seed 分を作り直すだけで live は消さない）。
  python seed_buy_log.py
"""
import glob
import json
import os
import re

import buy_stats

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "docs")
MKT = 1.15


def main():
    log = {k: v for k, v in buy_stats.load(DOCS).items() if v.get("src") != "seed"}
    n = 0
    for f in sorted(glob.glob(os.path.join(DOCS, "winticket_2026*.html"))):
        date = re.search(r"winticket_(\d{4})(\d{2})(\d{2})\.html", f)
        iso = "-".join(date.groups())
        h = open(f, encoding="utf-8").read()
        m = re.search(r'(\{"order".*?\});\s*\n', h, re.S)
        if not m:
            continue
        d = json.loads(m.group(1))
        for slug, races in d["venues"].items():
            venue = {"iwakidaira": "iwakitaira"}.get(slug, slug)
            for r in races:
                if not r["res"] or not r["combos"]:
                    continue
                od = {c[0]: c[3] for c in r["combos"] if c[3]}
                if len(od) < 30:
                    continue
                cov = min(1.0, sum(1 / o for o in od.values()) * 0.75)
                q = {k: (1 / o) ** MKT for k, o in od.items()}
                z = sum(q.values()) / max(cov, 0.3)
                q = {k: x / z for k, x in q.items()}
                win = {}
                for k, p in q.items():
                    win[k.split("-")[0]] = win.get(k.split("-")[0], 0) + p
                top = max(win.values()) * 100
                typ = "堅い" if top >= 45 else ("混戦" if top < 30 else "中間")
                items = [[k, od[k], round(p * 100, 3)] for k, p in sorted(q.items(), key=lambda x: -x[1])][:buy_stats.KEEP]
                log[buy_stats._key(iso, venue, r["r"])] = {
                    "date": iso, "venue": venue, "race_no": r["r"], "deadline": r["s"], "type": typ,
                    "top": round(top, 1), "items": items, "winner": r["res"]["k"], "src": "seed"}
                n += 1
    buy_stats.save(DOCS, log)
    print("seed", n, "レース / 累計", len(log))


if __name__ == "__main__":
    main()
