"""
競輪: サイトのAIが出す確率を全部使った、3連単の買い方の総当たり検証。

入力: wt_replay_model.py の出力 wt_model_replay.npz(1着率・2着率・3着率・3着内率・3連単出目確率・拮抗/本命判定・確定オッズ)

買い方(どれも3連単・各100円):
  [出目] AI出目確率の上位N点 / 確率q以上を全部 / 確率の累積X%まで / 期待値(確率×確定オッズ)t以上 / 期待値t以上かつ確率q以上
  [フォーメ] 1列目=1着率a以上、2列目=2着率b以上、3列目=3着率c以上(a,b,c=5〜50%)
  [BOX] 3着内率x以上の選手のBOX
  [軸] AI1位を1着固定 → 2着率上位k → 3着率上位m
レースの条件: 拮抗レース / 本命レース / 1位と2位の差 / AI1位の1着率 / 車立て / 級班 / グレード / 並びの形 と、その2つの組合せ。
期間: --select-until より前で選び、以降で確かめる。選定の成績だけで選んだ上位が検証でどうなるかも出す(偶然の当てはまりの確認)。

使い方: python scripts/wt_model_search.py data/wt_model_replay.npz --select-until 2026-01-01

結果(2026-11-10、2025年で選定→2026年で検証、50,568レース、400買い方×191条件=46,284通り):
  条件なしで最も良いのは「出目確率10〜15%以上の1点」で回収率83〜85%。期待値で買うと50〜72%(AIの出目確率が過大なため)。
  選定上位は検証で崩れる(上位10: 281%→53%、上位1000: 122%→76%)。全体でも検証100%超は3.6%で偶然以下。勝てる物は無し。
"""
import argparse
from itertools import combinations

import numpy as np
import pandas as pd

TOPN = [1, 2, 3, 5, 8, 10, 15, 20, 30]
PQ = [0.005, 0.01, 0.02, 0.03, 0.05, 0.08, 0.10, 0.15]
COVER = [0.2, 0.3, 0.5, 0.7]
EVT = [0.8, 1.0, 1.2, 1.5, 2.0, 3.0]
EVQ = [0.005, 0.01, 0.02]
FTH = [0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50]
BOXP = [0.3, 0.4, 0.5, 0.6]
AXK = [(2, 2), (2, 3), (2, 4), (3, 3), (3, 4), (3, 5), (4, 4), (4, 6)]


def strategy_names():
    S = [f"出目 上位{N}点" for N in TOPN] + [f"出目 確率{q:.1%}以上" for q in PQ] + [f"出目 累積{c:.0%}まで" for c in COVER]
    for t in EVT:
        S.append(f"期待値{t}以上")
        S += [f"期待値{t}以上&確率{q:.1%}以上" for q in EVQ]
    S += [f"フォーメ 1着{a:.0%}→2着{b:.0%}→3着{c:.0%}" for a in FTH for b in FTH for c in FTH]
    S += [f"BOX 3着内率{x:.0%}以上" for x in BOXP]
    S += [f"軸 AI1位→2着率上位{k}→3着率上位{m}" for k, m in AXK]
    return S


STRATS = strategy_names()
META = ["race_id", "date", "n", "grade", "cls", "rt", "lt", "payout", "close", "high", "gap", "pmax", "maxplace", "p_win", "ev_win"]


def race_row(r):
    """1レース -> (メタ情報dict, 点数配列, 的中配列)。STRATS の順"""
    cars = sorted(r["p1"])
    w1, w2, w3 = r["win"]
    tk, ht = [], []
    tri, odds = r["tri"], r["odds"]
    keys = list(tri)
    pr = np.array([tri[k] for k in keys])
    od = np.array([odds.get(k, np.nan) for k in keys])
    evv = np.nan_to_num(pr * od, nan=0.0)
    pw = tri.get(r["win"], 0.0)
    ow = odds.get(r["win"], np.nan)
    evw = pw * ow if pw and ow == ow else 0.0
    rank_w = int((pr > pw).sum()) + 1 if r["win"] in tri else 10 ** 6
    cum = np.cumsum(np.sort(pr)[::-1])
    for N in TOPN:
        tk.append(min(N, len(keys))); ht.append(rank_w <= N)
    for q in PQ:
        tk.append(int((pr >= q).sum())); ht.append(pw >= q)
    for c in COVER:
        k = int(np.searchsorted(cum, c) + 1)
        tk.append(k); ht.append(rank_w <= k)
    for t in EVT:
        tk.append(int((evv >= t).sum())); ht.append(evw >= t)
        for q in EVQ:
            tk.append(int(((evv >= t) & (pr >= q)).sum())); ht.append((evw >= t) and (pw >= q))
    p1 = np.array([r["p1"][c] for c in cars])
    p2 = np.array([r["p2"].get(c, 0) for c in cars])
    p3 = np.array([r["p3"].get(c, 0) for c in cars])
    ci = {c: i for i, c in enumerate(cars)}
    A = {a: p1 >= a for a in FTH}
    B = {b: p2 >= b for b in FTH}
    C = {c: p3 >= c for c in FTH}
    for a in FTH:
        for b in FTH:
            for c in FTH:
                x, y, z = A[a], B[b], C[c]
                cnt = x.sum() * y.sum() * z.sum() - (x & y).sum() * z.sum() - (x & z).sum() * y.sum() \
                    - (y & z).sum() * x.sum() + 2 * (x & y & z).sum()
                cnt = max(int(cnt), 0)
                tk.append(cnt); ht.append(bool(cnt and x[ci[w1]] and y[ci[w2]] and z[ci[w3]]))
    pl = np.array([r["place"][c] for c in cars])
    for x in BOXP:
        m = pl >= x
        k = int(m.sum())
        tk.append(k * (k - 1) * (k - 2) if k >= 3 else 0)
        ht.append(bool(k >= 3 and m[ci[w1]] and m[ci[w2]] and m[ci[w3]]))
    top = cars[int(np.argmax(p1))]
    o2 = [c for c in sorted(cars, key=lambda c: -r["p2"].get(c, 0)) if c != top]
    o3 = [c for c in sorted(cars, key=lambda c: -r["p3"].get(c, 0)) if c != top]
    for k, m in AXK:
        S2, S3 = o2[:k], o3[:m]
        tk.append(sum(1 for b in S2 for c in S3 if c != b))
        ht.append((w1 == top) and (w2 in S2) and (w3 in S3))
    meta = dict(race_id=r["race_id"], date=r["date"], n=len(cars), grade=r["grade"], cls=r["class"], rt=r["race_type"],
                lt=r["line_type"], payout=r["payout"], close=r["close"], high=r["high"], gap=r["top_gap"] or 0,
                pmax=float(p1.max()), maxplace=r["max_place"], p_win=pw, ev_win=evw)
    return meta, np.array(tk, dtype=np.int32), np.array(ht, dtype=bool)


def load(path):
    z = np.load(path, allow_pickle=False)
    D = pd.read_parquet(path.replace(".npz", "_meta.parquet"))
    return D, z["tk"], z["hit"]


def conditions(D):
    g = D.grade.astype(str)
    c = {
        "全レース": np.ones(len(D), bool),
        "拮抗レース": D.close.to_numpy(), "本命レース(1着率55%以上)": D.high.to_numpy(),
        "1位2位の差5pt未満": (D.gap < 5).to_numpy(), "1位2位の差15pt以上": (D.gap >= 15).to_numpy(),
        "AI1位の1着率30%未満": (D.pmax < 0.30).to_numpy(), "AI1位の1着率30〜45%": D.pmax.between(0.30, 0.45).to_numpy(),
        "AI1位の1着率45%以上": (D.pmax > 0.45).to_numpy(),
        "7車": (D.n == 7).to_numpy(), "9車": (D.n == 9).to_numpy(),
        "A級": (D.cls == "A級").to_numpy(), "S級": (D.cls == "S級").to_numpy(), "ガールズ": (D.cls == "L級").to_numpy(),
        "F2": (g == "F2").to_numpy(), "F1": (g == "F1").to_numpy(), "G戦": g.str.startswith("G").to_numpy(),
        "決勝・準決勝": D.rt.isin(["決勝", "準決勝"]).to_numpy(),
        "二分戦": (D["lt"] == "二分戦").to_numpy(), "三分戦": (D["lt"] == "三分戦").to_numpy(),
        "細切れ・四分戦": D["lt"].isin(["細切れ", "四分戦"]).to_numpy(),
    }
    names = list(c)
    for x, y in combinations(names[1:], 2):
        c[f"{x} & {y}"] = c[x] & c[y]
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("replay")
    ap.add_argument("--select-until", default="2026-01-01")
    ap.add_argument("--out", default="wt_model_search.csv")
    ap.add_argument("--min-hits", type=int, default=30)
    a = ap.parse_args()
    D, TKa, HTa = load(a.replay)
    sel = (D.date < a.select_until.replace("-", "")).to_numpy()
    pay = D.payout.to_numpy()
    strats = STRATS
    C = conditions(D)
    TK = TKa.astype(np.float64)
    HT = HTa & (TK > 0)
    PH = HT * pay[:, None]
    cn_list = list(C)
    M = np.stack([C[c] for c in cn_list], axis=1).astype(np.float64)
    rows = []
    for per, pm in (("sel", sel), ("val", ~sel)):
        Mp = M * pm[:, None]
        T = Mp.T @ TK                    # 条件 × 買い方 の点数合計
        P = Mp.T @ PH                    # 払戻合計
        H = Mp.T @ HT.astype(np.float64)  # 的中数
        NR = Mp.T @ (TK > 0).astype(np.float64)
        for i, cn in enumerate(cn_list):
            for j, st in enumerate(strats):
                if T[i, j] > 0:
                    rows.append((cn, st, per, int(NR[i, j]), int(T[i, j]), int(H[i, j]), P[i, j] / (T[i, j] * 100)))
    R = pd.DataFrame(rows, columns=["cond", "bet", "period", "races", "tickets", "hits", "roi"])
    W = R.pivot_table(index=["cond", "bet"], columns="period", values=["races", "tickets", "hits", "roi"])
    W.columns = [f"{x}_{y}" for x, y in W.columns]
    W = W.reset_index()
    W.to_csv(a.out, index=False)
    pd.set_option("display.width", 260)
    print(f"レース {len(D):,}(選定 {sel.sum():,} / 検証 {(~sel).sum():,})、買い方 {len(strats)}種 × 条件 {len(C)} = {len(W):,}通り")
    W["fam"] = W.bet.str.split(" ").str[0].str.replace(r"\d.*", "", regex=True)
    base = W[W.cond == "全レース"]
    print("\n■ 条件なし: 買い方の系統ごと(平均・最高)")
    print(base.groupby("fam")[["roi_sel", "roi_val"]].agg(["mean", "max"]).to_string(float_format="%.3f"))
    print("\n■ 条件なし: 出目確率・期待値の買い方")
    cols = ["bet", "races_sel", "tickets_sel", "hits_sel", "roi_sel", "hits_val", "roi_val"]
    print(base[base.bet.str.startswith(("出目", "期待値"))][cols].to_string(index=False, float_format="%.3f"))
    print("\n■ 拮抗レース・本命レースでの出目・BOX・軸")
    for cn in ["拮抗レース", "本命レース(1着率55%以上)"]:
        s = W[(W.cond == cn) & W.bet.str.startswith(("出目 上位", "BOX", "軸"))]
        print("--", cn)
        print(s[cols].to_string(index=False, float_format="%.3f"))
    cand = W[W.hits_sel >= a.min_hits]
    print(f"\n■ 選定の成績だけで選んだ上位 → 検証(選定の的中{a.min_hits}回以上 {len(cand):,}通り)")
    for top in (10, 50, 200, 1000, 5000):
        t = cand.sort_values("roi_sel", ascending=False).head(top)
        print(f"  上位{top}: 選定 {t.roi_sel.mean():.3f} → 検証 {t.roi_val.mean():.3f}(検証100%超 {(t.roi_val > 1).mean():.2f})")
    print(f"  (参考)全{len(cand):,}通りの検証平均 {cand.roi_val.mean():.3f}、検証100%超 {(cand.roi_val > 1).mean():.3f}")
    print(cand.sort_values("roi_sel", ascending=False).head(25)[["cond"] + cols + ["races_val"]].to_string(index=False, float_format="%.3f"))


if __name__ == "__main__":
    main()
