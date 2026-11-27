"""
選手コメント(前検コメント)でAIの1着率を補正する(11/27)。
2025〜2026年の約36万人分(wt_entries のコメント)で、AIの1着率にコメントの特徴を足した条件付きロジットを学習。
片方の年で学習→もう片方の年で確かめると、1着の予測の対数損失が1レースあたり0.007〜0.010良くなった
(AIの1位が1着になる率はほぼ変わらず。下位の評価が良くなる)。オッズと合わせた確率への上乗せはごくわずか(0.001〜0.002)。
  ・「自力」「単騎」「(〇〇君・〇〇勢へ などの)マーク」は上げ、「〇〇3番手」は大きく下げる、「補充」は上げる 等
"""
import math
import re

W_LA = 0.85
W = {"jiriki": 0.436, "jizai": -0.123, "tanki": 0.411, "mark": 0.34, "sanban": -0.944,
     "hoju": 0.578, "bad": -0.239, "good": -0.118, "gamba": -0.064}
PAT = {
    "jiriki": r"自力|自分で|先行|逃げ|前々|積極|主導権|風を切|仕掛け",
    "jizai": r"自在|決めず|何でも|流れ|取れた位置|好位|位置取|臨機|様子",
    "tanki": r"単騎|一人|１人|1人|ひとり",
    "mark": r"君|さん|勢へ|勢。|勢$|後ろ|付い|番手|マーク|の後|任せ",
    "sanban": r"[３3]番手",
    "hoju": r"補充",
    "bad": r"不安|悪い|いまいち|イマイチ|微妙|重い|痛|怪我|ケガ|落車|ダメ|厳し|良くない|自信がない|自信ない|戻って|休み|修正|不調|疲れ",
    "good": r"いい|良い|良く|上向|仕上が|万全|好調|手応え|自信|問題ない|悪くない|ある程度",
    "gamba": r"頑張|全力|しっかり|勝負",
}
_RE = {k: re.compile(p) for k, p in PAT.items()}


def tags(comment):
    c = comment or ""
    return [k for k, r in _RE.items() if r.search(c)]


def apply(result, comments):
    """result["rows"] の adjusted(AIの1着率%)をコメントで補正。comments = {車番: コメント}。
    コメントが半分以上の車に無いときは何もしない。返り値: 補正したか"""
    rows = (result or {}).get("rows") or []
    cm = {r["car"]: (comments.get(r["car"]) or comments.get(str(r["car"])) or "").strip() for r in rows}
    if not rows or sum(1 for v in cm.values() if v) < len(rows) / 2:
        return False
    tot = sum(r["adjusted"] for r in rows) or 100
    sc = {}
    for r in rows:
        p = max(r["adjusted"] / tot, 1e-4)
        sc[r["car"]] = W_LA * math.log(p) + sum(W[k] for k in tags(cm[r["car"]]))
    m = max(sc.values())
    ex = {c: math.exp(v - m) for c, v in sc.items()}
    s = sum(ex.values())
    for r in rows:
        r["ai_before_comment"] = r["adjusted"]
        r["adjusted"] = round(ex[r["car"]] / s * tot, 2)
        r["comment"] = r.get("comment") or cm[r["car"]]
        r["comment_tags"] = tags(cm[r["car"]])
    result["comment_adj"] = True
    return True
