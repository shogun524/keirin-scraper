"""
競輪: レース結果から逆算する「どんな出目が安く(配当が高すぎるくらいに)売られているか」の網羅分析。

全レースの3連単の全組(約1,200万組)それぞれに、特徴を付ける:
  オッズ帯・人気順 / 1〜3着それぞれの 予想印・競走得点順位・ライン(印で並べた何番目のラインか)・ライン内の位置・脚質 /
  並びの形(1-2着が同じライン、ラインの並び通り、何本のラインで決まったか など) / レースの条件(車立て・級班・グレード・並びの形)
「その特徴を持つ組を全部100円ずつ買い続けたら」の回収率を、特徴1つ・2つの組合せごとに出す。
回収率が高い = 市場がその出目を安く見ている(実際の出現率の割に配当が高い)。
期間: --select-until より前で選び、以降で確かめる。

使い方: python scripts/wt_result_patterns.py data/ --select-until 2026-01-01
"""
import argparse
import gzip
import json
from itertools import combinations, permutations

import numpy as np
import pandas as pd

MARK_PT = {1: 4, 2: 3, 3: 2, 4: 1}
MARK_NAME = {0: "無印", 1: "◎", 2: "○", 3: "▲", 4: "△"}
PERM = {n: np.array(list(permutations(range(n), 3)), dtype=np.int8) for n in range(3, 10)}
ODDS_BINS = [0, 5, 10, 20, 50, 100, 300, 1000, 1e9]
ODDS_LAB = ["〜5倍", "5〜10倍", "10〜20倍", "20〜50倍", "50〜100倍", "100〜300倍", "300〜1000倍", "1000倍〜"]
POP_BINS = [0, 1, 3, 6, 10, 20, 50, 100, 1e9]
POP_LAB = ["1番人気", "2〜3番人気", "4〜6番人気", "7〜10番人気", "11〜20番人気", "21〜50番人気", "51〜100番人気", "101番人気〜"]


def build(d):
    r = pd.read_csv(f"{d}/wt_races.csv", dtype={"race_id": str, "date": str})
    e = pd.read_csv(f"{d}/wt_entries.csv", dtype={"race_id": str})
    r["race_id"] = r.race_id.str.zfill(12)
    e["race_id"] = e.race_id.str.zfill(12)
    r = r.drop_duplicates("race_id").set_index("race_id")
    e = e[e.absent == 0].drop_duplicates(["race_id", "car"])
    # 3連単だけを、組番号(1着*100+2着*10+3着)の並び順の配列で持つ(全オッズをそのまま持つとメモリが足りない)
    O = {}
    with gzip.open(f"{d}/wt_odds.jsonl.gz", "rt") as f:
        for line in f:
            o = json.loads(line)
            if not o.get("final"):
                continue
            ks, vs, ps = [], [], []
            for k, v, *rest in o["odds"].get("3連単", []):
                try:
                    x, y, z = (int(t) for t in str(k).split("."))
                    ks.append(x * 100 + y * 10 + z)
                    vs.append(float(v))
                    ps.append(int(rest[0]) if rest and rest[0] else 0)
                except (TypeError, ValueError):
                    pass
            if not ks:
                continue
            idx = np.argsort(ks)
            pay = {k: float(v or 0) for k, v in o["payoff"].get("3連単", {}).items()}
            O[str(o["race_id"]).zfill(12)] = (np.array(ks, dtype=np.int16)[idx], np.array(vs, dtype=np.float32)[idx],
                                              np.array(ps, dtype=np.int16)[idx], pay)
    chunks, races = [], []
    for ri, (rid, g) in enumerate(e.groupby("race_id")):
        if rid not in r.index or rid not in O or not isinstance(r.at[rid, "line_text"], str):
            continue
        g = g.sort_values("car")
        cars = g.car.astype(int).to_numpy()
        n = len(cars)
        if n < 5 or n > 9:
            continue
        fin = pd.to_numeric(g.finish, errors="coerce").to_numpy()
        top = [int(np.where(fin == k)[0][0]) if (fin == k).sum() == 1 else -1 for k in (1, 2, 3)]
        if min(top) < 0:
            continue
        ok_, ov_, op_, opay = O[rid]
        payout = float(opay.get(".".join(str(cars[i]) for i in top), 0) or 0)
        ci = {c: i for i, c in enumerate(cars)}
        mark = g.mark.fillna(0).astype(int).to_numpy()
        pt = g.race_point.fillna(0).to_numpy()
        style = g["style"].map({"逃": 0, "両": 1, "追": 2}).fillna(1).astype(int).to_numpy()
        lines = [[ci[int(x)] for x in s.split("-") if x and int(x) in ci] for s in r.at[rid, "line_text"].split(",")]
        lines = [L for L in lines if L]
        if len(lines) < 2:
            continue
        sc = [sum(MARK_PT.get(int(mark[i]), 0) for i in L) + 0.001 * np.mean([pt[i] for i in L]) for L in lines]
        lorder = sorted(range(len(lines)), key=lambda i: -sc[i])
        lrank = np.full(n, 9, dtype=np.int8)   # 何番目のラインか(1〜、単騎は ラインとして数える)
        lpos = np.full(n, 9, dtype=np.int8)    # 0=先頭 1=番手 2=3番手 3=4番手以降 / 5=単騎
        lid = np.full(n, -1, dtype=np.int16)
        for k, li in enumerate(lorder):
            for p, i in enumerate(lines[li]):
                lrank[i] = min(k + 1, 4)
                lpos[i] = 5 if len(lines[li]) == 1 else min(p, 3)
                lid[i] = li
        ptrank = (-pt).argsort().argsort().astype(np.int8) + 1
        P = PERM[n]
        a, b, c = P[:, 0], P[:, 1], P[:, 2]
        kk = (cars[a] * 100 + cars[b] * 10 + cars[c]).astype(np.int16)
        j = np.clip(np.searchsorted(ok_, kk), 0, len(ok_) - 1)
        found = ok_[j] == kk
        oo = np.where(found, ov_[j], np.nan).astype(np.float32)
        pop = np.where(found, op_[j], 0).astype(np.int16)
        hit = (a == top[0]) & (b == top[1]) & (c == top[2])
        same12, same23, same13 = lid[a] == lid[b], lid[b] == lid[c], lid[a] == lid[c]
        order12 = same12 & (lpos[b] == lpos[a] + 1)       # 1着→2着がライン内で前→後ろ(先頭→番手など)
        rev12 = same12 & (lpos[a] == lpos[b] + 1)         # 後ろ→前(番手が差した)
        nlines = 1 + (~same12).astype(int) + ((~same13) & (~same23)).astype(int)
        lineorder3 = same12 & same23 & (lpos[b] == lpos[a] + 1) & (lpos[c] == lpos[b] + 1)
        ch = pd.DataFrame(dict(
            race=np.int32(len(races)), odds=oo, pop=pop, hit=hit,
            m1=mark[a].astype(np.int8), m2=mark[b].astype(np.int8), m3=mark[c].astype(np.int8), pr1=ptrank[a], pr2=ptrank[b], pr3=ptrank[c],
            lr1=lrank[a], lr2=lrank[b], lr3=lrank[c], lp1=lpos[a], lp2=lpos[b], lp3=lpos[c],
            st1=style[a].astype(np.int8), st2=style[b].astype(np.int8), st3=style[c].astype(np.int8),
            same12=same12, same23=same23, order12=order12, rev12=rev12, nlines=nlines.astype(np.int8),
            lineorder3=lineorder3))
        chunks.append(ch[np.isfinite(ch.odds)])
        races.append(dict(race_id=rid, date=r.at[rid, "date"], n=n, cls=str(r.at[rid, "class"]), grade=str(r.at[rid, "grade"]),
                          lt=str(r.at[rid, "line_type"]), rt=str(r.at[rid, "race_type"]), payout=payout))
        if ri % 10000 == 0:
            print(f"  {ri:,}", flush=True)
    C = pd.concat(chunks, ignore_index=True)
    R = pd.DataFrame(races)
    return C, R


def label(C, R):
    """組ごとの特徴 -> {特徴名: (整数コード配列, ラベル一覧)}(文字列を1,200万行持つとメモリが足りないので整数で持つ)"""
    F = {}

    def put(name, values, labels):
        F[name] = (np.asarray(values, dtype=np.int16), list(labels))

    o = np.digitize(C.odds.to_numpy(), ODDS_BINS[1:-1])
    put("オッズ帯", o, ODDS_LAB)
    pp = C["pop"].replace(0, 9999).to_numpy()
    put("人気", np.digitize(pp, [1.5, 3.5, 6.5, 10.5, 20.5, 50.5, 100.5]), POP_LAB)
    posmap = np.array([0, 1, 2, 3, 4, 4, 4, 4, 4, 4])  # 0先頭 1番手 2三番手 3四番手〜 4単騎/?
    for k in (1, 2, 3):
        put(f"{k}着の印", C[f"m{k}"].clip(0, 4).to_numpy(), [MARK_NAME[i] for i in range(5)])
        put(f"{k}着の得点順位", C[f"pr{k}"].clip(1, 5).to_numpy() - 1, ["得点1位", "得点2位", "得点3位", "得点4位", "得点5位〜"])
        put(f"{k}着のライン", C[f"lr{k}"].clip(1, 4).to_numpy() - 1, ["L1", "L2", "L3", "L4〜"])
        put(f"{k}着の位置", posmap[C[f"lp{k}"].clip(0, 9).to_numpy()], ["先頭", "番手", "3番手", "4番手〜", "単騎"])
        put(f"{k}着の脚質", C[f"st{k}"].to_numpy(), ["逃", "両", "追"])
    rel = np.select([C.order12, C.rev12, C.same12], [0, 1, 2], 3)
    put("1-2着の関係", rel, ["同ライン 前→後", "同ライン 後→前(差し)", "同ライン(離れ)", "別ライン"])
    put("何本のラインで決着", C.nlines.to_numpy() - 1, ["1本(ライン決着)", "2本", "3本"])
    put("ライン並び通り3車", (~C.lineorder3).astype(int).to_numpy(), ["並び通り3車", "それ以外"])
    ri = C.race.to_numpy()
    nn = R.n.to_numpy()[ri]
    put("車立て", np.select([nn <= 6, nn == 7, nn == 8], [0, 1, 2], 3), ["〜6車", "7車", "8車", "9車"])
    cl = R.cls.map({"A級": 0, "S級": 1, "L級": 2}).fillna(3).astype(int).to_numpy()[ri]
    put("級班", cl, ["A級", "S級", "ガールズ", "他"])
    gr = R.grade.map({"F2": 0, "F1": 1}).fillna(2).astype(int).to_numpy()[ri]
    put("グレード", gr, ["F2", "F1", "G戦"])
    lt = R["lt"].map({"二分戦": 0, "三分戦": 1, "四分戦": 2, "細切れ": 3}).fillna(3).astype(int).to_numpy()[ri]
    put("並びの形", lt, ["二分戦", "三分戦", "四分戦", "細切れ"])
    return F


def evaluate(F, hit, pay, sel, pairs=True):
    out = []
    hp = pay * hit

    def agg(name, code, labels):
        K = len(labels)
        for per, m in (("sel", sel), ("val", ~sel)):
            n = np.bincount(code[m], minlength=K)
            h = np.bincount(code[m], weights=hit[m], minlength=K)
            p = np.bincount(code[m], weights=hp[m], minlength=K)
            for i in np.nonzero(n)[0]:
                out.append((name, labels[i], per, int(n[i]), int(h[i]), p[i] / (n[i] * 100)))

    names = list(F)
    for f in names:
        agg(f, F[f][0].astype(np.int64), F[f][1])
    if pairs:
        for f1, f2 in combinations(names, 2):
            c1, l1 = F[f1]
            c2, l2 = F[f2]
            code = c1.astype(np.int64) * len(l2) + c2
            labels = [f"{x} | {y}" for x in l1 for y in l2]
            agg(f"{f1} × {f2}", code, labels)
    R = pd.DataFrame(out, columns=["feat", "value", "period", "tickets", "hits", "roi"])
    W = R.pivot_table(index=["feat", "value"], columns="period", values=["tickets", "hits", "roi"])
    W.columns = [f"{x}_{y}" for x, y in W.columns]
    return W.reset_index()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir")
    ap.add_argument("--select-until", default="2026-01-01")
    ap.add_argument("--out", default="wt_result_patterns.csv")
    a = ap.parse_args()
    import os
    pk = a.out.replace(".csv", "_combos.parquet")
    if os.path.exists(pk):
        C = pd.read_parquet(pk)
        R = pd.read_parquet(pk.replace("_combos", "_races"))
    else:
        C, R = build(a.data_dir)
        C.to_parquet(pk)
        R.to_parquet(pk.replace("_combos", "_races"))
    print(f"レース {len(R):,} / 3連単の組 {len(C):,}")
    F = label(C, R)
    sel = (R.date.to_numpy()[C.race.to_numpy()] < a.select_until.replace("-", ""))
    pay = R.payout.to_numpy()[C.race.to_numpy()]
    hit = C.hit.to_numpy().astype(np.float64)
    W = evaluate(F, hit, pay, sel)
    W.to_csv(a.out, index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 500)
    cols = ["value", "tickets_sel", "hits_sel", "roi_sel", "tickets_val", "hits_val", "roi_val"]
    print("\n■ 特徴1つずつ: 全部買ったときの回収率(選定→検証)")
    for f in F:
        s = W[W.feat == f].sort_values("roi_sel", ascending=False)
        print(f"-- {f}")
        print(s[cols].to_string(index=False, float_format="%.3f"))
    P = W[W.feat.str.contains(" × ") & (W.hits_sel >= 30) & (W.hits_val >= 20)].copy()
    print(f"\n■ 特徴2つの組合せ(選定の的中30回以上・検証20回以上 {len(P):,}通り)")
    for top in (10, 50, 200, 1000):
        t = P.sort_values("roi_sel", ascending=False).head(top)
        print(f"  選定上位{top}: 選定 {t.roi_sel.mean():.3f} → 検証 {t.roi_val.mean():.3f}(100%超 {(t.roi_val > 1).mean():.2f})")
    print(f"  全体: 検証平均 {P.roi_val.mean():.3f}、検証100%超 {(P.roi_val > 1).mean():.3f}")
    P["低い方"] = P[["roi_sel", "roi_val"]].min(axis=1)
    print("-- 選定上位30")
    print(P.sort_values("roi_sel", ascending=False).head(30)[["feat"] + cols].to_string(index=False, float_format="%.3f"))
    print("-- 両期間とも高い30(的中が多い物を優先: 両期間の的中合計100回以上)")
    Q = P[(P.hits_sel + P.hits_val) >= 100]
    print(Q.sort_values("低い方", ascending=False).head(30)[["feat"] + cols].to_string(index=False, float_format="%.3f"))


if __name__ == "__main__":
    main()
