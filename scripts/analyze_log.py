# -*- coding: utf-8 -*-
"""
予想成績ログ（docs/_prediction_log.json）の検証スクリプト。サイトの自動実行とは独立に、手元で1回走らせる。

使い方:  python analyze_log.py path/to/_prediction_log.json

やること（すべて実データから計算。仮定の数値は出さない）
  1. 監査: 件数・欠損・確率の合計・日別件数（集計表の分母が揃っているか）
  2. 確率の質: 全選手ベースの校正表、対数損失(Log Loss)、Brierスコア（本命だけの帯別表より選択バイアスが小さい）
  3. 時系列の前向き検証: 毎日「前日までのデータだけ」で γ と方程式バフ β を学習し、翌日のレースで
     基準値と比べる（学習と評価が重ならない）。差はレース単位のブートストラップで区間つきで出す。
  4. 方程式の点差別の本命成績（ブートストラップ95%区間）
  5. 3連単上位5点の的中率と、ログに残っている買い目点数
"""
import sys, json, math, random, datetime, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import calibration as C


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def probs_of(e):
    pr = e.get("p0") or e.get("probs")
    return {int(c): float(p) / 100 for c, p, *_ in pr} if pr else None


def ev_z(e):
    ev = e.get("ev")
    return C._z_from_ev(ev) if ev else None


def audit(log):
    n = len(log)
    res = [e for e in log.values() if e.get("result") and len(e["result"].get("finish_order", [])) >= 3]
    print(f"[監査] ログ {n}件 / 結果あり {len(res)}件")
    for k in ("probs", "p0", "ev", "cond", "trifecta"):
        print(f"  {k} あり: {sum(1 for e in res if e.get(k))}件")
    bad = 0
    for e in res:
        p = probs_of(e)
        if p and abs(sum(p.values()) - 1) > 0.03:
            bad += 1
    print(f"  確率の合計が100%±3%を外れるレース: {bad}件")
    by_day = {}
    for e in res:
        by_day[e["date"]] = by_day.get(e["date"], 0) + 1
    print("  日別（結果あり）:", dict(sorted(by_day.items())))
    n_ev = sum(1 for e in res if e.get("ev"))
    print(f"  方程式を記録したレース {n_ev}件 / 記録のない結果あり {len(res) - n_ev}件（ガールズ戦・記録開始前）")


def calib_table(res):
    bins = [(0, .05), (.05, .1), (.1, .15), (.15, .2), (.2, .3), (.3, .4), (.4, .5), (.5, 1.01)]
    acc = {b: [0, 0.0, 0] for b in bins}
    ll = br = 0.0
    n = 0
    for e in res:
        p = probs_of(e)
        if not p:
            continue
        w = e["result"]["finish_order"][0]
        if w not in p:
            continue
        n += 1
        ll += -math.log(max(p[w], 1e-9))
        br += sum((q - (1.0 if c == w else 0.0)) ** 2 for c, q in p.items())
        for c, q in p.items():
            for b in bins:
                if b[0] <= q < b[1]:
                    acc[b][0] += 1; acc[b][1] += q; acc[b][2] += (c == w)
    print(f"\n[確率の質] {n}レース  Log Loss={ll / n:.4f}  Brier(多クラス)={br / n:.4f}  （ランダムのLog Loss≈ln(車数)=1.95）")
    print("  全選手ベースの校正表（予測帯 / 件数 / 予測平均 / 実際の1着率）")
    for b, (m, sp, sw) in acc.items():
        if m:
            print(f"   {b[0]*100:>4.0f}〜{min(b[1],1)*100:<4.0f}%  n={m:<5} 予測{sp / m * 100:5.1f}%  実際{sw / m * 100:5.1f}%")


def _fit_gamma_beta(samples):
    g = C.fit_gamma([(pm, sf, w) for pm, sf, w, _ in samples], C._default_gamma()) if samples else C._default_gamma()
    b = C.fit_beta(samples, g) if samples else 0.0
    return g, b


def walk_forward(log, min_train=60):
    sm = []
    for e in sorted((e for e in log.values() if e.get("result")), key=lambda e: e["date"]):
        p = {c: v * 100 for c, v in (probs_of(e) or {}).items()}
        z = ev_z(e)
        fin = e["result"].get("finish_order") or []
        if not p or not z or not fin or fin[0] not in p or any(c not in z for c in p):
            continue
        sm.append((e["date"], p, float(e.get("sf") or C._default_gamma()), fin[0], z))
    days = sorted({s[0] for s in sm})
    g0 = C._default_gamma()
    rows = []   # (day, ll_default, ll_fit_gamma, ll_fit_gamma_beta)
    for d in days:
        train = [(p, sf, w, z) for dd, p, sf, w, z in sm if dd < d]
        test = [(p, sf, w, z) for dd, p, sf, w, z in sm if dd == d]
        if len(train) < min_train:
            continue
        g, b = _fit_gamma_beta(train)
        for t in test:
            rows.append((d, C._loglik([t[:3]], g0), C._loglik([t[:3]], g), C._loglik_buff([t], g, b)))
    if not rows:
        print(f"\n[前向き検証] 学習に必要な{min_train}レースが溜まる前のため実行できません（対象{len(sm)}レース）")
        return
    n = len(rows)
    m = [sum(r[i] for r in rows) / n for i in (1, 2, 3)]
    print(f"\n[前向き検証] 毎日、前日までで学習→翌日を評価。評価レース{n}件（1レースあたり対数尤度、大きいほど良い）")
    print(f"  基準値(γ={g0}) {m[0]:.4f} / γを学習 {m[1]:.4f} / γ+方程式バフ {m[2]:.4f}")
    rnd = random.Random(0)
    byday = {}
    for r in rows:
        byday.setdefault(r[0], []).append(r)
    keys = list(byday)
    for name, i in (("γ学習 − 基準", 2), ("γ+バフ − γ学習", 3)):
        base = 1 if i == 2 else 2
        diffs = []
        for _ in range(1000):   # 同じ日のレースは相関するので「日」単位で再標本化
            pick = [rnd.choice(keys) for _ in keys]
            rr = [r for k in pick for r in byday[k]]
            diffs.append(sum(r[i] - r[base] for r in rr) / len(rr))
        diffs.sort()
        print(f"  {name}: 平均{sum(r[i] - r[base] for r in rows) / n:+.4f}  95%区間[{diffs[25]:+.4f}, {diffs[975]:+.4f}]"
              f"  ← 区間が0をまたぐ間は「改善とは言えない」")


def gap_split(log):
    rows = []
    for e in log.values():
        ev, res = e.get("ev"), e.get("result")
        if not ev or len(ev) < 3 or not res or not res.get("finish_order"):
            continue
        s = sorted((t for _, t in ev), reverse=True)
        rows.append((s[0] - s[1], e["order"][0] == res["finish_order"][0], ev[0][0] == res["finish_order"][0], e["date"]))
    if not rows:
        return
    print(f"\n[方程式の点差別] {len(rows)}レース（本命=AI、1位=方程式。1着率とブートストラップ95%区間）")
    rnd = random.Random(1)
    for lo, hi, lab in ((-1e9, 5, "点差5未満"), (5, 10, "5〜10"), (10, 1e9, "10以上")):
        sub = [r for r in rows if lo <= r[0] < hi]
        if len(sub) < 5:
            continue
        out = []
        for idx in (1, 2):
            v = [r[idx] for r in sub]
            bs = sorted(sum(rnd.choice(v) for _ in v) / len(v) for _ in range(1000))
            out.append(f"{sum(v) / len(v) * 100:5.1f}% [{bs[25] * 100:.0f},{bs[975] * 100:.0f}]")
        print(f"  {lab:<8} n={len(sub):<4} AI本命 {out[0]}   方程式1位 {out[1]}")


def trifecta(log):
    n = hit = pts = 0
    for e in log.values():
        res, tf = e.get("result"), e.get("trifecta")
        if not res or not tf or len(res.get("finish_order", [])) < 3:
            continue
        n += 1
        pts += len(tf[:5])
        hit += any(c == res["finish_order"][:3] for c in tf[:5])
    if n:
        print(f"\n[3連単上位5点] {n}レース 的中{hit}件（{hit / n * 100:.1f}%）/ 1レース{pts / n:.1f}点購入。"
              f"回収率は払戻・オッズをログに持っていないため評価不能。")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "docs/_prediction_log.json"
    log = load(path)
    audit(log)
    res = [e for e in log.values() if e.get("result") and len(e["result"].get("finish_order", [])) >= 3]
    calib_table(res)
    walk_forward(log)
    gap_split(log)
    trifecta(log)
