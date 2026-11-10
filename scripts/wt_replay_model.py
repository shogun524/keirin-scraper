"""
サイトの競輪AI(model.predict_race)を、winticket の過去レース(wt_backfill.py のデータ)に当て直して、
AIが出す確率を全部保存する(買い方の検証用)。

保存する物(wt_model_search.race_row で買い方ごとの点数・的中に変換して npz + メタ情報 parquet):
  race_id, date, n, grade, class, race_type, line_type, payout(3連単の払戻), win(1〜3着の車番)
  p1  {車番: 1着率}             … rows[].adjusted
  p2  {車番: 2着率}             … 3連単確率の周辺(2着に来る確率)
  p3  {車番: 3着率}             … 同上(3着)
  place {車番: 3着内率}          … rows[].place_rate
  tri {(1着,2着,3着): 確率}     … 3連単の出目確率(全組)
  close / high / top_gap / max_place … 拮抗レース・本命レースの判定と1位2位の差
  odds {(1着,2着,3着): 確定オッズ}

注意: 対戦成績・調子(rivalry/form)は過去分が無いので使わない(本番より少し情報が少ない)。
     日々の自動補正(docs/_model_params.json)は今の値を使う。学習済みの重みは2020〜2025年のデータなので、2025年分は学習期間と重なる。
使い方: python scripts/wt_replay_model.py data/ data/wt_model_replay.npz
"""
import argparse
import gzip
import json
import os
import shutil
import sys
import tempfile

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import calibration  # noqa: E402
import model  # noqa: E402
import wt_model_search  # noqa: E402

MARK = {1: "◎", 2: "○", 3: "▲", 4: "△"}
SLUG_TO_MODEL = {"iwakidaira": "iwakitaira"}
OV = None


def rank_of(cls, grp):
    if cls == 4:
        return "L1"
    if cls == 0:
        return "SS"
    return ("S" if cls == 1 else "A") + str(grp)


def _init():
    global OV
    d = tempfile.mkdtemp()
    shutil.copy(os.path.join(HERE, "..", "docs", "_model_params.json"), os.path.join(d, "_model_params.json"))
    OV = {**calibration.get_overrides(d), "trifecta_max_combos": 1000, "simulation_trials": 1}


def one(job):
    meta, ents, odds = job
    racers = []
    for e in ents:
        racers.append(dict(
            car=int(e["car"]), name=str(e["name"]), mark=MARK.get(int(e["mark"] or 0), ""),
            rank=rank_of(int(e["cls"]), int(e["grp"])), tactic=e["style"], souhyou=0, waku=int(e["bracket"]),
            gear=float(e["gear"]), score=float(e["race_point"] or 0), age=int(e["age"]), period=int(e["term"]),
            kimarite={"逃": e["front_runner"], "捲": e["deep_closer"], "差": e["stalker"], "マ": e["marker"]},
            finishes={"f1": e["first"], "f2": e["second"], "f3": e["third"], "fo": e["others"]},
            pref=e["pref"], b_count=e["back"], s_count=e["standing"], comment=str(e.get("comment") or "")))
    try:
        res = model.predict_race(racers, meta["line_text"] or "", settings=OV,
                                 venue_slug=SLUG_TO_MODEL.get(meta["venue_slug"], meta["venue_slug"]),
                                 race_title=f"{meta['class']}{meta['race_type']}")
    except Exception as ex:  # noqa: BLE001
        return None, str(ex)
    if not res or not res.get("trifecta"):
        return None, "no trifecta"
    tri = {(c["first"], c["second"], c["third"]): c["prob"] / 100 for c in res["trifecta"]["combos"]}
    s = sum(tri.values()) or 1
    tri = {k: v / s for k, v in tri.items()}
    p2, p3 = {}, {}
    for (a, b, c), v in tri.items():
        p2[b] = p2.get(b, 0) + v
        p3[c] = p3.get(c, 0) + v
    out = dict(meta)
    out.update(p1={r["car"]: r["adjusted"] / 100 for r in res["rows"]}, p2=p2, p3=p3,
               place={r["car"]: r["place_rate"] / 100 for r in res["rows"]}, tri=tri,
               close=bool(res["is_close_race"]), high=bool(res["is_high_prob"]), top_gap=res["top_gap"],
               max_place=res["max_place_rate"], odds=odds)
    return out, None


def jobs(d):
    r = pd.read_csv(f"{d}/wt_races.csv", dtype={"race_id": str, "date": str})
    e = pd.read_csv(f"{d}/wt_entries.csv", dtype={"race_id": str})
    r["race_id"] = r.race_id.str.zfill(12)
    e["race_id"] = e.race_id.str.zfill(12)
    r = r.drop_duplicates("race_id").set_index("race_id")
    e = e[e.absent == 0].drop_duplicates(["race_id", "car"])
    O = {}
    with gzip.open(f"{d}/wt_odds.jsonl.gz", "rt") as f:
        for line in f:
            o = json.loads(line)
            if o.get("final"):
                O[str(o["race_id"]).zfill(12)] = o
    for rid, g in e.groupby("race_id"):
        if rid not in r.index or rid not in O or len(g) < 5:
            continue
        t = r.loc[rid]
        fin = dict(zip(g.car.astype(int), pd.to_numeric(g.finish, errors="coerce")))
        top = sorted([c for c in fin if fin[c] in (1, 2, 3)], key=lambda c: fin[c])
        if len(top) != 3 or len({fin[c] for c in top}) != 3:
            continue
        o = O[rid]
        odds = {}
        for k, od, *_ in o["odds"].get("3連単", []):
            try:
                odds[tuple(int(x) for x in str(k).split("."))] = float(od)
            except (TypeError, ValueError):
                pass
        meta = dict(race_id=rid, date=t.date, n=len(g), grade=str(t.grade), **{"class": str(t["class"])},
                    race_type=str(t.race_type), line_type=str(t.line_type), venue_slug=t.venue_slug,
                    line_text=t.line_text if isinstance(t.line_text, str) else "",
                    win=tuple(top), payout=float(o["payoff"].get("3連単", {}).get(".".join(map(str, top)), 0) or 0))
        yield meta, g.to_dict("records"), odds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir")
    ap.add_argument("out")
    a = ap.parse_args()
    metas, tks, hits, errs = [], [], [], {}
    # 1レース数ミリ秒なので1プロセスで回す。出目確率(全組)は大きいので保存せず、その場で買い方ごとの点数・的中に変換する
    _init()
    for i, job in enumerate(jobs(a.data_dir)):
        res, err = one(job)
        if res:
            m, t, h = wt_model_search.race_row(res)
            metas.append(m)
            tks.append(t)
            hits.append(h)
        else:
            errs[err] = errs.get(err, 0) + 1
        if i % 5000 == 0:
            print(f"  {i:,}レース", flush=True)
    np.savez_compressed(a.out, tk=np.stack(tks), hit=np.stack(hits))
    pd.DataFrame(metas).to_parquet(a.out.replace(".npz", "_meta.parquet"))
    print(f"保存 {len(metas):,}レース × 買い方 {len(wt_model_search.STRATS)}種 / 失敗 {errs}")


if __name__ == "__main__":
    main()
