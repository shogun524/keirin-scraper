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
  body{ margin:0; background:var(--paper); color:var(--ink); font-family:"Hiragino Sans","Hiragino Kaku Gothic ProN","Yu Gothic","Noto Sans JP","Meiryo",sans-serif; }
  .num{ font-variant-numeric:tabular-nums; font-feature-settings:"tnum" 1; }
  header{ background:linear-gradient(155deg,var(--board),var(--board2)); color:#fff; padding:20px 18px 0; }
  header .top-row{ display:flex; justify-content:space-between; align-items:baseline; flex-wrap:wrap; gap:8px; }
  header h1{ margin:0; font-size:20px; font-family:"Hiragino Sans","Hiragino Kaku Gothic ProN","Yu Gothic","Noto Sans JP","Meiryo",sans-serif; font-weight:700; letter-spacing:.02em; }
  header h1 a{ border-bottom:1px solid rgba(255,255,255,.35); padding-bottom:1px; }
  header .date{ color:var(--gold); font-size:12.5px; font-family:"Hiragino Sans","Hiragino Kaku Gothic ProN","Yu Gothic","Noto Sans JP","Meiryo",sans-serif; }
  header p{ margin:7px 0 0; color:#bcc9bf; font-size:12.5px; }
  header p.tagline{ color:#a9bcae; }
  header nav.top-nav{ margin-top:8px; display:flex; flex-wrap:wrap; gap:4px 14px; }
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


KIMARITE_DISPLAY = [t for t in KIMARITE if t != "マ"]  # マーク（マ）は表示から除外


def render_kimarite_table(kimarite_ratio, venue_slug=None):
    venue_avg = kimarite_venue_average(venue_slug) if venue_slug else None
    venue_name = VENUE_NAMES.get(venue_slug, venue_slug) if venue_slug else ""

    cells = "".join(f"<th>{KIMARITE_LABELS[t]}</th>" for t in KIMARITE_DISPLAY)
    vals = ""
    for t in KIMARITE_DISPLAY:
        v = kimarite_ratio.get(t, 0)
        if venue_avg and t in venue_avg:
            diff = v - venue_avg[t]
            if abs(diff) < 0.1:
                cell_html = '<span class="dim">±0.0%</span>'
            else:
                arrow = "↑" if diff > 0 else "↓"
                cls = "delta-up" if diff > 0 else "delta-down"
                cell_html = f'<span class="{cls}">{abs(diff):.1f}%{arrow}</span>'
        else:
            cell_html = '<span class="dim">-</span>'
        vals += f"<td>{cell_html}</td>"

    avg_note = ""
    if venue_avg:
        avg_note = (f"<p class='dim' style='margin:4px 0 0;'>{venue_name}競輪の場平均"
                     f"（1着・A級7車ベース、<a href='bank.html'>詳細</a>）と比べた今回の予測構成比の上昇率／低下率です。</p>")
    else:
        avg_note = "<p class='dim' style='margin:4px 0 0;'>この競輪場の場平均データはまだありません。</p>"

    return f"""
    <table class="main kimarite-table"><thead><tr>{cells}</tr></thead><tbody><tr>{vals}</tr></tbody></table>
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
    <script>window.MATRIX_DATA=window.MATRIX_DATA||{{}}; window.MATRIX_DATA["{tab_id}"]={payload_json};</script>"""


def build_trifecta_payload(trifecta, rows):
    """
    3連単を1着候補（車番）ごとにグループ化し、タップ式ウィジェット用にJSON化する。
    戻り値: {"default": 車番, "cars": [{"car":,"bg":,"fg":,"total":その車が1着の合計確率}, ...],
             "groups": {"車番文字列": [{"second":,"second_name":,"third":,"third_name":,"prob":}, ...]}}
    """
    if not trifecta or not trifecta.get("combos"):
        return None

    groups = {}
    car_totals = {}
    for c in trifecta["combos"]:
        car = c["first"]
        groups.setdefault(str(car), []).append({
            "second": c["second"], "second_name": c["second_name"],
            "third": c["third"], "third_name": c["third_name"],
            "prob": round(c["prob"], 2),
        })
        car_totals[car] = car_totals.get(car, 0) + c["prob"]

    for lst in groups.values():
        lst.sort(key=lambda x: -x["prob"])

    cars_meta = []
    for car in sorted(car_totals, key=lambda c: -car_totals[c]):
        bg, fg = car_color(car)
        cars_meta.append({"car": car, "bg": bg, "fg": fg, "total": round(car_totals[car], 1)})

    default_car = cars_meta[0]["car"] if cars_meta else None
    return {"default": default_car, "cars": cars_meta, "groups": groups}


def render_trifecta_groups(tab_id, payload):
    """1着候補（車番）をタップすると、その車が1着になる買い目上位を表示する。"""
    if not payload:
        return ""
    payload_json = _json.dumps(payload, ensure_ascii=False)
    return f"""
    <div class="mw-chips" id="{tab_id}_tf_chips"></div>
    <div class="tf-list" id="{tab_id}_tf_list"></div>
    <script>window.TRIFECTA_DATA=window.TRIFECTA_DATA||{{}}; window.TRIFECTA_DATA["{tab_id}"]={payload_json};</script>"""


def render_odds_trend_block(info):
    """
    投票の盛り上がり（発売票数の伸び）を表示する。十分なスナップショットが
    蓄積されるまでは何も表示しない（1〜2回の実行だけでは「動き」とは言えないため）。
    """
    trend = info.get("odds_trend")
    if not trend or trend.get("snapshot_count", 0) < 2:
        return ""
    growth = trend["growth_pct"]
    if growth >= 15:
        arrow, cls = "↑↑", "delta-up"
    elif growth >= 3:
        arrow, cls = "↑", "delta-up"
    elif growth <= -3:
        arrow, cls = "↓", "delta-down"
    else:
        arrow, cls = "→", "dim"
    return (f'<p class="dim" style="margin:2px 0 0;">投票状況: {trend["latest"]:,}票 '
            f'<span class="{cls}">{arrow} 初回計測比 {growth:+.0f}%</span></p>')


def render_form_badge(form_trend):
    """直近の調子（フォーム）バッジ。安定（flat）またはデータ不足なら何も表示しない。"""
    if not form_trend or form_trend.get("trend") == "flat":
        return ""
    arrow = "↑" if form_trend["trend"] == "up" else "↓"
    cls = "delta-up" if form_trend["trend"] == "up" else "delta-down"
    return f'<span class="{cls}" style="font-size:10px;">調子{arrow}</span>'


def render_rivalry_badge(rivalry_summary):
    """対戦相性（選手間の相性）バッジ。五分五分に近い場合や、データ不足なら何も表示しない。"""
    if not rivalry_summary:
        return ""
    rate = rivalry_summary["avg_win_rate"]
    if rate >= 0.6:
        return f'<span class="delta-up" style="font-size:10px;">対戦相性◎({rate*100:.0f}%)</span>'
    if rate <= 0.4:
        return f'<span class="delta-down" style="font-size:10px;">対戦相性△({rate*100:.0f}%)</span>'
    return ""


def render_odds_alert_badge(info):
    """オッズ妙味アラート（投票の伸びが同時間帯の他レースより鈍いレース候補）バッジ。"""
    if not info.get("odds_value_alert"):
        return ""
    return '<span class="value-alert-badge">🔍 妙味候補</span>'


def build_development_payload(development_simulation):
    if not development_simulation:
        return None
    return development_simulation


def _car_badge(car):
    bg, fg = car_color(car)
    return f'<span class="car" style="background:{bg};color:{fg};">{car}</span>'


def render_development_block(payload):
    """展開パターン別の1着候補。上位2パターンのみ、簡潔に表示する。"""
    if not payload:
        return ""
    scenario_blocks = []
    for s in payload["scenarios"][:2]:
        picks_html = "".join(
            f'<span class="dev-pick">{_car_badge(c["car"])} {c["win_pct"]:.0f}%</span>'
            for c in s["conditional_win_rates"][:3]
        )
        scenario_blocks.append(f"""
        <div class="dev-scenario-block">
          <div class="dev-scenario-row">
            <span class="dev-scenario-label">{s["label"]}</span>
            <span class="dev-scenario-pct">{s["share"]:.0f}%</span>
          </div>
          <div class="dev-picks">{picks_html}</div>
        </div>""")
    return f"""
    <div class="mw-label">展開別の1着候補</div>
    <div class="dev-scenarios">{"".join(scenario_blocks)}</div>"""


_DEV_CX, _DEV_CY, _DEV_HALF_LEN, _DEV_R = 200, 150, 80, 70


def _dev_track_xy(fraction, r):
    """report.py 側の静的SVG用に、JSのdevTrackXYと全く同じ幾何学を複製したもの
    （コーナーラベルなど、アニメーションしない固定要素の座標を置くため）。"""
    import math
    cx, cy, half_len = _DEV_CX, _DEV_CY, _DEV_HALF_LEN
    if fraction < 0.25:
        t1 = fraction / 0.25
        a1 = math.radians(90 - 180 * t1)
        return (cx + half_len) + r * math.cos(a1), cy + r * math.sin(a1)
    elif fraction < 0.5:
        t2 = (fraction - 0.25) / 0.25
        return (cx + half_len) - t2 * (2 * half_len), cy - r
    elif fraction < 0.75:
        t3 = (fraction - 0.5) / 0.25
        a3 = math.radians(-90 - 180 * t3)
        return (cx - half_len) + r * math.cos(a3), cy + r * math.sin(a3)
    else:
        t4 = (fraction - 0.75) / 0.25
        return (cx - half_len) + t4 * (2 * half_len), cy + r


def _dev_stadium_path(r):
    cx, cy, half_len = _DEV_CX, _DEV_CY, _DEV_HALF_LEN
    return (f"M {cx+half_len},{cy-r} L {cx-half_len},{cy-r} "
            f"A {r},{r} 0 0 0 {cx-half_len},{cy+r} "
            f"L {cx+half_len},{cy+r} "
            f"A {r},{r} 0 0 0 {cx+half_len},{cy-r} Z")


def render_development_animation(tab_id, payload):
    """
    展開シミュレーションを、実際のバンク形状（ホームストレッチ・バックストレッチ・
    2つのコーナー）を模したSVGトラック上で動くアニメーションとして再生するウィジェット。
    向正面（バックストレッチ）入口から残り1周半をアニメーション化し、各車の進路（レーン）
    の動きで捲り（外から一気に）・差し（直線だけ外に出す）といった決まり手の違いも表現する。

    画面の手前（下側）にゴール（ホームストレッチ）、奥（上側）に向正面（バックストレッチ）
    を配置する。実際の競輪と同じ反時計回り（左回り）で周回する。同じラインの選手は
    線で結び、ライン単位のまとまりが見た目でも分かるようにする。

    見た目は、緑の芝生の走路・ねずみ色の路面・内外のレーンガイドライン・コーナー番号
    （1〜4コーナー）・進行方向の矢印を描いた、実際のバンクに近いトラック背景の上で、
    車体（簡易的な自転車アイコン）が進行方向を向いて走るようにしている（ユーザー提示の
    参考イメージ「KEIRIN TACTICS 競輪展開ボード」の見た目に寄せたもの。ただし今回は
    見た目の改善のみで、あちらのような手動配置エディタ機能は追加していない）。
    """
    if not payload or not payload.get("animation"):
        return ""
    anim = payload["animation"]
    line_groups = {}
    for c in anim["cars"]:
        if c.get("line_index") is not None:
            line_groups.setdefault(c["line_index"], []).append(c)
    lines_html = ""
    for idx, members in line_groups.items():
        if len(members) < 2:
            continue
        members = sorted(members, key=lambda x: x["line_position"])
        lines_html += f'<polyline id="{tab_id}_devline_{idx}" class="dev-line-connector" points=""/>'

    cars_html = ""
    for c in anim["cars"]:
        bg, fg = car_color(c["car"])
        cars_html += f"""
        <g id="{tab_id}_dev_car_{c["car"]}" class="dev-car-icon">
          <g id="{tab_id}_dev_car_{c["car"]}_bike">
            <ellipse class="dev-bike-wheel" cx="-6.5" cy="0" rx="2.3" ry="2.3"/>
            <ellipse class="dev-bike-wheel" cx="6.5" cy="0" rx="2.3" ry="2.3"/>
            <line class="dev-bike-frame" x1="-6.5" y1="0" x2="6.5" y2="0"/>
            <ellipse class="dev-bike-rider" cx="0" cy="0" rx="5.6" ry="3.3" fill="{bg}"/>
          </g>
          <text id="{tab_id}_dev_car_{c["car"]}_t" class="dev-car-label" fill="{fg}">{c["car"]}</text>
        </g>"""

    road_outer_r = _DEV_R + 54
    road_inner_r = _DEV_R - 12
    guide_inner_r = _DEV_R - 4
    guide_outer_r = _DEV_R + 42 + 4
    road_path = _dev_stadium_path(road_outer_r) + " " + _dev_stadium_path(road_inner_r)
    field_path = _dev_stadium_path(road_inner_r)

    corner_labels = []
    for label, frac in (("２コーナー", 0.19), ("１コーナー", 0.06),
                         ("３コーナー", 0.56), ("４コーナー", 0.69)):
        lx, ly = _dev_track_xy(frac, road_outer_r + 12)
        corner_labels.append(f'<text class="dev-track-corner-label" x="{lx:.1f}" y="{ly:.1f}">{label}</text>')

    field_label_y_back = _DEV_CY - (road_inner_r - 16)
    field_label_y_home = _DEV_CY + (road_inner_r - 16)

    payload_json = _json.dumps(anim, ensure_ascii=False)
    return f"""
    <div class="mw-label">展開シミュレーション（向正面から残り1周半）</div>
    <div class="dev-anim-note">※ このアニメーションは「最も起こりやすい展開パターン」の中の1つの具体例です。
    表の「予測1着率」は全パターンを確率で加重平均した数字なので、このアニメーションの着順と
    一致しないことがあります。</div>
    <button type="button" class="dev-play-btn" onclick="playDevAnimation('{tab_id}')">▶ 再生</button>
    <div class="dev-track-wrap">
      <svg id="{tab_id}_dev_svg" class="dev-track-svg" viewBox="0 0 400 300" preserveAspectRatio="xMidYMid meet">
        <defs>
          <pattern id="devGrassStripes" width="14" height="14" patternUnits="userSpaceOnUse" patternTransform="rotate(0)">
            <rect width="14" height="14" fill="#4f8a52"/>
            <rect width="7" height="14" fill="#5a9a5d"/>
          </pattern>
        </defs>
        <path class="dev-track-road" fill-rule="evenodd" d="{road_path}"/>
        <path class="dev-track-field" d="{field_path}"/>
        <path class="dev-lane-guide dev-lane-guide-inner" d="{_dev_stadium_path(guide_inner_r)}"/>
        <path class="dev-lane-guide dev-lane-guide-outer" d="{_dev_stadium_path(guide_outer_r)}"/>
        {''.join(corner_labels)}
        <text class="dev-track-field-label" x="{_DEV_CX}" y="{field_label_y_back:.1f}">バック</text>
        <text class="dev-track-field-label" x="{_DEV_CX}" y="{field_label_y_home:.1f}">ホーム</text>
        <text class="dev-track-arrow" x="{_DEV_CX - 30}" y="{_DEV_CY - (road_inner_r - 16):.1f}">&#8249;</text>
        <text class="dev-track-arrow" x="{_DEV_CX + 30}" y="{_DEV_CY + (road_inner_r - 16):.1f}">&#8250;</text>
        <text class="dev-track-caption" x="{_DEV_CX}" y="12">向正面（バックストレッチ）</text>
        <line class="dev-finish-line-svg" x1="{_DEV_CX + _DEV_HALF_LEN}" y1="{_DEV_CY + guide_inner_r:.1f}" x2="{_DEV_CX + _DEV_HALF_LEN}" y2="{_DEV_CY + guide_outer_r:.1f}"/>
        <text class="dev-track-caption dev-track-caption-goal" x="{_DEV_CX}" y="294">ゴール（ホームストレッチ）</text>
        {lines_html}
        {cars_html}
      </svg>
    </div>
    <script>window.DEV_ANIM_DATA=window.DEV_ANIM_DATA||{{}}; window.DEV_ANIM_DATA["{tab_id}"]={payload_json};</script>"""


def render_hole_candidates_block(candidates):
    """穴目候補。目立たせすぎないよう最有力1名だけを一行で示す。"""
    if not candidates:
        return ""
    c = candidates[0]
    return f"""
    <div class="hole-line">{_car_badge(c["car"])} {c["name"]} <span class="hole-tag">穴目候補</span></div>"""


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
        cr = r.get("course_record")
        cr_html = ""
        if cr:
            cr_html = f'<br><span class="dim">当地{cr["races"]}走{cr["wins"]}勝{cr["top3"]}連対</span>'
        form_badge_html = render_form_badge(r.get("form_trend"))
        rivalry_badge_html = render_rivalry_badge(r.get("rivalry_summary"))
        extra_badges = " ".join(x for x in [form_badge_html, rivalry_badge_html] if x)
        extra_badges_html = f'<br>{extra_badges}' if extra_badges else ""

        base_pct = r["base"] * 100
        adjusted_pct = r["adjusted"]
        rise = adjusted_pct - base_pct
        if abs(rise) < 0.05:
            rise_html = '<span class="dim">±0.0pt</span>'
        else:
            arrow = "↑" if rise > 0 else "↓"
            cls = "delta-up" if rise > 0 else "delta-down"
            rise_html = f'<span class="{cls}">{abs(rise):.1f}pt{arrow}</span>'
        rate_html = f'<b>{adjusted_pct:.1f}%</b><br><span class="dim">基礎{base_pct:.1f}%</span><br>{rise_html}'

        rows_html += f"""
        <tr style="{highlight}">
          <td><span class="car" style="background:{bg};color:{fg}">{r['car']}</span></td>
          <td>{r['name']}{cr_html}{extra_badges_html}</td>
          <td>{r['rank']}</td>
          <td>{KIMARITE_LABELS.get(r['dominant_type'], '-')}<br><span class="dim">({r['kimarite_prediction']['ratio']*100:.0f}%)</span></td>
          <td>{line_label}</td>
          <td>{rate_html}</td>
          <td>{r['confidence']['score']:.0f}</td>
          <td>{r.get('place_rate', 0):.1f}%</td>
        </tr>"""

    banner_html = ""
    if high_prob:
        banner_html = (f'<div class="banner-high">{top["car"]}号車 {top["name"]} が本命'
                        f'（予測1着率 {top["adjusted"]:.1f}%）</div>')

    bar_chart = svg_bar_chart(result["rows"])
    line_info_html = render_line_info_block(result, title)
    odds_trend_html = render_odds_trend_block(info)
    kimarite_table_html = render_kimarite_table(result["kimarite_ratio"], info.get("venue"))
    matrix_payload = build_matrix_payload(result["rows"], result["second_place_matrix"], result["full_third_place_data"], top["car"])
    matrix_widget_html = render_matrix_widget(tab_id, matrix_payload)
    trifecta_payload = build_trifecta_payload(result.get("trifecta"), result["rows"])
    trifecta_html = render_trifecta_groups(tab_id, trifecta_payload)
    dev_payload = build_development_payload(result.get("development_simulation"))
    dev_anim_html = render_development_animation(tab_id, dev_payload)
    dev_html = render_development_block(dev_payload)
    hole_html = render_hole_candidates_block(result.get("hole_candidates"))

    deadline = info.get("deadline")
    deadline_html = f'<span class="deadline">締切 {deadline}</span>' if deadline else ""
    odds_alert_html = render_odds_alert_badge(info)
    pick_color = car_color(top["car"])[0]
    has_trifecta = bool(trifecta_payload)
    has_dev = bool(dev_payload) or bool(hole_html)
    subtab_bar_html = ""
    if has_trifecta or has_dev:
        buttons = ['<button class="subtab-btn active" id="' + tab_id + '_subbtn_main" '
                   'onclick="showSubTab(\'' + tab_id + '\',\'main\',this)">予想</button>']
        if has_trifecta:
            buttons.append('<button class="subtab-btn" id="' + tab_id + '_subbtn_tf" '
                            'onclick="showSubTab(\'' + tab_id + '\',\'tf\',this)">3連単</button>')
        if has_dev:
            buttons.append('<button class="subtab-btn" id="' + tab_id + '_subbtn_dev" '
                            'onclick="showSubTab(\'' + tab_id + '\',\'dev\',this)">展開</button>')
        subtab_bar_html = '<div class="subtab-bar">' + "".join(buttons) + '</div>'
    trifecta_block_html = ""
    if has_trifecta:
        trifecta_block_html = f"""
    <div id="{tab_id}_sub_tf" class="subtab-panel" style="display:none;">
      {trifecta_html}
    </div>"""
    dev_block_html = ""
    if has_dev:
        dev_block_html = f"""
    <div id="{tab_id}_sub_dev" class="subtab-panel" style="display:none;">
      {hole_html}
      {dev_anim_html}
      {dev_html}
    </div>"""
    return f"""
    <div id="{tab_id}" class="race-panel" style="display:none;">
      <div class="race-card" style="--pick-color:{pick_color};">
        <div class="race-head">
          <span class="raceno">{info['race_no']}R</span>
          <span class="title">{title}</span>
          {deadline_html}
          {odds_alert_html}
        </div>
        {banner_html}
        {line_info_html}
        {odds_trend_html}
        {subtab_bar_html}
    <div id="{tab_id}_sub_main" class="subtab-panel">
        <table class="main">
          <thead><tr><th>号車</th><th>選手</th><th>級班</th><th>予測決まり手</th><th>ライン</th><th>予測1着率</th><th>信頼度</th><th>予測3着内率</th></tr></thead>
          <tbody>{rows_html}</tbody>
        </table>

        <div class="chart-block">
          {bar_chart}
        </div>

        <div class="chart-block">{kimarite_table_html}</div>
        <div class="chart-block">{matrix_widget_html}</div>
    </div>
    {trifecta_block_html}
    {dev_block_html}
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
  .race-head .raceno{ font-family:"Hiragino Sans","Hiragino Kaku Gothic ProN","Yu Gothic","Noto Sans JP","Meiryo",sans-serif; font-weight:700; font-size:17px; color:var(--board); }
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
  .tf-chip{ min-width:44px; height:auto; border-radius:8px; border:2px solid var(--line); background:var(--paper);
            font-size:13px; font-weight:700; color:var(--ink); cursor:pointer; padding:5px 8px; line-height:1.3; }
  .tf-chip .mw-chip-sub{ display:block; font-size:9px; font-weight:600; opacity:.85; }
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
  .tf-list{ display:flex; flex-direction:column; gap:2px; }
  .tf-row{ display:flex; align-items:center; gap:10px; padding:6px 4px; border-bottom:1px solid var(--line); }
  .tf-row:first-child{ background:rgba(198,154,78,.10); border-radius:3px; }
  .tf-rank{ flex:0 0 auto; width:18px; text-align:center; font-size:12px; font-weight:700; color:var(--ink-soft); }
  .tf-combo{ flex:1; display:flex; align-items:center; gap:5px; }
  .tf-arrow{ color:var(--ink-soft); font-size:12px; }
  .tf-prob{ flex:0 0 auto; font-size:13px; font-weight:700; color:var(--brick); min-width:52px; text-align:right; }
  .subtab-bar{ display:flex; gap:6px; margin:12px 0 10px; border-bottom:1px solid var(--line); }
  .subtab-btn{ background:none; border:none; border-bottom:2px solid transparent; padding:7px 4px; margin-bottom:-1px;
               font-size:13px; font-weight:600; color:var(--ink-soft); cursor:pointer; }
  .subtab-btn.active{ color:var(--board); border-bottom-color:var(--gold); }
  .subtab-panel{ }
  .value-alert-badge{ background:#fdecc8; border:1px solid var(--gold); color:#8a5a12; border-radius:3px;
                       padding:2px 8px; font-size:11px; font-weight:700; }
  .dev-scenarios{ display:flex; flex-direction:column; gap:8px; }
  .dev-scenario-block{ background:var(--paper2); border-radius:4px; padding:7px 10px; }
  .dev-scenario-row{ display:flex; align-items:center; justify-content:space-between; gap:8px; }
  .dev-scenario-label{ font-size:12px; color:var(--ink); font-weight:600; }
  .dev-scenario-pct{ font-size:13px; font-weight:700; color:#b8763f; }
  .dev-picks{ margin-top:5px; font-size:11.5px; color:var(--ink-soft); display:flex; align-items:center; gap:6px; flex-wrap:wrap; }
  .dev-pick{ display:inline-flex; align-items:center; gap:3px; font-weight:700; color:var(--ink); }
  .hole-line{ font-size:13px; font-weight:600; color:var(--ink); display:flex; align-items:center; gap:6px; margin-bottom:10px; }
  .hole-tag{ font-size:10px; font-weight:700; color:#8a5a12; background:#fdecc8; border-radius:3px; padding:1px 6px; }
  .dev-anim-note{ font-size:10.5px; color:var(--ink-soft); line-height:1.5; margin:-4px 0 9px; }
  .dev-play-btn{ background:var(--board); color:#fff; border:none; border-radius:4px; padding:7px 16px;
                 font-size:12.5px; font-weight:700; cursor:pointer; margin-bottom:10px; }
  .dev-track-wrap{ background:#cfd6c6; border-radius:8px; padding:6px; margin-bottom:14px; }
  .dev-track-svg{ width:100%; height:auto; display:block; }
  .dev-track-road{ fill:#9a9d97; stroke:#7d8077; stroke-width:1; }
  .dev-track-field{ fill:url(#devGrassStripes); }
  .dev-lane-guide{ fill:none; stroke-width:1.1; opacity:.55; }
  .dev-lane-guide-inner{ stroke:#c0392b; }
  .dev-lane-guide-outer{ stroke:#2d5fa8; }
  .dev-finish-line-svg{ stroke:#fff; stroke-width:3; }
  .dev-track-caption{ font-size:10px; font-weight:700; text-anchor:middle; fill:var(--ink-soft); }
  .dev-track-caption-goal{ fill:#8a5a12; }
  .dev-track-corner-label{ font-size:7px; font-weight:700; text-anchor:middle; fill:#5c6b60; opacity:.75; }
  .dev-track-field-label{ font-size:8px; font-weight:700; text-anchor:middle; fill:rgba(255,255,255,.55); letter-spacing:1px; }
  .dev-track-arrow{ font-size:11px; font-weight:700; text-anchor:middle; fill:rgba(255,255,255,.6); }
  .dev-car-icon{ transition:none; }
  .dev-bike-wheel{ fill:#2a2a2a; }
  .dev-bike-frame{ stroke:#2a2a2a; stroke-width:1.4; stroke-linecap:round; }
  .dev-bike-rider{ stroke:rgba(0,0,0,.3); stroke-width:.6; }
  .dev-car-label{ font-size:7.5px; font-weight:800; text-anchor:middle; pointer-events:none; dominant-baseline:central; }
  .dev-line-connector{ fill:none; stroke:#fff; stroke-width:2.5; stroke-linecap:round; opacity:.5; }
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

// レースパネル内の「予想」「3連単」サブタブ切り替え
function showSubTab(tabId, which, btn){
  ['main', 'tf', 'dev'].forEach(function(key){
    var panel = document.getElementById(tabId + '_sub_' + key);
    if(panel) panel.style.display = (which === key) ? '' : 'none';
  });
  var bar = btn.parentElement;
  if(bar){
    bar.querySelectorAll('.subtab-btn').forEach(function(b){ b.classList.remove('active'); });
  }
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

// 3連単一覧（1着候補ごとにタップで絞り込み）
function renderTrifectaGroups(tabId){
  const payload = window.TRIFECTA_DATA && window.TRIFECTA_DATA[tabId];
  if(!payload) return;
  const car = payload.selected || payload.default;
  const chipsEl = document.getElementById(tabId+'_tf_chips');
  if(!chipsEl) return;
  chipsEl.innerHTML = payload.cars.map(function(c){
    const isActive = c.car === car;
    const bg = isActive ? c.bg : 'transparent';
    const fg = isActive ? c.fg : 'inherit';
    return '<button type="button" class="tf-chip'+(isActive?' active':'')+'"' +
      ' style="background:'+bg+';color:'+fg+';border-color:'+c.bg+';"' +
      ' onclick="selectTrifectaCar(\\''+tabId+'\\','+c.car+')">'+c.car+'号車<span class="mw-chip-sub">'+c.total.toFixed(1)+'%</span></button>';
  }).join('');
  const list = payload.groups[String(car)] || [];
  const listEl = document.getElementById(tabId+'_tf_list');
  listEl.innerHTML = list.length ? list.map(function(c, i){
    return '<div class="tf-row">' +
      '<span class="tf-rank">'+(i+1)+'</span>' +
      '<span class="tf-combo">' +
        '<span class="car" style="background:'+payload.cars.find(function(x){return x.car===car;}).bg+';color:'+payload.cars.find(function(x){return x.car===car;}).fg+';">'+car+'</span>' +
        '<span class="tf-arrow">\\u2192</span>' +
        '<span class="car" style="background:'+carColorLookup(payload,c.second).bg+';color:'+carColorLookup(payload,c.second).fg+';">'+c.second+'</span>' +
        '<span class="tf-arrow">\\u2192</span>' +
        '<span class="car" style="background:'+carColorLookup(payload,c.third).bg+';color:'+carColorLookup(payload,c.third).fg+';">'+c.third+'</span>' +
      '</span>' +
      '<span class="tf-prob">'+c.prob.toFixed(2)+'%</span>' +
    '</div>';
  }).join('') : '<p class="dim">データがありません</p>';
}
function carColorLookup(payload, car){
  const found = payload.cars.find(function(x){ return x.car === car; });
  return found || {bg:'#888', fg:'#fff'};
}
function selectTrifectaCar(tabId, car){
  window.TRIFECTA_DATA[tabId].selected = car;
  renderTrifectaGroups(tabId);
}

// 展開シミュレーションのアニメーション再生（実際のバンク形状の上を動かす）
// トラック座標系: 中心(200,120)、直線半長80、コーナー基準半径70、レーン幅30
// （report.py の SVG <path>（dev-track-outline）とここのジオメトリ定数は対応している）
// 画面の奥（上側 y小）を向正面（バックストレッチ）、手前（下側 y大）をゴール
// （ホームストレッチ）とする。フィニッシュ（fraction=0=1.0）は、ホームストレッチが
// 手前右側のコーナーに入る直前（x=cx+halfLen側）に位置する。実際の競輪と同じ
// 反時計回り（左回り）：ゴール→右コーナー→向正面→左コーナー→ゴール、の順で周回する。
function devTrackXY(fraction, lane){
  var cx = 200, cy = 150, halfLen = 80, R = 70, laneW = 42;
  var r = R + lane * laneW;
  if(fraction < 0.25){
    // 右側コーナー（ゴール側→向正面側、外側＝右に膨らむ）
    var t1 = fraction / 0.25;
    var a1 = (90 - 180 * t1) * Math.PI / 180;
    return { x: (cx + halfLen) + r * Math.cos(a1), y: cy + r * Math.sin(a1) };
  } else if(fraction < 0.5){
    // 向正面（バックストレッチ、奥＝上側）: 右端→左端
    var t2 = (fraction - 0.25) / 0.25;
    return { x: (cx + halfLen) - t2 * (2 * halfLen), y: cy - r };
  } else if(fraction < 0.75){
    // 左側コーナー（向正面側→ゴール側、外側＝左に膨らむ）
    var t3 = (fraction - 0.5) / 0.25;
    var a3 = (-90 - 180 * t3) * Math.PI / 180;
    return { x: (cx - halfLen) + r * Math.cos(a3), y: cy + r * Math.sin(a3) };
  } else {
    // ホームストレッチ（ゴール、手前＝下側）: 左端→フィニッシュ(x=cx+halfLen)
    var t4 = (fraction - 0.75) / 0.25;
    return { x: (cx - halfLen) + t4 * (2 * halfLen), y: cy + r };
  }
}
function devFractionFromPosition(track, positionLaps){
  // positionLaps は既に「実際の周回距離（周）」そのもの（race_simulation.py の
  // build_animation 参照）。start_fraction はアニメーション開始地点（向正面あたり）
  // のトラック位置で、そこに周回距離をそのまま足すだけでよい（0-100换算は不要）。
  var f = track.start_fraction + positionLaps;
  return f - Math.floor(f);
}
// 進行方向の接線角度（度）を、fractionをごく僅かに前後にずらした2点から求める。
// 反時計回りに周回しているので、常に「少し先」の点との差分を使う。
function devTrackAngle(fraction, lane){
  var eps = 0.004;
  var f0 = fraction, f1 = fraction + eps;
  if(f1 >= 1) f1 -= 1;
  var p0 = devTrackXY(f0, lane);
  var p1 = devTrackXY(f1, lane);
  return Math.atan2(p1.y - p0.y, p1.x - p0.x) * 180 / Math.PI;
}
// 車体アイコン（<g class="dev-car-icon">、内側に回転用の<g>_bike、きょうだい要素に
// 直立したまま表示する車番<text>）の位置と向きをまとめて更新する。
function setDevCarPose(tabId, car, x, y, angleDeg){
  var outer = document.getElementById(tabId + '_dev_car_' + car);
  var bike = document.getElementById(tabId + '_dev_car_' + car + '_bike');
  if(outer){ outer.setAttribute('transform', 'translate(' + x + ',' + y + ')'); }
  if(bike){ bike.setAttribute('transform', 'rotate(' + angleDeg.toFixed(1) + ')'); }
}
function updateDevLineConnectors(tabId, anim, xyByCar){
  var groups = {};
  anim.cars.forEach(function(c){
    if(c.line_index === null || c.line_index === undefined) return;
    (groups[c.line_index] = groups[c.line_index] || []).push(c);
  });
  Object.keys(groups).forEach(function(idx){
    var members = groups[idx];
    if(members.length < 2) return;
    members.sort(function(a, b){ return a.line_position - b.line_position; });
    var el = document.getElementById(tabId + '_devline_' + idx);
    if(!el) return;
    var pts = members.map(function(c){
      var xy = xyByCar[c.car];
      return xy ? (xy.x + ',' + xy.y) : '';
    }).join(' ');
    el.setAttribute('points', pts);
  });
}
// Catmull-Romスプラインで5点のチェックポイントを滑らかに通す（各区間の境目で
// 速度が0にならず、ずっと同じ調子で動き続けるようにするため）。端点は同じ値を
// 複製して扱う（クランプ）。
function devCatmullRom(values, u){
  var n = values.length;
  var i = Math.floor(u);
  if(i < 0) i = 0;
  if(i > n - 2) i = n - 2;
  var t = u - i;
  var p0 = values[Math.max(i - 1, 0)];
  var p1 = values[i];
  var p2 = values[Math.min(i + 1, n - 1)];
  var p3 = values[Math.min(i + 2, n - 1)];
  var t2 = t * t, t3 = t2 * t;
  return 0.5 * ((2 * p1) + (-p0 + p2) * t +
    (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 +
    (-p0 + 3 * p1 - 3 * p2 + p3) * t3);
}
function placeDevCarsAtU(tabId, anim, u){
  var xyByCar = {};
  anim.cars.forEach(function(c){
    var pos = devCatmullRom(c.positions, u);
    var lane = devCatmullRom(c.lanes, u);
    var frac = devFractionFromPosition(anim.track, pos);
    var xy = devTrackXY(frac, lane);
    var angle = devTrackAngle(frac, lane);
    xyByCar[c.car] = xy;
    setDevCarPose(tabId, c.car, xy.x, xy.y, angle);
  });
  updateDevLineConnectors(tabId, anim, xyByCar);
}
function initDevTrack(tabId){
  var anim = window.DEV_ANIM_DATA && window.DEV_ANIM_DATA[tabId];
  if(!anim) return;
  placeDevCarsAtU(tabId, anim, 0);
}
function playDevAnimation(tabId){
  var anim = window.DEV_ANIM_DATA && window.DEV_ANIM_DATA[tabId];
  if(!anim) return;
  var totalMs = 9000; // ゆっくり・途切れず動く見た目にするため、やや長めの一定速度で通しで再生する
  var maxU = anim.checkpoints - 1;
  placeDevCarsAtU(tabId, anim, 0);
  var start = null;
  function frame(now){
    if(start === null) start = now;
    var t = Math.min((now - start) / totalMs, 1);
    placeDevCarsAtU(tabId, anim, t * maxU);
    if(t < 1){ requestAnimationFrame(frame); }
  }
  requestAnimationFrame(frame);
}

window.addEventListener('DOMContentLoaded', function(){
  const tabs = Array.from(document.querySelectorAll('.tab-btn'));
  if(window.MATRIX_DATA){
    Object.keys(window.MATRIX_DATA).forEach(renderMatrixWidget);
  }
  if(window.TRIFECTA_DATA){
    Object.keys(window.TRIFECTA_DATA).forEach(renderTrifectaGroups);
  }
  if(window.DEV_ANIM_DATA){
    Object.keys(window.DEV_ANIM_DATA).forEach(initDevTrack);
  }
  if(tabs.length === 0) return;
  // まとめページ（本命1着率45%超レース一覧など）からの「?r=5」のような直接リンクが
  // あれば、そのレース番号のタブを優先して開く。無ければ従来どおり締切が一番近い
  // レースを自動で開く。
  const rParam = new URLSearchParams(window.location.search).get('r');
  if(rParam){
    const direct = tabs.find(function(t){ return t.getAttribute('data-race-no') === rParam; });
    if(direct){ direct.click(); return; }
  }
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
        tabs += (f'<button class="tab-btn" data-deadline="{deadline}" data-race-no="{no}" '
                 f'onclick="showTab(\'{tab_id}\', this)">{label}</button>')
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


def _race_flags(rd):
    """レースの特記事項（本命が堅い／拮抗／妙味候補）のキー一覧を返す。"""
    flags = []
    result = rd.get("prediction")
    if result:
        if result.get("is_high_prob"):
            flags.append("high")
        if result.get("is_close_race"):
            flags.append("close")
    if rd["race_info"].get("odds_value_alert"):
        flags.append("value")
    return flags


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
         "race_no": rd["race_info"]["race_no"], "deadline": rd["race_info"].get("deadline"),
         "flags": _race_flags(rd)}
        for rd in all_race_data if rd["race_info"].get("deadline")
    ], ensure_ascii=False)

    from zoneinfo import ZoneInfo as _ZI
    updated_str = (now or datetime.datetime.now(_ZI("Asia/Tokyo"))).strftime("%m/%d %H:%M")

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
            // 特記事項バッジ（本命が堅い／拮抗／妙味候補）
            const FLAG_LABELS = {high:'本命堅い', close:'拮抗', value:'妙味'};
            const badges = (r.flags || []).map(function(f){
              return '<span class="up-badge up-badge-' + f + '">' + FLAG_LABELS[f] + '</span>';
            }).join('');
            // レース番号つきで遷移する（?r=N）。付けないと、その場の「締切が一番近いレース」が開いてしまう
            html += '<a class="upcoming-row' + soon + '" href="' + r.venue + '/index.html?r=' + r.race_no + '">' +
              '<span class="up-rank">' + (idx+1) + '</span>' +
              '<span class="up-main"><span class="up-name">' + r.name + '競輪 ' + r.race_no + 'R</span>' +
              (badges ? '<span class="up-badges">' + badges + '</span>' : '') + '</span>' +
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
  h2.section{{ font-size:14px; color:var(--ink-soft); margin:18px 0 10px; }}
  {_TABNAV_STYLE}
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
  .up-main{{ flex:1; min-width:0; display:flex; flex-direction:column; gap:4px; }}
  .up-name{{ font-weight:700; color:var(--ink); }}
  .up-badges{{ display:flex; flex-wrap:wrap; gap:4px; }}
  .up-badge{{ font-size:10.5px; font-weight:700; color:#fff; border-radius:4px; padding:1px 6px; }}
  .up-badge-high{{ background:var(--brick); }} .up-badge-close{{ background:var(--slate); }}
  .up-badge-value{{ background:#8a5a12; }}
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
  {gate_stripe_html()}
</header>
<main>
  {_tab_grid_html()}
  <div id="upcomingListBox"></div>
  <h2 class="section">本日の開催場</h2>
  {rows_html if by_venue else "<p style='text-align:center;color:var(--ink-soft);'>本日は取得できたレースがありませんでした。</p>"}
</main>
<footer>最終更新 {updated_str}（1時間おきに自動更新）<br>このページはGitHub Actionsにより自動生成されています。予測はAIモデルによる参考情報であり、的中を保証するものではありません。</footer>
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


def _fmt_date_jp(date=None):
    date = date or datetime.date.today()
    weekday_map = {0: "月", 1: "火", 2: "水", 3: "木", 4: "金", 5: "土", 6: "日"}
    return f"{date.strftime('%Y年%m月%d日')}({weekday_map[date.weekday()]})"


# 集計ページ（本命が堅い／拮抗／妙味／全レース早見表）の一覧。
# ナビゲーションの並び順・文言はここ1か所で管理する。
AGG_GROUPS = [
    ("レースをさがす", [
        ("overview.html", "全レース早見表"),
        ("high_prob.html", "本命が堅い"),
        ("close_race.html", "拮抗レース"),
        ("value.html", "投票が鈍い(妙味)"),
    ]),
    ("選手・開催場・成績", [
        ("players.html", "選手一覧"),
        ("venues_today.html", "開催場別"),
        ("results.html", "予想成績"),
        ("venues.html", "全競輪場データ"),
        ("print.html", "印刷用"),
    ]),
]
AGG_PAGES = [item for _, items in AGG_GROUPS for item in items]


def _agg_nav_html(current=None):
    """集計ページ上部の「タブ」ストリップ（横スクロール、現在のページは自動で見える位置へ）。"""
    tabs = "".join(
        f'<a class="tab-link{" current" if href == current else ""}" href="{href}">{label}</a>'
        for href, label in AGG_PAGES)
    return f'<nav class="tab-strip" aria-label="ページ切替">{tabs}</nav>'


def _tab_grid_html():
    """トップページ用：グループ見出しつきの大きなタブボタン（全ページが一目で見える）。"""
    out = []
    for title, items in AGG_GROUPS:
        links = "".join(f'<a class="tab-link" href="{href}">{label}</a>' for href, label in items)
        out.append(f'<div class="tab-group-title">{title}</div><nav class="tab-grid">{links}</nav>')
    return "".join(out)


_TABNAV_STYLE = """
  .tab-link{ display:flex; align-items:center; justify-content:center; text-align:center; min-height:46px; padding:8px 12px;
             font-size:14px; font-weight:700; color:var(--ink); background:#fff; border:1px solid var(--border);
             border-bottom:4px solid var(--border); border-radius:10px 10px 4px 4px; white-space:nowrap;
             -webkit-tap-highlight-color:transparent; }
  .tab-link:active{ transform:translateY(1px); background:var(--paper2); }
  .tab-link.current{ background:var(--navy); color:#fff; border-color:var(--navy); border-bottom-color:var(--gold); }
  .tab-strip{ display:flex; gap:6px; overflow-x:auto; margin:0 0 14px; padding:2px 2px 6px; -webkit-overflow-scrolling:touch; scrollbar-width:none; }
  .tab-strip::-webkit-scrollbar{ display:none; }
  .tab-strip .tab-link{ flex:0 0 auto; }
  .tab-group-title{ font-size:12px; color:var(--ink-soft); font-weight:700; margin:12px 0 6px; }
  .tab-grid{ display:grid; grid-template-columns:repeat(auto-fit,minmax(138px,1fr)); gap:8px; margin-bottom:4px; }
"""


_AGG_SCRIPT = """
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
      const cur = document.querySelector('.tab-strip .tab-link.current');
      if(cur && cur.scrollIntoView){ cur.scrollIntoView({inline:'center', block:'nearest'}); }
      const nowJstMinutes = getNowJstMinutes();
      document.querySelectorAll('[data-deadline]').forEach(function(el){
        const mins = minutesUntilDeadline(el.getAttribute('data-deadline'), nowJstMinutes);
        if(mins <= 5){ el.classList.add('soon'); }
        if(mins >= 1e9){ el.classList.add('ended'); }
      });
    });
"""

_AGG_STYLE = _TABNAV_STYLE + """
  main{ max-width:720px; margin:0 auto; padding:16px 10px 60px; }
  .hp-lead{ font-size:12.5px; color:var(--ink-soft); margin:0 0 14px; }
  .hp-list{ display:flex; flex-direction:column; gap:8px; }
  .hp-card{ display:block; background:#fff; border:1px solid var(--border); border-radius:8px;
             padding:10px 12px; text-decoration:none; color:inherit; }
  .hp-card.soon{ background:linear-gradient(135deg,#fff4de,#fbe9c9); border-color:var(--gold); }
  .hp-card.ended{ opacity:.45; }
  .hp-card-head{ display:flex; justify-content:space-between; align-items:baseline; margin-bottom:6px; }
  .hp-venue{ font-weight:700; font-size:13px; color:var(--ink); }
  .hp-deadline{ font-size:12px; font-weight:700; color:#8a5a12; }
  .hp-card-body{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
  .hp-name{ font-size:13px; color:var(--ink); flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .hp-line{ font-size:11px; }
  .hp-pct{ font-size:15px; font-weight:800; color:var(--brick); }
  .hp-sub{ font-size:11.5px; color:var(--ink-soft); margin-top:5px; }
  .hp-contender{ display:inline-flex; align-items:center; gap:4px; font-size:13px; font-weight:700; color:var(--brick); margin-right:8px; }
  .hp-sub-inline{ font-size:11px; font-weight:400; color:var(--ink-soft); margin-left:2px; }
  .dim{ color:var(--ink-soft); }
"""


def _render_race_list_page(*, title, heading, tagline, lead, entries, empty_msg, current, date_str):
    """
    全競輪場横断の「条件に合うレースだけ」一覧ページの共通レンダラ。
    entries: [{"venue","venue_name","race_no","deadline","body_html"}]。
    締切が近い順（締切不明・既に終了したものは後方）に並べて表示する。
    各カードは各場ページの該当レースタブ（?r=N）に直接リンクする。
    """
    from zoneinfo import ZoneInfo as _ZoneInfo
    now_jst = datetime.datetime.now(_ZoneInfo("Asia/Tokyo"))
    entries = sorted(entries, key=lambda e: _minutes_until_deadline(e["deadline"], now_jst))

    cards_html = ""
    for e in entries:
        deadline_html = f'<span class="hp-deadline">{e["deadline"]}</span>' if e["deadline"] else ""
        cards_html += f"""
        <a class="hp-card" href="{e['venue']}/index.html?r={e['race_no']}" data-deadline="{e['deadline'] or ''}">
          <div class="hp-card-head">
            <span class="hp-venue">{e['venue_name']} {e['race_no']}R</span>
            {deadline_html}
          </div>
          {e['body_html']}
        </a>"""

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} | 競輪AI予想</title>
<style>
{COMMON_STYLE}{_AGG_STYLE}
</style>
</head>
<body>
<header>
  <div class="top-row">
    <h1>&larr; <a href="index.html">{heading}</a></h1>
    <span class="date">{date_str}</span>
  </div>
  <p class="tagline">{tagline}</p>
  {gate_stripe_html()}
</header>
<main>
  {_agg_nav_html(current)}
  <p class="hp-lead">{lead.format(n=len(entries))}</p>
  <div class="hp-list">
    {cards_html if entries else f"<p style='text-align:center;color:var(--ink-soft);'>{empty_msg}</p>"}
  </div>
</main>
<footer>このページはGitHub Actionsにより毎朝自動生成されています。予測はAIモデルによる参考情報であり、的中を保証するものではありません。</footer>
<script>{_AGG_SCRIPT}</script>
</body>
</html>"""


def _line_label_of(row):
    info = row.get("line_info")
    if not info:
        return "単騎"
    return "先頭" if info["position"] == 1 else f'{info["position"]}番手'


def _race_entry(rd, body_html):
    info = rd["race_info"]
    return {
        "venue": info["venue"],
        "venue_name": VENUE_NAMES.get(info["venue"], info["venue"]),
        "race_no": info["race_no"],
        "deadline": info.get("deadline"),
        "body_html": body_html,
    }


def render_high_prob_page(all_race_data, date=None):
    """
    本命の予測1着率が一定以上（model.py の DEFAULT_SETTINGS["th_high"]、既定55%）の
    レースだけを、全競輪場横断でまとめた一覧ページ。各レースの is_high_prob は
    predict_race() が既に th_high で判定済みの値をそのまま使う（閾値の定義を
    ここで重複して持たない。基準を変えたい場合は model.py 側の設定を変えれば
    自動的にこのページにも反映される）。
    """
    entries = []
    for rd in all_race_data:
        result = rd.get("prediction")
        if not result or not result.get("is_high_prob"):
            continue
        top = result["top"]
        bg, fg = car_color(top["car"])
        body = f"""
          <div class="hp-card-body">
            <span class="car" style="background:{bg};color:{fg};">{top['car']}</span>
            <span class="hp-name">{top['name']}</span>
            <span class="hp-line dim">{_line_label_of(top)}</span>
            <span class="hp-pct">{top['adjusted']:.1f}%</span>
          </div>"""
        entries.append(_race_entry(rd, body))
    return _render_race_list_page(
        title="本命1着率55%超レース一覧", heading="本命1着率55%超レース",
        tagline="予測1着率が55%を超えた、今日の本命が堅いレースだけを集めました。",
        lead="対象：{n}レース（予測1着率55%超。全競輪場・本日開催分）",
        entries=entries, empty_msg="本日は該当するレースがありませんでした。",
        current="high_prob.html", date_str=_fmt_date_jp(date))


def render_close_race_page(all_race_data, date=None):
    """
    拮抗しているレース（予測3着内率が60%以上の選手が1人もいない＝抜けた選手がいない混戦）を
    横断表示する。判定は predict_race() の is_close_race（settings["th_close_place"]、既定60%）を
    そのまま使い、ここでは閾値を持たない。カードには予測1着率の上位3車を、1着率と3着内率つきで
    並べ、誰と誰が競っているかが一目で分かるようにする。
    """
    entries = []
    for rd in all_race_data:
        result = rd.get("prediction")
        if not result or not result.get("is_close_race"):
            continue
        limit = result["settings"]["th_close_place"]
        picks_html = ""
        for r in result["rows"][:3]:
            bg, fg = car_color(r["car"])
            picks_html += (f'<span class="hp-contender"><span class="car" style="background:{bg};color:{fg};">'
                           f'{r["car"]}</span>{r["adjusted"]:.1f}%'
                           f'<span class="hp-sub-inline">3着内{r.get("place_rate", 0):.0f}%</span></span>')
        body = f"""
          <div class="hp-card-body">{picks_html}</div>
          <div class="hp-sub">3着内率の最高 {result['max_place_rate']:.1f}%（{limit}%以上の選手がいない）　1位と2位の差 {result['top_gap']:.1f}pt</div>"""
        entries.append(_race_entry(rd, body))
    return _render_race_list_page(
        title="拮抗しているレース", heading="拮抗しているレース",
        tagline="3着内率60%以上の選手がいない、抜けた本命のいない混戦レースです。",
        lead="対象：{n}レース（予測3着内率が60%以上の選手がいない。全競輪場・本日開催分）。各選手の数字は「予測1着率 / 3着内率」です。",
        entries=entries, empty_msg="本日は該当するレースがありませんでした。",
        current="close_race.html", date_str=_fmt_date_jp(date))


def render_hole_page(all_race_data=None, date=None):
    """
    【廃止済みページ】穴目候補の一覧ページは廃止した。古い run_daily.py（このページを
    書き出す版）と組み合わさっても import エラーで日次処理全体が止まらないよう、
    廃止の案内だけを返す関数を残している。
    """
    return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>このページは終了しました | 競輪AI予想</title><style>{COMMON_STYLE}</style></head>
<body><header><div class="top-row"><h1>&larr; <a href="index.html">競輪AI予想</a></h1></div></header>
<main style="max-width:600px;margin:0 auto;padding:30px 14px;text-align:center;color:var(--ink-soft);">
このページは終了しました。<br><a href="index.html" style="text-decoration:underline;">トップページへ</a></main></body></html>"""


def render_value_page(all_race_data, date=None):
    """
    オッズ妙味アラート（odds_alerts.py：本命の確信度が高いのに、投票の伸びが同時間帯の他レース
    より鈍いレース）に該当するレースを横断表示する。車券ごとのオッズは取得できていないため、
    あくまで「投票状況」ベースの簡易な指標であることをリード文で明記する。
    """
    entries = []
    for rd in all_race_data:
        info = rd["race_info"]
        result = rd.get("prediction")
        if not result or not info.get("odds_value_alert"):
            continue
        top = result["top"]
        bg, fg = car_color(top["car"])
        trend = info.get("odds_trend")
        if trend and trend.get("snapshot_count", 0) >= 2:
            vote_html = f'投票状況: {trend["latest"]:,}票（初回計測比 {trend["growth_pct"]:+.0f}%）'
        else:
            vote_html = "投票状況: 計測中（まだ伸びを判定できる回数に達していません）"
        body = f"""
          <div class="hp-card-body">
            <span class="car" style="background:{bg};color:{fg};">{top['car']}</span>
            <span class="hp-name">{top['name']}</span>
            <span class="hp-line dim">{_line_label_of(top)}</span>
            <span class="hp-pct">{top['adjusted']:.1f}%</span>
          </div>
          <div class="hp-sub">{vote_html}</div>"""
        entries.append(_race_entry(rd, body))
    return _render_race_list_page(
        title="投票が鈍い本命レース（妙味候補）", heading="投票が鈍い本命レース",
        tagline="モデルが本命を強く推すのに、まだ投票が集まっていないレースです。",
        lead=("対象：{n}レース（予測1着率55%以上かつ、発売票数の伸びが同時間帯の他レースより鈍い）。"
              "車券ごとのオッズは取得できていないため、レース全体の投票状況から見た簡易な目安です。"),
        entries=entries, empty_msg="本日は該当するレースがありません（投票の計測回数が足りない場合も含みます）。",
        current="value.html", date_str=_fmt_date_jp(date))


_OVERVIEW_SCRIPT = """
    window.addEventListener('DOMContentLoaded', function(){
      const table = document.getElementById('__TID__');
      if(!table) return;
      const tbody = table.tBodies[0];
      const ths = table.tHead.rows[0].cells;
      let sortCol = __COL__, sortDir = __DIR__;
      function cellVal(tr, i){
        const v = tr.cells[i].getAttribute('data-sort');
        return v === null ? tr.cells[i].textContent : v;
      }
      function applySort(){
        const rows = Array.from(tbody.rows);
        rows.sort(function(a, b){
          const x = cellVal(a, sortCol), y = cellVal(b, sortCol);
          // 「10:05」のような文字列を parseFloat で10と誤読しないよう、完全な数値表記のときだけ数値比較する
          const isNum = function(v){ return /^-?\\d+(\\.\\d+)?$/.test(String(v).trim()); };
          const cmp = (isNum(x) && isNum(y)) ? (parseFloat(x) - parseFloat(y)) : String(x).localeCompare(String(y), 'ja');
          return cmp * sortDir;
        });
        rows.forEach(function(r){ tbody.appendChild(r); });
        Array.from(ths).forEach(function(th, i){
          th.classList.toggle('sorted-asc', i === sortCol && sortDir === 1);
          th.classList.toggle('sorted-desc', i === sortCol && sortDir === -1);
        });
      }
      Array.from(ths).forEach(function(th, i){
        if(!th.hasAttribute('data-sortable')) return;
        th.style.cursor = 'pointer';
        th.addEventListener('click', function(){
          if(sortCol === i){ sortDir = -sortDir; } else { sortCol = i; sortDir = th.getAttribute('data-default-dir') === 'desc' ? -1 : 1; }
          applySort();
        });
      });
      function refilter(){
        const active = Array.from(document.querySelectorAll('.ov-filter.on')).map(function(b){ return b.getAttribute('data-flag'); });
        const q = (window.__ovSearch || '').toLowerCase();
        Array.from(tbody.rows).forEach(function(tr){
          const flags = (tr.getAttribute('data-flags') || '').split(' ');
          const okFlag = active.every(function(f){ return flags.indexOf(f) >= 0; });
          const okName = !q || (tr.getAttribute('data-name') || '').toLowerCase().indexOf(q) >= 0;
          tr.style.display = (okFlag && okName) ? '' : 'none';
        });
      }
      window.__ovRefilter = refilter;
      document.querySelectorAll('.ov-filter').forEach(function(btn){
        btn.addEventListener('click', function(){ btn.classList.toggle('on'); refilter(); });
      });
      applySort();
    });
"""


def render_overview_page(all_race_data, date=None):
    """
    本日の全レースを1つの表に並べた早見表。本命・予測1着率・1位2位の差・予測決まり手・
    各種フラグ（本命堅い／拮抗／妙味）を列にして、列見出しクリックで並べ替え、
    フラグボタンで絞り込みができる。「どのレースを見るか」を決めるための入口ページ。
    """
    rows_html = ""
    count = 0
    for rd in all_race_data:
        result = rd.get("prediction")
        if not result:
            continue
        count += 1
        info = rd["race_info"]
        top = result["top"]
        second = result["rows"][1] if len(result["rows"]) > 1 else None
        bg, fg = car_color(top["car"])
        flags = []
        badges = []
        if result.get("is_high_prob"):
            flags.append("high"); badges.append('<span class="ov-badge ov-high">堅</span>')
        if result.get("is_close_race"):
            flags.append("close"); badges.append('<span class="ov-badge ov-close">拮抗</span>')
        if info.get("odds_value_alert"):
            flags.append("value"); badges.append('<span class="ov-badge ov-value">妙味</span>')
        deadline = info.get("deadline") or ""
        gap = result.get("top_gap")
        second_pct = f"{second['adjusted']:.1f}%" if second else "—"
        gap_html = f"{gap:.1f}" if gap is not None else "—"
        venue_name = VENUE_NAMES.get(info["venue"], info["venue"])
        rows_html += f"""
        <tr data-flags="{' '.join(flags)}" data-deadline="{deadline}">
          <td data-sort="{venue_name}{info['race_no']:02d}"><a href="{info['venue']}/index.html?r={info['race_no']}">{venue_name} {info['race_no']}R</a></td>
          <td data-sort="{deadline or '99:99'}">{deadline or '—'}</td>
          <td data-sort="{top['car']}"><span class="car" style="background:{bg};color:{fg};">{top['car']}</span> {top['name']}</td>
          <td data-sort="{top['adjusted']:.2f}"><b>{top['adjusted']:.1f}%</b></td>
          <td data-sort="{second['adjusted'] if second else 0:.2f}">{second_pct}</td>
          <td data-sort="{gap if gap is not None else 999:.2f}">{gap_html}</td>
          <td data-sort="{KIMARITE_LABELS.get(top['dominant_type'], '-')}">{KIMARITE_LABELS.get(top['dominant_type'], '-')}</td>
          <td data-sort="{len(flags)}">{''.join(badges) or '<span class="dim">—</span>'}</td>
        </tr>"""

    style = """
  main.wide{ max-width:980px; }
  .ov-filters{ display:flex; flex-wrap:wrap; gap:6px; margin:0 0 10px; align-items:center; }
  .ov-filters .lbl{ font-size:12px; color:var(--ink-soft); }
  .ov-filter{ font-size:12px; padding:4px 10px; border:1px solid var(--border); border-radius:999px; background:#fff; color:var(--ink-soft); cursor:pointer; font-family:inherit; }
  .ov-filter.on{ background:var(--gold); border-color:var(--gold); color:#fff; font-weight:700; }
  .ov-scroll{ overflow-x:auto; }
  table.ov{ width:100%; border-collapse:collapse; font-size:13px; background:#fff; }
  table.ov th, table.ov td{ border:1px solid var(--border); padding:6px 8px; text-align:center; white-space:nowrap; }
  table.ov th{ background:var(--paper2); position:sticky; top:0; }
  table.ov th[data-sortable]:after{ content:" \\2195"; color:#b9b3a3; font-size:10px; }
  table.ov th.sorted-asc:after{ content:" \\25B2"; color:var(--brick); }
  table.ov th.sorted-desc:after{ content:" \\25BC"; color:var(--brick); }
  table.ov td:first-child, table.ov td:nth-child(3){ text-align:left; }
  table.ov td a{ color:var(--navy); text-decoration:underline; }
  table.ov tr.soon{ background:#fff4de; }
  table.ov tr.ended{ opacity:.45; }
  .ov-badge{ display:inline-block; font-size:10.5px; font-weight:700; border-radius:4px; padding:1px 6px; margin:0 2px; color:#fff; }
  .ov-high{ background:var(--brick); } .ov-close{ background:var(--slate); }
  .ov-value{ background:#8a5a12; }
"""
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>全レース早見表 | 競輪AI予想</title>
<style>
{COMMON_STYLE}{_AGG_STYLE}{style}
</style>
</head>
<body>
<header>
  <div class="top-row">
    <h1>&larr; <a href="index.html">全レース早見表</a></h1>
    <span class="date">{_fmt_date_jp(date)}</span>
  </div>
  <p class="tagline">今日の全レースを1枚で。見出しをタップで並べ替え、ボタンで絞り込み。</p>
  {gate_stripe_html()}
</header>
<main class="wide">
  {_agg_nav_html("overview.html")}
  <p class="hp-lead">対象：{count}レース（全競輪場・本日開催分）。「差」は予測1着率の1位と2位の差（pt）。</p>
  <div class="ov-filters"><span class="lbl">絞り込み:</span>
    <button type="button" class="ov-filter" data-flag="high">堅</button>
    <button type="button" class="ov-filter" data-flag="close">拮抗</button>
    <button type="button" class="ov-filter" data-flag="value">妙味</button>
  </div>
  <div class="ov-scroll">
    <table class="ov" id="ovTable">
      <thead><tr>
        <th data-sortable>レース</th><th data-sortable>締切</th><th data-sortable>本命</th>
        <th data-sortable data-default-dir="desc">本命1着率</th><th data-sortable data-default-dir="desc">2位</th>
        <th data-sortable>差</th><th data-sortable>予測決まり手</th><th data-sortable data-default-dir="desc">注目</th>
      </tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
  </div>
  {"" if count else "<p style='text-align:center;color:var(--ink-soft);'>本日は取得できたレースがありませんでした。</p>"}
</main>
<footer>このページはGitHub Actionsにより毎朝自動生成されています。予測はAIモデルによる参考情報であり、的中を保証するものではありません。</footer>
<script>{_AGG_SCRIPT}{_sortable_table_script("ovTable", 1, 1)}</script>
</body>
</html>"""


COURSE_STRONG_MIN_RACES = 5     # 「当地巧者」と呼ぶのに必要な当地での最低出走数
COURSE_STRONG_TOP3_RATE = 0.6   # 同、当地での3着内率の下限


def _sortable_table_script(table_id, init_col, init_dir):
    """列見出しクリックで並べ替え、.ov-filter ボタンで data-flags 絞り込みができる共通スクリプト。"""
    return (_OVERVIEW_SCRIPT
            .replace("__TID__", table_id)
            .replace("__COL__", str(init_col))
            .replace("__DIR__", str(init_dir)))


_TABLE_STYLE = """
  main.wide{ max-width:980px; }
  .ov-filters{ display:flex; flex-wrap:wrap; gap:6px; margin:0 0 10px; align-items:center; }
  .ov-filters .lbl{ font-size:12px; color:var(--ink-soft); }
  .ov-filter{ font-size:12px; padding:4px 10px; border:1px solid var(--border); border-radius:999px; background:#fff; color:var(--ink-soft); cursor:pointer; font-family:inherit; }
  .ov-filter.on{ background:var(--gold); border-color:var(--gold); color:#fff; font-weight:700; }
  .ov-search{ font-size:13px; padding:5px 10px; border:1px solid var(--border); border-radius:6px; font-family:inherit; width:150px; }
  .ov-scroll{ overflow-x:auto; }
  table.ov{ width:100%; border-collapse:collapse; font-size:13px; background:#fff; }
  table.ov th, table.ov td{ border:1px solid var(--border); padding:6px 8px; text-align:center; white-space:nowrap; }
  table.ov th{ background:var(--paper2); position:sticky; top:0; }
  table.ov th[data-sortable]:after{ content:" \\2195"; color:#b9b3a3; font-size:10px; }
  table.ov th.sorted-asc:after{ content:" \\25B2"; color:var(--brick); }
  table.ov th.sorted-desc:after{ content:" \\25BC"; color:var(--brick); }
  table.ov td.l{ text-align:left; }
  table.ov td a{ color:var(--navy); text-decoration:underline; }
  table.ov tr.soon{ background:#fff4de; }
  table.ov tr.ended{ opacity:.45; }
  .ov-badge{ display:inline-block; font-size:10.5px; font-weight:700; border-radius:4px; padding:1px 6px; margin:0 2px; color:#fff; }
  .ov-high{ background:var(--brick); } .ov-close{ background:var(--slate); }
  .ov-value{ background:#8a5a12; }
  .ov-up{ background:var(--pine); } .ov-down{ background:var(--brick); } .ov-home{ background:#8a5a12; }
"""


def _page_shell(*, title, heading, tagline, date_str, body, current, script="", extra_style="", wide=True):
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} | 競輪AI予想</title>
<style>
{COMMON_STYLE}{_AGG_STYLE}{_TABLE_STYLE}{extra_style}
</style>
</head>
<body>
<header>
  <div class="top-row">
    <h1>&larr; <a href="index.html">{heading}</a></h1>
    <span class="date">{date_str}</span>
  </div>
  <p class="tagline">{tagline}</p>
  {gate_stripe_html()}
</header>
<main{' class="wide"' if wide else ''}>
  {_agg_nav_html(current)}
  {body}
</main>
<footer>このページはGitHub Actionsにより自動生成されています。予測はAIモデルによる参考情報であり、的中を保証するものではありません。</footer>
<script>{_AGG_SCRIPT}{script}</script>
</body>
</html>"""


def render_players_page(all_race_data, date=None):
    """
    本日の出走選手を1人1行で並べた選手一覧。レース横断で「今日調子の上がっている選手」
    「当地(そのバンク)で強い選手」「名前での検索」ができる、選手目線の入口ページ。
    """
    rows_html = ""
    count = 0
    for rd in all_race_data:
        result = rd.get("prediction")
        if not result:
            continue
        info = rd["race_info"]
        venue_name = VENUE_NAMES.get(info["venue"], info["venue"])
        deadline = info.get("deadline") or ""
        for rank_in_race, r in enumerate(result["rows"], start=1):
            count += 1
            bg, fg = car_color(r["car"])
            flags, badges = [], []
            ft = r.get("form_trend")
            if ft and ft.get("trend") == "up":
                flags.append("up"); badges.append('<span class="ov-badge ov-up">調子↑</span>')
            elif ft and ft.get("trend") == "down":
                flags.append("down"); badges.append('<span class="ov-badge ov-down">調子↓</span>')
            cr = r.get("course_record")
            cr_txt = "—"
            cr_sort = -1
            if cr:
                cr_txt = f'{cr["races"]}走{cr["wins"]}勝{cr["top3"]}連対'
                cr_sort = cr["top3"] / cr["races"] if cr["races"] else -1
                if cr["races"] >= COURSE_STRONG_MIN_RACES and cr_sort >= COURSE_STRONG_TOP3_RATE:
                    flags.append("home"); badges.append('<span class="ov-badge ov-home">当地巧者</span>')
            rows_html += f"""
        <tr data-flags="{' '.join(flags)}" data-name="{r['name']}" data-deadline="{deadline}">
          <td class="l" data-sort="{r['name']}"><span class="car" style="background:{bg};color:{fg};">{r['car']}</span> {r['name']}</td>
          <td class="l" data-sort="{venue_name}{info['race_no']:02d}"><a href="{info['venue']}/index.html?r={info['race_no']}">{venue_name} {info['race_no']}R</a></td>
          <td data-sort="{deadline or '99:99'}">{deadline or '—'}</td>
          <td data-sort="{r['adjusted']:.2f}"><b>{r['adjusted']:.1f}%</b></td>
          <td data-sort="{rank_in_race}">{rank_in_race}位</td>
          <td>{r['rank']}</td>
          <td>{KIMARITE_LABELS.get(r['dominant_type'], '-')}</td>
          <td data-sort="{cr_sort:.3f}">{cr_txt}</td>
          <td data-sort="{len(flags)}">{''.join(badges) or '<span class="dim">—</span>'}</td>
        </tr>"""

    body = f"""
  <p class="hp-lead">対象：{count}人（全競輪場・本日開催分）。見出しタップで並べ替え。当地巧者＝当地で{COURSE_STRONG_MIN_RACES}走以上かつ3着内率{int(COURSE_STRONG_TOP3_RATE*100)}%以上。</p>
  <div class="ov-filters"><span class="lbl">絞り込み:</span>
    <button type="button" class="ov-filter" data-flag="up">調子↑</button>
    <button type="button" class="ov-filter" data-flag="down">調子↓</button>
    <button type="button" class="ov-filter" data-flag="home">当地巧者</button>
    <input type="search" id="ovSearch" class="ov-search" placeholder="選手名で検索">
  </div>
  <div class="ov-scroll">
    <table class="ov" id="plTable">
      <thead><tr>
        <th data-sortable>選手</th><th data-sortable>レース</th><th data-sortable>締切</th>
        <th data-sortable data-default-dir="desc">予測1着率</th><th data-sortable>レース内順位</th>
        <th>級班</th><th>予測決まり手</th><th data-sortable data-default-dir="desc">当地成績</th>
        <th data-sortable data-default-dir="desc">注目</th>
      </tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
  </div>
  {"" if count else "<p style='text-align:center;color:var(--ink-soft);'>本日は取得できたレースがありませんでした。</p>"}"""
    search_js = """
    window.addEventListener('DOMContentLoaded', function(){
      const box = document.getElementById('ovSearch');
      if(!box) return;
      box.addEventListener('input', function(){
        window.__ovSearch = box.value.trim();
        if(window.__ovRefilter) window.__ovRefilter();
      });
    });
"""
    return _page_shell(
        title="本日の出走選手一覧", heading="本日の出走選手", date_str=_fmt_date_jp(date),
        tagline="今日走る全選手を1枚で。調子・当地成績・予測1着率でさがせます。",
        body=body, current="players.html",
        script=_sortable_table_script("plTable", 3, -1) + search_js)


def render_venues_today_page(all_race_data, date=None):
    """
    本日の開催場ごとのサマリ。レース数、本命の予測1着率の平均、堅い／拮抗のレース数、
    予測決まり手の構成（全レース平均）、バンク周長を1行にまとめ、「今日どの場が堅いか／荒れそうか」
    を比べられるようにする。
    """
    by_venue = {}
    for rd in all_race_data:
        if rd.get("prediction"):
            by_venue.setdefault(rd["race_info"]["venue"], []).append(rd)

    rows_html = ""
    for venue, rds in by_venue.items():
        n = len(rds)
        avg_top = sum(r["prediction"]["top"]["adjusted"] for r in rds) / n
        n_high = sum(1 for r in rds if r["prediction"].get("is_high_prob"))
        n_close = sum(1 for r in rds if r["prediction"].get("is_close_race"))
        gaps = [r["prediction"]["top_gap"] for r in rds if r["prediction"].get("top_gap") is not None]
        avg_gap = sum(gaps) / len(gaps) if gaps else 0.0
        kim = {t: sum(r["prediction"]["kimarite_ratio"].get(t, 0) for r in rds) / n for t in KIMARITE}
        d = VENUE_BANK_DATA.get(venue, {})
        bclass = bank_class(d.get("circumference")) or "—"
        name = VENUE_NAMES.get(venue, venue)
        kim_cells = "".join(f'<td data-sort="{kim[t]:.1f}">{kim[t]:.0f}%</td>' for t in KIMARITE)
        rows_html += f"""
        <tr>
          <td class="l" data-sort="{name}"><a href="{venue}/index.html">{name}</a></td>
          <td data-sort="{n}">{n}</td>
          <td data-sort="{avg_top:.2f}"><b>{avg_top:.1f}%</b></td>
          <td data-sort="{avg_gap:.2f}">{avg_gap:.1f}</td>
          <td data-sort="{n_high}">{n_high}</td>
          <td data-sort="{n_close}">{n_close}</td>
          {kim_cells}
          <td data-sort="{bclass}">{bclass}</td>
        </tr>"""

    kim_heads = "".join(f'<th data-sortable data-default-dir="desc">{KIMARITE_LABELS[t]}</th>' for t in KIMARITE)
    body = f"""
  <p class="hp-lead">対象：{len(by_venue)}場（本日開催分）。「本命平均」は各レースの本命の予測1着率の平均、「差」は1位と2位の差の平均です。
  数字が大きいほど本命が堅く、小さいほど混戦気味の開催場です。決まり手は各レースの予測構成の平均です。</p>
  <div class="ov-scroll">
    <table class="ov" id="vtTable">
      <thead><tr>
        <th data-sortable>競輪場</th><th data-sortable data-default-dir="desc">レース数</th>
        <th data-sortable data-default-dir="desc">本命平均</th><th data-sortable data-default-dir="desc">差(平均)</th>
        <th data-sortable data-default-dir="desc">堅</th><th data-sortable data-default-dir="desc">拮抗</th>
        {kim_heads}<th data-sortable>バンク</th>
      </tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
  </div>
  {"" if by_venue else "<p style='text-align:center;color:var(--ink-soft);'>本日は取得できたレースがありませんでした。</p>"}"""
    return _page_shell(
        title="開催場別サマリ", heading="開催場別サマリ", date_str=_fmt_date_jp(date),
        tagline="今日どの開催場が堅いか、荒れそうかを横並びで比較。",
        body=body, current="venues_today.html", script=_sortable_table_script("vtTable", 2, -1))


def render_results_page(log, date=None, model_params=None):
    """
    予想成績ページ。prediction_log に溜めた「予想」と「確定結果」から、
    本命が実際に何%勝ったか／予測1着率は実際と合っているか（キャリブレーション）／
    堅い・拮抗の区分ごとの成績／日別の成績／直近の答え合わせ を表示する。
    サンプルが少ないうちは数字がブレるため、件数を必ず併記する。
    """
    from prediction_log import compute_prediction_stats
    stats = compute_prediction_stats(log or {})
    ov = stats["overall"]

    # モデルの毎日の自動補正の状況（calibration.py）
    mp = model_params or {}
    n_cal = mp.get("n", 0)
    min_cal = mp.get("min_races", 120)
    if mp.get("active"):
        cal_line = (f'<b>適用中</b>：1着率の絞り込み {mp.get("default", 0):.2f} → <b>{mp["sharpness_first"]:.2f}</b>'
                    f'（補正に使った{n_cal}レース／1レースあたり対数尤度 {mp.get("ll_per_race_default", 0):.3f} → {mp.get("ll_per_race_new", 0):.3f}、大きいほど良い）')
    else:
        cal_line = f'<b>学習中</b>：補正に使えるレースが{n_cal}件（{min_cal}件以上で適用開始。それまでは基準値のまま）'
    model_html = (f'<div class="hp-lead" style="margin-top:8px;">モデルの自動補正（毎日1回）：{cal_line}'
                  f'<br><span class="dim">更新日 {mp.get("updated", "—")}。各選手の予測を記録したレースの答え合わせから、1着率の絞り込みの強さだけを見直します。</span></div>')

    def pct(v):
        return f"{v:.1f}%"

    def tile(label, value, sub=""):
        return (f'<div class="rs-tile"><div class="rs-label">{label}</div><div class="rs-value">{value}</div>'
                f'<div class="rs-sub">{sub}</div></div>')

    if ov["n"]:
        tiles = "".join([
            tile("本命の1着率", pct(ov["top1"]), f"予測の平均 {pct(ov['pred_top'])}"),
            tile("本命の連対率(2着以内)", pct(ov["top2"])),
            tile("本命の3着内率", pct(ov["top3"])),
            tile("予想上位3車ボックス", pct(ov["box3"]), "3連複の的中率"),
            tile("3連単 予想1位の組合せ", pct(ov["tri1"]), f"上位5点なら {pct(ov['tri5'])}"),
        ])
        low_note = ("<p class='hp-lead'>※ 件数が少ないうちは数字が大きくブレます（目安：100レース以上で傾向が見えてきます）。</p>"
                    if ov["n"] < 100 else "")
        summary = f'<p class="hp-lead">集計対象：結果が確定した{ov["n"]}レース（結果待ち{stats["pending_count"]}件）。</p>{low_note}<div class="rs-tiles">{tiles}</div>{model_html}'
    else:
        summary = (f'<p class="hp-lead">まだ結果が確定したレースがありません（記録中：{stats["tracked_count"]}レース、'
                   f'結果待ち{stats["pending_count"]}件）。予想は毎時の自動実行のたびに記録され、締切後に結果と照合されます。</p>{model_html}')

    def seg_row(label, s):
        if not s["n"]:
            return f'<tr><td class="l">{label}</td><td>0</td><td colspan="5" class="dim">—</td></tr>'
        return (f'<tr><td class="l">{label}</td><td>{s["n"]}</td><td>{pct(s["pred_top"])}</td>'
                f'<td><b>{pct(s["top1"])}</b></td><td>{pct(s["top3"])}</td><td>{pct(s["box3"])}</td><td>{pct(s["tri5"])}</td></tr>')

    seg = stats["segments"]
    seg_html = f"""
  <h2 class="section">区分ごとの成績</h2>
  <div class="ov-scroll"><table class="ov"><thead><tr>
    <th>区分</th><th>件数</th><th>本命予測の平均</th><th>本命1着率</th><th>本命3着内</th><th>3連複BOX</th><th>3連単上位5点</th>
  </tr></thead><tbody>
    {seg_row("本命が堅い", seg["high"])}{seg_row("拮抗", seg["close"])}{seg_row("その他", seg["other"])}
  </tbody></table></div>"""

    cal_rows = ""
    for c in stats["calibration"]:
        if not c["n"]:
            cal_rows += f'<tr><td class="l">{c["label"]}</td><td>0</td><td colspan="3" class="dim">—</td></tr>'
            continue
        diff = c["top1"] - c["pred_top"]
        cls = "delta-up" if diff >= 0 else "delta-down"
        cal_rows += (f'<tr><td class="l">{c["label"]}</td><td>{c["n"]}</td><td>{pct(c["pred_top"])}</td>'
                     f'<td><b>{pct(c["top1"])}</b></td><td><span class="{cls}">{diff:+.1f}pt</span></td></tr>')
    cal_html = f"""
  <h2 class="section">予測1着率は当たっているか（本命の予測1着率の帯ごと）</h2>
  <p class="hp-lead">「予測の平均」と「実際の1着率」が近いほど、数字を信用できます。件数が少ない帯は参考程度に。</p>
  <div class="ov-scroll"><table class="ov"><thead><tr>
    <th>本命の予測1着率</th><th>件数</th><th>予測の平均</th><th>実際の1着率</th><th>差</th>
  </tr></thead><tbody>{cal_rows}</tbody></table></div>"""

    day_rows = "".join(
        f'<tr><td class="l">{d["date"]}</td><td>{d["n"]}</td><td><b>{pct(d["top1"])}</b></td><td>{pct(d["top3"])}</td><td>{pct(d["box3"])}</td></tr>'
        for d in stats["by_day"][:14])
    day_html = f"""
  <h2 class="section">日別の成績（直近14日）</h2>
  <div class="ov-scroll"><table class="ov"><thead><tr>
    <th>日付</th><th>件数</th><th>本命1着率</th><th>本命3着内</th><th>3連複BOX</th>
  </tr></thead><tbody>{day_rows or '<tr><td colspan="5" class="dim">—</td></tr>'}</tbody></table></div>""" if stats["by_day"] else ""

    recent_rows = ""
    for e in stats["recent"][:30]:
        fin = e["result"]["finish_order"]
        top = e["order"][0]
        mark = "◎" if fin[0] == top else ("○" if top in fin[:3] else "×")
        mcls = "delta-up" if mark != "×" else "delta-down"
        venue_name = VENUE_NAMES.get(e["venue"], e["venue"])
        tri = e["trifecta"][0] if e["trifecta"] else None
        tri_txt = "-".join(map(str, tri)) if tri else "—"
        tri_hit = " 的中" if tri and tri == fin[:3] else ""
        recent_rows += (f'<tr><td class="l">{e["date"][5:]} {venue_name} {e["race_no"]}R</td>'
                        f'<td>{top}</td><td><span class="{mcls}"><b>{mark}</b></span></td>'
                        f'<td>{"-".join(map(str, fin[:3]))}</td><td>{tri_txt}{tri_hit}</td></tr>')
    recent_html = f"""
  <h2 class="section">直近の答え合わせ（新しい順・最大30件）</h2>
  <p class="hp-lead">◎＝本命が1着、○＝本命が3着以内、×＝圏外。</p>
  <div class="ov-scroll"><table class="ov"><thead><tr>
    <th>レース</th><th>本命</th><th>結果</th><th>確定(1-2-3着)</th><th>予想の3連単1位</th>
  </tr></thead><tbody>{recent_rows}</tbody></table></div>""" if recent_rows else ""

    style = """
  main.wide{ max-width:820px; }
  h2.section{ font-size:14px; color:var(--ink-soft); margin:22px 0 8px; }
  .rs-tiles{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:8px; margin:0 0 6px; }
  .rs-tile{ background:#fff; border:1px solid var(--border); border-radius:8px; padding:10px 12px; }
  .rs-label{ font-size:11.5px; color:var(--ink-soft); }
  .rs-value{ font-size:22px; font-weight:800; color:var(--brick); margin-top:2px; font-variant-numeric:tabular-nums; }
  .rs-sub{ font-size:11px; color:var(--ink-soft); margin-top:2px; min-height:14px; }
  .delta-up{ color:var(--pine); } .delta-down{ color:var(--brick); }
"""
    return _page_shell(
        title="予想成績", heading="予想成績", date_str=_fmt_date_jp(date),
        tagline="AIの予想は実際どれくらい当たったか。毎時自動で記録して答え合わせしています。",
        body=summary + seg_html + cal_html + day_html + recent_html,
        current="results.html", extra_style=style)


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


# ============================================================
# 印刷用ページ（A4で紙に出す／PDFに保存する用）
# ============================================================
_PRINT_STYLE = """
  main.wide{ max-width:1000px; }
  .pv-controls{ background:var(--paper2); border:1px solid #d8d2c4; border-radius:10px; padding:12px; margin:10px 0 14px; }
  .pv-controls h3{ margin:0 0 6px; font-size:14px; }
  .pv-row{ display:flex; flex-wrap:wrap; gap:6px 14px; align-items:center; margin:6px 0; font-size:13px; }
  .pv-row label{ display:inline-flex; align-items:center; gap:4px; }
  .pv-vchips{ display:flex; flex-wrap:wrap; gap:6px; }
  .pv-vchips label{ border:1px solid #bbb; border-radius:999px; padding:6px 12px; background:#fff; min-height:34px; }
  .pv-controls select, .pv-controls button{ font:inherit; font-size:14px; padding:8px 12px; border-radius:8px; border:1px solid #999; background:#fff; }
  .pv-print-btn{ background:#1f3a5f !important; color:#fff !important; border-color:#1f3a5f !important; font-weight:700; padding:10px 18px !important; }
  .pv-hint{ font-size:12px; color:#666; margin:6px 0 0; line-height:1.6; }
  .pv-venue{ margin:0 0 14px; }
  .pv-venue > h2{ font-size:16px; margin:12px 0 6px; padding:4px 8px; border-left:5px solid #1f3a5f; background:#f1efe8; }
  .pv-grid{ display:grid; grid-template-columns:1fr; gap:12px; }
  .pv-grid.two{ grid-template-columns:repeat(2, minmax(0,1fr)); gap:8px; }
  .pv-grid.two .pv-opt, .pv-grid.two .pv-mxwrap{ display:none; }
  .pv-card{ border:1.5px solid #333; border-radius:5px; padding:8px 10px; background:#fff; color:#111; break-inside:avoid; page-break-inside:avoid; font-size:12.5px; }
  .pv-head{ display:flex; justify-content:space-between; align-items:baseline; gap:8px; border-bottom:2px solid #111; padding-bottom:3px; margin-bottom:5px; }
  .pv-head b{ font-size:19px; }
  .pv-head .pv-t{ font-size:13px; color:#222; }
  .pv-flags span{ display:inline-block; border:1.5px solid #111; border-radius:4px; padding:0 6px; font-size:12px; font-weight:700; margin-left:4px; }
  .pv-sub{ font-size:12px; color:#222; margin:2px 0; line-height:1.55; }
  .pv-sub b{ font-weight:700; }
  table.pv-t{ width:100%; border-collapse:collapse; font-size:12px; margin-top:5px; }
  table.pv-t th, table.pv-t td{ border:1px solid #aaa; padding:3px 4px; text-align:center; line-height:1.35; white-space:nowrap; }
  table.pv-t th{ background:#e9e9e9; font-weight:700; font-size:11px; }
  table.pv-t td.nm{ text-align:left; }
  table.pv-t td.pv-note{ font-size:10.5px; white-space:normal; line-height:1.25; }
  table.pv-t tr.top td{ font-weight:700; background:#f3f3f3; }
  table.pv-t td.hl{ font-weight:700; }
  .pv-car{ display:inline-block; min-width:20px; border-radius:4px; border:1px solid #333; font-weight:700; }
  .pv-mid{ display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1.3fr); gap:10px; margin-top:7px; }
  .pv-grid.two .pv-mid{ grid-template-columns:1fr; }
  .pv-box{ border:1px solid #aaa; border-radius:4px; padding:3px 6px; }
  .pv-box-t{ font-size:11.5px; font-weight:700; color:#222; border-bottom:1px solid #ccc; margin-bottom:2px; }
  .pv-tri{ font-size:12px; display:grid; grid-template-columns:1fr 1fr; gap:0 14px; }
  .pv-tri div{ display:flex; justify-content:space-between; border-bottom:1px dotted #bbb; line-height:1.55; }
  .pv-head-row{ font-size:12px; line-height:1.6; }
  .pv-mxwrap{ margin-top:9px; }
  .pv-mxhead{ display:none; font-size:15px; font-weight:700; margin-bottom:6px; padding-bottom:3px; border-bottom:2px solid #111; }
  .pv-mxtitle{ font-size:12.5px; font-weight:700; margin-bottom:4px; padding-bottom:2px; border-bottom:2px solid #333; }
  .pv-mxgrid{ display:grid; grid-template-columns:repeat(2, minmax(0,1fr)); gap:10px 12px; }
  .pv-mx{ break-inside:avoid; page-break-inside:avoid; }
  .pv-mx-h{ font-size:12px; font-weight:700; margin-bottom:2px; }
  table.pv-m{ width:100%; border-collapse:collapse; font-size:11.5px; table-layout:fixed; }
  table.pv-m th, table.pv-m td{ border:1px solid #bbb; text-align:center; padding:2px 0; line-height:1.3; }
  table.pv-m th{ background:#ececec; font-size:11px; }
  table.pv-m td.dg{ background:#d8d8d8; }
  table.pv-m td.sum, table.pv-m th.sum{ background:#f1f1f1; font-weight:700; }
  table.pv-m td.v1{ background:#e8e8e8; } table.pv-m td.v2{ background:#cfcfcf; font-weight:700; } table.pv-m td.v3{ background:#a8a8a8; font-weight:700; }
  table.pv-t td.sm{ font-size:10.5px; }
  table.pv-t td.pv-rc{ text-align:left; font-size:10px; line-height:1.4; white-space:normal; background:#fafafa; border-top:none; }
  table.pv-t td.pv-rc b{ font-weight:700; }
  table.pv-t td.pv-rc .cm{ color:#111; }
  .pv-pref{ font-size:9.5px; color:#444; font-weight:400; }
  .pv-mix{ display:grid; grid-template-columns:repeat(4, minmax(0,1fr)); gap:0 10px; }
  .pv-mix .pv-box-t{ font-size:11px; }
  .pv-tickets{ margin-top:7px; display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1.5fr); gap:10px; }
  .pv-grid.two .pv-tickets{ grid-template-columns:1fr; }
  .pv-view{ border:1.5px solid #333; border-radius:4px; padding:4px 8px; margin-top:6px; font-size:12.5px; line-height:1.65; background:#f8f8f8; }
  .pv-view b.t{ font-size:12px; border:1px solid #111; border-radius:3px; padding:0 5px; margin-right:6px; }
  .pv-form{ font-size:11px; margin-top:3px; border-top:1px dotted #999; padding-top:2px; }
  .pv-memo{ margin-top:7px; border-top:1px dashed #888; min-height:20px; font-size:11px; color:#777; }
  .pv-mxnote{ font-size:10.5px; color:#555; margin-top:3px; }
  @media print{
    @page{ size:A4; margin:8mm; }
    html, body{ background:#fff !important; }
    header, footer, nav.tab-strip, .pv-controls, .gate-stripe{ display:none !important; }
    main, main.wide{ max-width:none !important; padding:0 !important; margin:0 !important; }
    .pv-venue{ break-before:page; page-break-before:always; margin:0; }
    .pv-venue:first-of-type{ break-before:auto; page-break-before:auto; }
    .pv-venue > h2{ margin-top:0; }
    .pv-car, table.pv-m td, table.pv-m th, table.pv-t th, table.pv-t td{ -webkit-print-color-adjust:exact; print-color-adjust:exact; }
    .pv-grid.mxon .pv-card + .pv-card{ break-before:page; page-break-before:always; }
    .pv-grid.mxon .pv-mxwrap{ break-before:page; page-break-before:always; }
    .pv-grid.mxon .pv-mxhead{ display:block !important; }
    .pv-grid.mxon .pv-mxtitle{ display:none; }
    .pv-grid.mxon{ gap:0; }
    .pv-card{ margin:0; }
    .pv-card{ border-color:#000; }
  }
"""

_PRINT_SCRIPT = """
(function(){
  var cards = Array.prototype.slice.call(document.querySelectorAll('.pv-card'));
  var venues = Array.prototype.slice.call(document.querySelectorAll('.pv-venue'));
  function nowHM(){ var d=new Date(); return ('0'+d.getHours()).slice(-2)+':'+('0'+d.getMinutes()).slice(-2); }
  function apply(){
    var chosen = {};
    document.querySelectorAll('.pv-vchk').forEach(function(c){ chosen[c.value] = c.checked; });
    var flag = document.getElementById('pvFlag').value;
    var future = document.getElementById('pvFuture').checked;
    var ntri = parseInt(document.getElementById('pvTri').value, 10);
    var two = document.getElementById('pvCols').value === '2';
    var thr = parseFloat(document.getElementById('pvMx').value);
    var hm = nowHM();
    cards.forEach(function(card){
      var ok = chosen[card.dataset.venue] !== false;
      if (ok && flag !== 'all') ok = (' ' + card.dataset.flags + ' ').indexOf(' ' + flag + ' ') >= 0;
      if (ok && future && card.dataset.deadline && card.dataset.deadline < hm) ok = false;
      card.style.display = ok ? '' : 'none';
      card.querySelectorAll('.pv-tri div').forEach(function(d, i){ d.style.display = i < ntri ? '' : 'none'; });
      var shown = 0;
      card.querySelectorAll('.pv-mx').forEach(function(m){
        var show = parseFloat(m.dataset.p1) >= thr;
        m.style.display = show ? '' : 'none'; if (show) shown++;
      });
      var wrap = card.querySelector('.pv-mxwrap'); if (wrap) wrap.dataset.shown = shown;
    });
    venues.forEach(function(v){
      var any = Array.prototype.some.call(v.querySelectorAll('.pv-card'), function(c){ return c.style.display !== 'none'; });
      v.style.display = any ? '' : 'none';
      var g = v.querySelector('.pv-grid');
      if (g){ g.classList.toggle('two', two); g.classList.toggle('mxon', !two && thr < 999); }
    });
    document.querySelectorAll('.pv-mxwrap').forEach(function(w){ w.style.display = (thr >= 999) ? 'none' : ''; });
  }
  document.querySelectorAll('.pv-controls input, .pv-controls select').forEach(function(el){ el.addEventListener('change', apply); });
  document.getElementById('pvAll').addEventListener('click', function(){ document.querySelectorAll('.pv-vchk').forEach(function(c){ c.checked = true; }); apply(); });
  document.getElementById('pvNone').addEventListener('click', function(){ document.querySelectorAll('.pv-vchk').forEach(function(c){ c.checked = false; }); apply(); });
  document.getElementById('pvPrint').addEventListener('click', function(){ apply(); window.print(); });
  apply();
})();
"""

_AI_MARKS = ["◎", "○", "▲", "△"]


def _lines_label(rows):
    """出走表の並び（ライン）を「1-2-3 ／ 4-5 ／ 6」の形で表す（ラインは並び予想の順、単騎は最後）。"""
    lines, singles = {}, []
    for r in rows:
        li = r.get("line_info")
        if li:
            lines.setdefault(li["line_index"], []).append((li["position"], r["car"]))
        else:
            singles.append(r["car"])
    parts = ["-".join(str(c) for _, c in sorted(lines[k])) for k in sorted(lines)]
    parts += [str(c) for c in sorted(singles)]
    return " ／ ".join(parts)


def _mx_class(v):
    return "v3" if v >= 3.0 else ("v2" if v >= 1.5 else ("v1" if v >= 0.7 else ""))


def _head_matrix_html(result, head_row, cars):
    """1着=head の出目確率表。縦=2着、横=3着、セルは3連単の確率(%)、右端は「その2着になる確率の合計」。"""
    y = head_row["car"]
    p1 = head_row["adjusted"]
    sec = {c["car"]: c["prob"] / 100 for c in (result.get("second_place_matrix") or {}).get(y, [])}
    thirds = (result.get("full_third_place_data") or {}).get(y, {})
    others = [c for c in cars if c != y]
    head = "".join(f'<th>{c}</th>' for c in others)
    body = ""
    for z in others:
        p2 = sec.get(z, 0.0)
        t = {c["car"]: c["prob"] / 100 for c in thirds.get(z, [])}
        cells = ""
        for w in others:
            if w == z:
                cells += '<td class="dg"></td>'
                continue
            v = p1 * p2 * t.get(w, 0.0)  # p1は%なので、結果も%
            cells += f'<td class="{_mx_class(v)}">{v:.1f}</td>' if v >= 0.05 else '<td>-</td>'
        body += f'<tr><th>{z}</th>{cells}<td class="sum">{p1 * p2:.1f}</td></tr>'
    bg, fg = car_color(y)
    return (f'<div class="pv-mx" data-p1="{p1:.2f}"><div class="pv-mx-h"><span class="pv-car" style="background:{bg};color:{fg};">{y}</span>'
            f' {head_row["name"]}　1着 {p1:.1f}%　<span style="font-weight:400">（縦＝2着／横＝3着）</span></div>'
            f'<table class="pv-m"><tr><th></th>{head}<th class="sum">2着計</th></tr>{body}</table></div>')


_KIND_SHORT = [("チャレンジ", "チャ"), ("Ａ級", "A"), ("Ｓ級", "S"), ("Ｂ級", "B"), ("準決勝", "準決"), ("決勝", "決"),
               ("予選", "予"), ("特選", "特"), ("選抜", "選"), ("一般", "一"), ("初日", "初"), ("ガールズ", "G")]


def _recent_txt(items):
    """日別成績を「10/4 A予6」のような短い表記に。"""
    out = []
    for it in items:
        kind = it.get("kind", "")
        for a, b in _KIND_SHORT:
            kind = kind.replace(a, b)
        fin = it.get("finish", "")
        fin = fin[:-1] if fin.endswith("着") else fin
        out.append(f'{it.get("date", "")} {kind}<b>{fin}</b>')
    return " ／ ".join(out)


def _rider_comment(r, rank, pos, kp):
    """データから作る短い一言コメント（紙面用）。"""
    bits = []
    if rank == 0:
        bits.append("AIの本命")
    elif rank == 1:
        bits.append("対抗格")
    li = r.get("line_info")
    if li and li.get("line_size", 1) > 1:
        bits.append(f'{li["line_size"]}車ラインの{pos}')
    else:
        bits.append("単騎")
    if kp.get("type") and kp.get("ratio", 0) >= 0.38:
        bits.append(f'{kp["type"]}中心({kp["ratio"] * 100:.0f}%)')
    ft = r.get("form_trend")
    if ft and ft.get("trend") == "up":
        bits.append("調子上向き")
    elif ft and ft.get("trend") == "down":
        bits.append("調子下降気味")
    cr = r.get("course_record")
    if cr and cr.get("wins", 0) >= 2:
        bits.append(f'当地{cr["wins"]}勝')
    rv = r.get("rivalry_summary")
    if rv and rv.get("avg_win_rate", 0.5) >= 0.6:
        bits.append("このメンバーに相性良")
    return "、".join(bits[:4])


def _ticket_lists(result):
    """3連単の全組み合わせ確率から、2車単・2車複・ワイド・3連複の確率上位を作る。"""
    combos = (result.get("trifecta") or {}).get("combos", [])
    ni, nf, wd, tr3 = {}, {}, {}, {}
    for c in combos:
        f, s_, t, pr = c["first"], c["second"], c["third"], c["prob"]
        ni[(f, s_)] = ni.get((f, s_), 0) + pr
        k2 = tuple(sorted((f, s_)))
        nf[k2] = nf.get(k2, 0) + pr
        k3 = tuple(sorted((f, s_, t)))
        tr3[k3] = tr3.get(k3, 0) + pr
        for pair in ((f, s_), (f, t), (s_, t)):
            kk = tuple(sorted(pair))
            wd[kk] = wd.get(kk, 0) + pr
    def top(d, n, sep):
        return [(sep.join(str(x) for x in k), v) for k, v in sorted(d.items(), key=lambda kv: -kv[1])[:n]]
    return {"2車単": top(ni, 5, "→"), "2車複": top(nf, 5, "-"), "ワイド": top(wd, 5, "-"), "3連複": top(tr3, 5, "-")}


def _formation_text(result):
    """AI上位から組む3連単フォーメーション（1着:上位2車／2着:上位4車／3着:上位5車）の点数と的中確率。"""
    rows = result["rows"]
    order = [r["car"] for r in rows]
    if len(order) < 5:
        return ""
    f1, f2, f3 = set(order[:2]), set(order[:4]), set(order[:5])
    pts, prob = 0, 0.0
    for c in (result.get("trifecta") or {}).get("combos", []):
        if c["first"] in f1 and c["second"] in f2 and c["third"] in f3 and len({c["first"], c["second"], c["third"]}) == 3:
            pts += 1
            prob += c["prob"]
    def j(x):
        return "".join(str(c) for c in order[:x])
    return (f'フォーメーション例：1着 {j(2)} ／ 2着 {j(4)} ／ 3着 {j(5)}（{pts}点・的中確率の目安 {prob:.1f}%）')


def _view_text(result, rows, flags):
    """レース全体の見立て（自動文）。"""
    marks = [f'{_AI_MARKS[i]}{r["car"]}' for i, r in enumerate(rows[:4])]
    top = rows[0]
    parts = [f'本命は <b>{top["car"]}番 {top["name"]}</b>（1着{top["adjusted"]:.0f}%、3着内{top.get("place_rate", 0):.0f}%）。']
    if len(rows) > 1:
        parts.append(f'対抗以下は {" ".join(marks[1:])}。')
    if "high" in flags:
        parts.append("抜けた本命がいる堅めの一戦。")
    elif "close" in flags:
        parts.append("3着内率で抜けた選手がいない混戦。ヒモ荒れに注意。")
    kr = result.get("kimarite_ratio") or {}
    if kr:
        k, v = max(kr.items(), key=lambda kv: kv[1])
        parts.append(f'決まり手は{k}が中心（{v:.0f}%）。')
    dev = (result.get("development_simulation") or {}).get("scenarios") or []
    if dev:
        parts.append(f'展開は「{dev[0]["label"]}」（{dev[0]["share"]:.0f}%）が最有力。')
    return " ".join(parts)


def _print_card_html(rd):
    result = rd.get("prediction")
    if not result:
        return ""
    info = rd["race_info"]
    rows = result["rows"]
    by_rank = {r["car"]: i for i, r in enumerate(rows)}
    slug = result.get("venue_slug") or info["venue"]
    venue_name = VENUE_NAMES.get(info["venue"], info["venue"])
    deadline = info.get("deadline") or ""

    flags, flag_html = [], []
    if result.get("is_high_prob"):
        flags.append("high"); flag_html.append("<span>本命堅い</span>")
    if result.get("is_close_race"):
        flags.append("close"); flag_html.append("<span>拮抗</span>")
    if info.get("odds_value_alert"):
        flags.append("value"); flag_html.append("<span>妙味</span>")

    bank = VENUE_BANK_DATA.get(slug) or {}
    bank_bits = []
    if bank.get("circumference"):
        bank_bits.append(f'周長{bank["circumference"]}')
    if bank.get("literal_straight"):
        bank_bits.append(f'直線{bank["literal_straight"]}m')
    tend = straight_tendency(bank.get("literal_straight")) if bank.get("literal_straight") else None
    if tend:
        bank_bits.append(tend)
    vavg = kimarite_venue_average(slug) or {}
    if vavg:
        bank_bits.append("場平均(1着) " + " ".join(f'{t}{vavg[t]:.0f}%' for t in ("逃", "捲", "差", "マ") if t in vavg))
    bank_html = f'<div class="pv-sub pv-opt">バンク：{" ／ ".join(bank_bits)}</div>' if bank_bits else ""

    ratio = result.get("kimarite_ratio") or {}
    ratio_txt = " ".join(f'{t}{ratio[t]:.0f}%' for t in ("逃", "捲", "差", "マ") if t in ratio)
    mr = result.get("most_reliable")
    sub = f'並び：<b>{_lines_label(rows)}</b>'
    if ratio_txt:
        sub += f'　／　予測の決まり手 {ratio_txt}'
    if mr:
        sub += f'　／　信頼度で選ぶなら <b>{mr["car"]}番</b>'

    first_p = {r["car"]: r["adjusted"] / 100 for r in rows}
    second_m = {r["car"]: 0.0 for r in rows}
    for y, cands in (result.get("second_place_matrix") or {}).items():
        for c in cands:
            second_m[c["car"]] = second_m.get(c["car"], 0.0) + first_p.get(y, 0.0) * c["prob"] / 100

    def num(v, fmt="{:.1f}"):
        return fmt.format(v) if isinstance(v, (int, float)) else "-"

    trs = ""
    for r in sorted(rows, key=lambda x: x["car"]):
        rank = by_rank[r["car"]]
        bg, fg = car_color(r["car"])
        ai = _AI_MARKS[rank] if rank < len(_AI_MARKS) else ""
        li = r.get("line_info")
        pos = "単騎" if not li or li.get("line_size", 1) == 1 else ("先頭" if li["position"] == 1 else f'{li["position"]}番手')
        kim = r.get("kimarite") or {}
        kp = r.get("kimarite_prediction") or {}
        w1 = r["adjusted"]
        w2 = second_m.get(r["car"], 0.0) * 100
        w3 = max(r.get("place_rate", 0) - w1 - w2, 0.0)
        age = r.get("age"); per = r.get("period")
        prof = f'{r.get("pref") or ""} {int(age) if age else ""}歳/{int(per) if per else ""}期'.strip()
        rc_bits = []
        rec = r.get("recent") or {}
        if rec.get("now"):
            rc_bits.append(f'<b>今場所</b> {_recent_txt(rec["now"])}')
        if rec.get("prev"):
            rc_bits.append(f'<b>前場所{("(" + rec["prev_venue"] + ")") if rec.get("prev_venue") else ""}</b> {_recent_txt(rec["prev"])}')
        if rec.get("prev2"):
            rc_bits.append(f'<b>前々場所{("(" + rec["prev2_venue"] + ")") if rec.get("prev2_venue") else ""}</b> {_recent_txt(rec["prev2"])}')
        cr = r.get("course_record")
        if cr:
            rc_bits.append(f'<b>当地</b> {cr["races"]}走{cr["wins"]}勝{cr["top3"]}連対')
        ft = r.get("form_trend")
        if ft and ft.get("trend") in ("up", "down"):
            rc_bits.append("調子" + ("↑" if ft["trend"] == "up" else "↓"))
        fin = r.get("finishes") or {}
        rc_bits.append(f'<b>通算</b> {fin.get("f1", 0)}-{fin.get("f2", 0)}-{fin.get("f3", 0)}-{fin.get("fo", 0)}')
        comment = _rider_comment(r, rank, pos, kp)
        rc_html = " ｜ ".join(rc_bits)
        trs += (f'<tr class="{"top" if rank == 0 else ""}">'
                f'<td><span class="pv-car" style="background:{bg};color:{fg};">{r["car"]}</span></td>'
                f'<td>{r.get("mark") or ""}</td><td>{ai}</td>'
                f'<td class="nm">{r["name"]}<br><span class="pv-pref">{prof}</span></td>'
                f'<td>{r.get("rank") or ""}</td><td>{r.get("tactic") or ""}</td><td class="pv-opt sm">{pos}</td>'
                f'<td class="pv-opt sm">{num(r.get("gear"), "{:.2f}")}</td><td class="pv-opt sm">{r.get("score", 0):.1f}</td>'
                f'<td class="pv-opt sm">{num(r.get("win_rate"))}</td><td class="pv-opt sm">{num(r.get("rentai2"))}</td><td class="pv-opt sm">{num(r.get("rentai3"))}</td>'
                f'<td class="pv-opt sm">{num(r.get("s_count"), "{:.0f}")}</td><td class="pv-opt sm">{num(r.get("b_count"), "{:.0f}")}</td>'
                f'<td class="pv-opt sm">{kim.get("逃", 0)}</td><td class="pv-opt sm">{kim.get("捲", 0)}</td><td class="pv-opt sm">{kim.get("差", 0)}</td><td class="pv-opt sm">{kim.get("マ", 0)}</td>'
                f'<td class="hl">{w1:.1f}</td><td class="pv-opt">{w2:.0f}</td><td class="pv-opt">{w3:.0f}</td>'
                f'<td class="hl">{r.get("place_rate", 0):.0f}</td></tr>'
                f'<tr class="pv-opt rc"><td></td><td class="pv-rc" colspan="21">{rc_html}'
                f'<br><span class="cm">▶ {comment}</span></td></tr>')
    thead = ("<tr><th rowspan=2>番</th><th rowspan=2>記者</th><th rowspan=2>AI</th><th rowspan=2>選手</th><th rowspan=2>級</th><th rowspan=2>脚質</th>"
             "<th class='pv-opt' rowspan=2>位置</th><th class='pv-opt' rowspan=2>ギア</th><th class='pv-opt' rowspan=2>得点</th>"
             "<th class='pv-opt' colspan=3>成績率(%)</th><th class='pv-opt' colspan=2>回数</th><th class='pv-opt' colspan=4>決まり手(回)</th>"
             "<th colspan=4>AI予測(%)</th></tr>"
             "<tr><th class='pv-opt'>勝率</th><th class='pv-opt'>2連</th><th class='pv-opt'>3連</th><th class='pv-opt'>S</th><th class='pv-opt'>B</th>"
             "<th class='pv-opt'>逃</th><th class='pv-opt'>捲</th><th class='pv-opt'>差</th><th class='pv-opt'>マ</th>"
             "<th>1着</th><th class='pv-opt'>2着</th><th class='pv-opt'>3着</th><th>3着内</th></tr>")

    combos = (result.get("trifecta") or {}).get("combos", [])[:10]
    tri = "".join(f'<div><span>{c["first"]}-{c["second"]}-{c["third"]}</span><span>{c["prob"]:.1f}%</span></div>' for c in combos)
    tri_html = f'<div class="pv-box"><div class="pv-box-t">3連単 確率の高い順</div><div class="pv-tri">{tri}</div></div>' if tri else ""
    tk = _ticket_lists(result)
    mix = ""
    for name in ("2車単", "2車複", "ワイド", "3連複"):
        lines = "".join(f'<div style="display:flex;justify-content:space-between;border-bottom:1px dotted #bbb;line-height:1.55;"><span>{k}</span><span>{v:.1f}%</span></div>' for k, v in tk[name])
        mix += f'<div><div class="pv-box-t">{name}</div>{lines}</div>'
    mix_html = f'<div class="pv-box"><div class="pv-box-t" style="border:none;margin:0;">券種別 確率の高い順（AIの予測）</div><div class="pv-mix">{mix}</div></div>' if combos else ""
    tickets = f'<div class="pv-tickets pv-opt">{tri_html}{mix_html}</div>' if (tri_html or mix_html) else ""
    form = _formation_text(result)
    form_html = f'<div class="pv-form pv-opt">{form}</div>' if form else ""

    dev = result.get("development_simulation") or {}
    dev_rows = ""
    for sc in (dev.get("scenarios") or [])[:2]:
        picks = " ".join(f'{c["car"]}番{c["win_pct"]:.0f}%' for c in sc.get("conditional_win_rates", [])[:3])
        dev_rows += f'<span style="margin-right:14px;"><b>{sc["label"]}</b>（{sc["share"]:.0f}%）→ 1着 {picks}</span>'
    dev_html = f'<div class="pv-sub pv-opt">展開の見通し：{dev_rows}</div>' if dev_rows else ""

    view = f'<div class="pv-view"><b class="t">AIの見立て</b>{_view_text(result, rows, flags)}{form_html}</div>'

    cars = sorted(r["car"] for r in rows)
    mats = "".join(_head_matrix_html(result, r, cars) for r in rows)  # rowsは1着率の高い順
    mx = (f'<div class="pv-mxwrap"><div class="pv-mxhead">{venue_name} {info["race_no"]}R　選手ごとの出目確率（続き）</div>'
          f'<div class="pv-mxtitle">選手ごとの出目確率（3連単・%）　1着が○番のとき、2着×3着の組み合わせ</div>'
          f'<div class="pv-mxgrid">{mats}</div>'
          f'<div class="pv-mxnote">濃いほど出やすい（0.7%以上／1.5%以上／3%以上で段階的に濃く）。"-"は0.05%未満。右端の「2着計」は、その選手が1着で、かつその車が2着になる確率の合計。</div></div>')
    return f"""
    <div class="pv-card" data-venue="{info['venue']}" data-flags="{' '.join(flags)}" data-deadline="{deadline}">
      <div class="pv-head"><b>{venue_name} {info['race_no']}R</b>
        <span class="pv-t">{info.get('title') or ''} {('締切 ' + deadline) if deadline else ''}</span>
        <span class="pv-flags">{''.join(flag_html)}</span></div>
      {bank_html}
      <div class="pv-sub">{sub}</div>
      {dev_html}
      <table class="pv-t">{thead}{trs}</table>
      {view}
      {tickets}
      {mx}
      <div class="pv-memo pv-opt">メモ：</div>
    </div>"""


def render_print_page(all_race_data, date=None):
    """
    A4の紙に出す（またはPDFに保存する）ための「印刷用」ページ。開催場・絞り込み・列数・3連単の
    点数を画面上で選び、「印刷／PDF保存」を押すとブラウザの印刷画面が開く。
    開催場ごとに改ページされ、操作パネルやナビは印刷に出ない。
    """
    by_venue = {}
    for rd in all_race_data:
        if rd.get("prediction"):
            by_venue.setdefault(rd["race_info"]["venue"], []).append(rd)
    venue_order = sorted(by_venue, key=lambda v: VENUE_NAMES.get(v, v))
    sections, chips = "", ""
    for v in venue_order:
        rds = sorted(by_venue[v], key=lambda rd: rd["race_info"]["race_no"])
        name = VENUE_NAMES.get(v, v)
        chips += f'<label><input type="checkbox" class="pv-vchk" value="{v}" checked> {name}</label>'
        sections += (f'<section class="pv-venue"><h2>{name}　{_fmt_date_jp(date)}</h2>'
                     f'<div class="pv-grid">{"".join(_print_card_html(rd) for rd in rds)}</div></section>')
    n_races = sum(len(x) for x in by_venue.values())
    controls = f"""
  <div class="pv-controls">
    <h3>印刷用：本日の予想一覧（{n_races}レース）</h3>
    <div class="pv-row"><span>開催場：</span>
      <button type="button" id="pvAll">全部</button><button type="button" id="pvNone">解除</button></div>
    <div class="pv-vchips">{chips}</div>
    <div class="pv-row">
      <label>絞り込み
        <select id="pvFlag"><option value="all">全レース</option><option value="high">本命が堅い</option>
        <option value="close">拮抗</option><option value="value">妙味</option></select></label>
      <label>列数
        <select id="pvCols"><option value="1">詳細（1ページ1レース）</option><option value="2">簡易（2列・出目表なし）</option></select></label>
      <label>出目確率表
        <select id="pvMx"><option value="10" selected>1着率10%以上の選手</option><option value="0">全選手（網羅）</option><option value="5">1着率5%以上の選手</option><option value="999">出さない</option></select></label>
      <label>3連単の点数
        <select id="pvTri"><option value="5">5点</option><option value="10" selected>10点</option><option value="3">3点</option></select></label>
      <label><input type="checkbox" id="pvFuture"> 締切前のレースだけ</label>
    </div>
    <div class="pv-row"><button type="button" class="pv-print-btn" id="pvPrint">印刷 / PDFに保存</button></div>
    <p class="pv-hint">開催場ごとに改ページ、詳細は1レース1ページです。印刷画面で「PDFとして保存」を選ぶとPDFになります
    （iPhone/iPadは、共有ボタン → 「プリント」→ プレビューをピンチアウト → 共有でPDF保存）。
    AI＝予測1着率の上位印（◎○▲△）、級＝級班、1着率・3着内％はAIの予測です。</p>
  </div>"""
    body = controls + (sections or '<p class="dim">本日は予想できたレースがありません。</p>')
    return _page_shell(
        title="印刷用 予想一覧", heading="印刷用 予想一覧",
        tagline="本日の予想をA4で印刷・PDF保存できる形にまとめました。",
        date_str=_fmt_date_jp(date), body=body, current="print.html",
        script=_PRINT_SCRIPT, extra_style=_PRINT_STYLE)
