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
from venue_data import VENUE_BANK_DATA, bank_class, straight_tendency, kimarite_venue_average

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
    7: ("#e07a1f", "#ffffff"), 8: ("#e2699a", "#ffffff"), 9: ("#8a5fb0", "#ffffff"),
}
KIMARITE_COLORS = {"逃": "#c1443b", "捲": "#e07a1f", "差": "#1f5fc4", "マ": "#2f8f4e"}

COMMON_STYLE = """
  :root{
    --board:#0f2018; --board2:#1a3226; --paper:#faf6ec; --paper2:#f1ead4;
    --ink:#182420; --ink-soft:#5c6b60; --line:#ddd2ae; --gold:#c69a4e;
    --pine:#2f6b4f; --brick:#a8402f; --slate:#3a6486;
    /* 旧変数名のエイリアス（既存CSSルールとの互換性維持のため） */
    --navy:var(--board); --navy2:var(--board2); --border:var(--line);
  }
  *{box-sizing:border-box;}
  html{ -webkit-text-size-adjust:100%; }
  body{ margin:0; background:var(--paper); color:var(--ink); font-family:"Hiragino Sans","Yu Gothic",sans-serif; }
  .num{ font-variant-numeric:tabular-nums; font-feature-settings:"tnum" 1; }
  header{ background:linear-gradient(155deg,var(--board),var(--board2)); color:#fff; padding:20px 18px 0; }
  header .top-row{ display:flex; justify-content:space-between; align-items:baseline; flex-wrap:wrap; gap:8px; }
  header h1{ margin:0; font-size:20px; font-family:"Hiragino Mincho ProN","Yu Mincho",serif; font-weight:600; letter-spacing:.02em; }
  header h1 a{ border-bottom:1px solid rgba(255,255,255,.35); padding-bottom:1px; }
  header .date{ color:var(--gold); font-size:12.5px; font-family:"Hiragino Mincho ProN","Yu Mincho",serif; }
  header p{ margin:7px 0 0; color:#bcc9bf; font-size:12.5px; }
  header p.tagline{ color:#a9bcae; }
  header nav.top-nav{ margin-top:6px; }
  header nav.top-nav a{ font-size:12px; color:#cdd9ce; border-bottom:1px solid rgba(255,255,255,.3); }
  .gate-stripe{ display:flex; height:5px; margin-top:16px; }
  .gate-stripe span{ flex:1; }
  a{ color:inherit; text-decoration:none; }
  footer{ text-align:center; color:var(--ink-soft); font-size:11px; padding:26px 14px 30px; line-height:1.7; }
"""

GATE_STRIPE_CAR_ORDER = [1, 2, 3, 4, 5, 6, 7, 8, 9]


def gate_stripe_html():
    """9車の公式カラーを並べた帯。競輪の発走ゲートの並びをモチーフにした共通の装飾要素。"""
    bars = "".join(f'<span style="background:{car_color(c)[0]};"></span>' for c in GATE_STRIPE_CAR_ORDER)
    return f'<div class="gate-stripe">{bars}</div>'


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
      <line x1="0" y1="{plot_h+10:.1f}" x2="{width}" y2="{plot_h+10:.1f}" stroke="var(--line)" stroke-width="1"/>
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


def svg_track_diagram(circumference, literal_straight, center_cant, width=360, height=260):
    """
    競輪場のコースレイアウト概略図（スタジアム形＝直線+半円のトラック）。
    周長（333/400/500）に応じて直線部分の長さを変え、実際の規模差を反映する。
    コーナー半径は固定にすることで、どのクラスでもラベルがviewBox内に収まるようにしている。
    数値の正確なジオメトリ図ではなく、相対的な形の違いを伝える模式図。
    """
    bclass = bank_class(circumference)
    # 周長クラスごとの直線部分の長さ（333は小回りで直線が短く、500は大回りで直線が長い）
    straight_lengths = {"333": 46, "400": 78, "500": 118}
    straight_len = straight_lengths.get(bclass, straight_lengths["400"])
    r = 62  # コーナー半径（固定。これによりどのクラスでも縦方向のレイアウトが揃う）

    cx, cy = width / 2, height / 2 - 4
    x_left = cx - straight_len / 2
    x_right = cx + straight_len / 2
    y_top = cy - r
    y_bottom = cy + r

    outer_path = (
        f"M{x_left:.1f},{y_top:.1f} "
        f"L{x_right:.1f},{y_top:.1f} "
        f"A{r:.1f},{r:.1f} 0 0 1 {x_right:.1f},{y_bottom:.1f} "
        f"L{x_left:.1f},{y_bottom:.1f} "
        f"A{r:.1f},{r:.1f} 0 0 1 {x_left:.1f},{y_top:.1f} Z"
    )
    inner_r = r * 0.66
    ix_left, ix_right = cx - straight_len / 2, cx + straight_len / 2
    iy_top, iy_bottom = cy - inner_r, cy + inner_r
    inner_path = (
        f"M{ix_left:.1f},{iy_top:.1f} "
        f"L{ix_right:.1f},{iy_top:.1f} "
        f"A{inner_r:.1f},{inner_r:.1f} 0 0 1 {ix_right:.1f},{iy_bottom:.1f} "
        f"L{ix_left:.1f},{iy_bottom:.1f} "
        f"A{inner_r:.1f},{inner_r:.1f} 0 0 1 {ix_left:.1f},{iy_top:.1f} Z"
    )

    straight_label = f"みなし直線 {literal_straight}m" if literal_straight is not None else ""
    cant_label = f"カント {center_cant}" if center_cant else ""

    return f"""<svg viewBox="0 0 {width} {height}" width="100%" style="max-width:{width}px; display:block; margin:0 auto;">
      <path d="{outer_path}" fill="none" stroke="#0e1b2b" stroke-width="14" stroke-linejoin="round"/>
      <path d="{outer_path}" fill="#f6f3ec" stroke="var(--gold)" stroke-width="1.5" stroke-linejoin="round"/>
      <path d="{inner_path}" fill="none" stroke="#b8ab8a" stroke-width="1" stroke-dasharray="3,3"/>
      <line x1="{x_right - 6:.1f}" y1="{y_top+7:.1f}" x2="{x_right - 6:.1f}" y2="{y_bottom-7:.1f}" stroke="var(--brick)" stroke-width="2"/>
      <text x="{cx:.1f}" y="{y_top - 16:.1f}" font-size="14" text-anchor="middle" fill="#0e1b2b" font-weight="700">1周 {circumference or '—'}</text>
      <text x="{cx:.1f}" y="{y_bottom + 24:.1f}" font-size="11" text-anchor="middle" fill="var(--ink-soft)">{straight_label}</text>
      <text x="{cx:.1f}" y="{y_bottom + 40:.1f}" font-size="10" text-anchor="middle" fill="#8a9099">{cant_label}</text>
      <text x="{x_right - 6:.1f}" y="{y_top - 2:.1f}" font-size="9.5" text-anchor="end" fill="var(--brick)">ゴール</text>
    </svg>"""


def render_kimarite_table(kimarite_ratio, venue_slug=None):
    venue_avg = kimarite_venue_average(venue_slug) if venue_slug else None
    venue_name = VENUE_NAMES.get(venue_slug, venue_slug) if venue_slug else ""

    cells = "".join(f"<th>{KIMARITE_LABELS[t]}</th>" for t in KIMARITE)
    vals = ""
    for t in KIMARITE:
        v = kimarite_ratio.get(t, 0)
        delta_html = ""
        if venue_avg and t in venue_avg:
            diff = v - venue_avg[t]
            if abs(diff) >= 0.1:
                arrow = "↑" if diff > 0 else "↓"
                cls = "delta-up" if diff > 0 else "delta-down"
                delta_html = f'<br><span class="{cls}">{abs(diff):.1f}%{arrow}</span>'
        vals += f"<td>{v:.1f}%{delta_html}</td>"

    avg_note = ""
    if venue_avg:
        avg_note = (f"<p class='dim' style='margin:4px 0 0;'>矢印は{venue_name}競輪の場平均"
                     f"（1着・A級7車ベース、<a href='bank.html'>詳細</a>）との差分です。</p>")
    else:
        avg_note = "<p class='dim' style='margin:4px 0 0;'>この競輪場の場平均データはまだありません。</p>"

    return f"""
    <table class="main kimarite-table"><thead><tr>{cells}</tr></thead><tbody><tr>{vals}</tr></tbody></table>
    <p class="dim" style="margin:6px 0 0;">各号車の「予測決まり手」の確率分布を合計した構成比です。過去の実績そのままではなく、ライン位置なども加味した今回のレースの予測値です。</p>
    {avg_note}"""


import json as _json


def build_matrix_payload(racers, second_place_matrix, full_third_place_data, top_car):
    """タップ式ウィジェット用に、1着→2着→3着の確率データを全組み合わせ分JSON化する。"""
    by_car = sorted(racers, key=lambda r: r["car"])
    name_by_car = {r["car"]: r["name"] for r in by_car}

    def entry(car, name, prob):
        bg, fg = car_color(car)
        return {"car": car, "name": name, "prob": round(prob, 1), "bg": bg, "fg": fg}

    data = {}
    for r in by_car:
        car = r["car"]
        second_list = [entry(c["car"], name_by_car.get(c["car"], ""), c["prob"])
                       for c in second_place_matrix.get(car, [])]
        third_by_second = {
            str(second_car): [entry(c["car"], name_by_car.get(c["car"], ""), c["prob"]) for c in candidates]
            for second_car, candidates in full_third_place_data.get(car, {}).items()
        }
        default_second = second_list[0]["car"] if second_list else None
        data[str(car)] = {"second": second_list, "third_by_second": third_by_second, "default_second": default_second}

    cars_meta = [{"car": r["car"], **dict(zip(("bg", "fg"), car_color(r["car"])))} for r in by_car]
    return {"default": top_car, "cars": cars_meta, "data": data}


def render_matrix_widget(tab_id, payload):
    payload_json = _json.dumps(payload, ensure_ascii=False)
    return f"""
    <div class="mw" data-tab="{tab_id}">
      <div class="mw-label">1着候補を選ぶ</div>
      <div class="mw-chips" id="{tab_id}_chips1"></div>
      <div class="mw-label">2着候補を選ぶ</div>
      <div class="mw-bars mw-tappable" id="{tab_id}_bars2"></div>
      <div class="mw-label" id="{tab_id}_label3"></div>
      <div class="mw-bars" id="{tab_id}_bars3"></div>
    </div>
    <p class="dim" style="margin:8px 0 0;">号車をタップすると1着・2着の組み合わせを切り替えられ、3着候補もその組み合わせに応じて連動します。</p>
    <script>window.MATRIX_DATA=window.MATRIX_DATA||{{}}; window.MATRIX_DATA["{tab_id}"]={payload_json};</script>"""


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
          <td>{r.get('place_rate', 0):.1f}%</td>
        </tr>"""

    banner_html = ""
    if high_prob:
        banner_html = (f'<div class="banner-high">{top["car"]}号車 {top["name"]} が本命'
                        f'（予測1着率 {top["adjusted"]:.1f}%）</div>')

    bar_chart = svg_bar_chart(result["rows"])
    line_info_html = render_line_info_block(result, title)
    kimarite_table_html = render_kimarite_table(result["kimarite_ratio"], info.get("venue"))
    matrix_payload = build_matrix_payload(result["rows"], result["second_place_matrix"], result["full_third_place_data"], top["car"])
    matrix_widget_html = render_matrix_widget(tab_id, matrix_payload)

    deadline = info.get("deadline")
    deadline_html = f'<span class="deadline">締切 {deadline}</span>' if deadline else ""
    pick_color = car_color(top["car"])[0]
    return f"""
    <div id="{tab_id}" class="race-panel" style="display:none;">
      <div class="race-card" style="--pick-color:{pick_color};">
        <div class="race-head">
          <span class="raceno">{info['race_no']}R</span>
          <span class="title">{title}</span>
          {deadline_html}
        </div>
        {banner_html}
        {line_info_html}
        <table class="main">
          <thead><tr><th>号車</th><th>選手</th><th>級班</th><th>予測決まり手</th><th>ライン</th><th>予測1着率</th><th>信頼度</th><th>予測3着内率</th></tr></thead>
          <tbody>{rows_html}</tbody>
        </table>
        <p class="dim" style="margin:6px 0 0;">予測決まり手のカッコ内は確信度、信頼度は直近の走行数と連対率から算出した安定感の指標です。</p>

        <div class="chart-block">
          {bar_chart}
          <p class="dim" style="margin:8px 0 0; text-align:center;">号車別の予測1着率です。</p>
        </div>

        <div class="chart-block">{kimarite_table_html}</div>
        <div class="chart-block">{matrix_widget_html}</div>
      </div>
    </div>"""


RACE_PANEL_STYLE = """
  main{ max-width:720px; margin:0 auto; padding:16px 10px 60px; }
  .tab-bar{ display:flex; gap:6px; overflow-x:auto; padding:14px 2px 14px; -webkit-overflow-scrolling:touch; }
  .tab-btn{ flex:0 0 auto; background:var(--paper); border:1px solid var(--line); border-radius:3px; padding:7px 13px;
            font-size:13px; font-weight:600; cursor:pointer; color:var(--ink); text-align:center; }
  .tab-btn .tab-deadline{ font-size:10px; font-weight:400; color:var(--ink-soft); }
  .tab-btn.active .tab-deadline{ color:#cfe0d5; }
  .tab-btn.active{ background:var(--board); color:#fff; border-color:var(--board); }
  .race-card{ background:var(--paper); border:1px solid var(--line); border-top:3px solid var(--pick-color,var(--board));
              border-radius:2px; padding:16px; }
  .race-head{ display:flex; gap:10px; align-items:baseline; margin-bottom:10px; flex-wrap:wrap; }
  .race-head .raceno{ font-family:"Hiragino Mincho ProN","Yu Mincho",serif; font-size:17px; color:var(--board); }
  .race-head .title{ color:var(--ink-soft); font-size:12.5px; }
  .race-head .deadline{ margin-left:auto; background:var(--paper2); border-radius:3px; padding:2px 9px; font-size:12px; color:var(--ink); font-weight:600; }
  .banner-high{ background:linear-gradient(120deg,#fbf1de,#f5e5c2); border:1px solid var(--gold); border-radius:3px;
                padding:9px 11px; font-size:13.5px; margin-bottom:10px; }
  .banner-normal{ background:var(--paper2); border-radius:3px; padding:9px 11px; font-size:13.5px; margin-bottom:10px; color:var(--ink-soft); }
  .note{ font-size:12px; color:var(--brick); margin:4px 0; }
  table.main{ width:100%; border-collapse:collapse; font-size:12px; }
  table.main th{ background:var(--board); color:#e9ecea; font-weight:500; padding:6px 4px; border-bottom:2px solid var(--gold); }
  table.main td{ padding:6px 4px; text-align:center; border-bottom:1px solid var(--line); }
  table.main tbody tr:nth-child(even){ background:rgba(198,154,78,.06); }
  .dim{ color:var(--ink-soft); font-size:10px; }
  .car{ display:inline-flex; align-items:center; justify-content:center; width:21px; height:21px; border-radius:50%;
        font-size:11px; font-weight:700; border:1px solid rgba(0,0,0,.18); }
  .sub-wrap{ display:flex; gap:16px; margin-top:10px; flex-wrap:wrap; }
  .sub-wrap h4{ font-size:12px; margin:0 0 4px; color:var(--ink-soft); font-weight:600; }
  table.sub{ font-size:12px; border-collapse:collapse; }
  table.sub td{ padding:2px 8px 2px 0; }
  .chart-block{ margin-top:18px; border-top:1px solid var(--line); padding-top:14px; }
  .chart-block h4{ font-size:12.5px; color:var(--ink-soft); margin:0 0 10px; text-align:center; font-weight:600; }
  .kimarite-table th, .kimarite-table td{ text-align:center; }
  .kimarite-table td{ font-family:ui-monospace,"SF Mono",Menlo,monospace; }
  .delta-up{ color:var(--brick); font-size:11px; font-weight:700; }
  .delta-down{ color:var(--slate); font-size:11px; font-weight:700; }
  .mw-label{ font-size:12px; color:var(--ink-soft); margin:14px 0 8px; font-weight:600; }
  .mw-label:first-child{ margin-top:0; }
  .mw-chips{ display:flex; gap:6px; flex-wrap:wrap; }
  .mw-chip{ width:34px; height:34px; border-radius:50%; border:2px solid var(--line); background:var(--paper);
            font-size:14px; font-weight:700; color:var(--ink); cursor:pointer; }
  .mw-chip.active{ border-color:transparent; box-shadow:0 0 0 2px var(--board); }
  .mw-bar-row{ display:flex; align-items:center; gap:8px; padding:5px 0; }
  .mw-bar-row-tap{ cursor:pointer; border-radius:4px; padding:5px 4px; margin:0 -4px; }
  .mw-bar-row-tap.active{ background:rgba(198,154,78,.16); }
  .mw-bar-row-tap:not(.active) .mw-bar-fill{ opacity:.55; }
  .mw-bar-name{ font-size:12px; color:var(--ink); flex:0 0 auto; width:64px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .mw-bar-track{ flex:1; height:9px; background:var(--paper2); border-radius:5px; overflow:hidden; }
  .mw-bar-fill{ display:block; height:100%; background:linear-gradient(90deg,var(--pine),#4c8a68); border-radius:5px; }
  .mw-bar-val{ flex:0 0 auto; width:30px; text-align:right; font-size:13px; font-weight:700; color:var(--pine); }
  .line-info-block{ font-size:12px; border-radius:3px; padding:10px 11px; margin:10px 0; display:flex; flex-wrap:wrap; gap:12px; align-items:center; }
  .line-info-block.ok{ background:#eef4ec; border:1px solid #c7dcc0; }
  .line-info-block.warn{ background:var(--paper2); color:#8a5a12; border:1px solid #e0cfa0; }
  .line-group{ display:inline-flex; align-items:center; gap:3px; }
  .line-arrow{ color:var(--ink-soft); font-size:11px; }
  @media (max-width:420px){
    table.main{ font-size:10.5px; }
    table.main th, table.main td{ padding:4px 3px; }
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

// タップ式の2着・3着ウィジェット（表4・表5の代わり）
function barRowHtml(c, tappable, onclickAttr){
  const pct = Math.min(Math.max(c.prob, 2), 100);
  const activeCls = c.active ? ' active' : '';
  const clickAttr = tappable ? ' onclick="'+onclickAttr+'"' : '';
  return '<div class="mw-bar-row'+(tappable?' mw-bar-row-tap':'')+activeCls+'"'+clickAttr+'>' +
    '<span class="car" style="background:'+c.bg+';color:'+c.fg+';">'+c.car+'</span>' +
    '<span class="mw-bar-name">'+c.name+'</span>' +
    '<span class="mw-bar-track"><span class="mw-bar-fill" style="width:'+pct+'%;"></span></span>' +
    '<span class="mw-bar-val num">'+c.prob.toFixed(0)+'</span>' +
  '</div>';
}
function renderMatrixWidget(tabId){
  const payload = window.MATRIX_DATA && window.MATRIX_DATA[tabId];
  if(!payload) return;
  const car = payload.selected || payload.default;
  const chipsEl = document.getElementById(tabId+'_chips1');
  if(!chipsEl) return;
  chipsEl.innerHTML = payload.cars.map(function(c){
    const isActive = c.car === car;
    const bg = isActive ? c.bg : 'transparent';
    const fg = isActive ? c.fg : 'inherit';
    return '<button type="button" class="mw-chip'+(isActive?' active':'')+'" ' +
      'style="background:'+bg+';color:'+fg+';border-color:'+c.bg+';" ' +
      'onclick="selectMatrixFirst(\\''+tabId+'\\','+c.car+')">'+c.car+'</button>';
  }).join('');
  const data = payload.data[String(car)] || {second:[], third_by_second:{}};
  const secondCar = payload.selectedSecond && payload.selectedSecond[car] ? payload.selectedSecond[car] : data.default_second;
  const bars2El = document.getElementById(tabId+'_bars2');
  bars2El.innerHTML = data.second.length ? data.second.map(function(c2){
    const marked = Object.assign({}, c2, {active: c2.car === secondCar});
    return barRowHtml(marked, true, 'selectMatrixSecond(\\''+tabId+'\\','+car+','+c2.car+')');
  }).join('') : '<p class="dim">データがありません</p>';

  const label3El = document.getElementById(tabId+'_label3');
  const bars3El = document.getElementById(tabId+'_bars3');
  const thirdList = secondCar ? (data.third_by_second[String(secondCar)] || []) : [];
  if(secondCar){
    label3El.textContent = car+'→'+secondCar+'のとき3着に来るのは';
    bars3El.innerHTML = thirdList.length ? thirdList.map(function(c3){ return barRowHtml(c3, false); }).join('') : '<p class="dim">データがありません</p>';
  } else {
    label3El.textContent = '';
    bars3El.innerHTML = '';
  }
}
function selectMatrixFirst(tabId, car){
  window.MATRIX_DATA[tabId].selected = car;
  renderMatrixWidget(tabId);
}
function selectMatrixSecond(tabId, firstCar, secondCar){
  const payload = window.MATRIX_DATA[tabId];
  payload.selectedSecond = payload.selectedSecond || {};
  payload.selectedSecond[firstCar] = secondCar;
  renderMatrixWidget(tabId);
}

window.addEventListener('DOMContentLoaded', function(){
  const tabs = Array.from(document.querySelectorAll('.tab-btn'));
  if(window.MATRIX_DATA){
    Object.keys(window.MATRIX_DATA).forEach(renderMatrixWidget);
  }
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
  {gate_stripe_html()}
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
  <nav class="top-nav"><a href="venues.html">全競輪場データ &rarr;</a></nav>
  {gate_stripe_html()}
</header>
<main>
  <div id="upcomingListBox"></div>
  <h2 class="section">本日の開催場</h2>
  {rows_html if by_venue else "<p style='text-align:center;color:var(--ink-soft);'>本日は取得できたレースがありませんでした。</p>"}
</main>
<footer>このページはGitHub Actionsにより毎朝自動生成されています。予測はAIモデルによる参考情報であり、的中を保証するものではありません。</footer>
<script>{index_script}</script>
</body>
</html>"""


def render_venues_page(date=None):
    date = date or datetime.date.today()
    weekday_map = {0: "月", 1: "火", 2: "水", 3: "木", 4: "金", 5: "土", 6: "日"}
    date_str = f"{date.strftime('%Y年%m月%d日')}({weekday_map[date.weekday()]})"

    def fmt(v, unit=""):
        return f"{v}{unit}" if v is not None else "—"

    rows_html = ""
    for slug, name in VENUE_NAMES.items():
        d = VENUE_BANK_DATA.get(slug, {})
        bclass = bank_class(d.get("circumference"))
        tendency = straight_tendency(d.get("literal_straight"))
        bclass_badge = f'<span class="bclass-badge bclass-{bclass}">{bclass}</span>' if bclass else ""
        tendency_badge = f'<span class="tendency-badge">{tendency}</span>' if tendency else ""
        note = d.get("note")

        if note:
            rows_html += f"""
            <tr>
              <td class="vname-cell">{name}</td>
              <td colspan="9" class="dim">{note}</td>
            </tr>"""
            continue

        rows_html += f"""
        <tr>
          <td class="vname-cell"><a href="{slug}/bank.html">{name}</a> {bclass_badge}</td>
          <td>{fmt(d.get('literal_straight'), 'm')} {tendency_badge}</td>
          <td>{fmt(d.get('center_cant'))}</td>
          <td>{fmt(d.get('straight_cant'))}</td>
          <td>{fmt(d.get('home_width'), 'm')}</td>
          <td>{fmt(d.get('back_width'), 'm')}</td>
          <td>{fmt(d.get('center_width'), 'm')}</td>
          <td>{fmt(d.get('record_time'))}<br><span class="dim">{fmt(d.get('record_holder'))}</span></td>
          <td>{fmt(d.get('nige_1st'), '%')}</td>
          <td>{fmt(d.get('sashi_1st'), '%')}</td>
          <td>{fmt(d.get('makuri_1st'), '%')}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>全競輪場データ | 競輪AI予想</title>
<style>
{COMMON_STYLE}
  main{{ max-width:1100px; margin:0 auto; padding:16px 10px 60px; }}
  h2.section{{ font-size:14px; color:var(--ink-soft); margin:18px 0 10px; }}
  .table-scroll{{ overflow-x:auto; }}
  table.venues{{ width:100%; border-collapse:collapse; font-size:12px; background:#fff; }}
  table.venues th, table.venues td{{ border:1px solid var(--border); padding:6px 8px; text-align:center; white-space:nowrap; }}
  table.venues td.vname-cell a{{ color:var(--navy); text-decoration:underline; }}
  table.venues th{{ background:var(--paper2); position:sticky; top:0; }}
  table.venues td.vname-cell, table.venues th:first-child{{ text-align:left; white-space:nowrap; font-weight:700; }}
  .bclass-badge{{ display:inline-block; border-radius:4px; padding:0 5px; font-size:10px; font-weight:700; margin-left:4px; }}
  .bclass-333{{ background:#e3f0ff; color:var(--slate); }}
  .bclass-400{{ background:var(--paper2); color:var(--ink-soft); }}
  .bclass-500{{ background:#fde3e3; color:var(--brick); }}
  .tendency-badge{{ display:block; font-size:9.5px; color:var(--ink-soft); font-weight:400; margin-top:1px; white-space:nowrap; }}
  .dim{{ color:var(--ink-soft); font-size:10.5px; }}
  .legend{{ background:#f7f5ee; border:1px dashed var(--border); border-radius:8px; padding:10px 12px; font-size:12px; color:var(--ink-soft); margin-bottom:14px; }}
</style>
</head>
<body>
<header>
  <div class="top-row">
    <h1>&larr; <a href="index.html">全競輪場データ</a></h1>
    <span class="date">{date_str}</span>
  </div>
  <p class="tagline">全国43場のバンク特性を1枚で。</p>
  {gate_stripe_html()}
</header>
<main>
  <div class="legend">
    周長バッジ：<span class="bclass-badge bclass-333">333</span>は小回り・先行有利の傾向、
    <span class="bclass-badge bclass-500">500</span>は大回り・差し有利の傾向、
    <span class="bclass-badge bclass-400">400</span>はその中間（全国で最も多い標準的なバンク）です。
    決まり手出現率はA級7車・2021〜2025年の集計（参考値）。
  </div>
  <div class="table-scroll">
    <table class="venues">
      <thead>
        <tr>
          <th>競輪場</th><th>みなし直線</th><th>センターカント</th><th>直線カント</th>
          <th>ホーム幅員</th><th>バック幅員</th><th>センター幅員</th><th>バンクレコード</th>
          <th>逃げ1着率</th><th>差し1着率</th><th>捲り1着率</th>
        </tr>
      </thead>
      <tbody>{rows_html}</tbody>
    </table>
  </div>
</main>
<footer>データ出典：keirin-brother.com「競輪場のバンクの特徴」（元データ: KEIRIN.JP）、決まり手出現率は競輪CLUBデータ分析。物理的な施設特性のため、更新頻度は低いです。</footer>
</body>
</html>"""


def render_venue_bank_page(slug, date=None):
    date = date or datetime.date.today()
    weekday_map = {0: "月", 1: "火", 2: "水", 3: "木", 4: "金", 5: "土", 6: "日"}
    date_str = f"{date.strftime('%Y年%m月%d日')}({weekday_map[date.weekday()]})"
    name = VENUE_NAMES.get(slug, slug)
    d = VENUE_BANK_DATA.get(slug, {})

    if d.get("note"):
        body = f'<p class="dim" style="text-align:center;padding:30px 10px;">{d["note"]}</p>'
        return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{name}競輪 データ | 競輪AI予想</title><style>{COMMON_STYLE}</style></head>
<body><header><div class="top-row"><h1>&larr; <a href="../venues.html">{name}競輪</a></h1></div></header>
<main style="max-width:700px;margin:0 auto;padding:16px 10px;">{body}</main></body></html>"""

    bclass = bank_class(d.get("circumference"))
    tendency = straight_tendency(d.get("literal_straight"))
    track_svg = svg_track_diagram(d.get("circumference"), d.get("literal_straight"), d.get("center_cant"))

    avg1 = kimarite_venue_average(slug) or {}
    kimarite_1st_table = ""
    if avg1:
        cells = "".join(f"<th>{KIMARITE_LABELS[t]}</th>" for t in KIMARITE)
        vals = "".join(f"<td>{avg1.get(t,0):.1f}%</td>" for t in KIMARITE)
        kimarite_1st_table = f"""
        <table class="main"><thead><tr>{cells}</tr></thead><tbody><tr>{vals}</tr></tbody></table>"""

    kimarite_2nd_table = ""
    if d.get("nige_2nd") is not None:
        kimarite_2nd_table = f"""
        <table class="main">
          <thead><tr><th>逃げ</th><th>差し</th><th>捲り</th><th>マーク</th></tr></thead>
          <tbody><tr>
            <td>{d.get('nige_2nd',0):.1f}%</td><td>{d.get('sashi_2nd',0):.1f}%</td>
            <td>{d.get('makuri_2nd',0):.1f}%</td><td>{d.get('mark_2nd',0):.1f}%</td>
          </tr></tbody>
        </table>"""

    bclass_badge = f'<span class="bclass-badge bclass-{bclass}">{bclass}バンク</span>' if bclass else ""
    tendency_note = f"<p class='dim' style='margin:4px 0 0;'>みなし直線の傾向：<b>{tendency}</b></p>" if tendency else ""

    def stat_row(label, value):
        return f'<div class="stat-row"><span class="stat-label">{label}</span><span class="stat-value">{value}</span></div>'

    stats_html = "".join([
        stat_row("周長", d.get("circumference") or "—"),
        stat_row("みなし直線", f"{d.get('literal_straight')}m" if d.get("literal_straight") is not None else "—"),
        stat_row("センター部路面傾斜（カント）", d.get("center_cant") or "—"),
        stat_row("直線部路面傾斜", d.get("straight_cant") or "—"),
        stat_row("ホーム幅員", f"{d.get('home_width')}m" if d.get("home_width") is not None else "—"),
        stat_row("バック幅員", f"{d.get('back_width')}m" if d.get("back_width") is not None else "—"),
        stat_row("センター幅員", f"{d.get('center_width')}m" if d.get("center_width") is not None else "—"),
        stat_row("バンクレコード", f"{d.get('record_time')}（{d.get('record_holder')} {d.get('record_date')}）"
                 if d.get("record_time") else "—"),
    ])

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{name}競輪 バンクデータ | 競輪AI予想</title>
<style>
{COMMON_STYLE}{RACE_PANEL_STYLE}
  .stat-row{{ display:flex; justify-content:space-between; padding:7px 4px; border-bottom:1px solid var(--border); font-size:13px; }}
  .stat-row:last-child{{ border-bottom:none; }}
  .stat-label{{ color:var(--ink-soft); }}
  .stat-value{{ font-weight:700; }}
  .track-card{{ background:#fff; border:1px solid var(--border); border-radius:8px; padding:14px; margin-bottom:14px; }}
</style>
</head>
<body>
<header>
  <div class="top-row">
    <h1>&larr; <a href="../venues.html">{name}競輪</a></h1>
    <span class="date">{date_str}</span>
  </div>
  <p class="tagline">{bclass_badge if bclass else ""}</p>
  {gate_stripe_html()}
</header>
<main style="max-width:720px;margin:0 auto;padding:14px 10px 60px;">
  <div class="track-card">
    <h4 style="text-align:center;">コースレイアウト（模式図）</h4>
    {track_svg}
    {tendency_note}
  </div>

  <div class="track-card">
    <h4>バンク基本データ</h4>
    {stats_html}
  </div>

  <div class="track-card">
    <h4>決まり手の場平均（1着・A級7車ベース）</h4>
    <p class="dim" style="margin:0 0 8px;">元データが逃げ・差し・捲りの1着出現率のみのため、マークは残差（100%からの引き算）で算出した参考値です。各レースの「決まり手構成」表では、この場平均との差分を↑↓で表示します。</p>
    {kimarite_1st_table}
  </div>

  <div class="track-card">
    <h4>決まり手の場平均（2着・A級7車ベース）</h4>
    {kimarite_2nd_table if kimarite_2nd_table else "<p class='dim'>データなし</p>"}
  </div>

  <div class="track-card">
    <a href="index.html" style="font-size:13px;">この競輪場の本日のレース予想を見る &rarr;</a>
  </div>
</main>
<footer>データ出典：keirin-brother.com「競輪場のバンクの特徴」（元データ: KEIRIN.JP）、決まり手出現率は競輪CLUBデータ分析。</footer>
</body>
</html>"""
