# -*- coding: utf-8 -*-
"""
締切直前のオッズを細かく記録し続ける(GitHub Actions で数時間動かしっぱなしにする。nk_watch.yml)。

netkeirin の API(nk_api.py)で、締切の約13分前から
  締切4分前まで … 60秒おき / 4分前から締切まで … 30秒おき
に3連単のオッズを取り、公式の更新時刻(official_dt)が変わったときだけ live/nk_live_YYYYMMDD.jsonl.gz に1行追記する。
締切後も 1.5分・4分・8分後 に取り直して「最終オッズ」を残す。
一定間隔で nk_drops.py を呼んで docs/drops.html を作り直し、git push する(--push のとき)。

行の中身: rid, venue, no, name, tosu, close, ts(取得時刻), mins(締切まで何分), odt(公式更新時刻), polls(取得回数), tri{組: オッズ}
使い方(scripts/ で): python nk_watch.py --until 23:50 [--push]
"""
import argparse
import datetime
import gzip
import json
import os
import random
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nk_api  # noqa: E402

JST = ZoneInfo("Asia/Tokyo")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIVE = os.path.join(ROOT, "live")
START_MIN = 13          # 締切の何分前から取り始めるか
FAST_MIN = 4            # この分数より締切に近づいたら30秒おき
AFTER = (90, 240, 480)  # 締切後に最終オッズを取り直す秒数
LIST_EVERY = 600        # レース一覧を取り直す間隔(秒)
PAGE_EVERY = 100        # ページを作り直す間隔(秒)
UPLOAD_EVERY = 600      # 記録をリリースに上げる間隔(秒)
DAILY_EVERY = 1800      # 予想ページ(daily.yml)を起こす間隔(秒)。daily の定期実行は混雑時に大きく間引かれるため(11/16 朝に未更新)


def live_path(d):
    return os.path.join(LIVE, f"nk_live_{d:%Y%m%d}.jsonl.gz")


def sh(cmd):
    return subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True, text=True)


def push_page(now):
    """drops.html / _drops.json / _drops_results.json だけを push する。
    他の自動更新とぶつかったら、最新の main に合わせ直してから、この3ファイルだけを上書きして作り直す
    (11/15: 以前の作り直し方は古い checkout の他のファイルまで戻してしまったので、必ず最新の main を土台にする)"""
    files = [f for f in ("docs/drops.html", "docs/_drops.json", "docs/_drops_results.json", "docs/_live_odds.json")
             if os.path.exists(os.path.join(ROOT, f))]
    if not files:
        return
    msg = f'chore: 締切直前オッズ {now:%H:%M}'
    git = 'git -c user.name="github-actions[bot]" -c user.email="github-actions[bot]@users.noreply.github.com"'
    for k in range(4):
        keep = {f: open(os.path.join(ROOT, f), "rb").read() for f in files}
        sh("git rebase --abort")
        if sh("git fetch -q origin main").returncode != 0:
            time.sleep(5)
            continue
        sh("git reset -q --hard origin/main")          # 最新の main(他のファイルは最新のまま)
        for f, b in keep.items():
            open(os.path.join(ROOT, f), "wb").write(b)  # この3ファイルだけ今回の内容にする
        sh("git add " + " ".join(files))
        if sh("git diff --cached --quiet").returncode == 0:
            return
        sh(f'{git} commit -q -m "{msg}"')
        r = sh("git push -q origin HEAD:main")
        if r.returncode == 0:
            print(f"[INFO] {now:%H:%M} ページを push")
            return
        print("[WARN] push 失敗:", (r.stderr or r.stdout)[-300:])
        time.sleep(5 + 5 * k)
    print("[WARN] push に失敗")


def write_live_odds(latest):
    """予想ページが直前オッズで1着率を計算し直すための最新3連単オッズ(締切前〜締切10分後のレースだけ)"""
    now = time.time()
    races = {}
    for rid, x in latest.items():
        if x["close"] and -600 < x["close"] - now < START_MIN * 60 + 600:
            races[rid] = dict(at=datetime.datetime.fromtimestamp(x["ts"], JST).strftime("%H:%M:%S"),
                              mins=round((x["close"] - x["ts"]) / 60, 1), tri=x["tri"])
    with open(os.path.join(ROOT, "docs", "_live_odds.json"), "w", encoding="utf-8") as f:
        json.dump(dict(updated=datetime.datetime.now(JST).strftime("%H:%M:%S"), races=races), f, ensure_ascii=False, separators=(",", ":"))


def upload_live(path):
    if os.path.exists(path):
        r = sh(f'gh release upload wt-odds-live "{path}" --clobber')
        if r.returncode:
            print("[WARN] 記録のアップロードに失敗:", r.stderr[-200:])


def main():
    sys.stdout.reconfigure(line_buffering=True)   # Actions のログにすぐ出す
    ap = argparse.ArgumentParser()
    ap.add_argument("--until", default="auto", help="この時刻(JST)で終わる。auto=5時間30分後(23:59まで)")
    ap.add_argument("--push", action="store_true")
    a = ap.parse_args()
    now = datetime.datetime.now(JST)
    if a.until == "auto":
        end = min(now + datetime.timedelta(hours=5, minutes=30), now.replace(hour=23, minute=59, second=0))
        if now.hour < 7:   # 深夜〜早朝はレースがないので何もしない
            print("[INFO] 早朝なので終了")
            return
    else:
        hh, mm = map(int, a.until.split(":"))
        end = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if end <= now:
            end += datetime.timedelta(days=1)
    os.makedirs(LIVE, exist_ok=True)
    day = now.date()
    path = live_path(day)
    races, t_list, t_page, t_up = [], 0, 0, time.time()
    t_daily = 0
    latest = {}
    last_poll, last_odt, polls, after_done = {}, {}, {}, {}
    print(f"[INFO] {now:%H:%M} 開始 → {end:%H:%M} まで。記録: {path}")
    while datetime.datetime.now(JST) < end:
        t = time.time()
        if t - t_list > LIST_EVERY or not races:
            try:
                races = nk_api.race_list(f"{day:%Y%m%d}")
                t_list = t
                print(f"[INFO] レース一覧 {len(races)}レース")
            except Exception as e:  # noqa: BLE001
                print("[WARN] レース一覧の取得に失敗:", e)
                time.sleep(30)
                continue
        todo = []
        for r in races:
            c = r["close_ts"]
            if not c:
                continue
            left = c - t
            rid = r["race_id"]
            if 0 < left <= START_MIN * 60:
                every = 30 if left <= FAST_MIN * 60 else 60
                if t - last_poll.get(rid, 0) >= every - 2:
                    todo.append(r)
            elif left <= 0:
                done = after_done.setdefault(rid, set())
                for k, sec in enumerate(AFTER):
                    if k not in done and -left >= sec and (-left) < sec + 900 and rid in last_poll:
                        done.add(k)
                        todo.append(r)
                        break
        recs = []
        for r in todo:
            rid = r["race_id"]
            try:
                o = nk_api.odds(rid)
            except Exception as e:  # noqa: BLE001
                print(f"[WARN] {r['venue']}{r['race_no']}R オッズ取得失敗: {e}")
                continue
            last_poll[rid] = time.time()
            polls[rid] = polls.get(rid, 0) + 1
            tri = o.get("3連単") or {}
            if not tri:
                continue
            sig = (o["official_dt"], len(tri), round(sum(1 / v for v in tri.values()), 6))
            if last_odt.get(rid) == sig:
                continue   # 公式の更新が無い(同じデータ)
            last_odt[rid] = sig
            ts = time.time()
            recs.append(dict(rid=rid, venue=r["venue"], no=r["race_no"], name=r["name"], tosu=r["tosu"], close=r["close_ts"],
                             start=r["start_ts"], ts=round(ts, 1), mins=round((r["close_ts"] - ts) / 60, 2),
                             odt=o["official_dt"], polls=polls[rid], tri=tri))
            time.sleep(random.uniform(0.3, 0.8))
        for x in recs:
            latest[x["rid"]] = x
        if recs:
            with gzip.open(path, "at", encoding="utf-8") as f:
                for x in recs:
                    f.write(json.dumps(x, ensure_ascii=False, separators=(",", ":")) + "\n")
        if time.time() - t_page > PAGE_EVERY:
            t_page = time.time()
            try:
                write_live_odds(latest)
            except Exception as e:  # noqa: BLE001
                print("[WARN] 直前オッズの書き出しに失敗:", e)
            r = sh(f'cd scripts && python nk_drops.py --live "{path}"')
            print(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-300:])
            if a.push:
                push_page(datetime.datetime.now(JST))
        if a.push and time.time() - t_daily > DAILY_EVERY:
            t_daily = time.time()
            r = sh('gh workflow run daily.yml')
            print("[INFO] 予想ページの更新を起動" if r.returncode == 0 else f"[WARN] 予想ページの起動に失敗: {r.stderr[-200:]}")
        if a.push and time.time() - t_up > UPLOAD_EVERY:
            t_up = time.time()
            upload_live(path)
        # 次に取るべきレースが無ければ少し長めに休む
        soon = [r for r in races if r["close_ts"] and -600 < r["close_ts"] - time.time() <= START_MIN * 60]
        time.sleep(5 if soon else 30)
        if not [r for r in races if r["close_ts"] and r["close_ts"] - time.time() > -600]:
            print("[INFO] 今日のレースはすべて終わりました")
            break
    sh(f'cd scripts && python nk_drops.py --live "{path}"')
    if a.push:
        push_page(datetime.datetime.now(JST))
        upload_live(path)


if __name__ == "__main__":
    main()
