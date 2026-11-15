# -*- coding: utf-8 -*-
"""
競輪「買うべきレース」(docs/picks.html)。ライン並び通りの3連単ルールに当てはまるレースだけを出す。

ルール(2025-01〜2026-11 の winticket 確定データで検証。scripts/wt_trifecta_search.py):
  ラインの強さ = ライン内の予想印(◎4 ○3 ▲2 △1)の合計(同点は競走得点の平均で決める)。出走表だけで分かる(オッズ不要)。
  A 9車立て → 印で2番目のラインを並び通り(先頭→番手→3番手)  … 2196点 回収率131%(2025年129%・2026年133%)
  B 9車立て → 印で3番目のラインを並び通り                      … 1420点 回収率110%
  C 7車立て → 印で3番目のラインを並び通り                      … 2462点 回収率122%
  (どれも3人以上のラインのときだけ。A+B+C 合計 6078点・的中84回・回収率122%、上位5本の的中を除くと93%)

記録: docs/_picks_log.json に買い目を残し、レースが終わったら結果(的中・払戻)を書き足す → ページ下部に通算成績。

使い方(scripts/ で): python wt_picks.py   ※ daily.yml(1時間おき)から呼ぶ
"""
import datetime
import html
import json

import numpy as np
import os
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wt_backfill import BASE, get_state, month_cups, queries, race_numbers  # noqa: E402
from wt_manshaken import market_view  # noqa: E402

JST = ZoneInfo("Asia/Tokyo")
DOCS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs")
LOG = os.path.join(DOCS, "_picks_log.json")
MARK_PT = {1: 4, 2: 3, 3: 2, 4: 1}
RULES = [
    ("A", 9, 2, "9車立て・印2番目のライン 並び通り", "検証 2196点 回収率131%(2025年129%・2026年133%)"),
    ("B", 9, 3, "9車立て・印3番目のライン 並び通り", "検証 1420点 回収率110%"),
    ("C", 7, 3, "7車立て・印3番目のライン 並び通り", "検証 2462点 回収率122%"),
]

# D: 車立てを問わず、印2番目のラインの並び通り3連単が「10〜30倍」のとき(レース結果からの逆算で見つけた物)
# 検証: 3548点 的中214回 回収率111%(2025年111%・2026年110%)、上位5本の的中を除いても106%(大穴頼みではない)
D_RULE = ("D", "印2番目のライン 並び通り(3連単が10〜30倍のとき)",
          "検証 3548点・的中214回・回収率111%(2025年111%・2026年110%、上位5本の的中を除いても106%)")
D_ODDS = (10.0, 30.0)


# F(穴): 印3番目のラインの並び通り3連単が「30〜300倍」のとき(レース結果からの逆算で見つけた穴の買い方)
# 検証: 2824点 的中34回 回収率139%(2025年140%・2026年136%)、平均配当11,507円、上位5本の的中を除くと96%
F_RULE = ("F", "穴: 印3番目のライン 並び通り(3連単が30〜300倍のとき)",
          "検証 2824点・的中34回・回収率139%(2025年140%・2026年136%)、平均配当11,507円")
F_ODDS = (30.0, 300.0)


# W(的中率と回収率の両立): 9車立てで、印1〜3番目のライン(3車以上)の「先頭と3番手」のワイドが 3〜12倍 のとき
# (番手を飛ばして先頭-3番手。番手は先頭を残しにいき、3番手は最後に差し込むので、2人とも3着内が市場の見込みより多い)
# 検証(確定オッズ): 2705点・的中率18.0%・回収率112.5%(2025年111.9%・2026年113.1%)、90%の幅104〜121%、上位5本を除いても110%
#   9車以外(主に7車)は 94% 前後で控除率(約25%)よりずっと良いが100%に届かない。先頭-番手・番手-3番手のワイドは 77〜95%
W_RULE = ("W", "ワイド: 9車立て・印1〜3番目のライン(3車以上)の先頭と3番手(3〜12倍のとき)",
          "検証 2705点・的中率18%(5〜6レースに1回)・回収率112%(2025年112%・2026年113%、上位5本を除いても110%)")
W_ODDS = (3.0, 12.0)


def wide_odds(O):
    """ワイドのオッズ(下限) {"小=大": オッズ}"""
    out = {}
    for x in (O or {}).get("quinellaPlace") or []:
        if x.get("absent") or not x.get("minOdds"):
            continue
        a, b = sorted(x["key"][:2])
        out[f"{a}={b}"] = x.get("minOdds")
    return out


# 穴目の表(wt_result_patterns.py の結果): 「ライン何番目 × 並び通り/番手差し × 3連単のオッズ帯」ごとの過去の回収率
ANA_TABLE_PATH = os.path.join(DOCS, "_ana_table.json")
ANA_MIN_ROI, ANA_MIN_HITS = 0.85, 15     # これ未満の穴目は出さない(損が大きい・当たりが少なすぎて当てにならない)
from keirin_region import line_relation  # noqa: E402
from hit_plan import plan as hit_plan  # noqa: E402
# 中穴(3連単5,000円以上): ルールA〜C・Fのうち今のオッズが50倍以上の買い目。
# 中でも「C・Fで、ラインの前3人が同じ地区」は 994点・的中14回・回収率199%(2025年148%・2026年259%)、
# F だけなら 1186点・的中17回・回収率217%(2025年184%・2026年257%、上位5本を除いても117%、平均配当15,123円)→ 中穴★
# (ライン構成の組み合わせを総当たりした50〜300倍の買い目は、2025年で選んでも2026年は71%で使えなかった)
CHU_ODDS = 50.0
HONMEI_MAN = 0.30                         # 万車率がこれ未満は本命レース(穴党は見送り)


def load_ana_table():
    try:
        with open(ANA_TABLE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


ANA_TABLE = load_ana_table()


def load_keshi(today):
    """予想ページ(run_daily.py)が保存した AI推奨の組 = 消し目。{"場スラッグ:R": [組, ...]}"""
    try:
        with open(os.path.join(DOCS, "_ai_keshi.json"), encoding="utf-8") as f:
            d = json.load(f)
        return d["races"] if d.get("date") == today.isoformat() else {}
    except (OSError, ValueError, KeyError):
        return {}


def race_lines(R):
    entries = [e for e in R.get("entries", []) if not e.get("absent")]
    cars = {int(e["number"]) for e in entries}
    lp = R.get("linePrediction") or {}
    lines = [[n for en in L.get("entries", []) for n in en.get("numbers", []) if n in cars] for L in lp.get("lines", [])]
    lines = [L for L in lines if L]
    rec = {r["playerId"]: r for r in R.get("records", [])}
    mark = {int(e["number"]): (rec.get(e["playerId"]) or {}).get("predictionMark") for e in entries}
    point = {int(e["number"]): (rec.get(e["playerId"]) or {}).get("racePoint") or 0 for e in entries}
    if len(lines) < 2 or not any(mark.values()):
        return []
    return [lines[i] for i in line_rank(lines, mark, point)]


def ana_candidates(R, tri, table=None):
    """このレースの穴目: 印で並べたライン1〜3番目の「並び通り」「番手差し」のうち、今のオッズ帯で過去の回収率が
    ANA_MIN_ROI 以上(的中 ANA_MIN_HITS 回以上)のもの。10倍未満(本命)と1000倍以上は出さない。過去の回収率の高い順"""
    table = ANA_TABLE if table is None else table
    out = []
    for k, L in enumerate(race_lines(R)[:3], start=1):
        if len(L) < 3:
            continue
        for pat, t in (("並び通り", f"{L[0]}-{L[1]}-{L[2]}"), ("番手差し", f"{L[1]}-{L[0]}-{L[2]}")):
            od = tri.get(t)
            if not od or od < 10 or od >= 1000:
                continue
            cell = next((c for c in table if c["pattern"] == pat and c["line"] == k and c["lo"] <= od < c["hi"]), None)
            if cell and cell["roi"] >= ANA_MIN_ROI and cell["hits"] >= ANA_MIN_HITS:
                out.append(dict(ticket=t, odds=od, label=f"{k}番目のライン {pat}", roi=cell["roi"], hits=cell["hits"],
                                win=cell["roi"] >= 1.0 and min(cell["roi2025"], cell["roi2026"]) >= 0.95))
    return sorted(out, key=lambda x: -x["roi"])


def second_line_ticket(R):
    """印2番目のライン(3車以上)の並び通りの買い目。無ければ None"""
    return line_ticket(R, 2)


# E(参考): 印で最強のラインの並び通りが10倍以下のとき。検証 15124点・的中率21%・回収率91%(両年とも90%前後)。
# 勝ち筋ではないが、ルールに当たらないレースで「買うならこれ」という一番損の少ない1点
E_RULE = ("E", "参考: 最強ラインの並び通り(3連単10倍以下のとき)", "検証 15124点・的中率21%・回収率91%(勝ち筋ではない)")
E_ODDS = 10.0


def line_ticket(R, k):
    """印でk番目のライン(3車以上)の並び通りの買い目。無ければ None"""
    entries = [e for e in R.get("entries", []) if not e.get("absent")]
    cars = {int(e["number"]) for e in entries}
    lp = R.get("linePrediction") or {}
    lines = [[n for en in L.get("entries", []) for n in en.get("numbers", []) if n in cars] for L in lp.get("lines", [])]
    lines = [L for L in lines if L]
    rec = {r["playerId"]: r for r in R.get("records", [])}
    mark = {int(e["number"]): (rec.get(e["playerId"]) or {}).get("predictionMark") for e in entries}
    point = {int(e["number"]): (rec.get(e["playerId"]) or {}).get("racePoint") or 0 for e in entries}
    if len(lines) < 2 or not any(mark.values()):
        return None
    order = line_rank(lines, mark, point)
    if len(order) < k:
        return None
    L = lines[order[k - 1]]
    return (f"{L[0]}-{L[1]}-{L[2]}", L) if len(L) >= 3 else None


def trifecta_odds(O):
    return {"-".join(map(str, x["key"])): x.get("odds") for x in (O or {}).get("trifecta") or [] if x.get("odds")}


# 重賞(G戦)の決勝・準決勝は毎レース出す「重賞パック」: 印◎ → ◎のライン番手 → 印順の相手5車(5点)
# 検証: 422レース 的中54回 回収率107%(2025年117%・2026年95%、決勝121%・準決勝103%)。トントン圏で、勝ちとまでは言えない
G_RULE = ("G", "重賞パック(G戦の決勝・準決勝): 印◎→◎の番手→印順の相手5車",
          "検証 422レース・的中54回・回収率107%(2025年117%・2026年95%)。トントン圏")


# 重賞(G戦)の決勝・準決勝以外(予選・特選・選抜・一般など)は「重賞パック(予選など)」:
#   3人以上のラインを全部 並び通り(先頭→番手→3番手) + 印で最強ラインの番手→先頭→3番手(番手差し)
# 検証: 3918レース 平均2.5点 的中535回(的中率14%)回収率102%(2025年100%・2026年105%)。トントン圏
H_RULE = ("H", "重賞パック(G戦の予選など): 3車以上のライン全部を並び通り + 最強ラインの番手差し",
          "検証 3918レース・的中535回・回収率102%(2025年100%・2026年105%)。トントン圏")
BIG = {"G": G_RULE, "H": H_RULE}


# K: レースごとに買い方(フォーメーション/1点)を変える3連単ルール(11/15。scripts の外の検証: winticket 2025〜2026年 約5万レース、
#    確定オッズで「合成オッズ2倍以上」の買い方だけを数えた。印でk番目のライン = ライン内の予想印の合計で並べた順)
#   K1 印3番目のライン(3車以上)の先頭・番手の2車 → 1・2着(順不同) → 3着は全員 (2×(車数-2)点)
#      合成オッズ8〜20倍・1番人気の1着率30〜45%のとき   2025年 468レース 回収率125% / 2026年 409レース 137%(的中率7〜11%)
#   K4 印2番目のラインの並び通り(1点)が8〜20倍のとき    2025年 946点 120% / 2026年 873点 102%(的中率7〜9%)
#   K6 三分戦(2車以上のラインが3本)で、印2番目のラインの並び通りが20〜60倍のとき
#                                                       2025年 1157点 105% / 2026年 1014点 106%(的中率3%)
#   K1→K4→K6 の順に1レース1つ。3つ合わせて 2025年121%・2026年128%(1日6〜7レース)。上位5本の的中を除くと82〜88%(大きい配当頼み)
K_RULES = {
    "K1": ("K1 フォーメーション: 印3番目のライン 先頭・番手 → 全(合成8〜20倍・1番人気30〜45%)",
           "検証 2025年 468レース 回収率125%・2026年 409レース 137%(的中率7〜11%)"),
    "K4": ("K4 1点: 印2番目のライン 並び通り(8〜20倍)", "検証 2025年 946点 120%・2026年 873点 102%(的中率7〜9%)"),
    "K6": ("K6 1点(穴): 三分戦で印2番目のライン 並び通り(20〜60倍)", "検証 2025年 1157点 105%・2026年 1014点 106%(的中率3%)"),
}
MIN_COMP = 2.0   # 合成オッズがこれ未満の買い目は出さない

# M: 万車率(3連単オッズ100倍以上の組の市場確率の合計)が高いレースで回収率が高かった形(11/15。winticket 2025〜2026年・確定オッズ)
#   M3 万車率50%以上・印1番目のライン 先頭・番手→先頭・番手→3番手(2点)・合成5〜10倍  2025年114%・2026年116%(的中率16%)
#   M2 万車率50%以上・印1番目のライン 番手→先頭→3番手(1点)                          2025年126%・2026年116%(的中率6%)
#   M1 万車率30〜40%・印3番目のライン 先頭・番手→先頭・番手→3番手(2点)              2025年116%・2026年136%(的中率3%)
#   (M4 全員→2番目のライン先頭・番手(2・3着) は単独では109〜131%だが、M3・M2と重ならないレースだけにすると88〜98%なので外した)
#   M3→M2→M1 の順に1つ。合わせて 2025年116%・2026年126%(1日3〜4レース)。大きい配当頼みの面もある(M1は的中率3%)
M_RULES = {
    "M3": ("M3 万車率50%以上: 1番目のライン 先頭・番手→先頭・番手→3番手(2点・合成5〜10倍)", "検証 2025年114%・2026年116%(的中率16%)"),
    "M2": ("M2 万車率50%以上: 1番目のライン 番手→先頭→3番手(1点)", "検証 2025年126%・2026年116%(的中率6%)"),
    "M1": ("M1 万車率30〜40%: 3番目のライン 先頭・番手→先頭・番手→3番手(2点)", "検証 2025年116%・2026年136%(的中率3%)"),
}


def manshaken_rate(tri):
    inv = {k: 1 / v for k, v in tri.items() if v}
    s = sum(inv.values())
    return sum(v for k, v in inv.items() if tri[k] >= 100) / s if s else None


def m_tickets(R, tri):
    """M3/M2/M1 のうち当てはまる最初の1つ -> (ルール, [買い目], 合成オッズ) か None"""
    if not tri:
        return None
    man = manshaken_rate(tri)
    lines = race_lines(R)
    cars = sorted({int(e["number"]) for e in R.get("entries", []) if not e.get("absent")})
    if man is None or len(lines) < 2:
        return None

    def box2_3(L):
        return [f"{L[0]}-{L[1]}-{L[2]}", f"{L[1]}-{L[0]}-{L[2]}"]
    c = []
    if man >= 0.5 and len(lines[0]) >= 3:
        c.append(("M3", box2_3(lines[0]), (5, 10)))
        c.append(("M2", [f"{lines[0][1]}-{lines[0][0]}-{lines[0][2]}"], (2, 1e9)))
    if 0.3 <= man < 0.4 and len(lines) >= 3 and len(lines[2]) >= 3:
        c.append(("M1", box2_3(lines[2]), (2, 1e9)))
    for key, tks, (lo, hi) in c:
        cp = composite(tri, tks)
        if cp and lo <= cp < hi and cp >= MIN_COMP:
            return key, tks, cp
    return None


def composite(tri, tickets):
    inv = [1 / tri[t] for t in tickets if tri.get(t)]
    return 1 / sum(inv) if inv and len(inv) == len(tickets) else None


def k_tickets(R, tri):
    """K1/K4/K6 のうち当てはまる最初の1つ -> (ルール, [買い目], 合成オッズ) か None"""
    if not tri:
        return None
    lines = race_lines(R)
    cars = sorted({int(e["number"]) for e in R.get("entries", []) if not e.get("absent")})
    if len(lines) < 2 or len(cars) < 5:
        return None
    head = {}
    for t, o in tri.items():
        if o:
            a = t.split("-")[0]
            head[a] = head.get(a, 0) + 1 / o
    q1 = max(head.values()) / sum(head.values()) if head else 0
    if len(lines) >= 3 and len(lines[2]) >= 3:
        a, b = lines[2][0], lines[2][1]
        tks = [f"{x}-{y}-{c}" for x, y in ((a, b), (b, a)) for c in cars if c not in (a, b)]
        cp = composite(tri, tks)
        if cp and 8 <= cp < 20 and 0.30 <= q1 < 0.45:
            return "K1", tks, cp
    if len(lines[1]) >= 3:
        L = lines[1]
        t = f"{L[0]}-{L[1]}-{L[2]}"
        od = tri.get(t)
        if od and 8 <= od < 20:
            return "K4", [t], od
        if od and 20 <= od < 60 and sum(len(x) >= 2 for x in lines) == 3:
            return "K6", [t], od
    return None


# 参考(どのレースにも出す3連単): 回収率100%の形に当たらないレースで「買うならこれ」。勝ち筋ではない。
# 2025〜2026年 約5万レース・合成オッズ2倍以上で検証した、出せるレースが多い形の中で損の少ない順:
#   印1番目のラインの並び通り(1点)            回収率84〜85%・的中率11%(3車以上のラインのレースの約6割)
#   印1番目のライン 先頭→番手→全(流し)         回収率77〜81%・的中率17%
#   人気上位3車BOX(6点)                       回収率72〜77%
#   (どれも合成オッズ2倍未満になる堅いレース(約3%)は見送り)
# (レースごとに一番良い形を細かい条件で選ぶ方法も53通りの形で試したが、選んだ年と別の年では74〜78%に落ちた=当てはめすぎ)
REF_NOTE = "参考(勝ち筋ではない。過去の回収率72〜85%)"


def ref_tickets(R, tri):
    """参考の3連単 -> (ラベル, [買い目]) か None。合成オッズ2倍未満の形は飛ばす"""
    if not tri:
        return None
    lines = race_lines(R)
    cars = sorted({int(e["number"]) for e in R.get("entries", []) if not e.get("absent")})
    cand = []
    if lines and len(lines[0]) >= 3:
        L = lines[0]
        cand.append(("参考 1番目のライン並び通り(過去84%)", [f"{L[0]}-{L[1]}-{L[2]}"]))
    if lines and len(lines[0]) >= 2:
        h, b = lines[0][0], lines[0][1]
        cand.append(("参考 1番目のライン 先頭→番手→全(過去80%)", [f"{h}-{b}-{c}" for c in cars if c not in (h, b)]))
    head = {}
    for t, o in tri.items():
        if o:
            head[t.split("-")[0]] = head.get(t.split("-")[0], 0) + 1 / o
    fav = [int(x) for x in sorted(head, key=lambda x: -head[x])[:3]]
    if len(fav) == 3:
        import itertools as _it
        cand.append(("参考 人気上位3車BOX(過去74%)", ["-".join(map(str, t)) for t in _it.permutations(fav, 3)]))
    for lab, tks in cand:
        cp = composite(tri, tks)
        if cp and cp >= MIN_COMP:
            return lab, tks
    return None


def is_g_race(grade):
    return str(grade or "").startswith("G")


def prelim_tickets(R):
    """重賞パック(予選など)の買い目"""
    entries = [e for e in R.get("entries", []) if not e.get("absent")]
    cars = {int(e["number"]) for e in entries}
    lp = R.get("linePrediction") or {}
    lines = [[n for en in L.get("entries", []) for n in en.get("numbers", []) if n in cars] for L in lp.get("lines", [])]
    lines = [L for L in lines if L]
    rec = {r["playerId"]: r for r in R.get("records", [])}
    mark = {int(e["number"]): (rec.get(e["playerId"]) or {}).get("predictionMark") for e in entries}
    point = {int(e["number"]): (rec.get(e["playerId"]) or {}).get("racePoint") or 0 for e in entries}
    if len(lines) < 2 or not any(mark.values()):
        return []
    tks = [f"{L[0]}-{L[1]}-{L[2]}" for L in lines if len(L) >= 3]
    L1 = lines[line_rank(lines, mark, point)[0]]
    if len(L1) >= 3:
        tks.append(f"{L1[1]}-{L1[0]}-{L1[2]}")
    return list(dict.fromkeys(tks))


def is_big_race(grade, race_type):
    return str(grade or "").startswith("G") and race_type in ("決勝", "準決勝")


def big_race_tickets(R):
    """重賞パックの買い目。◎が番手を持たない(単騎・最後尾)レースは空"""
    entries = [e for e in R.get("entries", []) if not e.get("absent")]
    cars = {int(e["number"]) for e in entries}
    lp = R.get("linePrediction") or {}
    lines = [[n for en in L.get("entries", []) for n in en.get("numbers", []) if n in cars] for L in lp.get("lines", [])]
    lines = [L for L in lines if L]
    rec = {r["playerId"]: r for r in R.get("records", [])}
    mark = {int(e["number"]): int((rec.get(e["playerId"]) or {}).get("predictionMark") or 0) for e in entries}
    point = {int(e["number"]): (rec.get(e["playerId"]) or {}).get("racePoint") or 0 for e in entries}
    if not lines or not any(mark.values()):
        return [], None
    order = sorted(cars, key=lambda c: -(MARK_PT.get(mark[c], 0) + 0.001 * point[c]))
    a = order[0]
    L = next((x for x in lines if a in x), [a])
    i = L.index(a)
    if i + 1 >= len(L):
        return [], (a, None)
    b = L[i + 1]
    return [f"{a}-{b}-{c}" for c in [x for x in order if x not in (a, b)][:5]], (a, b)


def line_rank(lines, mark, point):
    def score(L):
        return sum(MARK_PT.get(int(mark.get(c) or 0), 0) for c in L) + 0.001 * sum(point.get(c, 0) or 0 for c in L) / len(L)
    return sorted(range(len(lines)), key=lambda i: -score(lines[i]))


def evaluate_race(R):
    """FETCH_KEIRIN_RACE のデータ -> 当てはまるルールのリスト [(rule, ticket, line)]"""
    race = R.get("race") or {}
    if race.get("cancel"):
        return [], "中止"
    entries = [e for e in R.get("entries", []) if not e.get("absent")]
    cars = {int(e["number"]) for e in entries}
    lp = R.get("linePrediction") or {}
    lines = [[n for en in L.get("entries", []) for n in en.get("numbers", []) if n in cars] for L in lp.get("lines", [])]
    lines = [L for L in lines if L]
    if len(lines) < 2:
        return [], "並び予想なし"
    rec = {r["playerId"]: r for r in R.get("records", [])}
    mark = {int(e["number"]): (rec.get(e["playerId"]) or {}).get("predictionMark") for e in entries}
    point = {int(e["number"]): (rec.get(e["playerId"]) or {}).get("racePoint") or 0 for e in entries}
    if not any(mark.values()):
        return [], "予想印なし"
    order = line_rank(lines, mark, point)
    out = []
    for key, n, rank, *_ in RULES:
        if len(cars) == n and len(order) >= rank:
            L = lines[order[rank - 1]]
            if len(L) >= 3:
                out.append((key, f"{L[0]}-{L[1]}-{L[2]}", L))
    return out, ""


def load_log():
    try:
        with open(LOG, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def save_log(log):
    with open(LOG, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=0)


def settle(log, now):
    """終わったレースの結果(3連単の的中組と払戻)を書き足す"""
    for p in log:
        if p.get("settled") or p["start_at"] > now.timestamp() - 15 * 60:
            continue
        try:
            if p["url"].startswith("nk:"):
                import alt_source
                R, O = alt_source.race_for_settle(p["url"])
            else:
                st, _ = get_state(p["url"])
                q = queries(st)
                R, O = q.get("FETCH_KEIRIN_RACE") or {}, q.get("FETCH_KEIRIN_RACE_ODDS") or {}
            if (R.get("race") or {}).get("cancel"):
                p.update(settled=True, result="中止", payout=0, refund=True)
                continue
            if not R.get("results"):
                continue
            if p.get("bet") == "ワイド":   # ルールW
                m = {x["id"]: x for x in O.get("quinellaPlace") or []}
                ids = [i for i in (R.get("quinellaPlaceWinningOddsIds") or []) if i in m]
                k2 = lambda x: "=".join(map(str, sorted(x["key"][:2])))  # noqa: E731
                wins = [k2(m[i]) for i in ids]
                pay = {k2(m[i]): m[i].get("payoffUnitPrice") or 0 for i in ids}
                final = {k2(x): x.get("minOdds") for x in O.get("quinellaPlace") or []}
            else:
                m = {x["id"]: x for x in O.get("trifecta") or []}
                wins = ["-".join(map(str, m[i]["key"])) for i in (R.get("trifectaWinningOddsIds") or []) if i in m]
                pay = {"-".join(map(str, m[i]["key"])): m[i].get("payoffUnitPrice") or 0
                       for i in (R.get("trifectaWinningOddsIds") or []) if i in m}
                final = {"-".join(map(str, x["key"])): x.get("odds") for x in O.get("trifecta") or []}
            tks = p.get("tickets") or [p["ticket"]]
            p.update(settled=True, result="・".join(wins), payout=int(sum(pay.get(t, 0) or 0 for t in tks)),
                     final_odds=final.get(tks[0]) if len(tks) == 1 else None)
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] 結果の取得に失敗 {p['url']}: {e}")


USE_WINTICKET = None


def _winticket_races(today):
    """winticket の開催・レース(今までのデータ元)"""
    ym = today.strftime("%Y%m")
    for c in month_cups(ym):
        if not c["slug"]:
            continue
        d0 = datetime.datetime.strptime(c["start"], "%Y%m%d").date()
        idx = (today - d0).days + 1
        if not 1 <= idx <= (c["duration"] or 1):
            continue
        try:
            nums = race_numbers(c, idx)
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] {c['venue']} のレース一覧に失敗: {e}")
            continue
        for n in nums:
            url = f"{BASE}/{c['slug']}/racecard/{c['cup']}/{idx}/{n}"
            try:
                st, _ = get_state(url)
                qq = queries(st)
                yield c, n, url, qq.get("FETCH_KEIRIN_RACE") or {}, qq.get("FETCH_KEIRIN_RACE_ODDS") or {}
            except Exception as e:  # noqa: BLE001
                print(f"[WARN] {url}: {e}")


def race_source(today):
    """winticket が読めれば winticket、読めなければ Kドリームス+netkeirin(alt_source.py)"""
    global USE_WINTICKET
    import alt_source
    if USE_WINTICKET is None:
        USE_WINTICKET = alt_source.winticket_ok()
        print(f"[INFO] データ元: {'winticket' if USE_WINTICKET else 'Kドリームス+netkeirin(winticketはアクセス制限中)'}")
    if USE_WINTICKET:
        yield from _winticket_races(today)
    else:
        yield from alt_source.todays_races(today)


def collect(today):
    ym = today.strftime("%Y%m")
    picks, checked, skipped, board = [], 0, {}, []
    keshi_map = load_keshi(today)
    for c, n, url, R, O in race_source(today):
            checked += 1
            hits, why = evaluate_race(R)
            dodds = None
            if why:
                skipped[why] = skipped.get(why, 0) + 1
            race = R.get("race") or {}
            if False and is_big_race(c["grade"], race.get("raceType3")):   # 重賞パックはトントン圏なので出さない(11/15)
                tks, ab = big_race_tickets(R)
                picks.append(dict(date=today.isoformat(), rule="G", ticket=" / ".join(tks), tickets=tks, url=url,
                                  venue=c["venue"], race_no=n, cup=c["name"], grade=c["grade"],
                                  start_at=race.get("startAt") or 0, close_at=race.get("closeAt") or 0,
                                  cls=race.get("class"), race_type=race.get("raceType3"),
                                  line=f"◎{ab[0]}・番手{ab[1]}" if ab and ab[1] else ("◎に番手なし → 見送り" if ab else "並び・印待ち")))
            elif False and is_g_race(c["grade"]) and not race.get("cancel"):
                tks = prelim_tickets(R)
                lp = R.get("linePrediction") or {}
                picks.append(dict(date=today.isoformat(), rule="H", ticket=" / ".join(tks), tickets=tks, url=url,
                                  venue=c["venue"], race_no=n, cup=c["name"], grade=c["grade"],
                                  start_at=race.get("startAt") or 0, close_at=race.get("closeAt") or 0,
                                  cls=race.get("class"), race_type=race.get("raceType3"),
                                  line=("並び " + " / ".join("-".join(str(x) for en in L.get("entries", []) for x in en.get("numbers", []))
                                                           for L in lp.get("lines", []))) if tks else "3車ラインなし → 見送り"))
            tri = trifecta_odds(O)
            d = second_line_ticket(R) if not race.get("cancel") else None
            if d:
                od = tri.get(d[0])
                if od and D_ODDS[0] <= od <= D_ODDS[1]:
                    hits.append(("D", d[0], d[1]))
                    dodds = od
            f3 = line_ticket(R, 3) if not race.get("cancel") else None
            if f3:
                od = tri.get(f3[0])
                if od and F_ODDS[0] <= od <= F_ODDS[1]:
                    hits.append(("F", f3[0], f3[1]))
            wide = wide_odds(O)
            n_now = len([x for x in R.get("entries", []) if not x.get("absent")])
            if False and n_now == 9 and not race.get("cancel"):   # ワイドWは表示しない(3連単だけにする。11/15)
                for k in (1, 2, 3):
                    lt = line_ticket(R, k)
                    if not lt:
                        continue
                    L = lt[1]
                    a, b = sorted((L[0], L[2]))
                    od = wide.get(f"{a}={b}")
                    if od and W_ODDS[0] <= od < W_ODDS[1]:
                        hits.append(("W", f"{a}={b}", L))
            e1 = line_ticket(R, 1) if not race.get("cancel") else None
            if e1 and tri.get(e1[0]) and tri[e1[0]] <= E_ODDS:
                hits.append(("E", e1[0], e1[1]))
            keshi = set(keshi_map.get(f'{ {"iwakidaira": "iwakitaira"}.get(c["slug"], c["slug"])}:{n}') or [])
            # 11/15: 消し目(AI推奨の組)も買い目から外さない
            pref_of = {int(e["number"]): (next((p for p in R.get("players", []) if p.get("id") == e.get("playerId")), {}) or {}).get("prefecture")
                       for e in R.get("entries", []) if e.get("number") is not None}
            kt = k_tickets(R, tri) if not race.get("cancel") else None
            mt = m_tickets(R, tri) if not race.get("cancel") else None
            if mt:
                key, tks, cp = mt
                picks.append(dict(date=today.isoformat(), rule=key, ticket=" / ".join(tks), tickets=tks, url=url, venue=c["venue"],
                                  race_no=n, cup=c["name"], grade=c["grade"], start_at=race.get("startAt") or 0,
                                  close_at=race.get("closeAt") or 0, cls=race.get("class"), race_type=race.get("raceType3"),
                                  bet="3連単", line=f"{len(tks)}点・合成{cp:.1f}倍・万車率{manshaken_rate(tri):.0%}"))
            if kt:
                key, tks, cp = kt
                picks.append(dict(date=today.isoformat(), rule=key, ticket=" / ".join(tks), tickets=tks, url=url, venue=c["venue"],
                                  race_no=n, cup=c["name"], grade=c["grade"], start_at=race.get("startAt") or 0,
                                  close_at=race.get("closeAt") or 0, cls=race.get("class"), race_type=race.get("raceType3"),
                                  bet="3連単", line=f"{len(tks)}点・合成{cp:.1f}倍"))
            for key, ticket, L in hits:
                rel = line_relation([pref_of.get(x) for x in L])
                picks.append(dict(date=today.isoformat(), rule=key, ticket=ticket, url=url, venue=c["venue"], race_no=n,
                                  region=rel["label"], same3=rel["same3"],
                                  chu=bool(tri.get(ticket) and tri[ticket] >= CHU_ODDS and key in ("A", "B", "C", "F")),
                                  chu_star=bool(tri.get(ticket) and tri[ticket] >= CHU_ODDS and key in ("C", "F") and rel["same3"]),
                                  cup=c["name"], grade=c["grade"], start_at=race.get("startAt") or 0,
                                  close_at=race.get("closeAt") or 0, cls=race.get("class"), race_type=race.get("raceType3"),
                                  bet="ワイド" if key == "W" else "3連単",
                                  line="-".join(map(str, L)) + (f"・{tri.get(ticket):.1f}倍" if key in ("D", "E", "F") and tri.get(ticket) else "")
                                  + (f"・ワイド{wide.get(ticket):.1f}倍" if key == "W" and wide.get(ticket) else "")))
            if not race.get("cancel"):
                mv = market_view(tri) if tri else None
                board.append(dict(url=url, venue=c["venue"], slug={"iwakidaira": "iwakitaira"}.get(c["slug"], c["slug"]),
                                  race_no=n, start_at=race.get("startAt") or 0, close_at=race.get("closeAt") or 0,
                                  grade=c["grade"], race_type=race.get("raceType3"), cls=race.get("class"),
                                  n=len([x for x in R.get("entries", []) if not x.get("absent")]),
                                  man=mv["man"] if mv else None, chu=mv.get("chu") if mv else None, q25=mv["q25"] if mv else None,
                                  q50=mv["q50"] if mv else None, q75=mv["q75"] if mv else None,
                                  odds={t: tri.get(t) for _, t, _ in hits},
                                  hit=hit_plan(tri, len([x for x in R.get("entries", []) if not x.get("absent")])) if tri else None,
                                  comments={str(e.get("number")): (next((r for r in R.get("records", []) if r.get("playerId") == e.get("playerId")), {}) or {}).get("comment") or ""
                                            for e in R.get("entries", []) if not e.get("absent")},
                                  ana=[a for a in ana_candidates(R, tri) if a["ticket"] not in keshi],
                                  keshi=sorted(keshi),
                                  rec=race_recommendation(picks, url, tri) or
                                  ([("ref", *ref_tickets(R, tri))] if ref_tickets(R, tri) else [])))
    print(f"[INFO] {today} : {checked}レースを確認、買い目 {len(picks)}件、対象外の理由 {skipped}")
    return picks, board


def merge(log, picks):
    """同じレース・同じルールは最新の判定で置き換える(並びや印が後から変わることがあるため)。結果確定済みは触らない"""
    keyf = lambda p: (p["url"], p["rule"])  # noqa: E731
    settled = {keyf(p) for p in log if p.get("settled")}
    today = {p["date"] for p in picks}
    keep = [p for p in log if p["date"] not in today or p.get("settled")]
    keep += [p for p in picks if keyf(p) not in settled]
    return sorted(keep, key=lambda p: (p["date"], p["start_at"], p["rule"]))


# 各ルールの検証回収率(2025年・2026年。表示用)。回収率の高い順に並べるのにも使う(下限の値)
RULE_ROI = {"F": ("136〜140%", 136), "M1": ("116〜136%", 116), "K1": ("125〜137%", 125), "A": ("129〜133%", 129),
            "C": ("122%", 122), "M2": ("116〜126%", 116), "M3": ("114〜116%", 114), "D": ("110〜111%", 110),
            "B": ("110%", 110), "K6": ("105〜106%", 105), "K4": ("102〜120%", 102)}


def race_recommendation(picks, url, tri=None):
    """そのレースの推奨買い目(3連単だけ) [(種類, ラベル, [買い目])]。
    K(レースごとに形を変える) と 1点ルール(A〜D・F)。全部まとめた合成オッズが MIN_COMP 未満なら、低いオッズの組から外す"""
    ps = [p for p in picks if p["url"] == url]
    out, seen = [], set()
    for p in ps:
        if (p["rule"] in K_RULES or p["rule"] in M_RULES) and p.get("tickets"):
            seen.update(p["tickets"])
            lab = {"K1": "K1 フォーメーション", "K4": "K4 1点", "K6": "K6 穴1点",
                   "M3": "M3 万車・ライン2点", "M2": "M2 万車・番手差し", "M1": "M1 万車・3番目ライン"}[p["rule"]]
            out.append(("win" if p["rule"] != "K6" else "ana", f'{lab}・過去{RULE_ROI[p["rule"]][0]}', list(p["tickets"])))
    for p in ps:
        if p["rule"] == "W" and p["ticket"] not in seen:
            seen.add(p["ticket"])
            out.append(("win", "W ワイド", [p["ticket"]]))
            continue
        if p["rule"] in ("A", "B", "C", "D", "F") and p["ticket"] not in seen:
            seen.add(p["ticket"])
            rs = sorted({q["rule"] for q in ps if q["ticket"] == p["ticket"] and q["rule"] in "ABCDF"}, key=lambda r: -RULE_ROI[r][1])
            out.append(("win", "・".join(rs) + f' 並び1点・過去{RULE_ROI[rs[0]][0]}', [p["ticket"]]))
    out = [x for x in out if x[0] != "big" and not x[1].startswith("W ")]   # 3連単だけ
    if tri:
        allt = [t for x in out for t in x[2]]
        while allt and (composite(tri, allt) or 0) < MIN_COMP:
            worst = min(allt, key=lambda t: tri.get(t) or 0)
            allt.remove(worst)
            out = [(k, lab, [t for t in ts if t != worst]) for k, lab, ts in out]
        out = [x for x in out if x[2]]
    return out  # 本命寄りの参考(E: 最強ラインの並び通り10倍以下)は穴党向けに出さない(記録だけ続ける)


def smooth_board(board, old_board, now_ts, keep=6, window=3):
    """万車率・配当の目安を、直近の更新(最大3回)の中央値にする。オッズは更新のたびに少しずつ動くので、
    1回ごとの値をそのまま出すと見るたびに数字が変わる。値の履歴は hist に残す"""
    old = {b["url"]: b for b in (old_board or [])}
    for b in board:
        hist = list((old.get(b["url"]) or {}).get("hist") or [])
        if b.get("man") is not None:
            hist.append([int(now_ts), b["man"], b["q25"], b["q50"], b["q75"]])
        hist = hist[-keep:]
        b["hist"] = hist
        if hist:
            last = np.array([h[1:] for h in hist[-window:]], dtype=float)
            med = np.median(last, axis=0)
            b["man"], b["q25"], b["q50"], b["q75"] = (float(x) for x in med)
            b["man_ts"] = hist[-1][0]
    return board


def board_html(board, todays, now):
    """全レースの 万車率・配当の目安・推奨買い目 の一覧"""
    if not board:
        return ""
    by = {}
    for p in todays:
        by.setdefault(p["url"], []).append(p)
    main_rows, other_rows = [], []
    for b in sorted(board, key=lambda x: (x["start_at"], x["venue"], x["race_no"])):
        hm = datetime.datetime.fromtimestamp(b["start_at"], JST).strftime("%H:%M") if b["start_at"] else "--:--"
        passed = b["start_at"] and b["start_at"] < now.timestamp()
        if b["man"] is None:
            man, pay = '<span class="skip">オッズ待ち</span>', ""
        else:
            lvl = "hi" if b["man"] >= 0.4 else ("lo" if b["man"] < 0.2 else "")
            man = f'<span class="man {lvl}">{b["man"]:.0%}</span>'
            pay = f'{b["q50"]:,.0f}円<br><small>{b["q25"]:,.0f}〜{b["q75"]:,.0f}</small>'
            if b.get("chu") is not None:
                man += f'<br><small>中穴 {b["chu"]:.0%}</small>'
        ps = by.get(b["url"], [])
        win = [p for p in ps if p["rule"] in ("A", "B", "C", "D", "F")]
        big = [p for p in ps if p["rule"] in BIG and p.get("tickets")]
        ref = [p for p in ps if p["rule"] == "E"]
        rec, seen = [], set()
        for p in win:
            if p["ticket"] not in seen:
                seen.add(p["ticket"])
                rules = "・".join(sorted(q["rule"] for q in win if q["ticket"] == p["ticket"]))
                chu = next((q for q in win if q["ticket"] == p["ticket"] and q.get("chu")), None)
                star = any(q.get("chu_star") for q in win if q["ticket"] == p["ticket"])
                tag = '<span class="rk chu">中穴★</span> ' if star else ('<span class="rk chu2">中穴</span> ' if chu else "")
                rec.append(f'{tag}<span class="rk win">{rules}</span> <b>{html.escape(p["ticket"])}</b>')
        for p in [q for q in ps if q["rule"] == "W"]:
            rec.append(f'<span class="rk wide">W ワイド</span> <b>{html.escape(p["ticket"])}</b>')
        for p in big:
            rec.append('<span class="rk big">重賞</span> ' + " ".join(html.escape(t) for t in p["tickets"]))
        for a in b.get("ana") or []:
            if a["ticket"] not in seen:
                seen.add(a["ticket"])
                rec.append(f'<span class="rk {"win" if a["win"] else "ana"}">穴</span> <b>{html.escape(a["ticket"])}</b>'
                           f' <small>{a["odds"]:.0f}倍・過去{a["roi"]:.0%}</small>')
        honmei = b["man"] is not None and b["man"] < HONMEI_MAN
        if honmei:
            rec = ['<span class="skip">本命レース(見送り)</span>']
        skip = honmei or not rec
        if skip:
            rec.append('<span class="skip">見送り</span>')
        row = (f'<tr class="{"passed" if passed else ""}{" honmei" if (b["man"] is not None and b["man"] < 0.3) else ""}"><td>{hm}</td><td>{html.escape(b["venue"])}{b["race_no"]}R'
               f'<br><small>{html.escape(str(b.get("race_type") or ""))} {b["n"]}車</small></td>'
               f'<td>{man}</td><td>{pay}</td><td class="rec">{"<br>".join(rec)}</td></tr>')
        (other_rows if (skip or passed) else main_rows).append(row)
    head = '<tr><th>発走</th><th>レース</th><th>万車率</th><th>配当の目安</th><th>推奨(3連単)</th></tr>'
    out = ('<h2>全レース一覧</h2>'
           '<p class="why">万車率 = 3連単が1万円以上になる確率、配当の目安 = 払戻の中央値(下は真ん中3分の1の範囲。実際の払戻は3回に1回くらいこの範囲、上下に外れるのは同じくらい)。'
           '中穴 = 5,000円以上になる確率。今のオッズから計算。<span class="rk chu">中穴★</span> 5,000円以上で過去の回収率が高い本線(C・Fの3人同地区ライン) ・ '
           '<span class="rk chu2">中穴</span> 5,000円以上の勝ち筋の買い目。'
           '<span class="rk win">赤</span> 勝ち筋(過去の回収率100%超・両年とも) ・ <span class="rk ana">穴</span> 穴目(過去85〜100%) ・ '
           '<span class="rk big">重賞</span> トントン圏。万車率30%未満は本命レースとして見送り</p>'
           '<p class="why"><label><input type="checkbox" id="anaOnly" checked onchange="document.body.classList.toggle(\'ana\', this.checked)"> '
           '穴党モード: 万車率30%未満(本命寄り)のレースを隠す</label></p>')
    out += ('<div class="tbl"><table class="board">' + head + "".join(main_rows) + '</table></div>') if main_rows else \
        '<p class="none">これから発走で推奨のあるレースはありません。</p>'
    if other_rows:
        out += (f'<details class="more"><summary>見送り・発走済みのレース({len(other_rows)})</summary>'
                '<div class="tbl"><table class="board">' + head + "".join(other_rows) + '</table></div></details>')
    return out


def render(log, now, board=None):
    today = now.date().isoformat()
    rule_desc = {k: (d, b) for k, _, _, d, b in RULES}
    for k, (_, d, b) in BIG.items():
        rule_desc[k] = (d, b)
    rule_desc["D"] = (D_RULE[1], D_RULE[2])
    rule_desc["W"] = (W_RULE[1], W_RULE[2])
    rule_desc["E"] = (E_RULE[1], E_RULE[2])
    rule_desc["F"] = (F_RULE[1], F_RULE[2])
    rule_desc.update(K_RULES)
    rule_desc.update(M_RULES)

    def hm(ts):
        return datetime.datetime.fromtimestamp(ts, JST).strftime("%H:%M") if ts else "--:--"

    todays = [p for p in log if p["date"] == today]

    def npts(p):
        return len(p.get("tickets") or [p["ticket"]]) if (p.get("tickets") or p.get("rule") not in BIG) else 0

    # 同じレースの A〜C の買い目(重賞パックのカードの中で★を付け、別カードは出さない)
    abc = {}
    for p in todays:
        if p["rule"] not in BIG and p["rule"] != "E":
            abc.setdefault(p["url"], {})[p["ticket"]] = p["rule"]
    big_urls = {p["url"] for p in todays if p["rule"] in BIG}

    # 同じレース・同じ買い目に当てはまる1点ルール(A と D など)は1枚のカードにまとめる
    tags = {}
    for p in todays:
        if p["rule"] not in BIG and p["rule"] != "E":
            tags.setdefault((p["url"], p["ticket"]), []).append(p["rule"])

    man_of = {b["url"]: b.get("man") for b in (board or [])}

    def region_note(p):
        if not p.get("region") or p["rule"] not in ("C", "D", "F"):
            return ""
        if p.get("same3"):
            return f'<div class="reg good">◎ {html.escape(p["region"])}のライン(このルールで3人同地区は回収率が高い: D 123%・F 192%・C 180%)</div>'
        return f'<div class="reg">{html.escape(p["region"])}(3人同地区のときより回収率が低い: D 102%・F 87%・C 75%)</div>'

    def card(p):
        passed = p["start_at"] and p["start_at"] < now.timestamp()
        res = ""
        if p.get("settled"):
            res = (f'<span class="hit">的中 {p["payout"]:,}円</span>' if p.get("payout") else
                   f'<span class="miss">{"中止(返還)" if p.get("refund") else "はずれ " + html.escape(p.get("result") or "")}</span>')
        tks = p.get("tickets") or ([p["ticket"]] if p["rule"] not in BIG else [])
        star = abc.get(p["url"], {}) if p["rule"] in BIG else {}
        bet = ("".join(f'<span class="combo{" star" if t in star else ""}">{"★" if t in star else ""}{html.escape(t)}</span>'
                       for t in tks) if tks else "見送り")
        extra = [t for t in star if t not in tks]
        if extra:
            bet += "".join(f'<span class="combo star">★{html.escape(t)}</span>' for t in extra)
            tks = tks + extra
        note = ("<div class=\"why\">★ = ルール" + "・".join(sorted(set(star.values()))) + "(1点ルール)の買い目</div>") if star else ""
        hon = man_of.get(p["url"])
        hon_cls = " honmei" if (hon is not None and hon < HONMEI_MAN) else ""
        return (f"""<article class="pick{' passed' if passed else ''}{' big' if p['rule'] in BIG else ''}{hon_cls}">
  <div class="top"><span class="time">{hm(p['start_at'])}</span><span class="race">{html.escape(p['venue'])}{p['race_no']}R</span>
  <span class="tag">{'重賞' if p['rule'] in BIG else '・'.join(sorted(tags.get((p['url'], p['ticket']), [p['rule']])))}</span>{'<span class="rk chu">中穴★</span>' if p.get('chu_star') else ('<span class="rk chu2">中穴</span>' if p.get('chu') else '')}{res}</div>
  <div class="sub">{html.escape(p.get('cup') or '')} {html.escape(p.get('grade') or '')} {html.escape(p.get('race_type') or '')}</div>
  <div class="bet">3連単 {bet}{f' <small>各100円・{len(tks)}点</small>' if tks else ''}</div>
  <div class="why">{html.escape(' / '.join(rule_desc[k][0] for k in sorted(tags.get((p['url'], p['ticket']), [p['rule']]))))}({html.escape(p['line'])})</div>{region_note(p)}{note}
</article>""")

    seen, singles = set(), []
    for p in todays:
        if p["rule"] not in BIG and p["rule"] != "E" and p["url"] not in big_urls and (p["url"], p["ticket"]) not in seen:
            seen.add((p["url"], p["ticket"]))
            singles.append(p)
    hits = [b for b in (board or []) if b.get("hit") and (b.get("close_at") or 0) > now.timestamp()]
    hits.sort(key=lambda b: -b["hit"]["items"][0][2])
    hit_sec = ""
    if hits:
        lis = "".join(f'<li><b>{html.escape(b["venue"])}{b["race_no"]}R</b> {datetime.datetime.fromtimestamp(b["close_at"], JST):%H:%M}締切 '
                      f'ワイド <b>{html.escape(b["hit"]["items"][0][1])}</b> <span class="hp">{b["hit"]["items"][0][2]:.0%}</span>'
                      f' ・ 3連複6点 <span class="hp">{b["hit"]["items"][2][2]:.0%}</span></li>' for b in hits[:6])
        hit_sec = ('<h2>的中率が高いレース</h2><p class="why">回収率は見ず、当たりやすさだけ。1番人気の1着率と車立てごとの過去の的中率'
                   '(2025年〜、51,075レース)。各レースのページに「的中率重視」の買い目があります。</p><ul class="hitl">' + lis + '</ul>')
    wps = [p for p in singles if p["rule"] == "W"]
    w_sec = ('<h2>的中率も回収率も: ワイドW</h2><p class="why">9車立てで、印1〜3番目のライン(3車以上)の先頭と3番手のワイド(3〜12倍)。'
             '過去 2705点・的中率18%(5〜6レースに1回)・回収率112%(2025年112%・2026年113%)。</p>'
             + ("".join(card(p) for p in wps) or '<p class="none">今日はまだ対象のレースがありません(9車立てのレースのみ)。</p>'))
    chu = [p for p in singles if p.get("chu")]
    chu.sort(key=lambda p: (not p.get("chu_star"), p["start_at"]))
    body = (w_sec + hit_sec + '<h2>中穴(5,000円以上)の買い目</h2>'
            '<p class="why">勝ち筋ルール(A〜C・F)のうち、今の3連単オッズが50倍以上の買い目。<b>★</b> はC・Fでラインの前3人が同じ地区のもの'
            '(過去 994点・的中14回・回収率199%、Fだけなら217%・平均配当15,123円)。当たりは70点に1回くらい。</p>'
            + ("".join(card(p) for p in chu) or '<p class="none">今のところ中穴の買い目はありません。</p>')
            + '<h2>勝ち筋ルールの買い目(全部)</h2>')
    body += "".join(card(p) for p in singles) or \
        '<p class="none">今日の勝ち筋ルールの対象レースはまだありません(並び予想が出ると1時間おきに追加されます)。</p>'
    for key, title, roi in (("G", "重賞(G戦)の決勝・準決勝", "107%"), ("H", "重賞(G戦)の予選・特選・選抜など", "102%")):
        bigs = [p for p in todays if p["rule"] == key]
        if bigs:
            body += (f'<h2>{title}</h2><p class="why">トントン圏(検証の回収率{roi})。楽しむ枠として。</p>'
                     + "".join(card(p) for p in bigs))
    body += board_html(board, todays, now)

    done = [p for p in log if p.get("settled") and not p.get("refund")]
    stat = ""
    if done:
        rows = []
        for key in ["M3", "M2", "M1", "K1", "K4", "K6", "A", "B", "C", "D", "F", "W", "G", "H", "全体", "E"]:
            if key == "全体":  # 重賞パックに含まれる買い目・同じ買い目の1点ルールは二重に数えない
                bu = {p["url"] for p in done if p["rule"] in BIG and p.get("tickets")}
                s, sk = [], set()
                for p in done:
                    if p["rule"] in ("E", "W"):
                        continue
                    if p["rule"] in BIG:
                        s.append(p)
                    elif p["url"] not in bu and (p["url"], p["ticket"]) not in sk:
                        sk.add((p["url"], p["ticket"]))
                        s.append(p)
            else:
                s = [p for p in done if p["rule"] == key]
            pts = sum(npts(p) for p in s)
            if pts:
                pay = sum(p["payout"] for p in s)
                rows.append(f"<tr><td>{ {'G': '重賞パック(決勝・準決勝)', 'H': '重賞パック(予選など)', '全体': '全体(A〜D・重賞)', 'E': 'E 参考(最強ライン並び通り)', 'W': 'W ワイド(9車・先頭-3番手)'}.get(key, key) }</td><td>{pts}</td><td>{sum(1 for p in s if p['payout'])}</td>"
                            f"<td>{pay:,}円</td><td>{pay / (pts * 100):.0%}</td></tr>")
        stat = ("<h2>このページの通算成績(本番)</h2><table><tr><th>ルール</th><th>点数</th><th>的中</th><th>払戻</th><th>回収率</th></tr>"
                + "".join(rows) + "</table>")
    notes = "".join(f"<li><b>{k}</b>: {html.escape(d)}。{html.escape(b)}。</li>" for k, _, _, d, b in RULES)
    notes += "".join(f"<li><b>{k}</b>: {html.escape(d)}。{html.escape(b)}。</li>" for k, (d, b) in {**M_RULES, **K_RULES}.items())
    notes += f"<li><b>W(ワイド・11/15から表示なし)</b>: {html.escape(W_RULE[1])}。{html.escape(W_RULE[2])}。ワイドのオッズは1時間おきの更新時点の値なので、買う前に3〜12倍か確認。</li>"
    notes += f"<li><b>D</b>: {html.escape(D_RULE[1])}。{html.escape(D_RULE[2])}。オッズは1時間おきの更新時点の値なので、買う前に10〜30倍か確認。</li>"
    notes += f"<li><b>F(穴)</b>: {html.escape(F_RULE[1])}。{html.escape(F_RULE[2])}。上位5本の的中を除くと96%。</li>"
    notes += f"<li><b>E(参考・表示なし)</b>: {html.escape(E_RULE[1])}。{html.escape(E_RULE[2])}。</li>"
    notes += "".join(f"<li><b>{html.escape(d.split('(')[0])}</b>: {html.escape(d)}。{html.escape(b)}。</li>" for _, d, b in BIG.values())
    return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>回収率重視の買い目</title>
<style>
  :root {{ --navy:#1B2A4A; --paper:#F5F6F8; --line:#DDE1E8; --ink:#1E2430; --soft:#5F6878; --accent:#C8402A; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--paper); color:var(--ink); font-family:"Noto Sans JP",system-ui,sans-serif; font-size:15px; line-height:1.6; }}
  header {{ background:var(--navy); color:#fff; padding:18px 16px; }}
  header h1 {{ margin:0; font-size:1.4rem; }} header p {{ margin:4px 0 0; font-size:.8rem; opacity:.9; }} header a {{ color:#FFD58A; }}
  main, footer {{ max-width:720px; margin:0 auto; padding:12px 16px; }}
  .pick {{ background:#fff; border:1px solid var(--line); border-left:5px solid var(--accent); border-radius:8px; padding:12px 14px; margin:0 0 12px; }}
  .pick.passed {{ opacity:.55; }}
  .top {{ display:flex; gap:8px; align-items:baseline; flex-wrap:wrap; }}
  .time {{ font-weight:700; font-size:1.2rem; font-variant-numeric:tabular-nums; }}
  .race {{ font-weight:700; font-size:1.1rem; color:var(--navy); }}
  .tag {{ background:var(--accent); color:#fff; font-size:.72rem; font-weight:700; padding:2px 8px; border-radius:999px; }}
  .hit {{ color:#0A7A3B; font-weight:700; }} .miss {{ color:var(--soft); font-size:.85rem; }}
  .sub, .why {{ font-size:.78rem; color:var(--soft); }}
  .reg {{ font-size:.76rem; color:var(--soft); margin-top:2px; }} .reg.good {{ color:#b03024; font-weight:700; }}
  .bet {{ margin-top:6px; font-size:1.05rem; }} .bet b {{ font-size:1.25rem; letter-spacing:.04em; font-variant-numeric:tabular-nums; }}
  .pick.big {{ border-left-color:#B8862B; }} .pick.big .tag {{ background:#B8862B; }}
  .combo {{ display:inline-block; font-weight:700; font-variant-numeric:tabular-nums; border:1px solid var(--line); background:#FAF7EE;
            border-radius:6px; padding:1px 8px; margin:2px 4px 2px 0; }}
  details.more {{ margin:12px 0; background:#fff; border:1px solid var(--line); border-radius:8px; padding:8px 12px; }}
  details.more summary {{ cursor:pointer; font-weight:700; font-size:.88rem; color:var(--soft); }}
  .combo.star {{ background:#FFE9C2; border-color:#E2B25A; }}
  .tbl {{ overflow-x:auto; }}
  body.ana tr.honmei, body.ana article.honmei {{ display:none; }}
  table.board td {{ text-align:left; vertical-align:top; }}
  table.board tr.passed {{ opacity:.5; }}
  .man {{ font-weight:700; font-variant-numeric:tabular-nums; }} .man.hi {{ color:#C8402A; }} .man.lo {{ color:#2F6B4F; }}
  .rk {{ font-size:.7rem; font-weight:700; color:#fff; padding:1px 6px; border-radius:999px; }}
  .hp {{ color:#0E7C66; font-weight:800; }} .hitl {{ font-size:.85rem; padding-left:18px; }}
  .rk.wide {{ background:#2E5BA8; }}
  .rk.chu {{ background:#0E7C66; }} .rk.chu2 {{ background:#5FA593; }}
  .rk.win {{ background:#C8402A; }} .rk.ana {{ background:#6A4FA0; }} .rk.big {{ background:#B8862B; }} .rk.ref {{ background:#7A8494; }}
  .skip {{ color:var(--soft); font-size:.85rem; }} td.rec b {{ font-variant-numeric:tabular-nums; }}
  .none {{ background:#fff; border:1px solid var(--line); border-radius:8px; padding:20px; text-align:center; }}
  h2 {{ font-size:1rem; margin:20px 0 8px; }}
  table {{ border-collapse:collapse; width:100%; background:#fff; font-size:.88rem; }}
  th, td {{ border:1px solid var(--line); padding:6px 8px; text-align:right; }} th:first-child, td:first-child {{ text-align:left; }}
  footer {{ font-size:.75rem; color:var(--soft); }} footer ul {{ padding-left:18px; }}
</style></head><body class="ana">
<header><h1>回収率重視の買い目(競輪)</h1>
<p>{html.escape(today)} ・ 更新 {now.strftime('%H:%M')}(30分おき) ・ <a href="index.html">全レースの予想</a> ・ <a href="drops.html">オッズ急落</a></p></header>
<main>{body}{stat}</main>
<footer><details class="more"><summary>ルールの説明と注意</summary><ul>{notes}</ul>
<p>ラインの強さは「予想印の合計」で決めるので、オッズを見なくても判定できます。並び予想や印が変わると買い目も変わるので、
買う直前にもう一度開いてください。A〜D・Fは1レース1点、重賞パックは決勝・準決勝が最大5点・予選などが平均2.5点(各100円)。過去の確定データでの検証結果で、
大きい配当に頼った成績(上位5本の的中を除くと回収率93%)なので、プラスを保証するものではありません。</p></details></footer>
</body></html>"""


def main():
    now = datetime.datetime.now(JST)
    log = load_log()
    board_path = os.path.join(DOCS, "_race_board.json")
    board = None
    try:
        picks, board = collect(now.date())
        log = merge(log, picks)
        try:
            with open(board_path, encoding="utf-8") as f:
                ob = json.load(f)
            old_board = ob["races"] if ob.get("date") == now.date().isoformat() else None
        except (OSError, ValueError, KeyError):
            old_board = None
        board = smooth_board(board, old_board, now.timestamp())
        with open(board_path, "w", encoding="utf-8") as f:
            json.dump(dict(date=now.date().isoformat(), races=board), f, ensure_ascii=False)
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] 今日の判定に失敗: {e}")
        try:
            with open(board_path, encoding="utf-8") as f:
                b = json.load(f)
            board = b["races"] if b.get("date") == now.date().isoformat() else None
        except (OSError, ValueError, KeyError):
            board = None
    settle(log, now)
    save_log(log)
    with open(os.path.join(DOCS, "picks.html"), "w", encoding="utf-8") as f:
        f.write(render(log, now, board))
    print("[INFO] docs/picks.html を書き出しました。")


if __name__ == "__main__":
    main()
