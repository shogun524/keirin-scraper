"""
競輪: AI・ライン・市場を使った買い方の総当たり探索(組み方 × 買うレースの条件)。JRA の strategy_search.py と同じ方式。

入力: wt_ml.py のウォークフォワード予測(wt_wf.parquet: race_id, date, car, p_ai, p_mkt, line_no, line_pos, line_size, ...)
     と wt_odds.jsonl.gz の確定払戻(payoff)。
期間: --select-until より前で組み合わせを選び、それ以降で確かめる。

使い方:
  python scripts/wt_strategy_search.py data/wt_wf.parquet data/wt_odds.jsonl.gz --select-until 2026-03-01
"""
import argparse
import gzip
import json
from itertools import combinations

import numpy as np
import pandas as pd

SORTED = {"2車複", "ワイド", "3連複"}


def key(bet, cars):
    cars = [int(c) for c in cars]
    if bet in SORTED:
        cars = sorted(cars)
    return ".".join(map(str, cars))


def box(bet, cs, k):
    return [(bet, key(bet, c)) for c in combinations(cs, k)]


def axis(bet, a, others, k):
    return [(bet, key(bet, (a,) + c)) for c in combinations([o for o in others if o != a], k - 1)]


def structures(A, M, line_of, lines, value):
    """A=AI順, M=市場順, line_of[car]=(ライン番号, 位置), lines[ライン番号]=並び順の車番リスト"""
    a1, a2, m1 = A[0], A[1], M[0]
    L1 = lines[line_of[a1][0]]                     # ◎のライン
    mate = [c for c in L1 if c != a1]              # ◎のライン仲間
    behind = L1[L1.index(a1) + 1] if L1.index(a1) + 1 < len(L1) else None  # ◎の番手
    Lm = lines[line_of[m1][0]]
    S = {
        "2車単 ◎→○": [("2車単", key("2車単", (a1, a2)))],
        "2車単 ◎→AI2〜4": [("2車単", key("2車単", (a1, x))) for x in A[1:4]],
        "2車複 ◎-○": [("2車複", key("2車複", (a1, a2)))],
        "2車複 ◎-AI2〜4": axis("2車複", a1, A[:4], 2),
        "2車複 AI上位3車BOX": box("2車複", A[:3], 2),
        "ワイド ◎-○": [("ワイド", key("ワイド", (a1, a2)))],
        "ワイド ◎-AI2,3": axis("ワイド", a1, A[:3], 2),
        "ワイド 妙味車-AI上位2車": axis("ワイド", value, [x for x in A if x != value][:2] + [value], 2),
        "3連複 AI上位3車BOX": box("3連複", A[:3], 3),
        "3連複 AI上位4車BOX": box("3連複", A[:4], 3),
        "3連複 ◎軸-AI2〜5": axis("3連複", a1, A[:5], 3),
        "3連単 ◎→○→AI3": [("3連単", key("3連単", A[:3]))],
        "3連単 ◎→AI2,3→AI2〜5": [("3連単", key("3連単", (a1, b, c))) for b in A[1:3] for c in A[1:5] if c != b],
        "3連単 ◎,○→◎,○→AI3〜5": [("3連単", key("3連単", (x, y, c))) for x, y in [(a1, a2), (a2, a1)] for c in A[2:5]],
        "2車単 妙味車→AI上位2車": [("2車単", key("2車単", (value, x))) for x in [y for y in A if y != value][:2]],
    }
    if mate:
        S["2車複 ◎-ライン仲間"] = [("2車複", key("2車複", (a1, x))) for x in mate]
        S["ワイド ◎-ライン仲間"] = [("ワイド", key("ワイド", (a1, x))) for x in mate]
        S["3連複 ◎軸-ライン仲間-AI上位"] = sorted({("3連複", key("3連複", (a1, x, y))) for x in mate
                                             for y in A[:5] if y not in (a1, x)})
    if behind:
        S["2車単 ◎→番手"] = [("2車単", key("2車単", (a1, behind)))]
        S["2車単 番手→◎"] = [("2車単", key("2車単", (behind, a1)))]
        S["2車複 ◎-番手"] = [("2車複", key("2車複", (a1, behind)))]
        S["3連単 ◎→番手→AI上位3"] = [("3連単", key("3連単", (a1, behind, c))) for c in [x for x in A if x not in (a1, behind)][:3]]
        S["3連単 ◎,番手→◎,番手→全"] = [("3連単", key("3連単", (x, y, c))) for x, y in [(a1, behind), (behind, a1)]
                                     for c in A if c not in (a1, behind)]
    if len(L1) >= 3:
        S["3連単 ◎ラインで並び通り"] = [("3連単", key("3連単", L1[:3]))]
        S["3連複 ◎ライン3車"] = [("3連複", key("3連複", L1[:3]))]
    if len(Lm) >= 2 and Lm[0] != m1 or len(Lm) >= 2:
        S["2車単 人気ライン先頭→番手"] = [("2車単", key("2車単", (Lm[0], Lm[1])))]
        S["2車単 人気ライン番手→先頭"] = [("2車単", key("2車単", (Lm[1], Lm[0])))]
    # 人気薄ラインの裏目: AIが市場より評価するライン(◎ラインが市場3番手以下のライン)
    return S


def race_table(W, odds):
    recs, feats = [], []
    for rid, g in W.groupby("race_id", sort=False):
        o = odds.get(rid)
        if not o or not o.get("final") or len(g) < 5:
            continue
        g = g.sort_values("p_ai", ascending=False)
        A = g.car.astype(int).tolist()
        M = g.sort_values("p_mkt", ascending=False).car.astype(int).tolist()
        line_of = {int(c): (int(l), int(p)) for c, l, p in zip(g.car, g.line_no.fillna(-1), g.line_pos.fillna(0))}
        lines = {}
        for c, (l, p) in sorted(line_of.items(), key=lambda x: (x[1][0], x[1][1])):
            lines.setdefault(l, []).append(c)
        ratio = (g.p_ai / g.p_mkt).to_numpy()
        value = A[int(np.argmax(ratio[:4]))]
        t = g.iloc[0]
        mrank = {c: i + 1 for i, c in enumerate(M)}
        L1 = lines[line_of[A[0]][0]]
        line_mkt = {l: g[g.line_no == l].p_mkt.sum() for l in lines}
        line_rank_mkt = {l: i + 1 for i, (l, _) in enumerate(sorted(line_mkt.items(), key=lambda x: -x[1]))}
        feats.append(dict(
            race_id=rid, date=t.date, ai1_p=t.p_ai, ai_gap=t.p_ai - g.iloc[1].p_ai, ai1_mrank=mrank[A[0]],
            ai1_pm=t.p_mkt, ai1_ratio=ratio[0], fav_pm=g.p_mkt.max(), n=len(g), line_type=str(t.line_type),
            grade=str(t.grade), klass=str(t["class"]), race_type=str(t.race_type), ai1_pos=int(line_of[A[0]][1]),
            ai1_linesize=len(L1), ai1_style=str(t["style"]), ai12_same_line=int(line_of[A[0]][0] == line_of[A[1]][0]),
            ai1_line_mrank=line_rank_mkt[line_of[A[0]][0]],
        ))
        pay = o["payoff"]
        for name, tickets in structures(A, M, line_of, lines, value).items():
            tickets = list(dict.fromkeys(tickets))
            if tickets:
                recs.append((rid, name, len(tickets), sum(float(pay.get(b, {}).get(c, 0) or 0) for b, c in tickets)))
    return pd.DataFrame(recs, columns=["race_id", "structure", "n", "ret"]), pd.DataFrame(feats).set_index("race_id")


def conditions(F):
    return {
        "全レース": pd.Series(True, index=F.index),
        "◎=1人気": F.ai1_mrank == 1, "◎=2〜3人気": F.ai1_mrank.between(2, 3), "◎=4人気以下": F.ai1_mrank >= 4,
        "◎AI1着率50%以上": F.ai1_p >= 0.5, "◎AI1着率30%未満": F.ai1_p < 0.3,
        "◎と○の差20pt以上": F.ai_gap >= 0.2, "◎と○の差5pt未満": F.ai_gap < 0.05,
        "◎が過小評価(AI/市場≧1.3)": F.ai1_ratio >= 1.3, "◎が過大人気(AI/市場<0.8)": F.ai1_ratio < 0.8,
        "1番人気の1着率50%以上": F.fav_pm >= 0.5, "1番人気の1着率30%未満(混戦)": F.fav_pm < 0.3,
        "7車": F.n == 7, "9車": F.n == 9,
        "二分戦": F.line_type == "二分戦", "三分戦": F.line_type == "三分戦", "細切れ・四分戦": F.line_type.isin(["細切れ", "四分戦"]),
        "F2": F.grade == "F2", "F1": F.grade == "F1", "G戦": F.grade.str.startswith("G"),
        "A級": F.klass == "A級", "S級": F.klass == "S級", "ガールズ": F.klass == "L級",
        "決勝・準決勝": F.race_type.isin(["決勝", "準決勝"]), "予選": F.race_type.str.contains("予選"),
        "◎がライン先頭": F.ai1_pos == 0, "◎が番手": F.ai1_pos == 1, "◎が単騎": F.ai1_linesize == 1,
        "◎が逃": F.ai1_style == "逃", "◎が追": F.ai1_style == "追",
        "◎と○が同じライン": F.ai12_same_line == 1, "◎ラインが市場2番手以下": F.ai1_line_mrank >= 2,
    }


def evaluate(R, F, select_until):
    conds = conditions(F)
    names = list(conds)
    is_sel = pd.to_datetime(F.date) < select_until
    pn = R.pivot(index="race_id", columns="structure", values="n").reindex(F.index).fillna(0)
    pr = R.pivot(index="race_id", columns="structure", values="ret").reindex(F.index).fillna(0)
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
            n, r = pn[m].sum(), pr[m].sum()
            for s in pn.columns:
                if n[s]:
                    rows.append(dict(cond=" & ".join(cond), structure=s, period=period, races=int((pn[m][s] > 0).sum()),
                                     tickets=int(n[s]), roi=r[s] / (n[s] * 100)))
    res = pd.DataFrame(rows)
    wide = res.pivot_table(index=["cond", "structure"], columns="period", values=["roi", "races", "tickets"])
    wide.columns = [f"{x}_{y}" for x, y in wide.columns]
    return wide.reset_index()


def bootstrap(R, F, cond, structure, select_until, n_boot=2000, exclude_top=5):
    conds = conditions(F)
    mask = pd.Series(True, index=F.index)
    for x in cond.split(" & "):
        mask &= conds[x].fillna(False)
    mask &= pd.to_datetime(F.date) >= select_until
    sub = R[(R.structure == structure) & R.race_id.isin(F.index[mask])]
    if sub.empty:
        return np.nan, np.nan, np.nan
    n, ret = sub.n.to_numpy(), sub.ret.to_numpy()
    rng = np.random.default_rng(0)
    idx = rng.integers(0, len(sub), (n_boot, len(sub)))
    bs = ret[idx].sum(1) / (n[idx].sum(1) * 100)
    trimmed = np.sort(ret)[: max(len(ret) - exclude_top, 0)].sum() / (n.sum() * 100)
    return np.percentile(bs, 2.5), np.percentile(bs, 97.5), trimmed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("preds")
    ap.add_argument("odds")
    ap.add_argument("--select-until", default="2026-03-01")
    ap.add_argument("--min-races", type=int, default=500)
    ap.add_argument("--out", default="wt_strategy_search.csv")
    a = ap.parse_args()
    W = pd.read_parquet(a.preds)
    odds = {}
    with gzip.open(a.odds, "rt") as f:
        for line in f:
            o = json.loads(line)
            odds[str(o["race_id"]).zfill(12)] = o
    R, F = race_table(W, odds)
    R.to_parquet(a.out.replace(".csv", "_races.parquet"))
    F.to_parquet(a.out.replace(".csv", "_feats.parquet"))
    E = evaluate(R, F, a.select_until)
    E.to_csv(a.out, index=False)
    sel = int((pd.to_datetime(F.date) < a.select_until).sum())
    print(f"レース数 {len(F)}(選定 {sel} / 検証 {len(F) - sel})/ 組み方×条件 {len(E)}")
    base = E[E.cond == "全レース"].sort_values("roi_選定", ascending=False)
    print("\n■ 条件なし(全レース)")
    print(base[["structure", "races_選定", "roi_選定", "roi_検証"]].to_string(index=False, float_format="%.3f"))
    cand = E[(E.races_選定 >= a.min_races) & (E.roi_選定 >= 1.0)].sort_values("roi_選定", ascending=False)
    print(f"\n■ 選定で回収率100%以上(選定{a.min_races}R以上): {len(cand)}件")
    if len(cand):
        print(f"  → 検証での回収率: 平均 {cand.roi_検証.mean():.3f} / 100%超の割合 {(cand.roi_検証 > 1).mean():.2f}")
        top = cand.head(30).copy()
        ci = [bootstrap(R, F, r.cond, r.structure, a.select_until) for r in top.itertuples()]
        top["検証95%下限"], top["検証95%上限"], top["検証 上位5本除く"] = zip(*ci)
        print(top[["cond", "structure", "races_選定", "roi_選定", "races_検証", "roi_検証", "検証95%下限", "検証95%上限",
                   "検証 上位5本除く"]].to_string(index=False, float_format="%.3f"))
    both = E[(E.races_選定 >= a.min_races) & (E.races_検証 >= a.min_races // 2)].copy()
    both["低い方"] = both[["roi_選定", "roi_検証"]].min(axis=1)
    print("\n■ 両期間とも安定して高い(低い方の回収率で並べた上位15)")
    print(both.sort_values("低い方", ascending=False).head(15)[["cond", "structure", "races_選定", "roi_選定", "races_検証",
                                                              "roi_検証"]].to_string(index=False, float_format="%.3f"))


if __name__ == "__main__":
    main()
