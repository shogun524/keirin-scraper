# -*- coding: utf-8 -*-
"""
「勝利の方程式」：能力値 + L指数 + M指数 = 期待値（スコア）。
（動画で紹介されていた競輪の攻略法をそのまま実装したもの。AIの確率予測とは別系統の、
 ルールベースの指数として併記する。有効性は予想成績ページで答え合わせして確かめる。）

  能力値 = 競走得点 + バック数(B) + マーク以外の決まり手の数(逃+捲+差) − max(0, 年齢 − 35)
  L指数  = ラインの人数 × 3（単騎は1人として3）
  M指数  = 0〜10。選手のメンタル・モチベーション。0を基準に、得点順位・車番・ライン位置・相性・地元戦・決勝などで
           加点した初期値を出し、画面上で手で書き換えられる。

※ ここでいう「期待値」は、配当を掛けた期待値ではなく、動画の呼び方に合わせたスコア。
"""

import re

AGE_BASE = 35
L_PER_CAR = 3
M_BASE = 0          # 0を基準に、やる気の材料ごとに加点（上限10）
M_HOME = 3          # 地元戦
M_FINAL = 2         # 決勝
M_SEMI = 1          # 準決勝

# 開催場スラッグ → 所在府県（選手の登録府県と照合して「地元戦」を判定）
VENUE_PREF = {
    "hakodate": "北海道", "aomori": "青森", "iwakitaira": "福島", "yahiko": "新潟",
    "maebashi": "群馬", "toride": "茨城", "utsunomiya": "栃木", "omiya": "埼玉",
    "seibuen": "埼玉", "keiokaku": "東京", "tachikawa": "東京", "matsudo": "千葉",
    "chiba": "千葉", "kawasaki": "神奈川", "hiratsuka": "神奈川", "odawara": "神奈川",
    "ito": "静岡", "shizuoka": "静岡", "nagoya": "愛知", "gifu": "岐阜", "ogaki": "岐阜",
    "toyohashi": "愛知", "toyama": "富山", "matsusaka": "三重", "yokkaichi": "三重",
    "fukui": "福井", "nara": "奈良", "mukomachi": "京都", "wakayama": "和歌山",
    "kishiwada": "大阪", "tamano": "岡山", "hiroshima": "広島", "hofu": "山口",
    "takamatsu": "香川", "komatsushima": "徳島", "kochi": "高知", "matsuyama": "愛媛",
    "kokura": "福岡", "kurume": "福岡", "takeo": "佐賀", "sasebo": "長崎",
    "beppu": "大分", "kumamoto": "熊本",
}


def _norm_pref(p):
    p = re.sub(r"\s+", "", p or "")
    return re.sub(r"[都道府県]$", "", p) if p not in ("北海道",) else p


def is_home(pref, venue_slug):
    vp = VENUE_PREF.get(venue_slug)
    return bool(pref and vp and _norm_pref(pref) == _norm_pref(vp))


def _context(rows):
    """M指数の判定に使う、レース内の相対情報（得点順位・最強ライン）。"""
    by_score = sorted(rows, key=lambda r: -(r.get("score") or 0))
    srank = {r["car"]: i + 1 for i, r in enumerate(by_score)}
    lines = {}
    for r in rows:
        li = r.get("line_info")
        if li and li.get("line_size", 1) >= 2:
            lines.setdefault(li["line_index"], []).append(r)
    strongest = None
    if lines:
        avg = {k: sum((x.get("score") or 0) for x in v) / len(v) for k, v in lines.items()}
        strongest = max(avg, key=avg.get)
    front = {}
    for k, v in lines.items():
        f = [x for x in v if x["line_info"]["position"] == 1]
        front[k] = f[0] if f else None
    return {"srank": srank, "lines": lines, "strongest": strongest, "front": front}


def estimate_m(rider, venue_slug, race_title, ctx=None):
    """
    M指数の自動推定値（0〜10）と根拠。0から始めて加点（動画の例を目安にした基準）:
      負けられない強者（得点1位+5 / 2位+3 / 3位+1）、車番が良い強者(1番+2・2番+1)、
      追込型なのにラインの先頭を走る(+3)、番手(+3)・番手で脚力上位(+2)、
      3番手(+1)、最強ラインの一員(+2)・その3番手(+2)、
      ライン相手との相性(◎+2/○+1)、地元戦(+3)、決勝(+2)・準決勝(+1)
    """
    m = M_BASE
    why = []
    def add(v, label):
        nonlocal m
        m += v
        why.append(f"{label}+{v}")
    ctx = ctx or {}
    sr = (ctx.get("srank") or {}).get(rider.get("car"))
    li = rider.get("line_info") or {}
    pos, size, lidx = li.get("position"), li.get("line_size", 1), li.get("line_index")
    if sr == 1: add(5, "得点1位")
    elif sr == 2: add(3, "得点2位")
    elif sr == 3: add(1, "得点3位")
    if sr and sr <= 3 and rider.get("car") in (1, 2):
        add(2 if rider["car"] == 1 else 1, "車番良")
    dom = rider.get("dominant_type")
    if size >= 2 and pos == 1 and dom in ("sashi", "mark", "差", "マ", "マーク"):
        add(3, "追込がライン先頭")
    if size >= 2 and pos == 2:
        add(3, "番手")
        fr = (ctx.get("front") or {}).get(lidx)
        if sr and sr <= 2 and fr and (rider.get("score") or 0) >= (fr.get("score") or 0):
            add(2, "番手で脚力上位")
    if size >= 3 and pos == 3:
        add(1, "3番手")
    if size >= 2 and lidx is not None and lidx == ctx.get("strongest"):
        add(2, "最強ライン")
        if pos == 3:
            add(2, "強ラインの3番手")
    rv = rider.get("rivalry_summary")
    if rv and size >= 2:
        rate = rv.get("avg_win_rate", 0.5)
        if rate >= 0.6: add(2, "相性◎")
        elif rate >= 0.55: add(1, "相性○")
    if is_home(rider.get("pref"), venue_slug):
        add(M_HOME, "地元戦")
    title = race_title or ""
    if "準決" in title: add(M_SEMI, "準決勝")
    elif "決勝" in title: add(M_FINAL, "決勝")
    return max(0, min(10, m)), why


def is_girls(rows, race_title=""):
    """ガールズ競輪（全員単騎でラインが無い）。方程式は使えないので計算の対象外にする。"""
    if "ガールズ" in (race_title or ""):
        return True
    return bool(rows) and all(r.get("rank") == "L1" for r in rows)


def compute_formula(rows, venue_slug=None, race_title=""):
    """
    rows: predict_race() の rows（各選手の dict。score/b_count/kimarite/age/line_info/pref を使う）
    戻り値: 合計の高い順の list。各要素に car,name,score,b,kim3,age_pen,ability,line_size,L,m,m_why,total,rank を持つ。
    """
    out = []
    ctx = _context(rows)
    for r in rows:
        kim = r.get("kimarite") or {}
        kim3 = int(kim.get("逃", 0)) + int(kim.get("捲", 0)) + int(kim.get("差", 0))
        b = r.get("b_count")
        age = r.get("age") or 0
        age_pen = max(0, int(age) - AGE_BASE) if age else 0
        score = float(r.get("score") or 0)
        ability = score + (b or 0) + kim3 - age_pen
        li = r.get("line_info")
        line_size = li["line_size"] if li and li.get("line_size") else 1
        L = line_size * L_PER_CAR
        m, why = estimate_m(r, venue_slug, race_title, ctx)
        out.append({
            "car": r["car"], "name": r["name"], "rank_class": r.get("rank"),
            "score": score, "b": b, "kim3": kim3, "age": int(age) if age else None, "age_pen": age_pen,
            "ability": ability, "line_size": line_size, "L": L, "m": m, "m_why": why,
            "total": ability + L + m, "ai_rank": None,
        })
    out.sort(key=lambda x: -x["total"])
    for i, x in enumerate(out):
        x["rank"] = i + 1
    return out
