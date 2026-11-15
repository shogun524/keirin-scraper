# -*- coding: utf-8 -*-
"""
競輪: JRA版と同じ「◎(AIそのまま)・込%(オッズ込み)・一言・推し」。

  ◎   … サイトのAI(model.py)の1着率1位。オッズを使わない(ai_raw)
  込% … オッズ込みの1着率(market_fix がオッズから作った1着率。オッズが無いときは出さない)
  人気 … 込%の順位

検証(winticket の過去 2025〜2026年 約5万レースに、今のAIを当て直した。AIの重みは〜2025年のデータで作ったので2026年が本番に近い):
  オッズ込みの1着率に AI を足しても当たり方はほぼ変わらない(条件付きロジットで AI の重み ≈ 0)。
  競輪はオッズ(みんなの評価)が AI の材料をほぼ織り込んでいる → 込% はオッズの1着率そのものに近い。
  ◎=1番人気      勝率52%・3着内82%(オッズどおり)            → 普通
  ◎=2番人気      勝率27%・3着内70%(オッズどおり 1.03倍)     → 普通
  ◎=3番人気      勝率15〜17%・3着内56〜58%(0.89倍)          → 注意
  ◎=4番人気以下  勝率10%・3着内29〜45%(◎軸ワイドの回収69%)  → 危険!
  注意/危険のときの推し = 1番人気(勝率37〜39%・3着内72%)
  ※ どの買い方も回収率100%は超えない(ワイド 1番人気→2〜4番人気 76〜77%・3連複 1番人気軸 72〜74%)。
"""
TAGS = {"普通": ("普通", "tg-ok"), "注意": ("注意", "tg-warn"), "危険": ("危険！", "tg-ng"), "推し": ("推し", "tg-push")}
CSS = (".tg{display:inline-block;font-size:10.5px;font-weight:700;padding:1px 6px;border-radius:9px;margin-left:3px;white-space:nowrap}"
       ".tg-ok{background:#E3F1E6;color:#2E7D46}.tg-warn{background:#FFF1D6;color:#9A6400}"
       ".tg-ng{background:#FBE3E1;color:#B0433A}.tg-push{background:#E3ECFB;color:#1E5FA8}"
       ".aimk{font-weight:900;color:#C8402A;margin-right:2px}.mmv{font-size:11px;color:#777;white-space:nowrap}"
       ".fb{margin:8px 0;padding:8px 10px;border:1px solid #ddd;border-radius:8px;background:#fff;font-size:13px}"
       ".fb-buy{margin:6px 0;padding:6px 8px;background:#F4FAF5;border:1px solid #CFE6D5;border-radius:6px;line-height:1.7}"
       ".fm{margin:4px 0}.fm-head{display:grid;grid-template-columns:1fr 18px 1fr 18px 1fr 40px;font-size:11px;color:#777}"
       ".fm-row{display:grid;grid-template-columns:1fr 18px 1fr 18px 1fr 40px;align-items:center;padding:3px 0;border-bottom:1px dashed #ddd}"
       ".fm-c{display:flex;flex-wrap:wrap;gap:2px}.fm-c .car{width:22px;height:22px;line-height:22px;font-size:12px}"
       ".fm-a{color:#999;text-align:center}.fm-n{font-size:11px;color:#555;text-align:right}"
       ".fb-h{font-weight:800;font-size:13px}.fb-row{display:flex;flex-wrap:wrap;gap:4px;align-items:center;margin:3px 0}"
       ".fb-row span{width:30px;font-size:12px;color:#555}.fb-b{width:32px;height:32px;border-radius:50%;border:2px solid #ccc;background:#fff;font-weight:800;cursor:pointer}"
       ".fb-b.on{background:var(--bg);color:var(--fg);border-color:#333}.fb-out{margin:6px 0;line-height:1.7}"
       ".fb-list span{display:inline-block;margin:1px 4px 1px 0;font-size:11.5px;color:#555}.fb-list .good{color:#2E7D46;font-weight:700}"
       ".fb-t{font-size:12px;border-collapse:collapse}.fb-t td,.fb-t th{padding:2px 6px;border-bottom:1px solid #eee}"
       ".fb-two{display:flex;gap:12px;flex-wrap:wrap;font-size:12px}.fb-two ol{margin:2px 0;padding-left:18px}"
       ".kguide{font-size:12px;margin:6px 0;padding:6px 10px;border:1px solid #ddd;border-radius:8px;background:#fff}"
       ".kguide summary{cursor:pointer;font-weight:700}.kguide ul{margin:4px 0 0;padding-left:18px;line-height:1.7}")
GUIDE = ('<details class="kguide"><summary>見かた(◎・込%・一言・買い目)</summary><ul>'
         '<li><b>◎○▲△</b> … AIの1着率の順(オッズは使わない)。1番人気以外も◎になる。</li>'
         '<li><b>込%</b> … オッズ込みの1着率。競輪はオッズがAIの材料をほぼ織り込んでいて、込%はオッズの1着率とほぼ同じ。オッズが出るまでは出ない。</li>'
         '<li><b>一言</b> … 普通=◎が1〜2番人気(オッズどおり) / 注意=◎が3番人気 / 危険！=◎が4番人気以下(過去の勝率10%) / '
         '推し=注意・危険のレースで代わりに推す選手(1番人気。過去 3着内72%)。</li>'
         '<li><b>買い目(3連単だけ)</b> … 過去の検証で回収率が100%を超えた形に当たったレースだけ。形はレースごとに変わる'
         '(フォーメーション・1点など)。合成オッズ2倍未満にはしない(<a href="../picks.html">ルールの説明</a>)。</li>'
         '</ul></details>')


def ai_probs(rows):
    return {r["car"]: (r.get("ai_raw") if r.get("ai_raw") is not None else r["adjusted"]) for r in rows}


def marks(rows):
    a = ai_probs(rows)
    return {c: m for c, m in zip(sorted(a, key=lambda c: -a[c]), "◎○▲△")}


def race_tags(result):
    """{車番: (表示, css, 対象)}。オッズが無い(込%が無い)ときは空"""
    rows = result.get("rows") or []
    if result.get("fix_mode") != "odds" or len(rows) < 3:
        return {}
    a = ai_probs(rows)
    h = max(a, key=a.get)
    order = sorted(rows, key=lambda r: -r["adjusted"])
    pop = {r["car"]: i + 1 for i, r in enumerate(order)}
    p = pop.get(h, 99)
    if p <= 2:
        return {h: (*TAGS["普通"], "◎")}
    out = {h: (*TAGS["危険" if p >= 4 else "注意"], "◎")}
    out[order[0]["car"]] = (*TAGS["推し"], "推し")
    return out


def tag_html(t):
    return f'<span class="tg {t[1]}">{t[0]}</span>' if t else ""
