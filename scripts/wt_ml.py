"""
競輪: winticket の過去データ(wt_backfill.py)から1着率モデルを学習し、市場(確定オッズ)と比べる + EVの検証。

やること
  1. 特徴量: 出走表の情報(競走得点・脚質・勝率・ライン・予想印・ギア…)+ 自前の過去成績(その日より前だけ)
  2. ウォークフォワード: 各期間を、それより前のデータだけで学習したモデルで予測
  3. 市場の1着率: 2車単オッズの逆数を1着の車番ごとに合計して正規化
  4. AI・市場・混合(条件付きロジット p ∝ p_ai^a p_mkt^b)の対数損失
  5. EV検証: 混合確率からハーヴィル式で 2車単/2車複/ワイド/3連単/3連複 の確率を出し、確定オッズ×確率=EV が
     閾値以上の買い目を全部買ったときの回収率(払戻は実際の確定払戻)

使い方:
  python scripts/wt_ml.py data/ --test-from 2025-07-01 --out data/wt_wf.parquet
"""
import argparse
import gzip
import json
from itertools import combinations, permutations

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.optimize import minimize

CAT = ["style", "venue_id", "grade", "class", "race_type", "line_type", "pref"]


def load(d):
    r = pd.read_csv(f"{d}/wt_races.csv", dtype={"race_id": str, "date": str})
    e = pd.read_csv(f"{d}/wt_entries.csv", dtype={"race_id": str})
    for x in (r, e):
        x["race_id"] = x["race_id"].str.zfill(12)
    r = r.drop_duplicates("race_id")
    e = e.drop_duplicates(["race_id", "car"])
    odds = {}
    with gzip.open(f"{d}/wt_odds.jsonl.gz", "rt") as f:
        for line in f:
            o = json.loads(line)
            odds[str(o["race_id"]).zfill(12)] = o
    return r, e, odds


def features(r, e):
    df = e.merge(r, on="race_id", how="inner")
    df = df[df.absent == 0].copy()
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df["finish"] = pd.to_numeric(df["finish"], errors="coerce")
    df["win"] = (df.finish == 1).astype(int)
    df["top3"] = df.finish.between(1, 3).astype(int)
    g = df.groupby("race_id")
    df["n"] = g.car.transform("size")
    # 競走得点のレース内での位置
    df["pt_rank"] = g.race_point.rank(ascending=False, method="min")
    df["pt_diff_max"] = df.race_point - g.race_point.transform("max")
    df["pt_z"] = (df.race_point - g.race_point.transform("mean")) / g.race_point.transform("std").replace(0, np.nan)
    # 決まり手の割合(出走表の通算)
    tot = df[["front_runner", "stalker", "deep_closer", "marker"]].sum(1).replace(0, np.nan)
    for c in ["front_runner", "stalker", "deep_closer", "marker"]:
        df[c + "_r"] = df[c] / tot
    racecnt = df[["first", "second", "third", "others"]].sum(1)
    df["starts_card"] = racecnt
    df["back_r"] = df.back / racecnt.replace(0, np.nan)
    df["standing_r"] = df.standing / racecnt.replace(0, np.nan)
    # ライン
    df["n_lines"] = g.line_no.transform("nunique")
    df["line_pt_sum"] = df.groupby(["race_id", "line_no"]).race_point.transform("sum")
    df["line_pt_mean"] = df.groupby(["race_id", "line_no"]).race_point.transform("mean")
    df["line_rank"] = df.groupby("race_id").line_pt_mean.rank(ascending=False, method="dense")
    df["is_leader"] = (df.line_pos == 0).astype(int)
    df["leader_pt"] = df.groupby(["race_id", "line_no"]).race_point.transform("first")  # 並び順は先頭から
    df["single"] = (df.line_size == 1).astype(int)
    df["n_nige"] = g["style"].transform(lambda s: (s == "逃").sum())
    df["mark_rank"] = df["mark"].replace(0, 9)
    df["gear_diff"] = df.gear - g.gear.transform("mean")
    df["cls_grp"] = df.cls * 10 + df.grp

    # 自前の過去成績(その日より前だけ): 直近10走の勝率・3着内率・平均着順(着順/頭数)、出走間隔
    df = df.sort_values(["player_id", "date", "race_id"])
    df["fin_ratio"] = df.finish / df.n
    hp = df.groupby("player_id")
    for c, w in [("win", 10), ("top3", 10), ("fin_ratio", 10), ("win", 30), ("top3", 30)]:
        df[f"h{w}_{c}"] = hp[c].transform(lambda s: s.shift(1).rolling(w, min_periods=1).mean())
    df["h_starts"] = hp.cumcount()
    df["days_since"] = hp.date.diff().dt.days
    df["last_finish"] = hp.finish.shift(1)
    # 同じ開催の前日までの成績(開催内の調子)
    df["cup_prev_fin"] = df.groupby(["player_id", "cup_id"]).fin_ratio.transform(lambda s: s.shift(1).expanding().mean())
    df["h10_vs_pt"] = df.h10_fin_ratio - df.groupby("race_id").h10_fin_ratio.transform("mean")
    for c in CAT:
        df[c] = df[c].astype(str).astype("category")
    return df.sort_values(["date", "race_id", "car"]).reset_index(drop=True)


FEATS = ["race_point", "pt_rank", "pt_diff_max", "pt_z", "first_rate", "second_rate", "third_rate", "starts_card",
         "front_runner_r", "stalker_r", "deep_closer_r", "marker_r", "back_r", "standing_r",
         "line_no", "line_pos", "line_size", "n_lines", "line_pt_sum", "line_pt_mean", "line_rank", "is_leader",
         "leader_pt", "single", "n_nige", "mark_rank", "gear", "gear_diff", "age", "term", "cls_grp", "gender_f",
         "n", "distance", "lap", "girls", "day", "duration",
         "h10_win", "h10_top3", "h10_fin_ratio", "h30_win", "h30_top3", "h_starts", "days_since", "last_finish",
         "cup_prev_fin", "h10_vs_pt"] + CAT


def market_win(df, odds):
    """2車単オッズの逆数を1着の車番ごとに合計 → レース内で正規化"""
    out = np.full(len(df), np.nan)
    for i, (rid, car) in enumerate(zip(df.race_id, df.car)):
        o = odds.get(rid)
        if not o:
            continue
        s = o.setdefault("_mw", None)
        if s is None:
            s = {}
            for combo, odd, *_ in o["odds"].get("2車単", []):
                try:
                    a, x = int(str(combo).split(".")[0]), float(odd)
                except (TypeError, ValueError):
                    continue
                if x > 0:
                    s[a] = s.get(a, 0) + 1 / x
            o["_mw"] = s
        out[i] = s.get(int(car), np.nan)
    df["p_mkt"] = out
    df["p_mkt"] = df.p_mkt / df.groupby("race_id").p_mkt.transform("sum")
    return df


def train_predict(tr, te):
    params = dict(objective="binary", learning_rate=0.03, num_leaves=31, min_data_in_leaf=100, feature_fraction=0.8,
                  bagging_fraction=0.8, bagging_freq=1, lambda_l2=5.0, verbose=-1, seed=0)
    m = lgb.train(params, lgb.Dataset(tr[FEATS], tr.win, categorical_feature=CAT), num_boost_round=600)
    p = m.predict(te[FEATS])
    return p, m


def norm(df, col):
    return df[col] / df.groupby("race_id")[col].transform("sum")


def ll(df, col):
    w = df[df.win == 1]
    return float(-np.log(np.clip(w[col], 1e-9, None)).mean())


def fit_blend(df):
    """p ∝ p_ai^a p_mkt^b の a,b を最尤推定"""
    rid = df.race_id.to_numpy()
    _, inv = np.unique(rid, return_inverse=True)
    la, lm, y = np.log(np.clip(df.p_ai, 1e-9, None)).to_numpy(), np.log(np.clip(df.p_mkt, 1e-9, None)).to_numpy(), df.win.to_numpy()

    def nll(w):
        z = w[0] * la + w[1] * lm
        zmax = np.zeros(inv.max() + 1)
        np.maximum.at(zmax, inv, z)
        ez = np.exp(z - zmax[inv])
        den = np.bincount(inv, ez)
        return -(np.log(ez[y == 1] / den[inv[y == 1]])).sum() / y.sum()
    r = minimize(nll, [0.3, 0.7], method="BFGS")
    return r.x


def apply_blend(df, a, b):
    z = np.exp(a * np.log(np.clip(df.p_ai, 1e-9, None)) + b * np.log(np.clip(df.p_mkt, 1e-9, None)))
    return z / z.groupby(df.race_id).transform("sum")


def harville(p: dict, g2=0.85, g3=0.75):
    """1着率 -> 2車単・3連単の確率(2着・3着はべき乗で割り引いたハーヴィル)"""
    cars = list(p)
    q2 = {c: p[c] ** g2 for c in cars}
    q3 = {c: p[c] ** g3 for c in cars}
    ex, tri = {}, {}
    for a in cars:
        s2 = sum(q2[c] for c in cars if c != a)
        for b in cars:
            if b == a:
                continue
            pab = p[a] * q2[b] / s2
            ex[(a, b)] = pab
            s3 = sum(q3[c] for c in cars if c not in (a, b))
            for c in cars:
                if c in (a, b):
                    continue
                tri[(a, b, c)] = pab * q3[c] / s3
    return ex, tri


def ev_backtest(df, odds, col, thresholds=(0.8, 1.0, 1.1, 1.2, 1.3, 1.5, 2.0), max_odds=None):
    """混合確率 col で全券種の EV を出し、閾値以上を全部100円ずつ買った場合の回収率"""
    rows = []
    for rid, g in df.groupby("race_id"):
        o = odds.get(rid)
        if not o or not o.get("final"):
            continue
        p = dict(zip(g.car.astype(int), g[col]))
        ex, tri = harville(p)
        qn = {}
        for (a, b), v in ex.items():
            k = tuple(sorted((a, b)))
            qn[k] = qn.get(k, 0) + v
        trio = {}
        for (a, b, c), v in tri.items():
            k = tuple(sorted((a, b, c)))
            trio[k] = trio.get(k, 0) + v
        # ワイド(3着内に2車): 3連単の確率から合計
        wide = {}
        for (a, b, c), v in tri.items():
            for k in combinations(sorted((a, b, c)), 2):
                wide[k] = wide.get(k, 0) + v
        prob = {"2車単": {f"{a}.{b}": v for (a, b), v in ex.items()},
                "2車複": {".".join(map(str, k)): v for k, v in qn.items()},
                "ワイド": {".".join(map(str, k)): v for k, v in wide.items()},
                "3連単": {f"{a}.{b}.{c}": v for (a, b, c), v in tri.items()},
                "3連複": {".".join(map(str, k)): v for k, v in trio.items()}}
        for bt, P in prob.items():
            pay = o["payoff"].get(bt, {})
            for item in o["odds"].get(bt, []):
                combo, odd = str(item[0]), item[1]
                try:
                    odd = float(odd)
                except (TypeError, ValueError):
                    continue
                if not odd or odd <= 0 or combo not in P:
                    continue
                ev = P[combo] * odd
                if ev < min(thresholds):
                    continue
                rows.append((rid, bt, combo, odd, P[combo], ev, float(pay.get(combo, 0) or 0)))
    B = pd.DataFrame(rows, columns=["race_id", "bet", "combo", "odds", "p", "ev", "payout"])
    out = []
    for bt in ["2車単", "2車複", "ワイド", "3連単", "3連複"]:
        for t in thresholds:
            s = B[(B.bet == bt) & (B.ev >= t)]
            if max_odds:
                s = s[s.odds <= max_odds]
            if len(s):
                out.append(dict(bet=bt, ev_min=t, tickets=len(s), races=s.race_id.nunique(), hits=int((s.payout > 0).sum()),
                                roi=s.payout.sum() / (len(s) * 100)))
    return pd.DataFrame(out), B


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir")
    ap.add_argument("--test-from", default="2025-07-01")
    ap.add_argument("--fold-months", type=int, default=3)
    ap.add_argument("--out", default="wt_wf.parquet")
    a = ap.parse_args()
    r, e, odds = load(a.data_dir)
    df = features(r, e)
    df["gender_f"] = (df.gender == "女").astype(int)
    df = market_win(df, odds)
    ok = df.groupby("race_id").agg(w=("win", "sum"), m=("p_mkt", lambda s: s.notna().all()))
    df = df[df.race_id.isin(ok.index[(ok.w == 1) & ok.m])].copy()
    print(f"対象 {df.race_id.nunique():,}レース / {len(df):,}行 / {df.date.min().date()}〜{df.date.max().date()}")

    # ウォークフォワード(fold-months ごとに、その前の全データで学習)
    starts = pd.date_range(a.test_from, df.date.max() + pd.Timedelta(days=1), freq=f"{a.fold_months}MS")
    preds = []
    for i, s in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else df.date.max() + pd.Timedelta(days=1)
        tr, te = df[df.date < s], df[(df.date >= s) & (df.date < end)].copy()
        if te.empty:
            continue
        te["p_raw"], m = train_predict(tr, te)
        te["p_ai"] = norm(te, "p_raw")
        preds.append(te)
        print(f"  学習〜{s.date()} ({tr.race_id.nunique():,}R) → 予測 {te.race_id.nunique():,}R  "
              f"AI {ll(te, 'p_ai'):.4f} / 市場 {ll(te, 'p_mkt'):.4f}", flush=True)
    W = pd.concat(preds)
    imp = pd.Series(m.feature_importance("gain"), index=FEATS).sort_values(ascending=False)
    print("重要度上位:", ", ".join(imp.index[:12]))

    # 混合の重みは「前半の検証期間」で推定して「後半」で評価(後半で推定すると楽観的になるため)
    mid = W.date.min() + (W.date.max() - W.date.min()) / 2
    A, Bh = W[W.date < mid].copy(), W[W.date >= mid].copy()
    wa, wb = fit_blend(A)
    for X in (A, Bh, W):
        X["p_blend"] = apply_blend(X, wa, wb)
    W["p_blend"] = apply_blend(W, wa, wb)
    n = Bh.groupby("race_id").size()
    print(f"\n混合の重み(前半で推定): AI a={wa:.3f} 市場 b={wb:.3f}")
    print(f"後半 {Bh.race_id.nunique():,}R の対数損失: AI {ll(Bh, 'p_ai'):.4f} / 市場 {ll(Bh, 'p_mkt'):.4f} / "
          f"混合 {ll(Bh, 'p_blend'):.4f} / 一様 {np.log(n).mean():.4f}")
    for col, name in [("p_ai", "AI"), ("p_mkt", "市場"), ("p_blend", "混合")]:
        top = Bh.loc[Bh.groupby("race_id")[col].idxmax()]
        print(f"  {name}の1番手 1着率 {top.win.mean():.3f}")
    W.to_parquet(a.out)

    print("\n■ EV検証(後半・確定オッズ・実際の払戻)")
    for col, name in [("p_blend", "混合"), ("p_mkt", "市場だけ(比較用)")]:
        res, _ = ev_backtest(Bh, odds, col)
        print(f"-- {name}")
        print(res.to_string(index=False, float_format="%.3f"))


if __name__ == "__main__":
    main()
