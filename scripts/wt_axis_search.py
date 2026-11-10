"""
競輪: 3連単の「軸を決めて流す」買い方・フォーメーション・複数買いの検証。

軸(8通り): 印◎ / 競走得点1位 / 1番人気 / 2番人気 / 印で最強ラインの先頭・番手 / 2番目のラインの先頭・番手
相手の並べ方(3通り): 予想印順(K) / 競走得点順(P) / 市場順(M=確定オッズ。締切前で近似できるかは要確認)
買い方(相手k頭、k=2〜5):
  1着固定(軸→相手→相手) / 2着固定 / 3着固定 / 1・2着マルチ / 軸1頭マルチ(1〜3着どこでも)
  2頭軸(軸と相手1番手): 1-2着固定(軸→相手1→相手) / 表裏 / 2頭軸マルチ
  フォーメーション 軸→相手上位2→相手k / 相手上位2→軸→相手k
  BOX(軸+相手k-1頭) / ライン(軸→番手→相手、番手→軸→相手、その表裏)
複数買い: 2025年の成績だけで選んだ上位の買い方をまとめて買ったときの2026年の成績も出す。

レースごとに実際の1〜3着が「軸か・相手の何番手か」を計算しておき、的中と点数は式で数える(買い目を列挙しない)ので速い。

使い方: python scripts/wt_axis_search.py data/ --select-until 2026-01-01

結果(2026-11-10、2025年で選定→2026年で検証、8軸×3並べ方×56買い方×9条件=12,096通り):
  どの型も全レース平均で回収率67〜69%(控除どおり)。2025年の上位10個は2026年に平均83%、まとめ買いでも74〜81%。
  一貫していたのは「9車・G戦で2番目のライン先頭を1着固定→相手2頭」で、ほぼ100%(勝ちとは言えない)。
"""
import argparse
import gzip
import json

import numpy as np
import pandas as pd

MARK_PT = {1: 4, 2: 3, 3: 2, 4: 1}
AXES = ["印◎", "得点1位", "1番人気", "2番人気", "最強ライン先頭", "最強ライン番手", "2番手ライン先頭", "2番手ライン番手"]
LISTS = ["K", "P", "M"]
BIG = 99


def summarize(d):
    r = pd.read_csv(f"{d}/wt_races.csv", dtype={"race_id": str, "date": str})
    e = pd.read_csv(f"{d}/wt_entries.csv", dtype={"race_id": str})
    r["race_id"] = r.race_id.str.zfill(12)
    e["race_id"] = e.race_id.str.zfill(12)
    r = r.drop_duplicates("race_id").set_index("race_id")
    e = e[e.absent == 0].drop_duplicates(["race_id", "car"])
    odds = {}
    with gzip.open(f"{d}/wt_odds.jsonl.gz", "rt") as f:
        for line in f:
            o = json.loads(line)
            if o.get("final"):
                odds[str(o["race_id"]).zfill(12)] = o
    rows = []
    for rid, g in e.groupby("race_id"):
        if rid not in r.index or rid not in odds or not isinstance(r.at[rid, "line_text"], str):
            continue
        o = odds[rid]
        cars = sorted(set(g.car.astype(int)))
        fin = dict(zip(g.car.astype(int), pd.to_numeric(g.finish, errors="coerce")))
        top = sorted([c for c in cars if fin.get(c) in (1, 2, 3)], key=lambda c: fin[c])
        if len(top) != 3 or len({fin[c] for c in top}) != 3:
            continue
        payout = float(o["payoff"].get("3連単", {}).get(".".join(map(str, top)), 0) or 0)
        mk = dict(zip(g.car.astype(int), g.mark.fillna(0).astype(int)))
        pt = dict(zip(g.car.astype(int), g.race_point.fillna(0)))
        mw = {}
        for c, od, *_ in o["odds"].get("2車単", []):
            try:
                a, x = int(str(c).split(".")[0]), float(od)
            except (TypeError, ValueError):
                continue
            if x > 0:
                mw[a] = mw.get(a, 0) + 1 / x
        score = {"K": {c: MARK_PT.get(mk.get(c, 0), 0) + 0.001 * pt.get(c, 0) for c in cars},
                 "P": {c: pt.get(c, 0) for c in cars},
                 "M": {c: mw.get(c, 0) for c in cars}}
        order = {k: sorted(cars, key=lambda c: -v[c]) for k, v in score.items()}
        lines = [[int(x) for x in s.split("-") if x and int(x) in cars] for s in r.at[rid, "line_text"].split(",")]
        lines = [L for L in lines if L]
        if len(lines) < 2:
            continue
        ls = [sum(MARK_PT.get(mk.get(c, 0), 0) for c in L) + 0.001 * np.mean([pt.get(c, 0) for c in L]) for L in lines]
        lo = [lines[i] for i in sorted(range(len(lines)), key=lambda i: -ls[i])]
        axis = {"印◎": order["K"][0], "得点1位": order["P"][0], "1番人気": order["M"][0], "2番人気": order["M"][1],
                "最強ライン先頭": lo[0][0], "最強ライン番手": lo[0][1] if len(lo[0]) > 1 else None,
                "2番手ライン先頭": lo[1][0], "2番手ライン番手": lo[1][1] if len(lo[1]) > 1 else None}
        line_of = {c: L for L in lines for c in L}
        rec = dict(race_id=rid, date=r.at[rid, "date"], n=len(cars), ltype=str(r.at[rid, "line_type"]),
                   cls=str(r.at[rid, "class"]), grade=str(r.at[rid, "grade"]), payout=payout)
        for ax, a in axis.items():
            if a is None:
                rec[f"{ax}|ok"] = 0
                continue
            rec[f"{ax}|ok"] = 1
            rec[f"{ax}|mrank"] = order["M"].index(a) + 1
            L = line_of[a]
            mate = L[L.index(a) + 1] if L.index(a) + 1 < len(L) else None
            # 実際の1〜3着が 軸(0) / 番手(-1) / 相手リストの何番手(1始まり、軸を除く) か
            for li in LISTS:
                partners = [c for c in order[li] if c != a]
                pos = {c: i + 1 for i, c in enumerate(partners)}
                for j, c in enumerate(top):
                    rec[f"{ax}|{li}|f{j + 1}"] = 0 if c == a else pos.get(c, BIG)
                # ライン番手の買い方用(相手は番手を除いて数え直す)
                if mate:
                    p2 = [c for c in order[li] if c not in (a, mate)]
                    pos2 = {c: i + 1 for i, c in enumerate(p2)}
                    for j, c in enumerate(top):
                        rec[f"{ax}|{li}|g{j + 1}"] = 0 if c == a else (-1 if c == mate else pos2.get(c, BIG))
                else:
                    for j in range(3):
                        rec[f"{ax}|{li}|g{j + 1}"] = np.nan
        rows.append(rec)
    return pd.DataFrame(rows)


def strategies(D, ax, li):
    """-> {名前: (的中の真偽配列, 1レースの点数配列)}。軸が無いレースは点数0"""
    ok = D[f"{ax}|ok"].to_numpy() == 1
    f1, f2, f3 = (D[f"{ax}|{li}|f{j}"].to_numpy() for j in (1, 2, 3))
    g1, g2, g3 = (D[f"{ax}|{li}|g{j}"].to_numpy() for j in (1, 2, 3))
    n = D.n.to_numpy()
    out = {}
    for k in (2, 3, 4, 5):
        kk = np.minimum(k, n - 1)  # 相手の数は出走数-1まで
        inP = lambda f: (f >= 1) & (f <= kk)  # noqa: E731
        t = kk * (kk - 1)
        out[f"1着固定 軸→相手{k}→相手{k}"] = ((f1 == 0) & inP(f2) & inP(f3), t)
        out[f"2着固定 相手{k}→軸→相手{k}"] = ((f2 == 0) & inP(f1) & inP(f3), t)
        out[f"3着固定 相手{k}→相手{k}→軸"] = ((f3 == 0) & inP(f1) & inP(f2), t)
        out[f"1・2着マルチ 相手{k}"] = (((f1 == 0) & inP(f2) & inP(f3)) | ((f2 == 0) & inP(f1) & inP(f3)), 2 * t)
        out[f"軸1頭マルチ 相手{k}"] = (((f1 == 0) & inP(f2) & inP(f3)) | ((f2 == 0) & inP(f1) & inP(f3)) |
                                  ((f3 == 0) & inP(f1) & inP(f2)), 3 * t)
        # 2頭軸: 軸 + 相手1番手(b)。残りは相手2..k+1 の k頭
        kq = np.minimum(k, n - 2)
        inQ = lambda f: (f >= 2) & (f <= kq + 1)  # noqa: E731
        out[f"2頭軸 軸→相手1→相手{k}"] = ((f1 == 0) & (f2 == 1) & inQ(f3), kq)
        out[f"2頭軸 表裏 相手{k}"] = ((((f1 == 0) & (f2 == 1)) | ((f1 == 1) & (f2 == 0))) & inQ(f3), 2 * kq)
        out[f"2頭軸マルチ 相手{k}"] = (((f1 == 0) | (f2 == 0) | (f3 == 0)) &
                                     ((f1 == 1) | (f2 == 1) | (f3 == 1)) &
                                     (inQ(f1) | inQ(f2) | inQ(f3)), 6 * kq)
        if k >= 3:
            out[f"フォーメ 軸→相手2→相手{k}"] = ((f1 == 0) & (f2 >= 1) & (f2 <= 2) & inP(f3), 2 * (kk - 1))
            out[f"フォーメ 相手2→軸→相手{k}"] = ((f2 == 0) & (f1 >= 1) & (f1 <= 2) & inP(f3), 2 * (kk - 1))
            out[f"フォーメ 軸→相手{k}→相手2"] = ((f1 == 0) & inP(f2) & (f3 >= 1) & (f3 <= 2), 2 * (kk - 1))
            kb = np.minimum(k, n)
            out[f"BOX 軸+相手{k - 1}"] = ((f1 <= k - 1) & (f2 <= k - 1) & (f3 <= k - 1), kb * (kb - 1) * (kb - 2))
        # ライン番手(番手がいるレースだけ)
        has = ~np.isnan(g1)
        kl = np.minimum(k, n - 2)
        inR = lambda g: (g >= 1) & (g <= kl)  # noqa: E731
        out[f"ライン 軸→番手→相手{k}"] = (has & (g1 == 0) & (g2 == -1) & inR(g3), np.where(has, kl, 0))
        out[f"ライン 番手→軸→相手{k}"] = (has & (g1 == -1) & (g2 == 0) & inR(g3), np.where(has, kl, 0))
        out[f"ライン 表裏 相手{k}"] = (has & (((g1 == 0) & (g2 == -1)) | ((g1 == -1) & (g2 == 0))) & inR(g3), np.where(has, 2 * kl, 0))
    return {name: (h & ok, np.where(ok, np.broadcast_to(t, len(D)), 0)) for name, (h, t) in out.items()}


def conditions(D):
    return {"全レース": np.ones(len(D), bool), "7車": (D.n == 7).to_numpy(), "9車": (D.n == 9).to_numpy(),
            "二分戦": (D.ltype == "二分戦").to_numpy(), "三分戦": (D.ltype == "三分戦").to_numpy(),
            "S級": (D.cls == "S級").to_numpy(), "A級": (D.cls == "A級").to_numpy(), "ガールズ": (D.cls == "L級").to_numpy(),
            "G戦": D.grade.str.startswith("G").to_numpy()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir")
    ap.add_argument("--select-until", default="2026-01-01")
    ap.add_argument("--out", default="wt_axis.csv")
    ap.add_argument("--min-hits", type=int, default=30)
    a = ap.parse_args()
    import os
    pk = a.out.replace(".csv", "_races.pkl")
    D = pd.read_pickle(pk) if os.path.exists(pk) else summarize(a.data_dir)
    D.to_pickle(pk)
    sel = (D.date < a.select_until.replace("-", "")).to_numpy()
    pay = D.payout.to_numpy()
    C = conditions(D)
    rows, keep = [], {}
    for ax in AXES:
        for li in LISTS:
            for name, (hit, tk) in strategies(D, ax, li).items():
                tk = tk.astype(float)
                for cn, cm in C.items():
                    r = {"axis": ax, "list": li, "bet": name, "cond": cn}
                    for p, pm in (("sel", sel), ("val", ~sel)):
                        m = cm & pm
                        T = tk[m].sum()
                        h = hit[m]
                        r[f"tickets_{p}"] = int(T)
                        r[f"races_{p}"] = int((tk[m] > 0).sum())
                        r[f"hits_{p}"] = int(h.sum())
                        r[f"roi_{p}"] = pay[m][h].sum() / (T * 100) if T else np.nan
                    rows.append(r)
                    keep[(ax, li, name, cn)] = (hit, tk)
    W = pd.DataFrame(rows)
    W.to_csv(a.out, index=False)
    pd.set_option("display.width", 250)
    print(f"レース {len(D):,}(選定 {sel.sum():,} / 検証 {(~sel).sum():,})/ 買い方×条件 {len(W):,}")

    print("\n■ 条件なし: 軸×買い方 の回収率(選定→検証)、相手は予想印順(K)。上位25")
    b = W[(W.cond == "全レース") & (W.list == "K")].sort_values("roi_sel", ascending=False)
    print(b.head(25)[["axis", "bet", "tickets_sel", "hits_sel", "roi_sel", "roi_val"]].to_string(index=False, float_format="%.3f"))

    print("\n■ 軸ごとの平均(全レース・全買い方)")
    g = W[W.cond == "全レース"].groupby("axis")[["roi_sel", "roi_val"]].mean().sort_values("roi_sel", ascending=False)
    print(g.to_string(float_format="%.3f"))
    print("\n■ 買い方の型ごとの平均(全レース・全軸)")
    W["型"] = W.bet.str.extract(r"^(\S+(?: \S+)?)")[0].str.replace(r"相手\d", "", regex=True)
    print(W[W.cond == "全レース"].groupby(W.bet.str.split(" ").str[0])[["roi_sel", "roi_val"]].mean().sort_values("roi_sel", ascending=False).to_string(float_format="%.3f"))

    cand = W[(W.hits_sel >= a.min_hits)].copy()
    print(f"\n■ 選定の成績だけで選んだ場合の検証(選定の的中{a.min_hits}回以上、{len(cand):,}件)")
    for top in (10, 50, 200, 1000):
        t = cand.sort_values("roi_sel", ascending=False).head(top)
        print(f"  選定ROI上位{top}: 選定 {t.roi_sel.mean():.3f} → 検証 {t.roi_val.mean():.3f}(100%超 {(t.roi_val > 1).mean():.2f})")
    best = cand.sort_values("roi_sel", ascending=False).head(30)
    print(best[["axis", "list", "bet", "cond", "tickets_sel", "hits_sel", "roi_sel", "tickets_val", "hits_val", "roi_val"]]
          .to_string(index=False, float_format="%.3f"))

    # 複数買い: 選定上位N個の買い方を全部まとめて買う(同じレースで重なった買い目は別々に数える=そのまま足す)
    print("\n■ 複数買い(選定の上位N個をまとめて買う)の検証")
    ranked = cand.sort_values("roi_sel", ascending=False)
    for N in (3, 5, 10, 20):
        T_s = P_s = T_v = P_v = 0.0
        for x in ranked.head(N).itertuples():
            hit, tk = keep[(x.axis, x.list, x.bet, x.cond)]
            m = C[x.cond]
            for p, pm in (("s", sel), ("v", ~sel)):
                mm = m & pm
                if p == "s":
                    T_s += tk[mm].sum(); P_s += pay[mm][hit[mm]].sum()
                else:
                    T_v += tk[mm].sum(); P_v += pay[mm][hit[mm]].sum()
        print(f"  上位{N}個: 選定 {P_s / (T_s * 100):.3f}({int(T_s):,}点) → 検証 {P_v / (T_v * 100):.3f}({int(T_v):,}点)")


if __name__ == "__main__":
    main()
