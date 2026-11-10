"""
競輪: 3連単の買い方の総当たり探索(ライン構成ベース)。

ラインの強さの並べ方を3通り用意して、それぞれで「何番目のラインを、どう組むか」を試す。
  M = 市場(確定2車単オッズの逆数和をラインで合計)… 締切後の値なので参考(締切前オッズで近似できるか要確認)
  P = 競走得点(ラインの平均)… 出走表だけで分かる
  K = 予想印(winticket の ◎○▲△ をライン内で点数化して合計)… 出走表だけで分かる
並び(line_text)は出走表時点の並び予想。

使い方:
  python scripts/wt_trifecta_search.py data/ --select-until 2026-01-01 --out data/wt_trifecta.csv
"""
import argparse
import gzip
import json
from itertools import combinations

import numpy as np
import pandas as pd

MARK_PT = {1: 4, 2: 3, 3: 2, 4: 1}


def k3(a, b, c):
    return f"{a}.{b}.{c}"


def load(d):
    r = pd.read_csv(f"{d}/wt_races.csv", dtype={"race_id": str, "date": str})
    e = pd.read_csv(f"{d}/wt_entries.csv", dtype={"race_id": str})
    r["race_id"] = r.race_id.str.zfill(12)
    e["race_id"] = e.race_id.str.zfill(12)
    r = r.drop_duplicates("race_id").set_index("race_id")
    e = e.drop_duplicates(["race_id", "car"])
    odds = {}
    with gzip.open(f"{d}/wt_odds.jsonl.gz", "rt") as f:
        for line in f:
            o = json.loads(line)
            odds[str(o["race_id"]).zfill(12)] = o
    return r, e, odds


def structures(lines, order, others_all):
    """lines: 並び順の車番リストのリスト。order: 強い順のラインindex。others_all: 全車番"""
    S = {}
    L = [lines[i] for i in order]
    heads = [x[0] for x in L]
    for rank, X in enumerate(L[:3], start=1):
        if len(X) >= 3:
            S[f"L{rank} 並び通り(先頭→番手→3番手)"] = [k3(*X[:3])]
            S[f"L{rank} 番手→先頭→3番手"] = [k3(X[1], X[0], X[2])]
            S[f"L{rank} 3車の着順6通り"] = [k3(a, b, c) for a in X[:3] for b in X[:3] for c in X[:3] if len({a, b, c}) == 3]
        if len(X) >= 2:
            oth_heads = [h for h in heads if h != X[0]]
            S[f"L{rank} 先頭→番手→他ライン先頭"] = [k3(X[0], X[1], h) for h in oth_heads]
            S[f"L{rank} 番手→先頭→他ライン先頭"] = [k3(X[1], X[0], h) for h in oth_heads]
            S[f"L{rank} 先頭→番手→全"] = [k3(X[0], X[1], c) for c in others_all if c not in X[:2]]
            S[f"L{rank} 番手→先頭→全"] = [k3(X[1], X[0], c) for c in others_all if c not in X[:2]]
            S[f"L{rank} 先頭,番手→先頭,番手→全"] = S[f"L{rank} 先頭→番手→全"] + S[f"L{rank} 番手→先頭→全"]
    if len(L) >= 2 and len(L[0]) >= 2 and len(L[1]) >= 2:
        a, b = L[0], L[1]
        S["L1先頭→L2先頭→L1番手"] = [k3(a[0], b[0], a[1])]
        S["L2先頭→L1先頭→L2番手"] = [k3(b[0], a[0], b[1])]
        S["L2先頭→L2番手→L1先頭"] = [k3(b[0], b[1], a[0])]
        S["L2番手→L2先頭→L1先頭"] = [k3(b[1], b[0], a[0])]
        S["L2先頭→L1番手→L1先頭"] = [k3(b[0], a[1], a[0])]
        S["L1番手→L2先頭→L1先頭"] = [k3(a[1], b[0], a[0])]
        S["L1番手→L1先頭→L2先頭 + L2番手→L2先頭→L1先頭"] = [k3(a[1], a[0], b[0]), k3(b[1], b[0], a[0])]
    if len(L) >= 3 and all(len(x) >= 1 for x in L[:3]):
        S["各ライン先頭のBOX(L1〜3)"] = [k3(x, y, z) for x in heads[:3] for y in heads[:3] for z in heads[:3] if len({x, y, z}) == 3]
    if sum(len(x) >= 3 for x in L[:3]) >= 2:
        S["3車ライン全部を並び通り"] = [k3(*x[:3]) for x in L[:3] if len(x) >= 3]
    return S


def build(r, e, odds):
    E = e[e.absent == 0].groupby("race_id")
    recs, feats = [], []
    for rid, g in E:
        if rid not in r.index:
            continue
        t = r.loc[rid]
        o = odds.get(rid)
        if not o or not o.get("final") or not isinstance(t.line_text, str):
            continue
        cars = set(g.car.astype(int))
        lines = [[int(x) for x in s.split("-") if x and int(x) in cars] for s in t.line_text.split(",")]
        lines = [x for x in lines if x]
        if len(lines) < 2:
            continue
        mw = {}
        for c, od, *_ in o["odds"].get("2車単", []):
            try:
                a, x = int(str(c).split(".")[0]), float(od)
            except (TypeError, ValueError):
                continue
            if x > 0:
                mw[a] = mw.get(a, 0) + 1 / x
        tot = sum(mw.values()) or 1
        pt = dict(zip(g.car.astype(int), g.race_point))
        mk = dict(zip(g.car.astype(int), g.mark))
        sc = {
            "M": [sum(mw.get(c, 0) for c in x) / tot for x in lines],
            "P": [np.mean([pt.get(c, 0) for c in x]) for x in lines],
            "K": [sum(MARK_PT.get(int(mk.get(c, 0) or 0), 0) for c in x) + 0.001 * np.mean([pt.get(c, 0) for c in x]) for x in lines],
        }
        pay = {k: float(v or 0) for k, v in o["payoff"].get("3連単", {}).items()}
        allc = sorted(cars)
        f = dict(race_id=rid, date=t.date, ltype=str(t.line_type), n=len(cars), cls=str(t["class"]), grade=str(t.grade),
                 rt=str(t.race_type), n3=sum(len(x) >= 3 for x in lines), n_single=sum(len(x) == 1 for x in lines))
        for s, v in sc.items():
            order = list(np.argsort(-np.array(v), kind="stable"))
            f[f"{s}_l1size"] = len(lines[order[0]])
            f[f"{s}_l1share"] = sc["M"][order[0]]
            for name, tk in structures(lines, order, allc).items():
                tk = list(dict.fromkeys(tk))
                recs.append((rid, f"[{s}] {name}", len(tk), sum(pay.get(x, 0) for x in tk)))
        f["PM_same"] = int(np.argmax(sc["P"]) == np.argmax(sc["M"]))
        feats.append(f)
    return pd.DataFrame(recs, columns=["race_id", "structure", "n", "ret"]), pd.DataFrame(feats).set_index("race_id")


def conditions(F):
    return {
        "全レース": pd.Series(True, index=F.index),
        "二分戦": F.ltype == "二分戦", "三分戦": F.ltype == "三分戦", "細切れ・四分戦": F.ltype.isin(["細切れ", "四分戦"]),
        "7車": F.n == 7, "9車": F.n == 9,
        "A級": F.cls == "A級", "S級": F.cls == "S級", "ガールズ": F.cls == "L級",
        "F2": F.grade == "F2", "F1": F.grade == "F1", "G戦": F.grade.str.startswith("G"),
        "予選": F.rt.str.contains("予選"), "決勝・準決勝": F.rt.isin(["決勝", "準決勝"]), "一般・選抜": F.rt.str.contains("一般|選抜"),
        "3車ライン2つ以上": F.n3 >= 2, "単騎あり": F.n_single >= 1,
        "得点上位ライン=人気ライン": F.PM_same == 1, "得点上位ライン≠人気ライン": F.PM_same == 0,
        "人気ラインの1着率55%以上": F.M_l1share >= 0.55, "人気ラインの1着率45%未満": F.M_l1share < 0.45,
    }


def evaluate(R, F, select_until):
    conds = conditions(F)
    names = list(conds)
    is_sel = pd.to_datetime(F.date) < select_until
    pn = R.pivot_table(index="race_id", columns="structure", values="n", aggfunc="sum").reindex(F.index).fillna(0)
    pr = R.pivot_table(index="race_id", columns="structure", values="ret", aggfunc="sum").reindex(F.index).fillna(0)
    rows = []
    for cond in [(x,) for x in names] + list(combinations(names[1:], 2)):
        mask = conds[cond[0]].copy()
        for x in cond[1:]:
            mask &= conds[x]
        mask = mask.fillna(False).astype(bool)
        for period, pm in [("選定", is_sel), ("検証", ~is_sel)]:
            m = (mask & pm).to_numpy()
            if m.sum() == 0:
                continue
            sub_n, sub_r = pn[m], pr[m]
            n, r = sub_n.sum(), sub_r.sum()
            races = (sub_n > 0).sum()
            hits = (sub_r > 0).sum()
            for s in pn.columns:
                if n[s]:
                    rows.append(dict(cond=" & ".join(cond), structure=s, period=period, races=int(races[s]), hits=int(hits[s]),
                                     tickets=int(n[s]), roi=r[s] / (n[s] * 100)))
    res = pd.DataFrame(rows)
    w = res.pivot_table(index=["cond", "structure"], columns="period", values=["roi", "races", "tickets", "hits"])
    w.columns = [f"{x}_{y}" for x, y in w.columns]
    return w.reset_index(), pn, pr


def boot(pn, pr, idx, s, B=2000, top=5):
    n, ret = pn.loc[idx, s].to_numpy(), pr.loc[idx, s].to_numpy()
    keep = n > 0
    n, ret = n[keep], ret[keep]
    if len(n) == 0:
        return np.nan, np.nan, np.nan
    rng = np.random.default_rng(0)
    ii = rng.integers(0, len(n), (B, len(n)))
    bs = ret[ii].sum(1) / (n[ii].sum(1) * 100)
    trimmed = np.sort(ret)[: max(len(ret) - top, 0)].sum() / (n.sum() * 100)
    return np.percentile(bs, 2.5), np.percentile(bs, 97.5), trimmed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir")
    ap.add_argument("--select-until", default="2026-01-01")
    ap.add_argument("--min-races", type=int, default=800)
    ap.add_argument("--out", default="wt_trifecta.csv")
    a = ap.parse_args()
    r, e, odds = load(a.data_dir)
    R, F = build(r, e, odds)
    E, pn, pr = evaluate(R, F, a.select_until)
    E.to_csv(a.out, index=False)
    is_sel = pd.to_datetime(F.date) < a.select_until
    print(f"レース数 {len(F)}(選定 {int(is_sel.sum())} / 検証 {int((~is_sel).sum())})/ 組み方×条件 {len(E)}")
    pd.set_option("display.width", 250)
    cols = ["cond", "structure", "tickets_選定", "roi_選定", "tickets_検証", "roi_検証", "hits_検証"]

    base = E[E.cond == "全レース"].sort_values("roi_選定", ascending=False)
    print("\n■ 条件なし 上位25(並べ方 M=市場, P=競走得点, K=予想印)")
    print(base.head(25)[cols].to_string(index=False, float_format="%.3f"))

    cand = E[(E.races_選定 >= a.min_races) & (E.roi_選定 >= 1.0)].sort_values("roi_選定", ascending=False)
    print(f"\n■ 選定で100%以上(選定{a.min_races}R以上): {len(cand)}件 → 検証で平均 {cand.roi_検証.mean():.3f}、"
          f"100%超 {(cand.roi_検証 > 1).mean():.2f}")

    both = E[(E.races_選定 >= a.min_races) & (E.races_検証 >= a.min_races * 0.7)].copy()
    both["低い方"] = both[["roi_選定", "roi_検証"]].min(axis=1)
    top = both.sort_values("低い方", ascending=False).head(30).copy()
    conds = conditions(F)
    ci = []
    for x in top.itertuples():
        m = pd.Series(True, index=F.index)
        for c in x.cond.split(" & "):
            m &= conds[c].fillna(False)
        ci.append(boot(pn, pr, F.index[m & ~is_sel], x.structure))
    top["検証95%下限"], top["検証95%上限"], top["検証 上位5本除く"] = zip(*ci)
    print("\n■ 両期間とも高い(低い方の回収率で並べた上位30)")
    print(top[cols + ["検証95%下限", "検証95%上限", "検証 上位5本除く"]].to_string(index=False, float_format="%.3f"))

    # 出走表だけ(P・K)で作れる買い方に限定
    pre = both[~both.structure.str.startswith("[M]")].sort_values("低い方", ascending=False).head(15)
    print("\n■ 出走表だけで判定できる買い方(P・K、市場オッズ不要)の上位15")
    print(pre[cols].to_string(index=False, float_format="%.3f"))


if __name__ == "__main__":
    main()
