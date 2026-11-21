# -*- coding: utf-8 -*-
"""
競輪「締切直前に動いた買い目」(docs/drops.html)。

nk_watch.py が記録した締切前オッズ(live/nk_live_YYYYMMDD.jsonl.gz、公式の更新ごとに1行)から、レースごとに
  選定時 = 締切前の最後の記録、比べる相手 = その45秒以上前で一番近い記録(だいたい1〜2回前の公式更新)
  各組の「支持の割合」 q = (1/オッズ) ÷ 全組の(1/オッズ)の合計
  q が何倍に増えたか(選定時 ÷ 比べる相手)が大きい順に、増えた組だけを最大5点(11/20〜。旧: 増えた差の順に15点)
を「締切直前にお金が入った3連単」として出す。締切前は同じ方法で「暫定」を出し、締切後に確定する。
並べ方は 1着-2着-3着 の候補をまとめた書き方(例: 235-4-35 = 1着2・3・5、2着4、3着3・5 の組のうち選んだもの)。
合成オッズ = 1 ÷ Σ(1/各組のオッズ)。選定時と、締切後の最終オッズの両方を出す。
結果は netkeirin の結果ページから3連単の組と払戻を読んで、1レース5,000円を均等買い(オッズに反比例・100円単位)で買った場合の収支を出す。

使い方(scripts/ で): python nk_drops.py --live ../live/nk_live_20261115.jsonl.gz
"""
import argparse
import datetime
import gzip
import html
import json
import math
import os
import re
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
DOCS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs")
MAX_PICKS = 5          # 11/20: 15点→5点
GAP_SEC = 120          # 比べる相手は選定時の記録よりこれ以上前(11/20: 45秒→2分)
MIN_SHARE = 0.002      # 選ぶのは支持の割合が0.2%以上の組だけ(大穴の数字のぶれを除く)
# 11/20 見直し(11/15〜11/20 の300レースで検証):
#   旧: 支持の割合の『増えた差』が大きい順15点・資金配分 → 回収率71〜78%(人気の組を選んでいるだけで、選んだ後もさらに下がる)
#   新: 支持の割合が『何倍に増えたか』が大きい順5点・均等買い → 回収率120%(的中44/300)。
#       同じ人気帯からランダムに5点選ぶと平均59%(300回中0回も120%に届かない)ので、たまたまではなさそう。
#   ただし効くのは締切直前(最後の記録は締切の中央25秒前)の動きだけ。締切2分以上前の記録で選ぶと後半3日で32〜48%に落ちる。
UPCOMING_MIN = 13      # 締切がこの分数以内のレースは「締切まもなく」に暫定で出す
RESULT_URL = "https://keirin.netkeiba.com/race/result/?race_id={}"


# ------------------------------------------------------------ 読み込み
def load(path):
    recs = {}
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                recs.setdefault(r["rid"], []).append(r)
    except (OSError, EOFError):
        pass
    for v in recs.values():
        v.sort(key=lambda r: r["ts"])
    return recs


def shares(tri):
    inv = {k: 1 / v for k, v in tri.items() if v and v > 0}
    s = sum(inv.values()) or 1
    return {k: x / s for k, x in inv.items()}


def synth(tri, combos):
    inv = [1 / tri[c] for c in combos if tri.get(c)]
    return 1 / sum(inv) if inv else None


BUDGET = 5000   # 1レースの資金(円)
MIN_SYNTH = 2.0  # 選定時の合成オッズがこれ未満のレースは出さない(成績にも入れない)


def allocate(tri, combos, budget=BUDGET):
    """均等買い(11/20〜。資金配分より均等の方が回収率が高かった): 100円単位で budget 円をなるべく同じ額ずつ -> {組: 金額}"""
    cs = [c for c in combos if tri.get(c)]
    if not cs:
        return {}
    unit = budget // 100 // len(cs)
    st = {c: unit * 100 for c in cs}
    for c in cs[: budget // 100 - unit * len(cs)]:
        st[c] += 100
    return st


def payout(stakes, r):
    """確定結果 r(combo, pay=100円あたりの払戻)で、配分した買い方の払戻"""
    if not r:
        return None
    return int(stakes.get(r["combo"], 0) / 100 * r["pay"])


# ------------------------------------------------------------ 選ぶ
def select(snaps, upto_ts=None):
    """締切前の記録の列 -> dict(picks=[(組, 前オッズ, 選定時オッズ, 増えた割合)], cur, prev) か None"""
    pre = [s for s in snaps if s["ts"] < s["close"] and (upto_ts is None or s["ts"] <= upto_ts)]
    if len(pre) < 2:
        return None
    cur = pre[-1]
    prev = None
    for s in reversed(pre[:-1]):
        if cur["ts"] - s["ts"] >= GAP_SEC:
            prev = s
            break
    if prev is None:
        prev = pre[-2]
    qc, qp = shares(cur["tri"]), shares(prev["tri"])
    gain = [(k, prev["tri"][k], cur["tri"][k], qc[k] / qp[k] - 1) for k in qc if k in qp and qp[k] > 0 and qc[k] > qp[k] and qc[k] >= MIN_SHARE]
    gain.sort(key=lambda x: -x[3])   # 何倍に増えたか
    return dict(picks=gain[:MAX_PICKS], cur=cur, prev=prev)


def formation(combos):
    """['5-4-3','2-4-3',...] -> ['235-4-35', ...]
    1着-2着-3着の候補のまとめで、選んだ組をちょうど表す(まとめが表す組 = 同じ車が重ならない組 が、全部選んだ組に入っている)。
    残っている組を一番多く含む「まとめ」を欲張りに作っていく"""
    sel = set(combos)
    if not sel:
        return []
    cars = sorted({int(x) for c in sel for x in c.split("-")})

    def tickets(box):
        return {f"{x}-{y}-{z}" for x in box[0] for y in box[1] for z in box[2] if len({x, y, z}) == 3}

    left = set(sel)
    out = []
    while left:
        best, best_cov = None, set()
        for seed in sorted(left):
            box = [{int(x)} for x in seed.split("-")]
            grown = True
            while grown:
                grown = False
                cand = None
                for k in range(3):
                    for v in cars:
                        if v in box[k]:
                            continue
                        nb = [set(b) for b in box]
                        nb[k].add(v)
                        t = tickets(nb)
                        if t <= sel:
                            gain = len(t & left)
                            if cand is None or gain > cand[0]:
                                cand = (gain, nb)
                if cand and cand[0] > len(tickets(box) & left):
                    box = cand[1]
                    grown = True
            cov = tickets(box) & left
            if len(cov) > len(best_cov):
                best, best_cov = box, cov
        out.append(best)
        left -= best_cov
    return ["-".join("".join(str(x) for x in sorted(b)) for b in box) for box in out]


# ------------------------------------------------------------ 結果
def load_results():
    try:
        with open(os.path.join(DOCS, "_drops_results.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_results(res):
    with open(os.path.join(DOCS, "_drops_results.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False)


def parse_result(h):
    """netkeirin の結果ページ -> ("2-6-5", 28260) か None(まだ確定していない)
    払戻の表(id="result_payback_section")の「３連単 2>6>5 28,260円」を読む"""
    i = h.find('id="result_payback_section"')
    if i < 0:
        return None
    seg = html.unescape(re.sub(r"<[^>]+>", " ", h[i:i + 8000]))
    seg = re.sub(r"\s+", " ", seg)
    z = str.maketrans("０１２３４５６７８９，＞", "0123456789,>")
    seg = seg.translate(z)
    m = re.search(r"3連単\s*(\d+)\s*>\s*(\d+)\s*>\s*(\d+)\s*([\d,]+)\s*円", seg)
    if not m:
        return None
    a, b, c = (int(x) for x in m.groups()[:3])
    return f"{a}-{b}-{c}", int(m.group(4).replace(",", ""))


def fetch_results(rids, res):
    import requests
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
    for rid in rids:
        try:
            r = s.get(RESULT_URL.format(rid), timeout=15)
            p = parse_result(r.content.decode("utf-8", "replace"))
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] 結果 {rid}: {e}")
            continue
        if p:
            res[rid] = dict(combo=p[0], pay=p[1])
    return res


# ------------------------------------------------------------ 表示
def hm(ts, sec=False):
    return datetime.datetime.fromtimestamp(ts, JST).strftime("%H:%M:%S" if sec else "%H:%M")


def odt_hms(s):
    return (s or "")[-8:] or "—"


def chart_svg(snaps, combos, close, hit=None):
    """15点のオッズの動き(縦は対数)。締切の線と最終オッズの点"""
    pts = [s for s in snaps if all(c in s["tri"] for c in combos[:1])]
    if len(pts) < 2:
        return ""
    W, H, L, R, T, B = 640, 260, 46, 120, 14, 26
    xs = [s["ts"] for s in pts]
    x0, x1 = min(xs), max(xs)
    if x1 <= x0:
        return ""
    vals = [s["tri"][c] for s in pts for c in combos if s["tri"].get(c)]
    lo, hi = math.log(min(vals)), math.log(max(vals))
    if hi - lo < 0.3:
        lo, hi = lo - 0.15, hi + 0.15
    X = lambda t: L + (t - x0) / (x1 - x0) * (W - L - R)  # noqa: E731
    Y = lambda v: T + (hi - math.log(v)) / (hi - lo) * (H - T - B)  # noqa: E731
    cols = ["#2E86AB", "#C8102E", "#2E7D32", "#B8860B", "#6A1B9A", "#00838F", "#D84315", "#5D4037",
            "#AD1457", "#283593", "#558B2F", "#EF6C00", "#4E342E", "#00695C", "#7B1FA2"]
    g = []
    for k in range(5):
        v = math.exp(lo + (hi - lo) * k / 4)
        g.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="#eee"/>'
                 f'<text x="{L - 4}" y="{Y(v) + 3:.1f}" font-size="9" text-anchor="end" fill="#888">{v:.1f}</text>')
    if x0 <= close <= x1:
        g.append(f'<line x1="{X(close):.1f}" x2="{X(close):.1f}" y1="{T}" y2="{H - B}" stroke="#B8860B" stroke-dasharray="4 3"/>'
                 f'<text x="{X(close) - 3:.1f}" y="{T + 9}" font-size="9" text-anchor="end" fill="#B8860B">締切</text>')
    for k in range(4):
        t = x0 + (x1 - x0) * k / 3
        g.append(f'<text x="{X(t):.1f}" y="{H - 8}" font-size="9" text-anchor="middle" fill="#888">{hm(t, True)}</text>')
    last = pts[-1]
    labels = []
    for i, c in enumerate(combos):
        col = cols[i % len(cols)]
        p = " ".join(f"{X(s['ts']):.1f},{Y(s['tri'][c]):.1f}" for s in pts if s["tri"].get(c))
        if not p:
            continue
        w = 2.6 if c == hit else 1.3
        g.append(f'<polyline points="{p}" fill="none" stroke="{col}" stroke-width="{w}"/>')
        lv = last["tri"].get(c)
        if lv:
            labels.append((Y(lv), f'<tspan fill="{col}">{c} {lv:.1f}倍{" 🎯" if c == hit else ""}</tspan>'))
    labels.sort()
    y_prev = -99
    for y, t in labels:
        y = max(y, y_prev + 10)
        y_prev = y
        g.append(f'<text x="{W - R + 6}" y="{y + 3:.1f}" font-size="9">{t}</text>')
    return f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="オッズの推移">{"".join(g)}</svg>'


def race_card(rid, snaps, sel, res, now_ts, provisional=False):
    cur, prev = sel["cur"], sel["prev"]
    s0 = snaps[0]
    combos = [p[0] for p in sel["picks"]]
    final = [s for s in snaps if s["ts"] > s["close"]]
    fin = final[-1] if final else None
    syn_sel = synth(cur["tri"], combos)
    syn_fin = synth(fin["tri"], combos) if fin else None
    r = res.get(rid)
    hit = r["combo"] if r and r["combo"] in combos else None
    chips = "<span class='sl'>／</span>".join(f'<span class="chip">{html.escape(f)}</span>' for f in formation(combos))
    head = "締切まもなく(暫定)" if provisional else "締切直前に動いた買い目"
    left = (s0["close"] - now_ts) / 60
    when = f'締切 {hm(s0["close"])}' + (f'(あと{left:.0f}分)' if provisional else "")
    res_html = ""
    stakes = allocate(cur["tri"], combos)
    alloc_html = ('<details class="gr"><summary>5,000円の買い方(均等買い)</summary><p class="note">'
                  + " ／ ".join(f'{c} {stakes[c]:,}円' for c in sorted(stakes, key=lambda c: -stakes[c])) + '</p></details>') if stakes else ""
    if not provisional:
        if r:
            pay = payout(stakes, r) or 0
            res_html = (f'<p class="res {"hit" if hit else "miss"}">{"🎯 的中 " + hit if hit else "不的中"} ｜ 確定結果 {r["combo"]}({r["pay"]:,}円) ｜ '
                        f'5,000円均等買い 払戻 {pay:,}円・収支 {pay - BUDGET:+,}円</p>')
        else:
            res_html = '<p class="res wait">結果待ち</p>'
    svg = chart_svg(snaps, combos, s0["close"], hit)
    return f"""<article class="card{' prov' if provisional else ''}">
  <h3>{head}<span class="sep">｜</span>{html.escape(s0["venue"])} {s0["no"]}R <small>{html.escape(s0.get("name", ""))}・{s0.get("tosu", "")}車・{when}</small></h3>
  <p class="type">三連単・最大{MAX_PICKS}点</p>
  <div class="chips">{chips}</div>
  <p class="syn">全{len(combos)}点の合成オッズ <b>{syn_sel:.2f}倍</b>(選定時){f" ／ 最終 {syn_fin:.2f}倍" if syn_fin else ""}</p>
  <p class="meta">締切前の記録で選定 ｜ {len(combos)}／{MAX_PICKS}点 ｜ {("提供元更新 " + odt_hms(prev.get("odt")) + " → " + odt_hms(cur.get("odt"))) if cur.get("odt") and prev.get("odt") else ("比べた記録 " + hm(prev["ts"], True) + " → " + hm(cur["ts"], True))} ｜ 記録{sum(1 for s in snaps if s["ts"] < s["close"])}回</p>
  {res_html}
  {alloc_html}
  {f'<details class="gr"><summary>{len(combos)}点をグラフ表示</summary>{svg}<p class="note">縦軸はオッズ(対数)。点線が締切、右端が最後に取ったオッズ(締切後なら最終オッズ)。</p></details>' if svg else ""}
</article>"""


def render(recs, res, now):
    now_ts = now.timestamp()
    up, done = [], []
    for rid, snaps in recs.items():
        close = snaps[0]["close"]
        sel = select(snaps)
        if not sel:
            continue
        cs = synth(sel["cur"]["tri"], [p[0] for p in sel["picks"]])
        if not cs or cs < MIN_SYNTH:   # 合成オッズ1倍台(2倍未満)のレースは出さない
            continue
        if close > now_ts:
            if close - now_ts <= UPCOMING_MIN * 60:
                up.append((close, rid, snaps, sel))
        else:
            done.append((close, rid, snaps, sel))
    up.sort()
    done.sort(reverse=True)
    # 今日の成績
    n_r = n_hit = cost = ret = 0
    rows = ""
    for close, rid, snaps, sel in done:
        combos = [p[0] for p in sel["picks"]]
        r = res.get(rid)
        s0 = snaps[0]
        state = "結果待ち"
        if r:
            n_r += 1
            cost += BUDGET
            h = r["combo"] in combos
            got = payout(allocate(sel["cur"]["tri"], combos), r) or 0
            if h:
                n_hit += 1
                ret += got
            state = f'{"🎯 " if h else ""}{r["combo"]} 払戻{got:,}円(収支{got - BUDGET:+,}円)'
        rows += (f'<tr><td>{hm(close)}</td><td>{html.escape(s0["venue"])}{s0["no"]}R</td><td>{len(combos)}点</td>'
                 f'<td>{synth(sel["cur"]["tri"], combos):.1f}</td><td class="l">{html.escape(" / ".join(formation(combos)))}</td><td>{state}</td></tr>')
    summary = (f'<p class="sum">今日 {n_r}レース確定(1レース5,000円を均等買い) ・ 的中 {n_hit} ・ 投資 {cost:,}円 ・ 払戻 {ret:,}円 ・ '
               f'<b>収支 {ret - cost:+,}円</b> ・ 回収率 {ret / cost * 100:.0f}%</p>' if cost else '<p class="sum">今日の確定はまだありません</p>')
    up_html = "".join(race_card(rid, snaps, sel, res, now_ts, provisional=True) for _, rid, snaps, sel in up) or \
        '<p class="none">いま締切13分以内のレースはありません</p>'
    done_html = "".join(race_card(rid, snaps, sel, res, now_ts) for _, rid, snaps, sel in done[:40]) or \
        '<p class="none">まだありません</p>'
    return f"""<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>締切直前に動いた買い目(競輪)</title>
<style>
:root {{ --ink:#1f2937; --soft:#6b7280; --line:#e5e7eb; --bg:#f6f7f9; --acc:#1f4d3a; --hit:#c8102e; }}
* {{ box-sizing:border-box; }} body {{ margin:0; background:var(--bg); color:var(--ink); font-family:-apple-system,"Hiragino Sans","Noto Sans JP",sans-serif; }}
header {{ background:var(--acc); color:#fff; padding:14px 16px; }} header h1 {{ margin:0; font-size:1.15rem; }}
header p {{ margin:4px 0 0; font-size:.8rem; opacity:.9; }} header a {{ color:#fff; }}
main {{ max-width:760px; margin:0 auto; padding:12px 16px 40px; }}
h2 {{ font-size:1rem; margin:20px 0 8px; }}
.card {{ background:#fff; border:1px solid var(--line); border-radius:14px; padding:14px 16px; margin:10px 0; }}
.card.prov {{ border-color:#d6b35a; background:#fffdf5; }}
.card h3 {{ margin:0 0 6px; font-size:1.02rem; }} .card h3 small {{ display:block; font-weight:400; color:var(--soft); font-size:.78rem; margin-top:2px; }}
.sep {{ color:#bbb; margin:0 6px; }} .type {{ color:var(--soft); font-size:.82rem; margin:4px 0 8px; }}
.chips {{ display:flex; flex-wrap:wrap; gap:6px; align-items:center; }}
.chip {{ border:1px solid #d1d5db; border-radius:8px; padding:6px 10px; font-size:1rem; font-variant-numeric:tabular-nums; background:#fff; }}
.sl {{ color:#9ca3af; }} .syn {{ margin:10px 0 4px; font-size:.95rem; }} .meta {{ color:var(--soft); font-size:.74rem; margin:4px 0; }}
.res {{ font-size:.9rem; margin:8px 0 4px; }} .res.hit {{ color:var(--hit); font-weight:700; }} .res.wait {{ color:var(--soft); }}
.gr summary, details.more summary {{ cursor:pointer; font-size:.85rem; color:var(--acc); font-weight:600; margin-top:6px; }}
.chart {{ width:100%; height:auto; margin-top:6px; background:#fff; }} .note {{ font-size:.72rem; color:var(--soft); }}
.sum {{ background:#fff; border:1px solid var(--line); border-radius:10px; padding:10px 12px; font-size:.9rem; }}
.none {{ color:var(--soft); font-size:.85rem; }}
table {{ width:100%; border-collapse:collapse; font-size:.78rem; background:#fff; }} td {{ border-bottom:1px solid var(--line); padding:5px 4px; text-align:center; }} td.l {{ text-align:left; }}
details.more {{ background:#fff; border:1px solid var(--line); border-radius:12px; padding:10px 14px; margin-top:14px; font-size:.82rem; line-height:1.6; }}
</style></head><body>
<header><h1>締切直前に動いた買い目(競輪・3連単)</h1>
<p>{now:%Y-%m-%d} ・ 更新 {now:%H:%M:%S}(約2分おき・このページは1分ごとに自動で読み直し) ・ <a href="picks.html">穴レース</a> ・ <a href="index.html">全レース</a></p></header>
<main>
{summary}
<h2>締切まもなく(暫定・締切まで変わります)</h2>
{up_html}
<h2>選定済み(締切前の最後の記録で決定)</h2>
{done_html}
<details class="more"><summary>選び方・結果の見方</summary>
<p>締切の約13分前から、netkeirin のオッズを60秒おき(締切4分前からは30秒おき)に取っています。公式のオッズ更新があったときだけ記録します。</p>
<p>締切前の最後の記録(選定時)と、その2分以上前の記録を比べます。各組の「支持の割合」(1/オッズを全組の合計で割ったもの)が<b>何倍に増えたか</b>が大きい順に最大5点選びます(割合0.2%未満の大穴は除く)。つまり、締切直前に普段より目立ってお金が入った組です。</p>
<p>11/20に選び方を変えました。11/15〜11/20の300レースでは、旧方式(増えた量の順に15点・資金配分)は回収率71〜78%、新方式(何倍に増えたかの順に5点・均等買い)は120%でした。同じ人気帯からランダムに5点選ぶと平均59%なので、たまたまではなさそうです。ただし効くのは締切直前の動きだけで、締切2分以上前の記録で選ぶと大きく落ちます。期間がまだ短いので、記録を続けて確かめます。</p>
<p>「235-4-35」のような書き方は、1着の候補が2・3・5、2着が4、3着が3・5を表します。この中で同じ車が重なる組を除いたものが、選んだ組です。</p>
<p>合成オッズは、全点を同じ額ずつ買ったときの払戻倍率(1÷Σ(1/オッズ))です。最終は締切後の確定オッズで計算しています。選定時の合成オッズが2倍未満のレースは出していません(成績にも入れていません)。結果は1レース5,000円を選んだ組に均等に買った場合の試算です(100円単位)。</p>
<p>注意: ページの更新は約2分おきで、表示までさらに1分ほどかかります。「締切まもなく」の暫定は、締切までに入れ替わることがあります。直前にお金が入った組は当たりやすい半面、オッズが下がっているので回収率は下がるとも言われます。記録がたまったら回収率を検証します。</p>
</details>
<details class="more"><summary>各レースの買い目・結果一覧</summary>
<table><tr><td>締切</td><td>レース</td><td>点数</td><td>合成</td><td class="l">買い目</td><td>結果</td></tr>{rows}</table></details>
</main>
<script>setTimeout(function(){{ location.replace(location.pathname + '?t=' + Date.now()); }}, 60000);</script>
</body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", required=True)
    ap.add_argument("--no-results", action="store_true")
    a = ap.parse_args()
    now = datetime.datetime.now(JST)
    recs = load(a.live)
    res = load_results()
    if not a.no_results:
        need = [rid for rid, s in recs.items() if rid not in res and now.timestamp() - s[0]["close"] > 600
                and now.timestamp() - s[0]["close"] < 6 * 3600]
        if need:
            res = fetch_results(need, res)
            save_results(res)
    with open(os.path.join(DOCS, "drops.html"), "w", encoding="utf-8") as f:
        _h = render(recs, res, now)
        try:
            import jra_layout
            _h = jra_layout.skin(_h, "競輪 オッズ急落", jra_layout.KEIRIN_LINKS)
        except Exception:  # noqa: BLE001
            pass
        f.write(_h)
    out = {}
    for rid, snaps in recs.items():
        sel = select(snaps)
        if sel:
            out[rid] = dict(venue=snaps[0]["venue"], no=snaps[0]["no"], close=snaps[0]["close"],
                            picks=[p[0] for p in sel["picks"]], formation=formation([p[0] for p in sel["picks"]]),
                            syn=round(synth(sel["cur"]["tri"], [p[0] for p in sel["picks"]]) or 0, 2), result=res.get(rid))
    with open(os.path.join(DOCS, "_drops.json"), "w", encoding="utf-8") as f:
        json.dump(dict(updated=now.isoformat(timespec="seconds"), races=out), f, ensure_ascii=False)
    print(f"[INFO] drops.html: 記録{len(recs)}レース・選定{len(out)}・結果{sum(1 for r in out.values() if r['result'])}")


if __name__ == "__main__":
    main()
