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

from scraper import extract_race_id_from_url, fetch_race_result

LOG_FILENAME = "_prediction_log.json"
KEEP_DAYS = 90            # ログを保持する日数（これより古い日付のレースは削除）
MAX_ATTEMPTS = 6          # 結果取得に失敗してよい回数の上限
MAX_FETCH_PER_RUN = 40    # 1回の実行で結果ページを取りに行く最大レース数（実行時間の上限対策）
TRIFECTA_KEEP = 5         # ログに残す3連単の上位組合せ数
# 結果ページの読み取り方式の版。版が変わったとき、結果が取れていないレースの失敗回数を
# 0に戻して取り直す（旧方式の不具合で積み上がった失敗回数のせいで、直った後も諦められたままに
# ならないようにするため）。読み取り方式を直したら数字を1つ上げる。
PARSER_VERSION = 2

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


def update_results(log, today, now_hm):
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
            continue
        if not res:
            v["attempts"] = v.get("attempts", 0) + 1  # まだ確定していない／解析できない
            failed += 1
            continue
        res = sorted(res, key=lambda r: r["finish"])
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
    newly = update_results(log, today, now_hm)
    _prune(log, today)
    save_log(docs_dir, log)
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

    pending = sum(1 for e in log.values() if e.get("result") is None and e.get("attempts", 0) < MAX_ATTEMPTS)
    return {
        "overall": _summarize(evals), "segments": segments, "calibration": calibration,
        "by_day": by_day_list, "recent": recent, "pending_count": pending,
        "tracked_count": len(log),
    }
