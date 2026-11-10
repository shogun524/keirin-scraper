"""
競輪: 3連単フォーメーションの総当たり探索(ラインの「役割」で組む)。

役割 = 予想印で並べたライン(L1=最強, L2, L3)× 位置(先頭h・番手b・3番手t)の9種 + その他X(4番手以降・4番目以降のライン)。
フォーメーション = 1着の役割集合 × 2着の役割集合 × 3着の役割集合。点数はレースごとに実在する役割で数える。

高速化: レースを「実在する役割の集合」と「1〜3着の役割」と「払戻」に要約し、フォーメーションをビットマスクで一括評価する。
期間: --select-until より前で選び、以降で確かめる。条件は 7車/9車 と 二分戦/三分戦 の別でも見る。

使い方: python scripts/wt_formation_search.py data/ --select-until 2026-01-01

結果(2026-11-10、2025年で選定→2026年で検証、141万通り×5条件):
  選定で回収率100%以上は13万件あったが、選定の成績だけで選んだ上位は検証で平均65〜73%・100%超は5%前後(ほぼ偶然)。
  「両期間とも高い」で並べた上位は検証期間も見て選んでいるので当てにならず、総当たりのフォーメーションに使える物は無かった。
"""
import argparse
import gzip
import json
from itertools import combinations, product

import numpy as np
import pandas as pd

ROLES = ["L1h", "L1b", "L1t", "L2h", "L2b", "L2t", "L3h", "L3b", "L3t", "X"]
RI = {r: i for i, r in enumerate(ROLES)}
MARK_PT = {1: 4, 2: 3, 3: 2, 4: 1}


def summarize(d):
    r = pd.read_csv(f"{d}/wt_races.csv", dtype={"race_id": str, "date": str})
    e = pd.read_csv(f"{d}/wt_entries.csv", dtype={"race_id": str})
    r["race_id"] = r.race_id.str.zfill(12)
    e["race_id"] = e.race_id.str.zfill(12)
    r = r.drop_duplicates("race_id").set_index("race_id")
    e = e[e.absent == 0].drop_duplicates(["race_id", "car"])
    pay = {}
    with gzip.open(f"{d}/wt_odds.jsonl.gz", "rt") as f:
        for line in f:
            o = json.loads(line)
            if o.get("final"):
                pay[str(o["race_id"]).zfill(12)] = o["payoff"].get("3連単", {})
    rows = []
    for rid, g in e.groupby("race_id"):
        if rid not in r.index or rid not in pay or not isinstance(r.at[rid, "line_text"], str):
            continue
        cars = set(g.car.astype(int))
        lines = [[int(x) for x in s.split("-") if x and int(x) in cars] for s in r.at[rid, "line_text"].split(",")]
        lines = [L for L in lines if L]
        if len(lines) < 2:
            continue
        mk = dict(zip(g.car.astype(int), g.mark.fillna(0).astype(int)))
        pt = dict(zip(g.car.astype(int), g.race_point.fillna(0)))
        sc = [sum(MARK_PT.get(mk.get(c, 0), 0) for c in L) + 0.001 * np.mean([pt.get(c, 0) for c in L]) for L in lines]
        order = sorted(range(len(lines)), key=lambda i: -sc[i])
        role = {}
        for k, li in enumerate(order):
            for p, c in enumerate(lines[li]):
                role[c] = RI[f"L{k + 1}{'hbt'[p]}"] if k < 3 and p < 3 else RI["X"]
        for c in cars:
            role.setdefault(c, RI["X"])
        fin = dict(zip(g.car.astype(int), pd.to_numeric(g.finish, errors="coerce")))
        top = sorted([c for c in cars if fin.get(c) in (1, 2, 3)], key=lambda c: fin[c])
        if len(top) != 3 or len({fin[c] for c in top}) != 3:
            continue
        combo = ".".join(map(str, top))
        cnt = np.bincount([role[c] for c in cars], minlength=len(ROLES))  # 役割ごとの車数(Xは複数あり得る)
        rows.append(dict(race_id=rid, date=r.at[rid, "date"], n=len(cars), ltype=str(r.at[rid, "line_type"]),
                         r1=role[top[0]], r2=role[top[1]], r3=role[top[2]], payout=float(pay[rid].get(combo, 0) or 0),
                         cnt=tuple(int(x) for x in cnt)))
    return pd.DataFrame(rows)


def formations(max1=2, max2=3, max3=4, pool1=("L1h", "L1b", "L2h", "L2b", "L3h", "L3b")):
    def subsets(pool, k):
        return [s for n in range(1, k + 1) for s in combinations(pool, n)]
    S1 = subsets(pool1, max1)
    S2 = subsets(ROLES, max2)
    S3 = subsets(ROLES, max3)
    return S1, S2, S3


def mask(s):
    m = 0
    for r in s:
        m |= 1 << RI[r]
    return m


def triple_tickets(cnt):
    """役割の車数 cnt -> T[a,b,c] = 役割(a,b,c)で作れる3連単の点数(同じ車は重ねない)"""
    c = np.array(cnt, dtype=float)
    T = c[:, None, None] * c[None, :, None] * c[None, None, :]
    n = len(c)
    for a in range(n):
        for b in range(n):
            for k in range(n):
                ca, cb, cc = c[a], c[b] - (a == b), c[k] - (a == k) - (b == k)
                T[a, b, k] = max(ca, 0) * max(cb, 0) * max(cc, 0)
    return T


def tensors(G):
    """期間内のレース集合 -> (点数テンソル, 払戻テンソル, 的中数テンソル)。各 [10,10,10]"""
    n = len(ROLES)
    TK, PY, HT = np.zeros((n, n, n)), np.zeros((n, n, n)), np.zeros((n, n, n))
    cache = {}
    for cnt, k in G.cnt.value_counts().items():
        if cnt not in cache:
            cache[cnt] = triple_tickets(cnt)
        TK += cache[cnt] * k
    np.add.at(PY, (G.r1.to_numpy(), G.r2.to_numpy(), G.r3.to_numpy()), G.payout.to_numpy())
    np.add.at(HT, (G.r1.to_numpy(), G.r2.to_numpy(), G.r3.to_numpy()), (G.payout > 0).to_numpy().astype(float))
    return TK, PY, HT


def indicator(S):
    M = np.zeros((len(S), len(ROLES)))
    for i, s in enumerate(S):
        for r in s:
            M[i, RI[r]] = 1
    return M


def evalf(M1, M2, M3, X):
    """X[a,b,c] をフォーメーション全部について合計 -> [F1,F2,F3]"""
    Y = np.einsum("ia,abc->ibc", M1, X)
    Y = np.einsum("jb,ibc->ijc", M2, Y)
    return np.einsum("kc,ijc->ijk", M3, Y)


def search(D, select_until, min_hits_sel=15, min_tickets=1500):
    D = D.copy()
    D["sel"] = D.date < select_until.replace("-", "")
    S1, S2, S3 = formations()
    M1, M2, M3 = indicator(S1), indicator(S2), indicator(S3)
    print(f"フォーメーション候補 {len(S1) * len(S2) * len(S3):,}")
    groups = {"全レース": D.index, "7車": D.index[D.n == 7], "9車": D.index[D.n == 9],
              "二分戦": D.index[D.ltype == "二分戦"], "三分戦": D.index[D.ltype == "三分戦"]}
    out = []
    for gname, idx in groups.items():
        G = D.loc[idx]
        res = {}
        for p in (True, False):
            TK, PY, HT = tensors(G[G.sel == p])
            res[p] = (evalf(M1, M2, M3, TK), evalf(M1, M2, M3, PY), evalf(M1, M2, M3, HT))
        (t1, p1, h1), (t2, p2, h2) = res[True], res[False]
        roi1 = np.where(t1 > 0, p1 / np.maximum(t1, 1) / 100, 0)
        roi2 = np.where(t2 > 0, p2 / np.maximum(t2, 1) / 100, np.nan)
        ok = (t1 >= min_tickets) & (h1 >= min_hits_sel) & (roi1 >= 1.0)
        nsel = int(G.sel.sum())
        for i, j, k in zip(*np.nonzero(ok)):
            out.append(dict(cond=gname, f1="・".join(S1[i]), f2="・".join(S2[j]), f3="・".join(S3[k]),
                            per_race=t1[i, j, k] / max(nsel, 1), tickets_sel=int(t1[i, j, k]), hits_sel=int(h1[i, j, k]),
                            roi_sel=roi1[i, j, k], tickets_val=int(t2[i, j, k]), hits_val=int(h2[i, j, k]),
                            roi_val=roi2[i, j, k]))
        n_all = int(((t1 >= min_tickets) & (h1 >= min_hits_sel)).sum())
        print(f"  {gname}: 条件を満たす {n_all:,}件中、選定で100%以上 {int(ok.sum()):,}件", flush=True)
    return pd.DataFrame(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir")
    ap.add_argument("--select-until", default="2026-01-01")
    ap.add_argument("--out", default="wt_formation.csv")
    a = ap.parse_args()
    import os
    pk = a.out.replace(".csv", "_races.pkl")
    if os.path.exists(pk):
        D = pd.read_pickle(pk)
    else:
        D = summarize(a.data_dir)
        D.to_pickle(pk)
    if "lt" in D.columns:
        D = D.rename(columns={"lt": "ltype"})
    print(f"レース {len(D):,}(選定 {(D.date < a.select_until.replace('-', '')).sum():,})")
    W = search(D, a.select_until)
    W.to_csv(a.out, index=False)
    pd.set_option("display.width", 250)
    print(f"\n選定で100%以上: {len(W):,}件 → 検証で 平均 {W.roi_val.mean():.3f}、100%超 {(W.roi_val > 1).mean():.2f}")
    W["低い方"] = W[["roi_sel", "roi_val"]].min(axis=1)
    cols = ["cond", "f1", "f2", "f3", "per_race", "tickets_sel", "hits_sel", "roi_sel", "tickets_val", "hits_val", "roi_val"]
    print("\n■ 両期間とも高い 上位40(検証の的中15回以上)")
    print(W[W.hits_val >= 15].sort_values("低い方", ascending=False).head(40)[cols].to_string(index=False, float_format="%.3f"))


if __name__ == "__main__":
    main()
