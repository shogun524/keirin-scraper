"""
競輪: レースごとの「万車率(3連単が1万円以上になる確率)」と「配当の目安(中央値・25〜75%の範囲)」。

やり方: 3連単の全組のオッズから、各組が来る確率を q ∝ (1/オッズ)^β で出す(β>1 は「人気薄ほど買われすぎ」の補正)。
  万車率   = オッズ100倍以上の組の q の合計
  配当目安 = q で重み付けした「オッズ×100円」の 25% / 50% / 75% 点
β は過去レースの「実際に来た組」の当たりやすさが最大になる値(2025年で 1.05)。

検証(2025年で β を決め → 2026年 23,000レース):
  万車率: 予測と実際がほぼ一致(予測10〜20%→実際13.9%、20〜30%→24.3%、30〜40%→35.2%、50〜60%→53.8%)。
  機械学習(LightGBM・ロジスティック、出走表の特徴も入れた物)と比べても当たり具合はほぼ同じ(対数損失 0.548 vs 0.547)なので、
  オッズだけで出すこの方式を使う(締切前のオッズでその場で計算できる)。
  配当目安: 実際の払戻が 25〜75%の範囲に入った割合 57%、帯ごとの中央値は実際とほぼ一致。

使い方(検証): python scripts/wt_manshaken.py data/ --fit-until 2026-01-01
本番: wt_picks.py から market_view() を呼ぶ。
"""
import argparse
import gzip
import json

import numpy as np

BETA = 1.05
MAN = 100.0  # 万車 = 100倍(1万円)以上


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
    qs = [float(o[idx][min(int(np.searchsorted(c, x)), len(c) - 1)] * 100) for x in (0.25, 0.5, 0.75)]
    return dict(man=float(q[o >= MAN].sum()), q25=qs[0], q50=qs[1], q75=qs[2])


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
            out.append((str(o["race_id"]).zfill(12), np.array(vs, dtype=np.float32), ks.index(wk), float(pay[wk])))
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
    print(f"実際の払戻が目安の25〜75%に入った割合: {((T.pay >= T.q25) & (T.pay <= T.q75)).mean():.3f}")


if __name__ == "__main__":
    main()
