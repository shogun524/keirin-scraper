"""
競輪: レースごとの「万車率(3連単が1万円以上になる確率)」と「配当の目安(中央値・25〜75%の範囲)」。

やり方: 3連単の全組のオッズから、各組が来る確率を q ∝ (1/オッズ)^β で出す(β>1 は「人気薄ほど買われすぎ」の補正)。
  万車率   = オッズ100倍以上の組の q の合計
  配当目安 = q で重み付けした「オッズ×100円」の中央値と、33〜67%点の範囲(真ん中3分の1)
           (11/13: 以前は「確率50%を含む一番狭い範囲(幅4倍)」だったが、範囲が安い側に寄り、
            実際の払戻が上に外れる42%・下に外れる8%と偏っていたので戻した。25〜75%点なら上24%・下19%、幅約7倍)
β は過去レースの「実際に来た組」の当たりやすさが最大になる値(2025年で 1.05)。

検証(2025年で β を決め → 2026年 23,000レース):
  万車率: 予測と実際がほぼ一致(予測10〜20%→実際13.9%、20〜30%→24.3%、30〜40%→35.2%、50〜60%→53.8%)。
  機械学習(LightGBM・ロジスティック、出走表の特徴も入れた物)と比べても当たり具合はほぼ同じ(対数損失 0.548 vs 0.547)なので、
  オッズだけで出すこの方式を使う(締切前のオッズでその場で計算できる)。
  配当目安: 範囲の出し方ごとの「実際の払戻が範囲に入った割合・上に外れ・下に外れ・幅」(2026年)
    25〜75%点 57%・24%・19%・7.0倍 / 33〜67%点 38%・34%・28%・3.4倍(11/13 狭くしたいとの要望でこちらにした)
  中穴率(5,000円以上): 予測30〜40%→実際37%、50〜60%→55%、70%以上→77%

使い方(検証): python scripts/wt_manshaken.py data/ --fit-until 2026-01-01
本番: wt_picks.py から market_view() を呼ぶ。
"""
import argparse
import gzip
import json

import numpy as np

BETA = 1.05
MAN = 100.0  # 万車 = 100倍(1万円)以上
CHU = 50.0   # 中穴 = 50倍(5,000円)以上


def shortest_interval(values, weights, mass=0.5):
    """重み付き分布で、確率 mass を含む「対数で一番狭い」区間 (下限, 上限)。
    25〜75%点より狭くなる(配当の分布は人気決着側に山があり、穴側に長く伸びるため)"""
    idx = np.argsort(values)
    v = np.asarray(values, dtype=float)[idx]
    lv = np.log(v)
    c = np.concatenate([[0.0], np.cumsum(np.asarray(weights, dtype=float)[idx])])
    best, j = (np.inf, v[0], v[-1]), 0
    for i in range(len(v)):
        while j < len(v) and c[j + 1] - c[i] < mass:
            j += 1
        if j >= len(v):
            break
        if lv[j] - lv[i] < best[0]:
            best = (lv[j] - lv[i], v[i], v[j])
    return float(best[1]), float(best[2])


def market_view(odds, beta=BETA):
    """odds: 3連単オッズの配列(または {組: オッズ})。-> dict(man=万車率, q25, q50, q75=配当の目安(円))。オッズが無ければ None"""
    if isinstance(odds, dict):
        odds = list(odds.values())
    o = np.array([v for v in odds if v and v > 0], dtype=float)
    if len(o) < 10:
        return None
    q = (1 / o) ** beta
    q /= q.sum()
    idx = np.argsort(o)
    c = np.cumsum(q[idx])
    v = o[idx] * 100
    at = lambda p: float(v[min(int(np.searchsorted(c, p)), len(c) - 1)])  # noqa: E731
    # 範囲は「真ん中3分の1」(33〜67%点)。狭く、上に外れる・下に外れるが同じくらいになる
    # chu = 中穴率(3連単が5,000円以上になる確率。2026年の検証で予測と実際がほぼ一致)
    return dict(man=float(q[o >= MAN].sum()), q25=at(1 / 3), q50=at(0.5), q75=at(2 / 3), chu=float(q[o >= CHU].sum()))


def load(path):
    out = []
    with gzip.open(path, "rt") as f:
        for line in f:
            o = json.loads(line)
            if not o.get("final"):
                continue
            ks, vs = [], []
            for k, v, *_ in o["odds"].get("3連単", []):
                try:
                    vs.append(float(v))
                    ks.append(k)
                except (TypeError, ValueError):
                    pass
            pay = o["payoff"].get("3連単", {})
            if not vs or not pay:
                continue
            wk = max(pay, key=lambda k: float(pay[k] or 0))
            if wk not in ks or not float(pay[wk] or 0):
                continue
            out.append((str(o["race_id"]).zfill(12), np.array(vs, dtype=np.float64), ks.index(wk), float(pay[wk])))
    return out


def main():
    import pandas as pd
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir")
    ap.add_argument("--fit-until", default="2026-01-01")
    a = ap.parse_args()
    races = load(f"{a.data_dir}/wt_odds.jsonl.gz")
    r = pd.read_csv(f"{a.data_dir}/wt_races.csv", dtype={"race_id": str, "date": str})
    dmap = dict(zip(r.race_id.str.zfill(12), r.date))
    fit = np.array([dmap.get(x[0], "") < a.fit_until.replace("-", "") for x in races])

    def nll(b):
        s = 0.0
        for (rid, o, i, p), m in zip(races, fit):
            if m:
                w = (1 / o.astype(float)) ** b
                s -= np.log(w[i] / w.sum())
        return s / fit.sum()
    grid = [0.9, 1.0, 1.05, 1.1, 1.15, 1.2]
    scores = {b: nll(b) for b in grid}
    beta = min(scores, key=scores.get)
    print("β ごとの当たりやすさ(小さいほど良い):", {k: round(v, 4) for k, v in scores.items()}, "→ β =", beta)
    rows = []
    for (rid, o, i, p), m in zip(races, fit):
        if not m:
            v = market_view(o, beta)
            rows.append(dict(man_pred=v["man"], q25=v["q25"], q50=v["q50"], q75=v["q75"], pay=p))
    T = pd.DataFrame(rows)
    T["man"] = (T.pay >= 10000).astype(int)
    T["bin"] = pd.cut(T.man_pred, [0, .1, .2, .3, .4, .5, .6, 1])
    print(f"検証 {len(T):,}レース")
    print(T.groupby("bin", observed=True).agg(レース=("man", "size"), 予測万車率=("man_pred", "mean"), 実際=("man", "mean"),
                                              配当目安の中央値=("q50", "median"), 実際の払戻の中央値=("pay", "median"))
          .to_string(float_format="%.3f"))
    print(f"実際の払戻が目安の範囲(25〜75%点)に入った割合: {((T.pay >= T.q25) & (T.pay <= T.q75)).mean():.3f}"
          f" / 幅(上限÷下限)の中央値 {(T.q75 / T.q25).median():.1f}倍")


if __name__ == "__main__":
    main()
