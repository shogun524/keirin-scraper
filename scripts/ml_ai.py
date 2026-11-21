"""
競輪の機械学習AI(11/21〜。JRAと同じく「過去のレース結果から学習したモデル」で1着率・3着内率を出す)。

学習: winticket の 2025〜2026年のレース(約5万レース)。オッズは使わない(選手データ・並び予想・印・バンクだけ)。
特徴量は KDドリームス / winticket どちらの選手データ(model.predict_race に渡す racers)からも同じように作れるものだけ。
  選手: 競走得点、級班、脚質、ギア、年齢、期別、決まり手の回数(逃・捲・差・マ)、着回数(1/2/3/着外)、S・B回数、印、枠
  レース内の比較: 得点の順位・平均との差、ライン(位置・人数・ラインの得点合計と順位・前の選手の得点)、
                逃げ選手の人数、同じラインの逃げ選手の有無
  レース: 車立て、級(S/A/L)、バンク
モデル: scripts/ml_ai_win.txt(1着)・scripts/ml_ai_top3.txt(3着内)。LightGBM。レースごとに合計1(3着内は合計3)にそろえる。

使い方(予想側): import ml_ai; p1, p3 = ml_ai.predict(racers, line_text, venue_slug) → {車番: 確率}
"""
import json
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
MARK_N = {"◎": 1, "○": 2, "▲": 3, "△": 4, "×": 5, "注": 6}
STYLE_N = {"逃": 0, "両": 1, "追": 2}
VENUES = ["hakodate", "aomori", "iwakitaira", "yahiko", "maebashi", "toride", "utsunomiya", "omiya", "seibuen",
          "keiokaku", "tachikawa", "matsudo", "chiba", "kawasaki", "hiratsuka", "odawara", "ito", "shizuoka",
          "nagoya", "gifu", "ogaki", "toyohashi", "toyama", "matsusaka", "yokkaichi", "fukui", "nara", "mukomachi",
          "wakayama", "kishiwada", "tamano", "hiroshima", "hofu", "takamatsu", "komatsushima", "kochi",
          "matsuyama", "kokura", "kurume", "takeo", "sasebo", "beppu", "kumamoto"]


def _rank_n(rank):
    r = str(rank or "")
    if r.startswith("SS"):
        return 0, 0
    if r.startswith("S"):
        return 1, int(r[1:] or 2) if r[1:].isdigit() else 2
    if r.startswith("L"):
        return 4, 1
    return 2, int(r[1:]) if r[1:].isdigit() else 2


def _num(x, d=np.nan):
    try:
        v = float(x)
        return v if np.isfinite(v) else d
    except (TypeError, ValueError):
        return d


def features(racers, line_text, venue_slug=None):
    """racers(model.predict_race と同じ形)から特徴量の表(1行1選手)"""
    import model
    lm = model.parse_line_prediction_text(line_text or "") or {}
    rows = []
    for r in racers:
        cls, grp = _rank_n(r.get("rank"))
        k = r.get("kimarite") or {}
        f = r.get("finishes") or {}
        f1, f2, f3, fo = (_num(f.get(x), 0) for x in ("f1", "f2", "f3", "fo"))
        nrun = f1 + f2 + f3 + fo
        L = lm.get(int(r["car"])) or {}
        rows.append(dict(
            car=int(r["car"]), score=_num(r.get("score")), cls=cls, grp=grp, style=STYLE_N.get(str(r.get("tactic", ""))[:1], 1),
            gear=_num(r.get("gear")), age=_num(r.get("age")), term=_num(r.get("period")),
            k_nige=_num(k.get("逃"), 0), k_makuri=_num(k.get("捲"), 0), k_sashi=_num(k.get("差"), 0), k_mark=_num(k.get("マ"), 0),
            f1=f1, f2=f2, f3=f3, fo=fo, r1=f1 / nrun if nrun else np.nan, r3=(f1 + f2 + f3) / nrun if nrun else np.nan,
            s_cnt=_num(r.get("s_count"), 0), b_cnt=_num(r.get("b_count"), 0),
            mark=MARK_N.get(str(r.get("mark") or ""), 0), waku=_num(r.get("waku")),
            line_id=L.get("line_index", -1 - int(r["car"])), lpos=L.get("position", 1), lsize=L.get("line_size", 1)))
    D = pd.DataFrame(rows)
    if D.empty:
        return D
    n = len(D)
    D["n"] = n
    D["score_rank"] = D["score"].rank(ascending=False, method="min")
    D["score_diff"] = D["score"] - D["score"].mean()
    D["score_z"] = D["score_diff"] / (D["score"].std() or 1)
    D["score_gap_top"] = D["score"] - D["score"].max()
    lg = D.groupby("line_id")["score"]
    D["line_sum"] = D["line_id"].map(lg.sum())
    D["line_mean"] = D["line_id"].map(lg.mean())
    ls = D.drop_duplicates("line_id").set_index("line_id")["line_sum"].rank(ascending=False, method="min")
    D["line_rank"] = D["line_id"].map(ls)
    D["n_lines"] = D["line_id"].nunique()
    lead = D.sort_values("lpos").groupby("line_id")["score"].first()
    D["lead_score"] = D["line_id"].map(lead)
    prev = {}
    for _, g in D.sort_values("lpos").groupby("line_id"):
        sc = g["score"].tolist()
        for i, c in enumerate(g["car"]):
            prev[c] = sc[i - 1] if i > 0 else np.nan
    D["front_score"] = D["car"].map(prev)
    D["nige_share"] = D["k_nige"] / (D["k_nige"].sum() or 1)
    D["n_nige_style"] = (D["style"] == 0).sum()
    D["line_has_nige"] = D["line_id"].map(D.groupby("line_id")["k_nige"].sum()) - D["k_nige"]
    D["mark_any"] = (D["mark"] > 0).astype(int)
    D["race_cls"] = 4 if (D["cls"] == 4).all() else (1 if (D["cls"] <= 1).mean() >= 0.5 else 2)
    D["venue"] = VENUES.index(venue_slug) if venue_slug in VENUES else -1
    return D


FEATS = ["score", "cls", "grp", "style", "gear", "age", "term", "k_nige", "k_makuri", "k_sashi", "k_mark", "f1", "f2", "f3", "fo",
         "r1", "r3", "s_cnt", "b_cnt", "mark", "waku", "lpos", "lsize", "n", "score_rank", "score_diff", "score_z", "score_gap_top",
         "line_sum", "line_mean", "line_rank", "n_lines", "lead_score", "front_score", "nige_share", "n_nige_style",
         "line_has_nige", "mark_any", "race_cls", "venue"]

_MODELS = {}


def _load(name):
    if name not in _MODELS:
        import lightgbm as lgb
        p = os.path.join(HERE, f"ml_ai_{name}.txt")
        _MODELS[name] = lgb.Booster(model_file=p) if os.path.exists(p) else None
    return _MODELS[name]


def predict(racers, line_text, venue_slug=None):
    """→ (1着率 {車番: p}, 3着内率 {車番: p})。モデルが無ければ (None, None)"""
    mw, m3 = _load("win"), _load("top3")
    if mw is None:
        return None, None
    D = features(racers, line_text, venue_slug)
    if D.empty:
        return None, None
    X = D[FEATS].astype(float)
    sw = mw.predict(X, raw_score=True)
    e = np.exp(sw - sw.max())
    p1 = e / e.sum()
    out3 = None
    if m3 is not None:
        q = 1 / (1 + np.exp(-m3.predict(X, raw_score=True)))
        q = np.clip(q * min(3, len(D)) / q.sum(), 0, 0.98)
        out3 = dict(zip(D["car"], q))
    return dict(zip(D["car"], p1)), out3
