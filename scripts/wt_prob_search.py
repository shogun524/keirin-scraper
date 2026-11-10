"""
競輪: 「1着率がしきい値以上の選手から買う」3連単の検証(AI1位やラインに頼らない買い方)。

確率の出どころ(3通り): p_ai(AIだけ) / p_mkt(市場=確定2車単オッズ) / p_blend(混合) … wt_ml.py のウォークフォワード予測
買い方:
  BOX: 1着率 θ 以上の選手のBOX
  フォーメ: 1着 θ1以上 → 2着 θ2以上 → 3着 θ3以上(θ1≧θ2≧θ3)
  1点ごとの確率: ハーヴィル式で出した3連単の確率が q 以上の買い目を全部
対象選手の人数(BOXの頭数)でも分けて見る。--select-until より前で選び、以降で確かめる。

使い方: python scripts/wt_prob_search.py data/wt_wf.parquet data/wt_odds.jsonl.gz --select-until 2026-03-01

結果(2026-11-10、2025-07〜2026-02で選定→2026-03〜11で検証、37,236レース):
  どの確率・しきい値・買い方でも回収率70〜76%(控除どおり)。AIだけの確率は市場・混合より少し悪い。勝てる物は無し。
"""
import argparse
import gzip
import json
from itertools import permutations

import numpy as np
import pandas as pd

TH = [0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25]
Q = [0.005, 0.01, 0.02, 0.03, 0.05, 0.08]


def race_table(W, odds, src):
    rows = []
    for rid, g in W.groupby("race_id", sort=False):
        o = odds.get(rid)
        if not o or not o.get("final"):
            continue
        fin = dict(zip(g.car.astype(int), pd.to_numeric(g.finish, errors="coerce")))
        top = sorted([c for c in fin if fin[c] in (1, 2, 3)], key=lambda c: fin[c])
        if len(top) != 3:
            continue
        p = dict(zip(g.car.astype(int), g[src] / g[src].sum()))
        payout = float(o["payoff"].get("3連単", {}).get(".".join(map(str, top)), 0) or 0)
        ps = np.array(sorted(p.values(), reverse=True))
        rec = dict(race_id=rid, date=pd.Timestamp(g.date.iloc[0]).strftime("%Y%m%d"), n=len(p), payout=payout,
                   p1=p[top[0]], p2=p[top[1]], p3=p[top[2]], pmax=ps[0])
        for t in TH:
            rec[f"cnt_{t}"] = int((ps >= t).sum())
        # ハーヴィルで全組の確率 → q以上の点数と、的中組の確率
        cars = list(p)
        pr = {}
        for a, b, c in permutations(cars, 3):
            pr[(a, b, c)] = p[a] * p[b] / (1 - p[a]) * p[c] / (1 - p[a] - p[b])
        v = np.array(list(pr.values()))
        for q in Q:
            rec[f"nq_{q}"] = int((v >= q).sum())
        rec["p_hit"] = pr.get(tuple(top), 0)
        rows.append(rec)
    return pd.DataFrame(rows)


def evaluate(D, sel):
    out = []
    pay = D.payout.to_numpy()

    def add(name, hit, tk, extra=""):
        for per, m in (("sel", sel), ("val", ~sel)):
            T = tk[m].sum()
            out.append(dict(bet=name, cond=extra, period=per, races=int((tk[m] > 0).sum()), tickets=int(T),
                            hits=int(hit[m].sum()), roi=pay[m][hit[m]].sum() / (T * 100) if T else np.nan))

    p1, p2, p3 = D.p1.to_numpy(), D.p2.to_numpy(), D.p3.to_numpy()
    for t in TH:
        k = D[f"cnt_{t}"].to_numpy()
        tk = np.where(k >= 3, k * (k - 1) * (k - 2), 0)
        hit = (p1 >= t) & (p2 >= t) & (p3 >= t) & (k >= 3)
        add(f"BOX 1着率{t:.0%}以上", hit, tk)
        for kk in (3, 4, 5):
            m = k == kk
            add(f"BOX 1着率{t:.0%}以上", hit & m, np.where(m, tk, 0), f"対象{kk}人")
    for t1 in TH:
        for t2 in TH:
            for t3 in TH:
                if not (t1 >= t2 >= t3):
                    continue
                a, b, c = (D[f"cnt_{t}"].to_numpy() for t in (t1, t2, t3))
                tk = np.clip(a, 0, None) * np.clip(b - 1, 0, None) * np.clip(c - 2, 0, None)
                hit = (p1 >= t1) & (p2 >= t2) & (p3 >= t3) & (tk > 0)
                add(f"フォーメ {t1:.0%}→{t2:.0%}→{t3:.0%}", hit, tk)
    ph = D.p_hit.to_numpy()
    for q in Q:
        tk = D[f"nq_{q}"].to_numpy()
        add(f"1点の確率{q:.1%}以上を全部", ph >= q, tk)
    R = pd.DataFrame(out)
    w = R.pivot_table(index=["bet", "cond"], columns="period", values=["races", "tickets", "hits", "roi"])
    w.columns = [f"{x}_{y}" for x, y in w.columns]
    return w.reset_index()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("preds")
    ap.add_argument("odds")
    ap.add_argument("--select-until", default="2026-03-01")
    ap.add_argument("--out", default="wt_prob.csv")
    a = ap.parse_args()
    W = pd.read_parquet(a.preds)
    odds = {}
    with gzip.open(a.odds, "rt") as f:
        for line in f:
            o = json.loads(line)
            odds[str(o["race_id"]).zfill(12)] = o
    pd.set_option("display.width", 250)
    allres = []
    for src in ["p_ai", "p_blend", "p_mkt"]:
        D = race_table(W, odds, src)
        sel = (D.date < a.select_until.replace("-", "")).to_numpy()
        E = evaluate(D, sel)
        E.insert(0, "src", src)
        allres.append(E)
        print(f"\n===== 確率 = {src}({len(D):,}レース、選定 {sel.sum():,} / 検証 {(~sel).sum():,})")
        cols = ["bet", "cond", "races_sel", "tickets_sel", "hits_sel", "roi_sel", "races_val", "hits_val", "roi_val"]
        print("-- BOX(全レース)")
        print(E[E.bet.str.startswith("BOX") & (E.cond == "")][cols].to_string(index=False, float_format="%.3f"))
        print("-- 1点の確率で絞る")
        print(E[E.bet.str.startswith("1点")][cols].to_string(index=False, float_format="%.3f"))
        f = E[E.bet.str.startswith("フォーメ") & (E.hits_sel >= 50)].sort_values("roi_sel", ascending=False)
        print(f"-- フォーメ(選定の回収率上位10、的中50回以上){len(f)}通り中 / 全体平均 選定 {f.roi_sel.mean():.3f} → 検証 {f.roi_val.mean():.3f}")
        print(f.head(10)[cols].to_string(index=False, float_format="%.3f"))
    pd.concat(allres).to_csv(a.out, index=False)


if __name__ == "__main__":
    main()
