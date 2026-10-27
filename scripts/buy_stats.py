# -*- coding: utf-8 -*-
"""
「このレースの買い方」の成績を毎日自動で貯めて、判定の根拠（レース数・的中率・回収率）を増やしていく。

流れ（run_daily.py から呼ぶ）:
  1) record : 締切前のレースについて、補正後の3連単の上位 KEEP 点（確率順・オッズつき）と型を
              docs/_buy_log.json に記録する（締切後は上書きしない＝結果を見たあとの情報を混ぜない）
  2) settle : 結果（prediction_log の着順）が出たレースの1着-2着-3着を記録する
  3) publish_hist : 型ごとに、記録済みレースで各買い方（合成1.5倍／5点／10点）を試した的中率・回収率を集計し、
              market_fix.LIVE_HIST に入れて画面の「判定の根拠」に使う

注意:
  - 記録したオッズは「締切前の最後の実行（最大1時間前）」の値。確定オッズとは少しずれる。
  - seed（src="seed"）は保存済みの winticket ページ（10/24〜10/26）から作った初期データ。
    オッズは3連単の約8割の組だけの近似。live（src="live"）が自動記録の本番データ。
  - 回収率は、選んだ買い目に当たりが入っていれば「払戻（オッズ×100円）÷ 買い目の点数×100円」で計算。
"""
import json
import os
import random

import market_fix

LOG_NAME = "_buy_log.json"
STATS_NAME = "_buy_stats.json"
KEEP = 40            # 1レースにつき保存する3連単の上位点数
PLAN_IDS = ("syn1.5", "top5", "top10")
MIN_RACES_TO_SHOW = 20


def _path(docs, name):
    return os.path.join(docs, name)


def load(docs):
    try:
        with open(_path(docs, LOG_NAME), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save(docs, log):
    with open(_path(docs, LOG_NAME), "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, separators=(",", ":"))


def _key(date, venue, race_no):
    return f"{date}_{venue}_{race_no}"


def record(log, all_race_data, today, now_hm):
    """締切前でオッズ補正済み（fix_mode=odds）のレースだけ記録／更新する。追加・更新した件数を返す。"""
    n = 0
    for rd in all_race_data:
        info, pred = rd["race_info"], rd.get("prediction")
        dl = info.get("deadline")
        if not pred or pred.get("fix_mode") != "odds" or not dl or dl <= now_hm:
            continue
        combos = (pred.get("trifecta") or {}).get("combos") or []
        items = [[f"{c['first']}-{c['second']}-{c['third']}", c["odds"], round(c["prob"], 3)]
                 for c in combos if c.get("odds")][:KEEP]
        if len(items) < 10:
            continue
        k = _key(today.isoformat(), info["venue"], info["race_no"])
        old = log.get(k) or {}
        log[k] = {"date": today.isoformat(), "venue": info["venue"], "race_no": info["race_no"],
                  "deadline": dl, "type": market_fix.race_type(pred["rows"]),
                  "top": round(max(r["adjusted"] for r in pred["rows"]), 1),
                  "items": items, "winner": old.get("winner"), "src": "live"}
        n += 1
    return n


def settle(log, prediction_log):
    """prediction_log に着順が入ったレースの勝ち組（1-2-3着）を書き込む。"""
    n = 0
    for k, v in log.items():
        if v.get("winner"):
            continue
        e = (prediction_log or {}).get(k)
        fin = ((e or {}).get("result") or {}).get("finish_order") or []
        if len(fin) >= 3:
            v["winner"] = "-".join(str(c) for c in fin[:3])
            n += 1
    return n


def evaluate(entries, plan_id):
    """entries（勝ち組が確定した記録）で買い方 plan_id を試す。(レース数, 的中数, 点数合計, 払戻合計[100円単位])"""
    races = hits = pts = ret = 0
    for v in entries:
        items = [(k, o) for k, o, _ in v["items"]]       # 確率の高い順で保存済み
        odds = dict(items)
        sel = market_fix.pick_plan(items, plan_id)
        races += 1
        pts += len(sel)
        if v["winner"] in sel:
            hits += 1
            ret += odds[v["winner"]]
    return races, hits, pts, ret


def _fmt(races, hits, pts, ret):
    return f"的中{hits / races * 100:.0f}%・回収率{ret / pts * 100:.0f}%" if races and pts else "—"


def summarize(log):
    """型×買い方ごとの成績。{型: {plan_id: {all:{...}, live:{...}}}}"""
    out = {}
    done = [v for v in log.values() if v.get("winner") and v.get("type")]
    for t in ("堅い", "中間", "混戦"):
        out[t] = {}
        for pid in PLAN_IDS:
            row = {}
            for name, es in (("all", [v for v in done if v["type"] == t]),
                             ("live", [v for v in done if v["type"] == t and v.get("src") == "live"])):
                races, hits, pts, ret = evaluate(es, pid)
                row[name] = {"races": races, "hits": hits, "points": pts, "return": round(ret, 1),
                             "hit_pct": round(hits / races * 100, 1) if races else None,
                             "roi_pct": round(ret / pts * 100, 1) if pts else None}
            out[t][pid] = row
    return out


def hist_texts(summary):
    """画面に出す『判定の根拠』の文章。実際に使う買い方（AUTO[型]["id"]）の成績で作る。"""
    texts = {}
    for t, cfg in market_fix.AUTO.items():
        s = summary.get(t, {}).get(cfg["id"])
        if not s or s["all"]["races"] < MIN_RACES_TO_SHOW:
            continue
        a, lv = s["all"], s["live"]
        txt = f"{a['races']}レースで的中{a['hit_pct']:.0f}%・回収率{a['roi_pct']:.0f}%"
        if lv["races"] >= 10:
            txt += f"（うち自動記録{lv['races']}レースは回収率{lv['roi_pct']:.0f}%）"
        elif lv["races"]:
            txt += f"（自動記録は{lv['races']}レース・検証中）"
        if cfg["skip"]:
            txt = (f"参考の5点で{a['races']}レース中、的中{a['hit_pct']:.0f}%・回収率{a['roi_pct']:.0f}%。"
                   "買い方しだいで回収が大きくブレ、控除後の約75%を安定して超える買い方がまだ見つかっていません")
        texts[t] = txt
    return texts


def publish_hist(docs):
    """毎回の実行の最初に呼ぶ。記録済みのログから根拠の文章を作って market_fix に渡す。"""
    log = load(docs)
    texts = hist_texts(summarize(log)) if log else {}
    market_fix.LIVE_HIST.clear()
    market_fix.LIVE_HIST.update(texts)
    return texts


def update(docs, all_race_data, prediction_log, today, now_hm):
    """毎回の実行の後半で呼ぶ。記録→答え合わせ→集計の保存。"""
    log = load(docs)
    rec = record(log, all_race_data, today, now_hm)
    st = settle(log, prediction_log)
    # 古い記録の整理（60日より前は消す）
    cutoff = (today.fromordinal(today.toordinal() - 60)).isoformat()
    for k in [k for k, v in log.items() if v.get("date", "") < cutoff]:
        del log[k]
    save(docs, log)
    summary = summarize(log)
    with open(_path(docs, STATS_NAME), "w", encoding="utf-8") as f:
        json.dump({"updated": today.isoformat(), "races": len(log), "summary": summary}, f,
                  ensure_ascii=False, indent=2)
    print(f"[INFO] 買い方の成績ログを更新（記録{rec}件・答え合わせ{st}件・累計{len(log)}レース）。")
    return summary


def bootstrap_interval(entries, plan_id, n=1000, seed=1):
    """回収率の90%区間（レースを復元抽出）。分析用。"""
    rnd = random.Random(seed)
    per = []
    for v in entries:
        items = [(k, o) for k, o, _ in v["items"]]
        sel = market_fix.pick_plan(items, plan_id)
        per.append((len(sel), dict(items)[v["winner"]] if v["winner"] in sel else 0))
    outs = []
    for _ in range(n):
        b = [rnd.choice(per) for _ in per]
        pts = sum(x for x, _ in b)
        outs.append(sum(y for _, y in b) / pts * 100 if pts else 0)
    outs.sort()
    return outs[int(.05 * n)], outs[int(.95 * n)]
