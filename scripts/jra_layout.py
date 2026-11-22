"""
JRAサイトと同じ見た目・形のページを作る共通部品(11/21。JRA週末AI予想の generate_html.py の形をそのまま使う)。
  page(...)      … ページ全体(緑のヘッダー・ボタン・リンク・会場タブ・レースタブ・本文・見方)
  race_card(...) … 1レースのカード(大きなレース番号・レース名・チップ・買い目の箱・6列の表)
JRA側の見た目を変えたら、ここの CSS も合わせる。
"""
import html as _h

CSS = r"""  .roles { font-size: .8rem; margin: 6px 0 2px; line-height: 1.7; color: #2A2118; }
  .roles span { margin-right: 8px; white-space: nowrap; display: inline-block; }
  .roles .role-0 { color: #1F4D3A; } .roles b { font-size: .92rem; }
  .roles small { color: #8A7F6E; font-size: .7rem; }
  :root {
    --turf: #1F4D3A; --turf-dark: #163A2B; --paper: #F6F1E4; --paper-line: #E4DAC0;
    --ink: #2A2118; --ink-soft: #6B5F4D; --gold: #B8862B; --gold-soft: #F0D896;
    --good: #2E7D46; --mid: #B8862B; --low: #B0433A;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--paper); color: var(--ink);
    font-family: "Noto Sans JP", sans-serif; padding-bottom: 48px;
  }
  h1, h2, .race-num { font-family: "Shippori Mincho", serif; }

  header.top {
    background: var(--turf); color: #fff; padding: 20px 20px 0;
  }
  header.top .inner { max-width: 900px; margin: 0 auto; }
  header.top h1 { margin: 0 0 4px; font-size: 1.5rem; font-weight: 800; letter-spacing: .02em; }
  header.top p { margin: 0 0 16px; font-size: .8rem; color: #CFE3D8; }

  nav.tabs {
    max-width: 900px; margin: 0 auto; display: flex; gap: 4px; overflow-x: auto;
    padding: 0 20px; scrollbar-width: none;
  }
  nav.tabs::-webkit-scrollbar { display: none; }
  .tab-btn {
    flex: 0 0 auto; background: transparent; border: none; cursor: pointer;
    color: #CFE3D8; font-family: "Noto Sans JP", sans-serif; font-weight: 700;
    font-size: .9rem; padding: 10px 16px; border-radius: 8px 8px 0 0;
    display: flex; align-items: baseline; gap: 6px;
  }
  .tab-btn .tab-count { font-size: .7rem; font-weight: 500; color: #9BB8A9; }
  .tab-btn.active { background: var(--paper); color: var(--ink); }
  .tab-btn.active .tab-count { color: var(--ink-soft); }

  main { max-width: 900px; margin: 0 auto; padding: 20px; }
  .tab-panel { display: none; }
  .tab-panel.active { display: block; }

  nav.race-tabs {
    display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 16px;
  }
  .race-tab-btn {
    background: #fff; border: 1px solid var(--paper-line); color: var(--ink-soft);
    font-family: "Noto Sans JP", sans-serif; font-weight: 700; font-size: .82rem;
    padding: 6px 12px; border-radius: 999px; cursor: pointer;
  }
  .race-tab-btn.active { background: var(--turf); border-color: var(--turf); color: #fff; }
  .race-panel { display: none; }
  .race-panel.active { display: block; }

  .race-card {
    background: #fff; border: 1px solid var(--paper-line); border-radius: 6px;
    margin-bottom: 16px; overflow: hidden;
  }
  .race-card-head {
    display: flex; align-items: center; gap: 14px;
    padding: 14px 16px; border-bottom: 2px solid var(--turf);
    background: linear-gradient(180deg, #fff, #FBF8F0);
  }
  .race-num {
    font-size: 1.8rem; font-weight: 800; color: var(--turf); line-height: 1;
    min-width: 2ch; text-align: center;
  }
  .race-num small { font-size: .9rem; font-weight: 600; margin-left: 1px; }
  .race-title h2 { margin: 0; font-size: 1.05rem; font-weight: 800; }
  .race-sub { margin: 3px 0 0; font-size: .78rem; color: var(--ink-soft); }
  .post-time { margin-left: 8px; color: var(--gold); font-weight: 700; }
  .manbaken { margin: 2px 0 0; font-size: .82rem; }
  .zenjitsu { background:#FFF3D6; border:1px solid #E2B94F; border-radius:8px; padding:8px 12px; margin:10px 0; font-size:.85rem; }
  .bias { margin: 2px 0 0; font-size: .8rem; } .bias small { color:#6B5F4D; }
  .bias-in b { color:#1F4D3A; } .bias-out b { color:#9A4A12; } .bias-flat b { color:#6B5F4D; }
  .ub-fav { display:inline-block; min-width:1.6em; text-align:center; border-radius:4px; background:#D9EEDF; color:#1F4D3A; font-weight:700; box-shadow:inset 0 0 0 1px #6FAE85; }
  .ub-unfav { display:inline-block; min-width:1.6em; text-align:center; color:#9A8F7E; text-decoration:line-through; text-decoration-color:#C9BFAE; }
  details.ev-summary > summary, details.ev-how > summary { cursor: pointer; }
  details.ev-how { margin-top: 6px; font-size: .8rem; }
  .manbaken b { font-variant-numeric: tabular-nums; }
  .manbaken b.hi { color: #B3261E; } .manbaken b.lo { color: #2F6B4F; }
  .manbaken small { margin-left: 4px; opacity: .75; } .manbaken .sep { margin: 0 4px; opacity: .5; }
  .manbaken.muted { opacity: .6; }

  table { border-collapse: collapse; width: 100%; font-size: .82rem; }
  .table-scroll { overflow-x: auto; -webkit-overflow-scrolling: touch; position: relative; }
  .race-card { position: relative; }
  .race-card::after {
    content: ""; position: absolute; top: 54px; bottom: 0; right: 0; width: 18px;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,.9));
    pointer-events: none; display: none;
  }
  @media (max-width: 620px) {
    .race-card::after { display: block; }
  }
  th {
    text-align: left; font-weight: 500; font-size: .72rem; color: var(--ink-soft);
    padding: 8px 10px; border-bottom: 1px solid var(--paper-line); white-space: nowrap;
  }
  td { padding: 8px 10px; border-bottom: 1px solid var(--paper-line); white-space: nowrap; }
  tr:last-child td { border-bottom: none; }
  tr.top-pick { background: #FBF3DC; }
  .rank { font-weight: 800; color: var(--turf); text-align: center; }
  .horse { font-weight: 700; } .horse .bl { font-weight:400; color:#6B5F4D; font-size:.72rem; } small.plc { color:#6B5F4D; }
  .pct { font-variant-numeric: tabular-nums; }
  .waku {
    display: inline-flex; align-items: center; justify-content: center;
    width: 22px; height: 22px; border-radius: 4px; font-weight: 700; font-size: .78rem;
  }
  .waku-none { background: #eee; color: #999; }
  .badge { padding: 2px 8px; border-radius: 999px; font-size: .72rem; font-weight: 700; }
  .ev-good { background: #E4F1E7; color: var(--good); }
  .ev-mid  { background: #F5EAD0; color: var(--mid); }
  .ev-low  { background: #F5DEDC; color: var(--low); }
  .na { color: #A9A093; font-size: .72rem; }
  .gap { color: var(--ink-soft); font-variant-numeric: tabular-nums; }
  .style { font-weight: 600; }
  .tag { padding: 2px 7px; border-radius: 4px; font-size: .72rem; font-weight: 600; background: #F0EBDD; color: var(--ink-soft); }
  .tag-place { background: #E4F1E7; color: var(--good); }
  .tag-win { background: #F5EAD0; color: var(--mid); }
  .conf { display: inline-block; min-width: 26px; text-align: center; padding: 2px 5px; border-radius: 4px; font-size: .72rem; font-weight: 700; }
  .conf-high { background: #E4F1E7; color: var(--good); }
  .conf-mid { background: #F5EAD0; color: var(--mid); }
  .conf-low { background: #EFEAE0; color: #948A7B; }
  .mark { font-size: 1.05rem; font-weight: 700; color: var(--turf); }
  .ai { font-variant-numeric: tabular-nums; font-weight: 700; color: var(--turf); }
  .vt { padding: 2px 7px; border-radius: 4px; font-size: .72rem; font-weight: 700; white-space: nowrap; }
  .vt-big { background: #DCEFE2; color: #1F7A46; }
  .vt-ok { background: #E9F2E4; color: #4A7A2E; }
  .vt-mid { background: #F0EBDD; color: #6B5F4D; }
  .vt-bad { background: #F5DEDC; color: #B0433A; }
  .rd { font-variant-numeric: tabular-nums; font-weight: 700; }
  .rd-good { color: var(--good); }
  .rd-bad { color: #B0433A; }
  .muted { color: #A9A093; }
  .wd-warn { color: #B0433A; font-weight: 700; }
  .cf { font-variant-numeric: tabular-nums; font-weight: 600; }
  .cf-good { color: var(--good); }
  .cf-bad { color: #B0433A; }

  .aibet { margin: 0 0 12px; padding: 10px 12px; background: #FBF6E8; border: 1px solid var(--gold-soft);
    border-left: 4px solid var(--gold); border-radius: 6px; font-size: .86rem; }
  .aibet-tag { display: inline-block; background: var(--gold); color: #fff; font-weight: 700; font-size: .72rem;
    padding: 2px 8px; border-radius: 999px; }
  .aibet-wait { background: #A9A093; }
  .aibet-reason { color: var(--ink-soft); font-size: .76rem; margin-left: 4px; }
  .aibet-body { margin-top: 6px; font-size: .95rem; }
  .aibet-combos { margin-top: 2px; color: var(--ink-soft); font-size: .78rem; font-variant-numeric: tabular-nums; }
  .aibet-summary { background: #fff; border: 1px solid var(--paper-line); border-top: 3px solid var(--gold);
    border-radius: 6px; padding: 12px 16px; margin-bottom: 16px; }
  .aibet-summary h2 { margin: 0 0 4px; font-size: 1.05rem; color: var(--turf); }
  .aibet-summary ul { margin: 8px 0 0; padding-left: 0; list-style: none; font-size: .86rem; line-height: 1.9; }
  .aibet-summary small { color: var(--ink-soft); margin-left: 4px; }
  .aibet-sub { border-left-color: #7A8B9A; background: #F3F5F7; }
  .aibet-h3 { margin: 10px 0 2px; font-size: .9rem; color: var(--gold); }
  .aibet-h3-sub { color: #5E6E7D; }
  .evbox { margin: 0 0 12px; padding: 10px 12px; background: #fff; border: 1px solid var(--paper-line); border-radius: 6px; }
  .evhead { font-size: .78rem; font-weight: 700; color: var(--turf); margin-bottom: 4px; }
  .evcols { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 8px; }
  .evcol h4 { margin: 0 0 2px; font-size: .78rem; color: var(--ink-soft); }
  .evcol ul, .ev-summary ul { margin: 0; padding-left: 0; list-style: none; font-size: .8rem; line-height: 1.8; }
  .ev-summary h2 small { font-size: .72rem; color: var(--ink-soft); font-weight: 500; }
  .mv { font-size: .72rem; font-weight: 700; }
  .mv-in { color: #B0433A; }
  .mv-out { color: #1E5FA8; }
  .wd { font-size: .72rem; color: var(--ink-soft); }
  .aibet-note { margin: 0; font-size: .76rem; color: var(--ink-soft); line-height: 1.6; }

  footer {
    max-width: 900px; margin: 16px auto 0; padding: 0 20px;
    color: var(--ink-soft); font-size: .74rem; line-height: 1.7;
  }

  /* 出走表(スマホで横スクロールなしで読める6列) */
  table.ht { min-width: 0; width: 100%; font-size: .84rem; table-layout: fixed; }
  table.ht td.horse { white-space: normal; overflow: hidden; word-break: break-all; }
  table.ht .bl { display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  table.ht th { font-size: .7rem; padding: 6px 3px; }
  table.ht th, table.ht td { padding: 6px 5px; vertical-align: middle; }
  table.ht td.c { text-align: center; } table.ht td.r { text-align: right; white-space: nowrap; }
  table.ht .ubc { white-space: nowrap; } table.ht .ubn { margin-left: 3px; font-size: .95rem; }
  table.ht .sub { color: var(--ink-soft); font-weight: 400; font-size: .72rem; }
  table.ht .rk { color: var(--ink-soft); font-size: .8rem; }
  table.ht .pct b { font-size: .95rem; }
  .guide { background:#fff; border:1px solid var(--paper-line); border-radius:12px; padding:10px 14px; margin:12px 0; font-size:.82rem; }
  .trioline { font-size:.8rem; margin:4px 0 0; line-height:1.5; } .trioline b { font-variant-numeric:tabular-nums; }
  .tr-e2 { color:#C8102E; }
  .guide summary { font-weight:700; color:var(--turf); cursor:pointer; }
  .guide ul { margin:8px 0 2px; padding-left:1.1em; line-height:1.6; } .guide li { margin:2px 0; }
  .rule { border-top:1px dashed var(--paper-line); padding-top:6px; margin-top:6px; } .rule:first-of-type { border-top:0; }
  .ai-b { display:inline-block; font-size:.66rem; font-weight:700; border-radius:10px; padding:1px 7px; margin-left:6px; vertical-align:middle; }
  .ai-old { background:#F3E6CC; color:#7A5A1E; } .ai-new { background:#DDEFE4; color:#1F4D3A; }
  .roi-b { font-size:.68rem; color:#8A7E6A; margin-left:6px; font-weight:500; }
  .aibet-none { font-size:.78rem; color:#8A7E6A; margin:8px 0 0; }
  .rnm { color:#6B6152; font-size:.8rem; }
  table.ht .vt { white-space:nowrap; font-size:.68rem; padding:1px 4px; }
  .evs { display:block; margin-top:2px; } .evs .badge { font-size:.66rem; padding:1px 5px; }
  .htag { display:inline-block; font-size:.62rem; font-weight:800; border-radius:4px; padding:1px 4px; margin-top:2px; white-space:nowrap; }
  .tg-go { background:#C8102E; color:#fff; } .tg-ok { background:#E6EFE9; color:#1F4D3A; }
  .tg-warn { background:#FFF0C2; color:#7A5A1E; } .tg-ng { background:#3A3A3A; color:#fff; }
  .tg-push { background:#2E5BA8; color:#fff; }
  table.ht .oldmk { display:inline-block; font-size:.62rem; color:#7A5A1E; border:1px solid #B88A2E; border-radius:4px; padding:0 3px; margin-top:2px; }
  .aibet-note { font-size:.72rem; color:#8A7E6A; margin-top:4px; line-height:1.4; }
  table.ht .mm { color: #2E5BA8; font-size: .72rem; font-weight: 600; }
  table.ht .mm-hi { color: #C8102E; }
  .hit-summary .hp, .hitline .hp { color:#1F4D3A; font-weight:800; }
  .hitline { margin: 3px 0 0; font-size: .76rem; } .hitline .hp { color: #1F4D3A; font-weight: 800; }
  .chips { display: flex; flex-wrap: wrap; gap: 4px 10px; margin-top: 2px; }
  .chips p { margin: 0; }
  .top .meta { margin: 4px 0 8px; font-size: .78rem; opacity: .9; }
  .top .actions { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }
  .top .btn { appearance: none; border: 0; border-radius: 999px; padding: 8px 14px; font-size: .85rem; font-weight: 700;
               background: #F0D896; color: #1F3B2C; text-decoration: none; cursor: pointer; }
  .top .btn-sub { background: transparent; color: #F0D896; box-shadow: inset 0 0 0 1.5px #F0D896; }
  .top .links { display: flex; gap: 6px; flex-wrap: wrap; }
  .top .links a { color: #fff; font-size: .78rem; text-decoration: none; padding: 3px 9px; border-radius: 999px; background: rgba(255,255,255,.12); }
  details.why { display: inline; font-size: .7rem; font-weight: 400; margin-left: 6px; }
  details.why summary { display: inline; cursor: pointer; color: var(--ink-soft); }
  .aibet-buy { font-weight: 700; }
  .evr { color: var(--ink-soft); font-size: .76rem; }
  details.evbox summary { cursor: pointer; }
  .ev-more summary { cursor: pointer; font-size: .78rem; color: var(--ink-soft); margin: 4px 0; }
  footer details summary { cursor: pointer; }
  .detail-link { display:inline-block; margin:8px 12px 12px; font-size:.8rem; color:var(--turf); font-weight:700; text-decoration:none; border:1px solid var(--paper-line); border-radius:999px; padding:4px 12px; background:#fff; }
  .card-extra { padding: 8px 12px 0; font-size: .84rem; }
  .card-extra details summary { cursor:pointer; color:var(--ink-soft); font-size:.8rem; }
  .carb { display:inline-flex; align-items:center; justify-content:center; width:24px; height:24px; border-radius:50%; font-weight:800; font-size:.85rem; border:1px solid rgba(0,0,0,.15); }
  .ln { font-size:.68rem; color:var(--ink-soft); }
  .aibet-summary a { color: var(--turf); }
"""


def esc(x):
    return _h.escape(str(x if x is not None else ""))


def race_card(num, title, sub_html="", chips_html="", aibet_html="", cols=None, rows_html="", extra_html="", link=None):
    """cols: [(見出し, 幅px or None)] 6列。rows_html: <tr>…</tr> の並び"""
    cols = cols or [("印", 26), ("番", 50), ("名前", None), ("人気", 58), ("AI<br><small>込</small>", 50), ("妙味", 54)]
    cg = "".join(f'<col style="width:{w}px">' if w else "<col>" for _, w in cols)
    th = "".join(f"<th>{t}</th>" for t, _ in cols)
    lk = f'<a class="detail-link" href="{link}">詳しく(3連単・展開など) →</a>' if link else ""
    return f"""
    <article class="race-card">
      <header class="race-card-head">
        <span class="race-num">{num}<small>R</small></span>
        <div class="race-title">
          <h2>{title}</h2>
          <p class="race-sub">{sub_html}</p>
          <div class="chips">{chips_html}</div>
        </div>
      </header>
      {aibet_html}
      <div class="table-scroll">
      <table class="ht"><colgroup>{cg}</colgroup>
        <thead><tr>{th}</tr></thead>
        <tbody>{rows_html}</tbody>
      </table>
      </div>
      {f'<div class="card-extra">{extra_html}</div>' if extra_html else ""}
      {lk}
    </article>"""



FOLD_CSS = """
  details.fold > summary { cursor: pointer; list-style: none; display: flex; align-items: center; gap: 6px; }
  details.fold > summary::-webkit-details-marker { display: none; }
  details.fold > summary::before { content: "▶"; font-size: .7em; color: #8A7F6E; transition: transform .15s; }
  details.fold[open] > summary::before { transform: rotate(90deg); }
  details.fold > summary h2 { display: inline; margin: 0; }
  details.fold:not([open]) { padding-bottom: 10px; }
"""


def fold(html):
    """<section class="..."><h2>見出し</h2>…</section> を、見出しを押すと開く <details>(最初は閉じた状態)にする。
    「このサイトの見方」も閉じた状態にする(11/22)"""
    import re
    html = re.sub(r'<section class="([^"]*)">\s*<h2>(.*?)</h2>',
                  lambda m: f'<details class="{m.group(1)} fold"><summary><h2>{m.group(2)}</h2></summary>', html, flags=re.S)
    html = re.sub(r'</section>', '</details>', html)
    html = html.replace('<details class="guide" open>', '<details class="guide">')
    return html

def page(title, meta_html, venues, top_html="", links=(), refetch_url=None, footer_html=""):
    """venues: [(会場名, [(レース番号, 星などの印, カードHTML), ...]), ...]"""
    tab_buttons, tab_panels = "", ""
    for i, (vn, races) in enumerate(venues):
        act = "active" if i == 0 else ""
        tab_buttons += f'<button class="tab-btn {act}" data-tab="tab-{i}">{esc(vn)}<span class="tab-count">{len(races)}R</span></button>'
        rb, rp = "", ""
        for j, (no, star, card) in enumerate(races):
            ra = "active" if j == 0 else ""
            rb += f'<button class="race-tab-btn {ra}" data-race="race-{i}-{j}" data-no="{no}">{star}{no}R</button>'
            rp += f'<div class="race-panel {ra}" id="race-{i}-{j}">{card}</div>'
        tab_panels += f'<section class="tab-panel {act}" id="tab-{i}"><nav class="race-tabs">{rb}</nav>{rp}</section>'
    lk = "".join(f'<a href="{u}">{esc(t)}</a>' for t, u in links)
    rf = (f'<a class="btn btn-sub" href="{refetch_url}" target="_blank" rel="noopener">オッズを今すぐ取り直す</a>' if refetch_url else "")
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Shippori+Mincho:wght@600;800&family=Noto+Sans+JP:wght@400;500;700&display=swap" rel="stylesheet">
<style>{CSS}{FOLD_CSS}</style>
</head>
<body>
<header class="top">
  <div class="inner">
    <h1>{esc(title)}</h1>
    <p class="meta">{meta_html}</p>
    <div class="actions">
      <button type="button" class="btn" onclick="location.href=location.pathname+'?t='+Date.now()">↻ 最新を表示</button>
      {rf}
    </div>
    <nav class="links">{lk}</nav>
  </div>
  <nav class="tabs">{tab_buttons}</nav>
</header>
<main>{fold(top_html)}{tab_panels}</main>
<footer>{footer_html}</footer>
<script>
document.querySelectorAll('.tab-btn').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(btn.dataset.tab).classList.add('active');
  }});
}});
document.querySelectorAll('.race-tab-btn').forEach(btn => {{
  btn.addEventListener('click', () => {{
    const panel = btn.closest('.tab-panel');
    panel.querySelectorAll('.race-tab-btn').forEach(b => b.classList.remove('active'));
    panel.querySelectorAll('.race-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(btn.dataset.race).classList.add('active');
  }});
}});
// 見ていた会場・レースを覚えておき、「最新を表示」や再読み込みのあとも同じレースを開く(11/22)
(function(){{
  var K = 'sel:' + location.pathname;
  function vname(b){{ return b ? (b.childNodes[0] ? b.childNodes[0].textContent : b.textContent).trim() : null; }}
  function rname(b){{ var m = b ? b.textContent.match(/(\\d+)R/) : null; return m ? m[1] : null; }}
  function save(){{
    try {{
      var t = document.querySelector('.tab-btn.active');
      var p = t ? document.getElementById(t.dataset.tab) : document;
      var r = p ? p.querySelector('.race-tab-btn.active') : null;
      sessionStorage.setItem(K, JSON.stringify({{ v: vname(t), r: rname(r) }}));
    }} catch (e) {{}}
  }}
  document.querySelectorAll('.tab-btn, .race-tab-btn').forEach(function(b){{
    b.addEventListener('click', function(e){{ if (e.isTrusted) save(); }});
  }});
  window.restoreSel = function(){{
    try {{
      var s = JSON.parse(sessionStorage.getItem(K) || 'null');
      if (!s) return false;
      var t = null;
      document.querySelectorAll('.tab-btn').forEach(function(b){{ if (vname(b) === s.v) t = b; }});
      if (t) t.click();
      var p = t ? document.getElementById(t.dataset.tab) : document;
      var r = null;
      if (p && s.r) p.querySelectorAll('.race-tab-btn').forEach(function(b){{ if (rname(b) === s.r) r = b; }});
      if (r) r.click();
      return !!(t || r);
    }} catch (e) {{ return false; }}
  }};
}})();
// ?v=会場番号&r=レース番号 で開く。指定が無ければ、各会場でこれから一番近いレースを開く
(function(){{
  const q = new URLSearchParams(location.search);
  const v = q.get('v'), r = q.get('r');
  if (v !== null) {{ const b = document.querySelector('.tab-btn[data-tab="tab-' + v + '"]'); if (b) b.click(); }}
  document.querySelectorAll('.tab-panel').forEach(p => {{
    let pick = null;
    if (r !== null && (v === null || p.id === 'tab-' + v)) pick = p.querySelector('.race-tab-btn[data-no="' + r + '"]');
    if (!pick) pick = p.querySelector('.race-tab-btn.next');
    if (pick) pick.click();
  }});
  if (v === null && r === null) restoreSel();
}})();
</script>
</body>
</html>"""


# ---------------------------------------------------------------- 既存ページをJRAと同じ見た目にする(11/21)
SKIN_CSS = r"""
  body { background: #F6F1E4 !important; color: #2A2118; font-family: "Noto Sans JP", sans-serif; }
  .jx-top { background: #1F4D3A; color: #fff; padding: 18px 20px 14px; margin: 0 0 12px; }
  .jx-top .jx-in { max-width: 900px; margin: 0 auto; }
  .jx-top h1 { margin: 0 0 4px; font: 800 1.45rem/1.3 "Shippori Mincho", serif; letter-spacing: .02em; color: #fff; }
  .jx-top h1 a { color: #fff; text-decoration: none; }
  .jx-top .jx-meta { margin: 0 0 8px; font-size: .78rem; color: #CFE3D8; line-height: 1.5; }
  .jx-top .jx-links { display: flex; gap: 6px; flex-wrap: wrap; }
  .jx-top .jx-links a { color: #fff; font-size: .78rem; text-decoration: none; padding: 3px 9px; border-radius: 999px; background: rgba(255,255,255,.12); }
  .jx-top .jx-links a.jx-home { background: #F0D896; color: #1F3B2C; font-weight: 700; }
  h1, h2 { font-family: "Shippori Mincho", serif; }
"""


def skin(html, title, links, home="index.html"):
    """既存のページの見出し(最初の<header>)を、JRAと同じ緑のヘッダーに置き換え、背景・字体をそろえる。何度かけても同じ"""
    import re
    if 'name="jx-skin"' in html:
        return html
    head_add = ('<meta name="jx-skin" content="1">'
                '<link href="https://fonts.googleapis.com/css2?family=Shippori+Mincho:wght@600;800&family=Noto+Sans+JP:wght@400;500;700&display=swap" rel="stylesheet">'
                f'<style>{SKIN_CSS}</style>')
    html = html.replace("</head>", head_add + "</head>", 1) if "</head>" in html else head_add + html
    meta = ""
    m = re.search(r"<header\b[^>]*>(.*?)</header>", html, re.S)
    if m:
        inner = re.sub(r"<h1\b.*?</h1>", "", m.group(1), flags=re.S)
        inner = re.sub(r"<(nav|script|style|button)\b.*?</\1>", "", inner, flags=re.S)
        txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", inner)).strip()
        meta = esc(txt[:180])
    lk = f'<a class="jx-home" href="{home}">← 今日の予想</a>' + "".join(f'<a href="{u}">{esc(t)}</a>' for t, u in links)
    hdr = (f'<header class="jx-top"><div class="jx-in"><h1>{esc(title)}</h1>'
           + (f'<p class="jx-meta">{meta}</p>' if meta else "") + f'<nav class="jx-links">{lk}</nav></div></header>')
    if m:
        html = html[:m.start()] + hdr + html[m.end():]
    else:
        html = re.sub(r"(<body[^>]*>)", lambda x: x.group(1) + hdr, html, count=1)
    return html


KEIRIN_LINKS = [("買うべきレース", "picks.html"), ("オッズ急落", "drops.html"), ("印刷用", "print.html"),
                ("成績", "results.html"), ("競輪場", "venues.html")]
KEIRIN_TITLES = {"picks.html": "買うべきレース", "drops.html": "オッズ急落", "print.html": "印刷用", "results.html": "予想成績",
                 "venues.html": "全競輪場データ", "formula.html": "勝利の方程式", "close_race.html": "拮抗レース",
                 "today.html": "今日のレース一覧", "high_prob.html": "本命が堅いレース", "edge.html": "回収の分析"}


def skin_file(path, title, links, home="index.html"):
    import os
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        h = f.read()
    h2 = skin(h, title, links, home)
    if h2 != h:
        with open(path, "w", encoding="utf-8") as f:
            f.write(h2)


def skin_keirin_docs(docs):
    """競輪サイトの index.html 以外のページを、JRAと同じ見た目のヘッダーにそろえる"""
    import os
    for fn, t in KEIRIN_TITLES.items():
        if fn == "drops.html":   # オッズ急落は nk_watch が1〜2分おきに作り直して push する(ここで触るとぶつかる)
            continue
        skin_file(os.path.join(docs, fn), f"競輪 {t}", KEIRIN_LINKS)
    sub = [(t, "../" + u) for t, u in KEIRIN_LINKS]
    for d in os.listdir(docs):
        p = os.path.join(docs, d, "index.html")
        if os.path.isdir(os.path.join(docs, d)) and os.path.exists(p):
            try:
                import report
                name = report.VENUE_NAMES.get(d, d)
            except Exception:  # noqa: BLE001
                name = d
            skin_file(p, f"{name}競輪", sub, "../index.html")
