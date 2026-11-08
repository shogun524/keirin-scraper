# -*- coding: utf-8 -*-
"""
「儲かるのか」を正直に測るための検証モジュール（ネットワーク不要・純粋な集計）。

入力は docs/_buy_log.json（締切前の3連単上位40点とオッズ＋確定した1-2-3着）と、
任意で docs/_close_odds.json（締切の直前に取ったオッズ）。

提供する機能
  1) roi_stats        : 買い方ごとの回収率と90%信頼区間（レースを復元抽出）＋「100%超え」の確からしさ
  2) band_table       : オッズ帯別の的中率・回収率（人気薄ほど損か＝人気薄バイアスの確認）
  3) walk_forward     : その日より前のデータだけで買い方を選び、その日で成績を測る（選び方の偏りを除く）
  4) clv_stats        : 購入候補を最初に見たときのオッズと、締切時オッズの比（CLV）。市場より先に動けているか
  5) evidence_gate    : 「買ってよい根拠が揃ったか」の判定（件数・信頼区間・前向き検証・CLV）
  6) paper_trade      : 仮想の資金で実際のルールに従ったときの損益の推移（最大ドローダウンつき）

配分（alloc）
  equal  : 各買い目に同額（buy_stats と同じ。1点100円×点数）
  payout : どれが当たっても払戻が同じになるよう 1/オッズ に比例して配分（1レースの投下=1単位）
"""
import math
import random
from collections import defaultdict

import market_fix

PLANS = ("syn1.5", "syn2", "top3", "top5", "top8", "top10")
TYPES = ("堅い", "中間", "混戦")
ODDS_BANDS = [(0, 10), (10, 20), (20, 40), (40, 80), (80, 150), (150, float("inf"))]
N_BOOT = 1000

# 「買ってよい」と判定する最低条件
GATE = {"min_races": 200, "lcb_min": 100.0, "min_wf_races": 100, "wf_min_roi": 100.0}


# ------------------------------------------------------------------ 基本
def settled(log):
    """答え合わせ済み（勝ち組あり）のレースを日付順で返す。"""
    es = [v for v in (log or {}).values() if v.get("winner") and v.get("items")]
    es.sort(key=lambda v: (v["date"], v.get("deadline") or "", v["venue"], v["race_no"]))
    return es


def race_key(v):
    return f"{v['date']}_{v['venue']}_{v['race_no']}"


def _select(items, plan_id):
    pairs = [(k, o) for k, o, *_ in items if o]
    return market_fix.pick_plan(pairs, plan_id), dict(pairs)


def outcome(entry, plan_id, alloc="equal"):
    """(投下, 払戻, 的中, 合成オッズ)。equal: 投下=点数、払戻=当たりのオッズ。payout: 投下=1、払戻=合成オッズ。"""
    sel, od = _select(entry["items"], plan_id)
    if not sel:
        return 0.0, 0.0, False, None
    hit = entry["winner"] in sel
    synth = 1.0 / sum(1.0 / od[k] for k in sel)
    if alloc == "payout":
        return 1.0, (synth if hit else 0.0), hit, synth
    return float(len(sel)), (od[entry["winner"]] if hit else 0.0), hit, synth


def _boot_ratio(pairs, n_boot, seed, threshold):
    """pairs=[(投下, 払戻)]。レースを復元抽出して 払戻/投下 の90%区間と P(>threshold) を返す。"""
    n = len(pairs)
    tot = sum(s for s, _ in pairs)
    roi = sum(r for _, r in pairs) / tot * 100 if tot else None
    if n < 2 or not tot:
        return roi, None, None, None
    rnd = random.Random(seed)
    outs = []
    for _ in range(n_boot):
        sm = rm = 0.0
        for s, r in rnd.choices(pairs, k=n):
            sm += s
            rm += r
        outs.append(rm / sm * 100 if sm else 0.0)
    outs.sort()
    lo, hi = outs[int(0.05 * n_boot)], outs[min(n_boot - 1, int(0.95 * n_boot))]
    p_gt = sum(1 for x in outs if x > threshold) / n_boot
    return roi, lo, hi, p_gt


def roi_stats(entries, plan_id, alloc="equal", n_boot=N_BOOT, seed=1, threshold=100.0):
    """買い方 plan_id の回収率と90%信頼区間。"""
    outs = [outcome(v, plan_id, alloc) for v in entries]
    outs = [o for o in outs if o[0] > 0]
    pairs = [(s, r) for s, r, _, _ in outs]
    roi, lo, hi, p_gt = _boot_ratio(pairs, n_boot, seed, threshold)
    n = len(outs)
    hits = sum(1 for o in outs if o[2])
    return {"plan": plan_id, "alloc": alloc, "races": n, "hits": hits,
            "hit_pct": round(hits / n * 100, 1) if n else None,
            "roi": _r(roi), "lo": _r(lo), "hi": _r(hi), "p_gt": None if p_gt is None else round(p_gt, 2)}


def _r(x, d=1):
    return None if x is None else round(x, d)


def grid(entries, plans=PLANS, alloc="equal", n_boot=N_BOOT):
    """{型または'全体': {plan: roi_stats}}"""
    out = {}
    groups = [("全体", entries)] + [(t, [v for v in entries if v.get("type") == t]) for t in TYPES]
    for name, es in groups:
        out[name] = {p: roi_stats(es, p, alloc, n_boot) for p in plans} if es else {}
    return out


# ------------------------------------------------------------------ オッズ帯別
def band_table(entries, bands=ODDS_BANDS, n_boot=N_BOOT, seed=1):
    """保存している上位40点を全部100円ずつ買ったとして、オッズ帯ごとの的中率と回収率。
    1レースに当たりは1点だけなので、レースを単位に復元抽出して90%区間を出す。"""
    rows = []
    for lo_o, hi_o in bands:
        per = []          # レースごとの (帯内の点数, 帯内の払戻)
        for v in entries:
            n = ret = 0
            for k, o, *_ in v["items"]:
                if lo_o <= o < hi_o:
                    n += 1
                    if k == v["winner"]:
                        ret += o
            per.append((n, ret))
        pts = sum(n for n, _ in per)
        hits = sum(1 for v in entries for k, o, *_ in v["items"] if lo_o <= o < hi_o and k == v["winner"])
        roi, lo, hi, _ = _boot_ratio([p for p in per if p[0] > 0], n_boot, seed, 100.0)
        rows.append({"lo": lo_o, "hi": None if hi_o == float("inf") else hi_o, "tickets": pts, "hits": hits,
                     "hit_pct": round(hits / pts * 100, 2) if pts else None,
                     "roi": _r(roi), "roi_lo": _r(lo), "roi_hi": _r(hi)})
    return rows


# ------------------------------------------------------------------ ウォークフォワード
def _plan_roi(entries, plan_id, alloc):
    s = r = 0.0
    for v in entries:
        a, b, _, _ = outcome(v, plan_id, alloc)
        s += a
        r += b
    return (r / s * 100) if s else None


def walk_forward(entries, plans=PLANS, alloc="equal", min_past=60, bet_threshold=100.0,
                 by_type=True, n_boot=N_BOOT, seed=1):
    """日ごとに、それより前の日だけを使って「型ごとに最良の買い方」を選び、その日を評価する。
    過去の回収率が bet_threshold に届かない型は見送る（賭けない）。
    戻り値: 実際に賭けたレースだけの成績と、選ばれた買い方の履歴。"""
    dates = sorted({v["date"] for v in entries})
    pairs, picks, bet_n, skip_n = [], [], 0, 0
    for d in dates:
        past = [v for v in entries if v["date"] < d]
        today = [v for v in entries if v["date"] == d]
        groups = ([(t, [v for v in past if v.get("type") == t], [v for v in today if v.get("type") == t])
                   for t in TYPES] if by_type else [("全体", past, today)])
        for name, pa, to in groups:
            if not to:
                continue
            if len(pa) < min_past:
                skip_n += len(to)
                continue
            scored = [(p, _plan_roi(pa, p, alloc)) for p in plans]
            scored = [(p, x) for p, x in scored if x is not None]
            best, best_roi = max(scored, key=lambda t: t[1])
            if best_roi < bet_threshold:
                picks.append({"date": d, "type": name, "plan": None, "past_roi": round(best_roi, 1)})
                skip_n += len(to)
                continue
            picks.append({"date": d, "type": name, "plan": best, "past_roi": round(best_roi, 1)})
            for v in to:
                s, r, _, _ = outcome(v, best, alloc)
                if s > 0:
                    pairs.append((s, r))
                    bet_n += 1
    roi, lo, hi, p_gt = _boot_ratio(pairs, n_boot, seed, 100.0)
    return {"alloc": alloc, "bet_races": bet_n, "skipped_races": skip_n,
            "roi": _r(roi), "lo": _r(lo), "hi": _r(hi), "p_gt": None if p_gt is None else round(p_gt, 2),
            "picks": picks}


def replay_auto(entries, alloc="equal", n_boot=N_BOOT, seed=1):
    """いま画面に出している自動おすすめ（market_fix.AUTO）に従って買った場合の成績（見送り型は賭けない）。
    AUTO は10/24〜10/26のデータで決めたので、それ以降の記録は『決めたあとのデータ』＝前向きの検証になる。"""
    pairs, skipped = [], 0
    for v in entries:
        cfg = market_fix.AUTO.get(v.get("type"))
        if not cfg or cfg["skip"]:
            skipped += 1
            continue
        s, r, _, _ = outcome(v, cfg["id"], alloc)
        if s > 0:
            pairs.append((s, r))
    roi, lo, hi, p_gt = _boot_ratio(pairs, n_boot, seed, 100.0)
    return {"bet_races": len(pairs), "skipped_races": skipped, "roi": _r(roi), "lo": _r(lo), "hi": _r(hi),
            "p_gt": None if p_gt is None else round(p_gt, 2)}


# ------------------------------------------------------------------ CLV
def _minutes(hm):
    try:
        h, m = hm.split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def clv_stats(entries, close_map=None, plan_id="top5", max_lead_min=None, n_boot=N_BOOT, seed=1):
    """CLV＝購入候補を最初に見たときのオッズ ÷ 締切時のオッズ（対数）。
    正なら『最初に見たときより締切までにオッズが下がった（=市場があとから同じ方向に動いた）』で、
    先に良い値段で買えていたことを意味する。結果（当たり外れ）に左右されないので、回収率より少ない件数で傾向が見える。
    締切時オッズは close_map（締切直前の取得）があればそれ、無ければ最後の毎時記録を使う（精度は落ちる）。"""
    close_map = close_map or {}
    per, src_n, leads = [], defaultdict(int), []
    for v in entries:
        first = v.get("first")
        if not first:
            continue
        lead = None
        if _minutes(v.get("deadline")) is not None and _minutes(first.get("ts")) is not None:
            lead = _minutes(v["deadline"]) - _minutes(first["ts"])
            if max_lead_min is not None and lead > max_lead_min:
                continue
        sel, _ = _select(first["items"], plan_id)
        cm = close_map.get(race_key(v))
        if cm and cm.get("odds"):
            close, src = cm["odds"], "close"
        else:
            if first.get("ts") == v.get("last_ts"):      # 記録が1回だけ＝比べる相手がない
                continue
            close, src = {k: o for k, o, *_ in v["items"]}, "last"
        fo = dict((k, o) for k, o in first["items"])
        vals = [math.log(fo[k] / close[k]) for k in sel if k in fo and close.get(k)]
        if len(vals) < max(2, len(sel) // 2):
            continue
        per.append(sum(vals) / len(vals))
        src_n[src] += 1
        if lead is not None:
            leads.append(lead)
    n = len(per)
    if not n:
        return {"plan": plan_id, "races": 0, "sources": dict(src_n)}
    mean = sum(per) / n
    rnd = random.Random(seed)
    bs = sorted(sum(rnd.choices(per, k=n)) / n for _ in range(n_boot))
    leads.sort()
    return {"plan": plan_id, "races": n, "mean_pct": round(mean * 100, 2),
            "lo_pct": round(bs[int(.05 * n_boot)] * 100, 2), "hi_pct": round(bs[min(n_boot - 1, int(.95 * n_boot))] * 100, 2),
            "pos_share": round(sum(1 for x in per if x > 0) / n * 100, 1),
            "median_lead_min": leads[len(leads) // 2] if leads else None, "sources": dict(src_n)}


# ------------------------------------------------------------------ 判定
def evidence_gate(stat, wf=None, clv=None, gate=GATE):
    """買い方1つについて『買ってよい根拠が揃ったか』。(通過か, 理由のリスト)。
    1つでも欠ければ通過しない（種類を多く試して良い結果を選ぶ偏りを避けるため、控えめに判定する）。"""
    why = []
    if not stat or not stat.get("races"):
        return False, ["記録なし"]
    if stat["races"] < gate["min_races"]:
        why.append(f"件数不足（{stat['races']}／{gate['min_races']}レース）")
    if stat.get("lo") is None or stat["lo"] < gate["lcb_min"]:
        why.append(f"回収率の下側90%が{stat.get('lo')}%で{gate['lcb_min']:.0f}%未満")
    if wf is not None:
        if wf.get("bet_races", 0) < gate["min_wf_races"]:
            why.append(f"前向き検証の件数不足（{wf.get('bet_races', 0)}／{gate['min_wf_races']}）")
        elif wf.get("roi") is None or wf["roi"] < gate["wf_min_roi"]:
            why.append(f"前向き検証の回収率が{wf.get('roi')}%")
    if clv is not None and clv.get("races", 0) >= 50 and clv.get("mean_pct", 0) < 0:
        why.append(f"CLVがマイナス（{clv['mean_pct']}%）")
    return (not why), why


# ------------------------------------------------------------------ ペーパートレード
def paper_trade(entries, picker, alloc="payout", unit=1000):
    """仮想の資金で picker(entry)->買い方ID または None（見送り）に従ったときの日別の損益。
    alloc=payout なら1レースに unit 円を、当たりの払戻が同額になるよう配分する。
    戻り値: {"days":[{date, bets, profit, cum}], "profit", "stake", "roi", "max_dd", "bets"}"""
    by_day = defaultdict(lambda: [0, 0.0, 0.0])
    for v in entries:
        pid = picker(v)
        if not pid:
            continue
        s, r, _, _ = outcome(v, pid, alloc)
        if s <= 0:
            continue
        mult = unit / s if alloc == "payout" else 100.0
        d = by_day[v["date"]]
        d[0] += 1
        d[1] += s * mult
        d[2] += r * mult
    days, cum, peak, max_dd, stake_all, ret_all, bets = [], 0.0, 0.0, 0.0, 0.0, 0.0, 0
    for date in sorted(by_day):
        n, stake, ret = by_day[date]
        cum += ret - stake
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
        stake_all += stake
        ret_all += ret
        bets += n
        days.append({"date": date, "bets": n, "profit": round(ret - stake), "cum": round(cum)})
    return {"days": days, "profit": round(cum), "stake": round(stake_all), "bets": bets,
            "roi": _r(ret_all / stake_all * 100) if stake_all else None, "max_dd": round(max_dd)}


def auto_picker(v):
    cfg = market_fix.AUTO.get(v.get("type"))
    return None if (not cfg or cfg["skip"]) else cfg["id"]


def fixed_picker(plan_id):
    return lambda v: plan_id


# ------------------------------------------------------------------ 一括
def build_report(log, close_map=None, n_boot=N_BOOT):
    """画面と _edge_report.json 用の結果をまとめて作る。"""
    es = settled(log)
    if not es:
        return {"races": 0}
    g = grid(es, n_boot=n_boot)
    wf = {a: walk_forward(es, alloc=a, n_boot=n_boot) for a in ("equal", "payout")}
    clv = {p: clv_stats(es, close_map, p, n_boot=n_boot) for p in ("top5", "syn1.5")}
    gates = {}
    for t in TYPES:
        row = {}
        typed = [v for v in es if v.get("type") == t]
        wf_t = walk_forward(typed, by_type=False, n_boot=n_boot) if typed else None
        for p, st in (g.get(t) or {}).items():
            ok, why = evidence_gate(st, wf_t, clv.get("top5") if p == "top5" else None)
            row[p] = {"pass": ok, "why": why}
        gates[t] = row
    return {"races": len(es), "dates": [es[0]["date"], es[-1]["date"]], "grid": g,
            "bands": band_table(es, n_boot=n_boot), "walk_forward": wf, "auto_replay": replay_auto(es, n_boot=n_boot),
            "clv": clv, "gates": gates,
            "paper": {"auto": paper_trade(es, auto_picker), "top5_all": paper_trade(es, fixed_picker("top5"))}}
