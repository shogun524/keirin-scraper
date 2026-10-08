# -*- coding: utf-8 -*-
"""
予想ログと答え合わせ（予想成績の自前集計）。

毎時の自動実行のたびに、
  1. 取得できた各レースの「予想の中身（予測順位・本命の1着率・3連単の上位組合せ・
     堅い／拮抗の判定）」を、レースごとに最初に見た時点のものを1回だけ記録し、
  2. 締切を過ぎたレースについて結果ページを取りに行き、確定した着順を記録する。
こうして溜めたログから、「本命は実際に何%勝ったか」「予測1着率は当たっているか
（キャリブレーション）」「堅い／拮抗の区分ごとの成績」などを集計し、予想成績ページに出す。

course_records.py / form_records.py と同じ考え方で、データは
docs/_prediction_log.json に保存する（GitHub Actionsが docs/ をコミットするため、
実行をまたいで蓄積される）。結果の取得は scraper.fetch_race_result を使う。
結果が未確定（None）のレースは次回以降の実行で再挑戦し、MAX_ATTEMPTS 回失敗した
レースは「結果不明」として集計から外す（無限にリトライしない）。
"""

import os
import json
import datetime

import scraper
from scraper import extract_race_id_from_url, fetch_race_result

LOG_FILENAME = "_prediction_log.json"
DEBUG_FILENAME = "_result_debug.json"   # 結果取得に失敗した理由の診断（原因調査用）
KEEP_DAYS = 90            # ログを保持する日数（これより古い日付のレースは削除）
MAX_ATTEMPTS = 6          # 結果取得に失敗してよい回数の上限
MAX_FETCH_PER_RUN = 150   # 1回の実行で結果ページを取りに行く最大レース数（実行時間の上限対策）
TRIFECTA_KEEP = 5         # ログに残す3連単の上位組合せ数
# 結果ページの読み取り方式の版。版が変わったとき、結果が取れていないレースの失敗回数を
# 0に戻して取り直す（旧方式の不具合で積み上がった失敗回数のせいで、直った後も諦められたままに
# ならないようにするため）。読み取り方式を直したら数字を1つ上げる。
PARSER_VERSION = 4

# キャリブレーション表の区分（本命の予測1着率の下限, 上限, 表示ラベル）
CALIBRATION_BUCKETS = [
    (0, 20, "〜20%"), (20, 30, "20〜30%"), (30, 40, "30〜40%"),
    (40, 50, "40〜50%"), (50, 101, "50%〜"),
]


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def _save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def load_log(docs_dir):
    return _load_json(os.path.join(docs_dir, LOG_FILENAME), {})


def save_log(docs_dir, log):
    _save_json(os.path.join(docs_dir, LOG_FILENAME), log)


def _key(date_str, venue, race_no):
    return f"{date_str}_{venue}_{race_no}"


def _formula_top(rd):
    try:
        from report import formula_top
        return formula_top(rd)
    except Exception:
        return None


def record_predictions(log, all_race_data, date_str):
    """
    all_race_data: run_daily.py の all_race_data（"race_info"/"prediction"/"url"）。
    すでに記録済みのレースは上書きしない（後から結果由来の補正で予想が動いても、
    「最初に出した予想」で成績を評価するため）。戻り値: 新規に記録した件数。
    """
    added = 0
    for rd in all_race_data:
        pred = rd.get("prediction")
        if not pred:
            continue
        info = rd["race_info"]
        key = _key(date_str, info["venue"], info["race_no"])
        if key in log:
            continue
        rows = pred["rows"]  # adjusted降順
        combos = (pred.get("trifecta") or {}).get("combos", [])[:TRIFECTA_KEEP]
        log[key] = {
            "date": date_str,
            "venue": info["venue"],
            "race_no": info["race_no"],
            "deadline": info.get("deadline"),
            "url": rd.get("url"),
            "order": [r["car"] for r in rows],
            "top_adj": round(rows[0]["adjusted"], 2),
            "is_high": bool(pred.get("is_high_prob")),
            "is_close": bool(pred.get("is_close_race")),
            "trifecta": [[c["first"], c["second"], c["third"]] for c in combos],
            # 各選手の予測（車番, 1着率%, 3着内率%）と、そのとき使った1着率の絞り込み（毎日の自動補正用）
            "probs": [[r["car"], round(r["adjusted"], 2), round(r.get("place_rate", 0), 1)] for r in rows],
            "sf": (pred.get("settings") or {}).get("sharpness_first"),
            # 2着・3着の確率を後から再計算するための入力（毎日の自動補正用。calibration.py）
            "cond": pred.get("cond_inputs"),
            # 勝利の方程式（能力値+L+M）の順位つき点数。成績ページで答え合わせする
            "ev": _formula_top(rd),
            "result": None,
            "attempts": 0,
            "parser_v": PARSER_VERSION,
        }
        added += 1
    return added


def _prune(log, today):
    cutoff = (today - datetime.timedelta(days=KEEP_DAYS)).isoformat()
    for k in [k for k, v in log.items() if v.get("date", "") < cutoff]:
        del log[k]


def update_results(log, today, now_hm, debug=None):
    """
    結果が未取得で、すでに締切を過ぎている（過去日付なら無条件で対象）レースの結果を取得する。
    戻り値: 新たに結果を記録できた件数。
    """
    today_str = today.isoformat()
    fetched = 0
    newly = 0
    failed = 0
    for v in log.values():
        if v.get("result") is None and v.get("parser_v") != PARSER_VERSION:
            v["attempts"] = 0
            v["parser_v"] = PARSER_VERSION
    pending = [
        v for v in log.values()
        if v.get("result") is None and v.get("attempts", 0) < MAX_ATTEMPTS and v.get("url")
        and (v["date"] < today_str or (v.get("deadline") and v["deadline"] < now_hm))
    ]
    pending.sort(key=lambda v: (v["date"], v.get("deadline") or ""))
    for v in pending:
        if fetched >= MAX_FETCH_PER_RUN:
            break
        race_id = extract_race_id_from_url(v["url"])
        if not race_id:
            v["attempts"] = MAX_ATTEMPTS  # URLから識別できないレースは諦める
            continue
        fetched += 1
        try:
            res = fetch_race_result(v["venue"], race_id)
        except Exception as e:
            v["attempts"] = v.get("attempts", 0) + 1
            print(f"[WARN] {v['venue']} {v['race_no']}R: 予想成績用の結果取得に失敗しました: {e}")
            if debug is not None and len(debug["failures"]) < 5:
                debug["failures"].append({"race": f"{v['date']} {v['venue']} {v['race_no']}R", "error": repr(e)[:300]})
            continue
        if not res:
            if debug is not None and len(debug["failures"]) < 5:
                debug["failures"].append({"race": f"{v['date']} {v['venue']} {v['race_no']}R",
                                          "diag": dict(scraper.LAST_RESULT_DIAG)})
            v["attempts"] = v.get("attempts", 0) + 1  # まだ確定していない／解析できない
            failed += 1
            continue
        res = sorted(res, key=lambda r: r["finish"])
        # 取り違え防止：結果の車番が、予想を記録したときの出走車番に含まれていなければ採用しない
        if v.get("order") and not {r["car"] for r in res} <= set(v["order"]):
            v["attempts"] = v.get("attempts", 0) + 1
            failed += 1
            if debug is not None and len(debug["failures"]) < 5:
                debug["failures"].append({"race": f"{v['date']} {v['venue']} {v['race_no']}R",
                                          "error": "結果の車番が出走車番と一致しない", "cars": [r["car"] for r in res]})
            continue
        v["result"] = {
            "finish_order": [r["car"] for r in res],
            "winner_kimarite": res[0].get("kimarite"),
        }
        newly += 1
    if fetched:
        print(f"[INFO] 予想成績: 結果ページ{fetched}件を取得し、{newly}件で着順を記録、{failed}件は未確定または解析失敗でした。")
    return newly


def refresh_log(docs_dir, all_race_data, today, now_hm):
    """予想の記録→結果の照合→保存までを一括で行う。戻り値: (log, 新規記録数, 新規結果数)。"""
    log = load_log(docs_dir)
    added = record_predictions(log, all_race_data, today.isoformat())
    debug = {"updated": f"{today.isoformat()} {now_hm}", "failures": []}
    newly = update_results(log, today, now_hm, debug)
    _prune(log, today)
    save_log(docs_dir, log)
    debug["tracked"] = len(log)
    debug["with_result"] = sum(1 for v in log.values() if v.get("result"))
    debug["without_url"] = sum(1 for v in log.values() if not v.get("url"))
    debug["pending_eligible"] = sum(
        1 for v in log.values() if v.get("result") is None and v.get("url")
        and (v["date"] < today.isoformat() or (v.get("deadline") and v["deadline"] < now_hm)))
    try:
        _save_json(os.path.join(docs_dir, DEBUG_FILENAME), debug)
    except OSError:
        pass
    if added or newly:
        print(f"[INFO] 予想成績ログ: 新規予想{added}件、新規結果{newly}件（累計{len(log)}件）。")
    return log, added, newly


# ============================================================
# 集計
# ============================================================
def _evaluate(entry):
    """1レースの予想と結果を突き合わせる（結果がなければNone）。"""
    res = entry.get("result")
    if not res or len(res.get("finish_order", [])) < 3:
        return None
    order = entry["order"]
    fin = res["finish_order"]
    top = order[0]
    return {
        "top1": fin[0] == top,
        "top2": top in fin[:2],
        "top3": top in fin[:3],
        "box3": set(order[:3]) == set(fin[:3]),
        "tri1": bool(entry["trifecta"]) and entry["trifecta"][0] == fin[:3],
        "tri5": any(c == fin[:3] for c in entry["trifecta"]),
        "top_adj": entry["top_adj"],
        "is_high": entry["is_high"],
        "is_close": entry["is_close"],
    }


def _summarize(evals):
    n = len(evals)
    if n == 0:
        return {"n": 0}
    def rate(k):
        return sum(1 for e in evals if e[k]) / n * 100
    return {
        "n": n,
        "top1": rate("top1"), "top2": rate("top2"), "top3": rate("top3"),
        "box3": rate("box3"), "tri1": rate("tri1"), "tri5": rate("tri5"),
        "pred_top": sum(e["top_adj"] for e in evals) / n,   # 本命の予測1着率の平均
    }


def _quantile_bands(vals, k):
    """値のリストを件数がほぼ等しいk個の帯に分ける。戻り値: [(下限, 上限)...]（下限以上・次の下限未満）。"""
    v = sorted(vals)
    if len(v) < k * 5:
        return []
    cuts = [v[int(len(v) * i / k)] for i in range(k)] + [float("inf")]
    return [(cuts[i], cuts[i + 1]) for i in range(k) if cuts[i] < cuts[i + 1]]


def _band_label(lo, hi, fmt="{:.0f}"):
    return (f"{fmt.format(lo)}以上" if hi == float("inf") else f"{fmt.format(lo)}〜{fmt.format(hi)}未満")


def formula_analysis(evaluated):
    """
    勝利の方程式の場合分け分析。evaluated: [(entry, ev)]（結果つき）。
      by_rank:  方程式で◯位だった選手の 1着/2着内/3着内の割合（AIの◯位と並べる）
      by_top:   方程式1位の期待値の帯ごと（1位が1着・3着内。AIの本命と比較）
      by_gap:   1位と2位の差の帯ごと
      by_value: 全選手の期待値の帯ごと（その選手が1着・3着内）
      by_tag:   堅い/拮抗/その他 × 方程式1位の成績
      by_cars:  車立て（7車/8車以上）ごと
    """
    rows = []
    for e, _ in evaluated:
        f = e.get("ev")
        if not f or len(f) < 3:
            continue
        rows.append((e, f, e["result"]["finish_order"]))
    out = {"n": len(rows)}
    if not rows:
        return out

    def hits(car, fin):
        return (fin[0] == car, car in fin[:2], car in fin[:3])

    def acc():
        return {"n": 0, "w": 0, "p2": 0, "p3": 0, "aw": 0, "ap2": 0, "ap3": 0}

    def add(t, f_car, a_car, fin):
        t["n"] += 1
        h = hits(f_car, fin); ah = hits(a_car, fin)
        t["w"] += h[0]; t["p2"] += h[1]; t["p3"] += h[2]
        t["aw"] += ah[0]; t["ap2"] += ah[1]; t["ap3"] += ah[2]

    # 順位別
    by_rank = {}
    maxr = max(len(f) for _, f, _ in rows)
    for k in range(min(maxr, 9)):
        t = acc()
        for e, f, fin in rows:
            if k < len(f) and k < len(e["order"]):
                add(t, f[k][0], e["order"][k], fin)
        by_rank[k + 1] = t
    out["by_rank"] = by_rank

    def banded(valfn, k, fmt):
        vals = [valfn(e, f) for e, f, _ in rows]
        bands = _quantile_bands(vals, k)
        res = []
        for lo, hi in bands:
            t = acc()
            for (e, f, fin), v in zip(rows, vals):
                if lo <= v < hi:
                    add(t, f[0][0], e["order"][0], fin)
            res.append((_band_label(lo, hi, fmt), t))
        return res

    out["by_top"] = banded(lambda e, f: f[0][1], 4, "{:.0f}")
    out["by_gap"] = banded(lambda e, f: f[0][1] - f[1][1], 4, "{:.1f}")

    # 全選手の期待値帯（その選手自身の成績）
    allv = [(x[1], x[0], fin) for e, f, fin in rows for x in f]
    bands = _quantile_bands([v for v, _, _ in allv], 5)
    byv = []
    for lo, hi in bands:
        n = w = p3 = 0
        for v, car, fin in allv:
            if lo <= v < hi:
                n += 1; w += fin[0] == car; p3 += car in fin[:3]
        byv.append((_band_label(lo, hi, "{:.0f}"), {"n": n, "w": w, "p3": p3}))
    out["by_value"] = byv

    def seg(pred):
        t = acc()
        for e, f, fin in rows:
            if pred(e):
                add(t, f[0][0], e["order"][0], fin)
        return t

    out["by_tag"] = [("本命が堅い", seg(lambda e: e.get("is_high"))),
                     ("拮抗", seg(lambda e: e.get("is_close"))),
                     ("どちらでもない", seg(lambda e: not e.get("is_high") and not e.get("is_close")))]
    out["by_cars"] = [("7車立て以下", seg(lambda e: len(e["order"]) <= 7)),
                      ("8車立て以上", seg(lambda e: len(e["order"]) >= 8))]
    return out


def compute_prediction_stats(log):
    """
    戻り値:
      overall / segments(堅い・拮抗・その他) / calibration(区分ごと) / by_day(新しい順) /
      recent(直近の結果つきレース、新しい順) / pending_count(結果待ちの件数)
    """
    evaluated = []
    for e in log.values():
        ev = _evaluate(e)
        if ev:
            ev["date"] = e["date"]
            evaluated.append((e, ev))

    evals = [ev for _, ev in evaluated]
    segments = {
        "high": _summarize([e for e in evals if e["is_high"]]),
        "close": _summarize([e for e in evals if e["is_close"]]),
        "other": _summarize([e for e in evals if not e["is_high"] and not e["is_close"]]),
    }

    calibration = []
    for lo, hi, label in CALIBRATION_BUCKETS:
        bucket = [e for e in evals if lo <= e["top_adj"] < hi]
        s = _summarize(bucket)
        calibration.append({"label": label, **s})

    by_day = {}
    for _, ev in evaluated:
        by_day.setdefault(ev["date"], []).append(ev)
    by_day_list = [{"date": d, **_summarize(v)} for d, v in sorted(by_day.items(), reverse=True)]

    recent = sorted(
        (e for e, _ in evaluated), key=lambda e: (e["date"], e.get("deadline") or ""), reverse=True)

    # 勝利の方程式 vs AIの本命（方程式を記録したレースだけで比べる）
    def _fa_new():
        return {"n": 0, "f1": 0, "f2": 0, "f3": 0, "fbox": 0, "a1": 0, "a2": 0, "a3": 0, "abox": 0}
    fa = _fa_new()
    fa_seg = {"same": _fa_new(), "diff": _fa_new(), "gap_big": _fa_new(), "gap_small": _fa_new()}
    for e, _ in evaluated:
        ev = e.get("ev")
        if not ev or len(ev) < 3:
            continue
        fin = e["result"]["finish_order"]
        fc, ac = ev[0][0], e["order"][0]
        gap = ev[0][1] - ev[1][1]
        hit = {
            "f1": fin[0] == fc, "f2": fc in fin[:2], "f3": fc in fin[:3],
            "fbox": {x[0] for x in ev[:3]} == set(fin[:3]),
            "a1": fin[0] == ac, "a2": ac in fin[:2], "a3": ac in fin[:3],
            "abox": set(e["order"][:3]) == set(fin[:3]),
        }
        segs = [fa, fa_seg["same" if fc == ac else "diff"], fa_seg["gap_big" if gap >= 10 else "gap_small"]]
        for t in segs:
            t["n"] += 1
            for k, v in hit.items():
                t[k] += bool(v)
    fa["seg"] = fa_seg
    fa["analysis"] = formula_analysis(evaluated)
    pending = sum(1 for e in log.values() if e.get("result") is None and e.get("attempts", 0) < MAX_ATTEMPTS)
    return {
        "overall": _summarize(evals), "segments": segments, "calibration": calibration,
        "by_day": by_day_list, "recent": recent, "pending_count": pending,
        "tracked_count": len(log), "formula": fa,
    }
