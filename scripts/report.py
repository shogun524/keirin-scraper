# -*- coding: utf-8 -*-
"""
1日分のレース予測結果を、スマホでそのまま見られる静的HTMLレポートに変換する。
GitHub Pages で公開する docs/ 以下のファイルを生成する。

構成：
  docs/index.html        … 競輪場の一覧（本日開催しているところだけ明るく表示）
  docs/{venue}/index.html … その競輪場のレース一覧（タブでレースを切り替え）
"""

import datetime
from zoneinfo import ZoneInfo
from model import KIMARITE_LABELS, KIMARITE

VENUE_NAMES = {
    "hakodate": "函館", "aomori": "青森", "iwakitaira": "いわき平",
    "yahiko": "弥彦", "maebashi": "前橋", "toride": "取手", "utsunomiya": "宇都宮",
    "omiya": "大宮", "seibuen": "西武園", "keiokaku": "京王閣", "tachikawa": "立川",
    "matsudo": "松戸", "chiba": "千葉", "kawasaki": "川崎", "hiratsuka": "平塚",
    "odawara": "小田原", "ito": "伊東", "shizuoka": "静岡",
    "nagoya": "名古屋", "gifu": "岐阜", "ogaki": "大垣", "toyohashi": "豊橋",
    "toyama": "富山", "matsusaka": "松阪", "yokkaichi": "四日市",
    "fukui": "福井", "nara": "奈良", "mukomachi": "向日町", "wakayama": "和歌山", "kishiwada": "岸和田",
    "tamano": "玉野", "hiroshima": "広島", "hofu": "防府",
    "takamatsu": "高松", "komatsushima": "小松島", "kochi": "高知", "matsuyama": "松山",
    "kokura": "小倉", "kurume": "久留米", "takeo": "武雄", "sasebo": "佐世保",
    "beppu": "別府", "kumamoto": "熊本",
}
VENUE_GRID = [
    ["hakodate", "aomori", "iwakitaira", "yahiko"],
    ["maebashi", "toride", "utsunomiya", "omiya"],
    ["seibuen", "keiokaku", "tachikawa", "matsudo"],
    ["chiba", "kawasaki", "hiratsuka", "odawara"],
    ["ito", "shizuoka", "nagoya", "gifu"],
    ["ogaki", "toyohashi", "toyama", "matsusaka"],
    ["yokkaichi", "fukui", "nara", "mukomachi"],
    ["wakayama", "kishiwada", "tamano", "hiroshima"],
    ["hofu", "takamatsu", "komatsushima", "kochi"],
    ["matsuyama", "kokura", "kurume", "takeo"],
    ["sasebo", "beppu", "kumamoto"],
]

CAR_COLORS = {
    1: ("#ffffff", "#1b2430"), 2: ("#1b1b1b", "#ffffff"), 3: ("#d8322a", "#ffffff"),
    4: ("#1f5fc4", "#ffffff"), 5: ("#e8c221", "#1b2430"), 6: ("#2f8f4e", "#ffffff"),
    7: ("#e07a1f", "#ffffff"), 8: ("#e2699a", "#ffffff"), 9: ("#3fb8c9", "#1b2430"),
}
KIMARITE_COLORS = {"逃": "#c1443b", "捲": "#e07a1f", "差": "#1f5fc4", "マ": "#2f8f4e"}

COMMON_STYLE = """
  :root{ --navy:#0e1b2b; --navy2:#132540; --paper:#f6f3ec; --ink:#1b2430; --ink-soft:#5b6472; --border:#d8d2c2; --gold:#d8a94a; }
  *{box-sizing:border-box;}
  body{ margin:0; background:var(--paper); color:var(--ink); font-family:"Hiragino Sans","Yu Gothic",sans-serif; }
  header{ background:linear-gradient(180deg,var(--navy),var(--navy2)); color:#fff; padding:18px 16px; }
  header .top-row{ display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; }
  header h1{ margin:0; font-size:19px; }
  header .date{ color:var(--gold); font-size:13px; font-weight:700; }
  header p{ margin:8px 0 0; color:#b9c3d4; font-size:12.5px; }
  header p.tagline{ font-style:italic; color:#cdd7e3; }
  a{ color:inherit; text-decoration:none; }
  footer{ text-align:center; color:var(--ink-soft); font-size:11px; padding:24px 10px; }
"""


def car_color(car):
    return CAR_COLORS.get(((car - 1) % 9) + 1, ("#888", "#fff"))


def svg_bar_chart(rows, height=170):
    by_car = sorted(rows, key=lambda r: r["car"])
    n = len(by_car)
    width = max(n * 46, 260)
    max_val = max((r["adjusted"] for r in by_car), default=1) or 1
    bar_w = 28
    gap = (width - n * bar_w) / (n + 1)
    plot_h = height - 34

    bars = ""
    for i, r in enumerate(by_car):
        x = gap + i * (bar_w + gap)
        h = max((r["adjusted"] / max_val) * plot_h, 2)
        y = plot_h - h + 10
        bg, fg = car_color(r["car"])
        bars += f"""
        <rect x="{x:.1f}" y="{y:.1f}" width="{bar_w}" height="{h:.1f}" fill="{bg}" stroke="#1b2430" stroke-width="1" rx="3"/>
        <text x="{x+bar_w/2:.1f}" y="{y-4:.1f}" font-size="10" text-anchor="middle" fill="#1b2430">{r['adjusted']:.1f}%</text>
        <text x="{x+bar_w/2:.1f}" y="{plot_h+24:.1f}" font-size="11" text-anchor="middle" fill="{fg}"
              style="paint-order:stroke; stroke:{bg}; stroke-width:5px;">{r['car']}</text>"""

    return f"""<svg viewBox="0 0 {width} {height}" width="100%" style="max-width:{width}px; display:block; margin:0 auto;">
      <line x1="0" y1="{plot_h+10:.1f}" x2="{width}" y2="{plot_h+10:.1f}" stroke="#d8d2c2" stroke-width="1"/>
      {bars}
    </svg>"""


def svg_donut_chart(kimarite_ratio, size=150):
    cx = cy = size / 2
    r_outer = size / 2 - 6
    r_inner = r_outer * 0.55
    total = sum(kimarite_ratio.values()) or 1
    start_angle = -90
    paths = ""
    legend = ""
    import math as _m
    for t in KIMARITE:
        val = kimarite_ratio.get(t, 0)
        frac = val / total
        angle = frac * 360
        end_angle = start_angle + angle
        large_arc = 1 if angle > 180 else 0

        def pt(a, r):
            rad = _m.radians(a)
            return cx + r * _m.cos(rad), cy + r * _m.sin(rad)

        x1o, y1o = pt(start_angle, r_outer)
        x2o, y2o = pt(end_angle, r_outer)
        x1i, y1i = pt(end_angle, r_inner)
        x2i, y2i = pt(start_angle, r_inner)
        color = KIMARITE_COLORS[t]
        if frac > 0.001:
            paths += (f'<path d="M{x1o:.1f},{y1o:.1f} A{r_outer:.1f},{r_outer:.1f} 0 {large_arc} 1 {x2o:.1f},{y2o:.1f} '
                       f'L{x1i:.1f},{y1i:.1f} A{r_inner:.1f},{r_inner:.1f} 0 {large_arc} 0 {x2i:.1f},{y2i:.1f} Z" '
                       f'fill="{color}"/>')
        legend += (f'<div style="display:flex;align-items:center;gap:5px;font-size:11.5px;">'
                   f'<span style="width:10px;height:10px;border-radius:2px;background:{color};display:inline-block;"></span>'
                   f'{KIMARITE_LABELS[t]} {val:.0f}%</div>')
        start_angle = end_angle

    return f"""<div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap;justify-content:center;">
      <svg viewBox="0 0 {size} {size}" width="{size}" height="{size}">{paths}</svg>
      <div style="display:flex;flex-direction:column;gap:4px;">{legend}</div>
    </div>"""


def render_kimarite_table(kimarite_ratio):
    cells = "".join(f"<th>{KIMARITE_LABELS[t]}</th>" for t in KIMARITE)
    vals = "".join(f"<td>{kimarite_ratio.get(t,0):.1f}%</td>" for t in KIMARITE)
    return f"""
    <h4>表2：レース全体の決まり手構成（AI予測ベース）</h4>
    <p class="dim" style="margin:0 0 6px;">各号車の「予測決まり手」の確率分布を合計した構成比です。過去の実績そのままではなく、ライン位置なども加味した今回のレースの予測値です。</p>
    <table class="main kimarite-table"><thead><tr>{cells}</tr></thead><tbody><tr>{vals}</tr></tbody></table>"""


def render_second_place_matrix_table(racers, matrix):
    by_car = sorted(racers, key=lambda r: r["car"])
    header = "<th>1着↓＼2着→</th>" + "".join(f"<th>{r['car']}</th>" for r in by_car)
    rows_html = ""
    for winner in by_car:
        candidates = {c["car"]: c for c in matrix.get(winner["car"], [])}
        cells = f"<td><b>{winner['car']} {winner['name']}</b></td>"
        for cand in by_car:
            if cand["car"] == winner["car"]:
                cells += '<td class="diag">—</td>'
            else:
                c = candidates.get(cand["car"])
                cls = "same-line" if (c and c["same_line"]) else ""
                cells += f'<td class="{cls}">{c["prob"]:.1f}%</td>' if c else '<td>-</td>'
        rows_html += f"<tr>{cells}</tr>"
    return f"""
    <h4>表4：号車別「仮に1着だった場合」の2着確率（全号車マトリクス）</h4>
    <p class="dim" style="margin:0 0 6px;">縦＝仮に1着になったと仮定する号車、横＝その場合に2着に来る号車。同ラインの組み合わせは背景色で強調しています。</p>
    <div class="matrix-scroll"><table class="main matrix"><thead><tr>{header}</tr></thead><tbody>{rows_html}</tbody></table></div>"""


def render_third_place_matrix_table(racers, matrix):
    by_car = sorted(racers, key=lambda r: r["car"])
    header = "<th>1着↓＼3着→（2着自動選定）</th>" + "".join(f"<th>{r['car']}</th>" for r in by_car)
    rows_html = ""
    for winner in by_car:
        entry = matrix.get(winner["car"])
        if not entry:
            cells = f"<td><b>{winner['car']} {winner['name']}</b></td>" + "".join('<td class="diag">-</td>' for _ in by_car)
            rows_html += f"<tr>{cells}</tr>"
            continue
        second_car = entry["second_car"]
        candidates = {c["car"]: c for c in entry["candidates"]}
        cells = f"<td><b>{winner['car']} {winner['name']}</b><br><span class='dim' style='font-size:10px;'>2着想定:{second_car}号車</span></td>"
        for cand in by_car:
            if cand["car"] in (winner["car"], second_car):
                cells += '<td class="diag">—</td>'
            else:
                c = candidates.get(cand["car"])
                cls = "same-line" if (c and c["same_line"]) else ""
                cells += f'<td class="{cls}">{c["prob"]:.1f}%</td>' if c else '<td>-</td>'
        rows_html += f"<tr>{cells}</tr>"
    return f"""
    <h4>表5：号車別「仮に1着だった場合」の3着確率（全号車マトリクス）</h4>
    <p class="dim" style="margin:0 0 6px;">縦＝仮に1着になったと仮定する号車（2着は表4の最有力候補を自動選定）、横＝その場合に3着に来る号車。</p>
    <div class="matrix-scroll"><table class="main matrix"><thead><tr>{header}</tr></thead><tbody>{rows_html}</tbody></table></div>"""


def render_line_info_block(result, race_title=""):
    # ガールズ競輪（全員単騎、女子選手7名）はライン概念が無いため表示しない
    if "ガールズ" in (race_title or ""):
        return ""

    line_map = result.get("line_map") or {}
    if not line_map:
        return ('<div class="line-info-block warn">⚠ 並び予想を検出できませんでした。'
                '決まり手予測・展開補正はライン情報なしで計算されています。</div>')

    by_line = {}
    for car, info in line_map.items():
        by_line.setdefault(info["line_index"], []).append((info["position"], car))

    def badge(car):
        bg, fg = car_color(car)
        return f'<span class="car" style="background:{bg};color:{fg}">{car}</span>'

    parts = []
    for li in sorted(by_line):
        members = sorted(by_line[li])
        cars_html = '<span class="line-arrow">→</span>'.join(badge(car) for _, car in members)
        parts.append(f'<span class="line-group">{cars_html}</span>')
    return '<div class="line-info-block ok">' + "".join(parts) + '</div>'


def render_race_card(race_data, tab_id):
    info = race_data["race_info"]
    result = race_data["prediction"]
    if not result:
        return f'<div id="{tab_id}" class="race-panel" style="display:none;"><p>このレースはデータを取得できませんでした。</p></div>'

    title = info.get("title", "")
    top = result["top"]
    high_prob = result["is_high_prob"]

    rows_html = ""
    for r in result["rows"]:
        bg, fg = car_color(r["car"])
        highlight = "background:#fff4de;" if (high_prob and r["car"] == top["car"]) else ""
        line_label = "単騎"
        if r["line_info"]:
            pos = r["line_info"]["position"]
            line_label = "先頭" if pos == 1 else f"{pos}番手"
        rows_html += f"""
        <tr style="{highlight}">
          <td><span class="car" style="background:{bg};color:{fg}">{r['car']}</span></td>
          <td>{r['name']}</td>
          <td>{r['rank']}</td>
          <td>{KIMARITE_LABELS.get(r['dominant_type'], '-')}<br><span class="dim">({r['kimarite_prediction']['ratio']*100:.0f}%)</span></td>
          <td>{line_label}</td>
          <td><b>{r['adjusted']:.1f}%</b></td>
          <td>{r['confidence']['score']:.0f}</td>
          <td>{r.get('old_model_place_rate', 0):.1f}%</td>
        </tr>"""

    banner_html = ""
    if high_prob:
        banner_html = (f'<div class="banner-high">{top["car"]}号車 {top["name"]} が本命'
                        f'（予測1着率 {top["adjusted"]:.1f}%）</div>')

    bar_chart = svg_bar_chart(result["rows"])
    line_info_html = render_line_info_block(result, title)
    kimarite_table_html = render_kimarite_table(result["kimarite_ratio"])
    second_matrix_html = render_second_place_matrix_table(result["rows"], result["second_place_matrix"])
    third_matrix_html = render_third_place_matrix_table(result["rows"], result["third_place_matrix"])

    deadline = info.get("deadline")
    deadline_html = f'<span class="deadline">締切 {deadline}</span>' if deadline else ""
    return f"""
    <div id="{tab_id}" class="race-panel" style="display:none;">
      <div class="race-card">
        <div class="race-head">
          <span class="raceno">{info['race_no']}R</span>
          <span class="title">{title}</span>
          {deadline_html}
        </div>
        {banner_html}
        {line_info_html}
        <h4>表1：号車別 予測1着率</h4>
        <table class="main">
          <thead><tr><th>号車</th><th>選手</th><th>級班</th><th>予測決まり手</th><th>ライン</th><th>予測1着率</th><th>信頼度</th><th>予測3着内率<br><span style="font-weight:400;font-size:9px;">(旧モデル)</span></th></tr></thead>
          <tbody>{rows_html}</tbody>
        </table>

        <div class="chart-block">
          {bar_chart}
        </div>

        <div class="chart-block">{kimarite_table_html}</div>
        <div class="chart-block">{second_matrix_html}</div>
        <div class="chart-block">{third_matrix_html}</div>
      </div>
    </div>"""


RACE_PANEL_STYLE = """
  main{ max-width:720px; margin:0 auto; padding:14px 10px 60px; }
  .tab-bar{ display:flex; gap:6px; overflow-x:auto; padding:4px 2px 12px; -webkit-overflow-scrolling:touch; }
  .tab-btn{ flex:0 0 auto; background:#fff; border:1px solid var(--border); border-radius:6px; padding:8px 14px;
            font-size:13px; font-weight:700; cursor:pointer; color:var(--ink); text-align:center; }
  .tab-btn .tab-deadline{ font-size:10px; font-weight:400; color:var(--ink-soft); }
  .tab-btn.active .tab-deadline{ color:#cdd7e3; }
  .tab-btn.active{ background:var(--navy); color:#fff; border-color:var(--navy); }
  .race-card{ background:#fff; border:1px solid var(--border); border-radius:8px; padding:14px; }
  .race-head{ display:flex; gap:8px; align-items:baseline; margin-bottom:8px; flex-wrap:wrap; }
  .race-head .raceno{ background:var(--navy); color:#fff; border-radius:4px; padding:1px 8px; font-size:13px; }
  .race-head .title{ color:var(--ink-soft); font-size:13px; }
  .race-head .deadline{ margin-left:auto; background:#f0ece0; border-radius:4px; padding:1px 8px; font-size:12px; color:var(--ink); font-weight:700; }
  .banner-high{ background:#fff4de; border:1px solid var(--gold); border-radius:6px; padding:8px 10px; font-size:13.5px; margin-bottom:8px; }
  .banner-normal{ background:#f0ece0; border-radius:6px; padding:8px 10px; font-size:13.5px; margin-bottom:8px; }
  .note{ font-size:12px; color:#b5482f; margin:4px 0; }
  table.main{ width:100%; border-collapse:collapse; font-size:12px; }
  table.main th, table.main td{ border:1px solid var(--border); padding:5px; text-align:center; }
  table.main th{ background:#f0ece0; }
  .dim{ color:var(--ink-soft); font-size:10px; }
  .car{ display:inline-flex; align-items:center; justify-content:center; width:20px; height:20px; border-radius:50%; font-size:11px; font-weight:700; border:1px solid rgba(0,0,0,.15); }
  .sub-wrap{ display:flex; gap:16px; margin-top:10px; flex-wrap:wrap; }
  .sub-wrap h4{ font-size:12px; margin:0 0 4px; color:var(--ink-soft); }
  table.sub{ font-size:12px; border-collapse:collapse; }
  table.sub td{ padding:2px 8px 2px 0; }
  .chart-block{ margin-top:16px; border-top:1px solid var(--border); padding-top:12px; }
  .chart-block h4{ font-size:12.5px; color:var(--ink-soft); margin:0 0 8px; text-align:center; }
  .kimarite-table th, .kimarite-table td{ text-align:center; }
  .matrix-scroll{ overflow-x:auto; }
  table.matrix{ font-size:10.5px; }
  table.matrix th, table.matrix td{ padding:4px; white-space:nowrap; }
  table.matrix td.diag{ background:#f0ece0; color:var(--ink-soft); }
  table.matrix td.same-line{ background:#e3f0ff; font-weight:700; }
  .line-info-block{ font-size:12px; border-radius:6px; padding:9px 10px; margin:8px 0; display:flex; flex-wrap:wrap; gap:12px; align-items:center; }
  .line-info-block.ok{ background:#e7f3ea; border:1px solid #b9dcc3; }
  .line-info-block.warn{ background:#fff4de; color:#8a5a12; border:1px solid #e8c98a; }
  .line-group{ display:inline-flex; align-items:center; gap:3px; }
  .line-arrow{ color:var(--ink-soft); font-size:11px; }
  @media (max-width:420px){
    table.main{ font-size:10.5px; }
    table.main th, table.main td{ padding:3px; }
  }
"""

TAB_SCRIPT = """
function showTab(id, btn){
  document.querySelectorAll('.race-panel').forEach(function(p){ p.style.display = 'none'; });
  document.querySelectorAll('.tab-btn').forEach(function(b){ b.classList.remove('active'); });
  document.getElementById(id).style.display = '';
  btn.classList.add('active');
}

// 「HH:MM」形式の締切時刻と、日本時間での現在時刻から、締切までの残り分数を返す。
// 開いた瞬間のブラウザの時計を使うため、ページ生成時刻に関わらず常に正しく判定できる。
function minutesUntilDeadline(deadlineStr, nowJstMinutes){
  if(!deadlineStr) return 1e9;
  const parts = deadlineStr.split(':');
  if(parts.length !== 2) return 1e9;
  const deadlineMinutes = parseInt(parts[0],10)*60 + parseInt(parts[1],10);
  const diff = deadlineMinutes - nowJstMinutes;
  if(diff < -5) return 1e9 + (-diff); // 5分以上過ぎているものは終了扱いで後方へ
  return diff < 0 ? 0 : diff;
}

function getNowJstMinutes(){
  // タイムゾーンに関わらず、日本時間（Asia/Tokyo）の「今」の分を取得する
  const parts = new Intl.DateTimeFormat('ja-JP', {
    timeZone: 'Asia/Tokyo', hour: '2-digit', minute: '2-digit', hour12: false
  }).formatToParts(new Date());
  const h = parseInt(parts.find(p=>p.type==='hour').value, 10);
  const m = parseInt(parts.find(p=>p.type==='minute').value, 10);
  return h*60 + m;
}

window.addEventListener('DOMContentLoaded', function(){
  const tabs = Array.from(document.querySelectorAll('.tab-btn'));
  if(tabs.length === 0) return;
  const nowJstMinutes = getNowJstMinutes();
  let best = tabs[0], bestMins = Infinity;
  tabs.forEach(function(t){
    const mins = minutesUntilDeadline(t.getAttribute('data-deadline'), nowJstMinutes);
    if(mins < bestMins){ bestMins = mins; best = t; }
  });
  best.click();
});
"""


def _minutes_until_deadline(deadline_str, now):
    """
    "HH:MM" 形式の締切時刻と現在時刻(datetime)から、締切までの残り分数を返す。
    すでに締切を過ぎている場合は非常に大きな値を返し、並び替えで後方に回す。
    締切時刻が取得できていない場合も同様に後方に回す。
    """
    if not deadline_str:
        return 10**9
    try:
        h, m = map(int, deadline_str.split(":"))
    except (ValueError, AttributeError):
        return 10**9
    deadline_minutes = h * 60 + m
    now_minutes = now.hour * 60 + now.minute
    diff = deadline_minutes - now_minutes
    if diff < -5:  # 5分以上過ぎているものは「終了」扱いで後方へ
        return 10**9 + (-diff)
    return diff if diff >= 0 else 0


def render_venue_page(venue, races, date, now=None):
    date_str = date.strftime("%Y年%m月%d日")
    venue_name = VENUE_NAMES.get(venue, venue)
    # レース番号順に並べる（「今に一番近いレース」の判定は開いた瞬間にブラウザ側のJSで行う）
    races = sorted(races, key=lambda r: r["race_info"]["race_no"])

    tabs = ""
    panels = ""
    for r in races:
        no = r["race_info"]["race_no"]
        deadline = r["race_info"].get("deadline") or ""
        tab_id = f"race{no}"
        label = f"{no}R" + (f"<br><span class='tab-deadline'>{deadline}</span>" if deadline else "")
        tabs += f'<button class="tab-btn" data-deadline="{deadline}" onclick="showTab(\'{tab_id}\', this)">{label}</button>'
        panels += render_race_card(r, tab_id)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{venue_name}競輪 AI予想 {date_str}</title>
<style>{COMMON_STYLE}{RACE_PANEL_STYLE}</style>
</head>
<body>
<header>
  <div class="top-row">
    <h1>&larr; <a href="../index.html">{venue_name}競輪</a></h1>
    <span class="date">{date_str}</span>
  </div>
</header>
<main>
  <div class="tab-bar">{tabs if tabs else "<p>本日このレース場のデータは取得できませんでした。</p>"}</div>
  {panels}
</main>
<footer>このページはGitHub Actionsにより毎朝自動生成されています。予測はAIモデルによる参考情報であり、的中を保証するものではありません。</footer>
<script>{TAB_SCRIPT}</script>
</body>
</html>"""


def render_index(all_race_data, date=None, now=None):
    import json
    date = date or datetime.date.today()
    weekday_map = {0: "月", 1: "火", 2: "水", 3: "木", 4: "金", 5: "土", 6: "日"}
    date_str = f"{date.strftime('%Y年%m月%d日')}({weekday_map[date.weekday()]})"

    by_venue = {}
    for rd in all_race_data:
        v = rd["race_info"]["venue"]
        by_venue.setdefault(v, []).append(rd)

    # 全レースの (venue, race_no, deadline) をJSに渡し、開いた瞬間に一番近いものを選ばせる
    all_races_json = json.dumps([
        {"venue": rd["race_info"]["venue"], "name": VENUE_NAMES.get(rd["race_info"]["venue"], rd["race_info"]["venue"]),
         "race_no": rd["race_info"]["race_no"], "deadline": rd["race_info"].get("deadline")}
        for rd in all_race_data if rd["race_info"].get("deadline")
    ], ensure_ascii=False)

    def venue_card(slug):
        name = VENUE_NAMES.get(slug, slug)
        races = by_venue.get(slug)
        if not races:
            return f'<div class="venue-card inactive"><span class="vname">{name}</span></div>'

        races_sorted = sorted(races, key=lambda r: r["race_info"]["race_no"])
        races_json = json.dumps([
            {"race_no": r["race_info"]["race_no"], "deadline": r["race_info"].get("deadline")}
            for r in races_sorted
        ], ensure_ascii=False)
        races_json_attr = races_json.replace('"', "&quot;")
        return f"""
        <a class="venue-card active" href="{slug}/index.html" data-races="{races_json_attr}">
          <span class="vname">{name}</span>
          <span class="meta next-race-meta">…</span>
        </a>"""

    rows_html = ""
    for row in VENUE_GRID:
        rows_html += '<div class="venue-row">' + "".join(venue_card(v) for v in row) + '</div>'

    index_script = """
    function minutesUntilDeadline(deadlineStr, nowJstMinutes){
      if(!deadlineStr) return 1e9;
      const parts = deadlineStr.split(':');
      if(parts.length !== 2) return 1e9;
      const deadlineMinutes = parseInt(parts[0],10)*60 + parseInt(parts[1],10);
      const diff = deadlineMinutes - nowJstMinutes;
      if(diff < -5) return 1e9 + (-diff);
      return diff < 0 ? 0 : diff;
    }
    function getNowJstMinutes(){
      const parts = new Intl.DateTimeFormat('ja-JP', {
        timeZone: 'Asia/Tokyo', hour: '2-digit', minute: '2-digit', hour12: false
      }).formatToParts(new Date());
      const h = parseInt(parts.find(p=>p.type==='hour').value, 10);
      const m = parseInt(parts.find(p=>p.type==='minute').value, 10);
      return h*60 + m;
    }
    window.addEventListener('DOMContentLoaded', function(){
      const races = ALL_RACES_DATA;
      const nowJstMinutes = getNowJstMinutes();

      // 「まもなく締切のレース」一覧（1件だけだと直前すぎて買えないことがあるため、近い順に複数件表示する）
      const box = document.getElementById('upcomingListBox');
      if(races.length && box){
        const withMins = races.map(function(r){
          return {r: r, mins: minutesUntilDeadline(r.deadline, nowJstMinutes)};
        });
        withMins.sort(function(a,b){ return a.mins - b.mins; });
        const upcoming = withMins.filter(function(x){ return x.mins < 1e9; }).slice(0, 8);
        if(upcoming.length){
          let html = '<h2 class="section">まもなく締切のレース</h2><div class="upcoming-list">';
          upcoming.forEach(function(x, idx){
            const r = x.r;
            const soon = x.mins <= 5 ? ' soon' : '';
            html += '<a class="upcoming-row' + soon + '" href="' + r.venue + '/index.html">' +
              '<span class="up-rank">' + (idx+1) + '</span>' +
              '<span class="up-name">' + r.name + '競輪 ' + r.race_no + 'R</span>' +
              '<span class="up-time">' + r.deadline + '（あと約' + x.mins + '分）</span></a>';
          });
          html += '</div>';
          box.innerHTML = html;
        }
      }

      // 各競輪場カードの「次走」表示（現在時刻に一番近いレース番号・締切）
      document.querySelectorAll('.venue-card[data-races]').forEach(function(card){
        let venueRaces;
        try { venueRaces = JSON.parse(card.getAttribute('data-races')); } catch(e){ venueRaces = []; }
        const metaEl = card.querySelector('.next-race-meta');
        if(!metaEl) return;
        let best = null, bestMins = Infinity;
        venueRaces.forEach(function(r){
          const mins = minutesUntilDeadline(r.deadline, nowJstMinutes);
          if(mins < bestMins){ bestMins = mins; best = r; }
        });
        if(!best){ metaEl.textContent = venueRaces.length + 'レース'; return; }
        if(bestMins >= 1e9){
          metaEl.textContent = '本日終了';
        } else {
          metaEl.textContent = '次走 ' + best.race_no + 'R（' + (best.deadline || '') + '）';
        }
      });
    });
    """.replace("ALL_RACES_DATA", all_races_json)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>競輪AI予想 {date_str}</title>
<style>
{COMMON_STYLE}
  main{{ max-width:900px; margin:0 auto; padding:16px 10px 60px; }}
  h2.section{{ font-size:14px; color:var(--ink-soft); margin:0 0 10px; }}
  .venue-row{{ display:grid; grid-template-columns:repeat(4,1fr); gap:8px; margin-bottom:8px; }}
  .venue-card{{ border-radius:8px; padding:14px 10px; min-height:64px; display:flex; flex-direction:column; justify-content:center; gap:4px; }}
  .venue-card.active{{ background:#fff; border:1px solid var(--border); box-shadow:0 1px 3px rgba(0,0,0,.06); }}
  .venue-card.active .vname{{ font-weight:800; font-size:14px; color:var(--ink); }}
  .venue-card.active .meta{{ font-size:11px; color:var(--ink-soft); }}
  .venue-card.inactive{{ background:#eee9dd; opacity:.55; }}
  .venue-card.inactive .vname{{ font-size:13px; color:#9a9488; }}
  .venue-card.active .meta.next-race-meta{{ font-size:11px; color:#b5482f; font-weight:700; }}
  .upcoming-list{{ display:flex; flex-direction:column; gap:6px; margin-bottom:20px; }}
  .upcoming-row{{ display:flex; align-items:center; gap:10px; background:#fff; border:1px solid var(--border);
                  border-radius:8px; padding:9px 12px; font-size:13px; }}
  .upcoming-row.soon{{ background:linear-gradient(135deg,#fff4de,#fbe9c9); border-color:var(--gold); }}
  .up-rank{{ display:inline-flex; align-items:center; justify-content:center; width:20px; height:20px; border-radius:50%;
             background:var(--navy); color:#fff; font-size:11px; font-weight:700; flex:0 0 auto; }}
  .up-name{{ font-weight:700; color:var(--ink); flex:1; }}
  .up-time{{ font-size:12px; color:#8a5a12; font-weight:700; white-space:nowrap; }}
  @media (max-width:520px){{ .venue-row{{ grid-template-columns:repeat(2,1fr); }} }}
</style>
</head>
<body>
<header>
  <div class="top-row">
    <h1>競輪AI予想</h1>
    <span class="date">{date_str}</span>
  </div>
  <p class="tagline">今日、どこで、どの目を買うか。</p>
</header>
<main>
  <div id="upcomingListBox"></div>
  <h2 class="section">本日の開催場</h2>
  {rows_html if by_venue else "<p style='text-align:center;color:#5b6472;'>本日は取得できたレースがありませんでした。</p>"}
</main>
<footer>このページはGitHub Actionsにより毎朝自動生成されています。予測はAIモデルによる参考情報であり、的中を保証するものではありません。</footer>
<script>{index_script}</script>
</body>
</html>"""
