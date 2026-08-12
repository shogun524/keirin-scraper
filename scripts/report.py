# -*- coding: utf-8 -*-
"""
1日分のレース予測結果を、スマホでそのまま見られる静的HTMLレポートに変換する。
GitHub Pages で公開する docs/index.html を生成する。
"""

import datetime
from model import KIMARITE_LABELS

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


def car_color(car):
    colors = {
        1: ("#ffffff", "#1b2430"), 2: ("#1b1b1b", "#ffffff"), 3: ("#d8322a", "#ffffff"),
        4: ("#1f5fc4", "#ffffff"), 5: ("#e8c221", "#1b2430"), 6: ("#2f8f4e", "#ffffff"),
        7: ("#e07a1f", "#ffffff"), 8: ("#e2699a", "#ffffff"), 9: ("#3fb8c9", "#1b2430"),
    }
    return colors.get(((car - 1) % 9) + 1, ("#888", "#fff"))


def render_race_card(race_data):
    info = race_data["race_info"]
    result = race_data["prediction"]
    if not result:
        return ""
    venue_name = VENUE_NAMES.get(info["venue"], info["venue"])
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
          <td>{KIMARITE_LABELS.get(r['dominant_type'], '-')} ({r['kimarite_prediction']['ratio']*100:.0f}%)</td>
          <td>{line_label}</td>
          <td><b>{r['adjusted']:.1f}%</b></td>
          <td>{r['confidence']['score']:.0f}</td>
        </tr>"""

    second_html = ""
    if result["second_candidates"]:
        second_html = "<h4>2着候補</h4><table class='sub'>"
        for c in result["second_candidates"][:3]:
            same = "（同ライン）" if c["same_line"] else ""
            second_html += f"<tr><td>{c['car']}号車 {c['name']}{same}</td><td>{c['prob']:.1f}%</td></tr>"
        second_html += "</table>"

    third_html = ""
    if result["third_candidates"]:
        third_html = "<h4>3着候補</h4><table class='sub'>"
        for c in result["third_candidates"][:3]:
            same = "（同ライン）" if c["same_line"] else ""
            third_html += f"<tr><td>{c['car']}号車 {c['name']}{same}</td><td>{c['prob']:.1f}%</td></tr>"
        third_html += "</table>"

    close_note = ""
    if result["most_reliable"] and result["most_reliable"]["car"] != top["car"]:
        mr = result["most_reliable"]
        close_note = (f"<p class='note'>⚠ 予測1着率が拮抗しています。信頼度が最も高いのは "
                       f"{mr['car']}号車 {mr['name']}（信頼度{mr['confidence']['score']:.0f}）です。</p>")

    banner_class = "banner-high" if high_prob else "banner-normal"
    banner_text = (
        f"{top['car']}号車 {top['name']} が本命（予測1着率 {top['adjusted']:.1f}%）"
        if high_prob else
        f"拮抗レース。最有力は{top['car']}号車 {top['name']}（{top['adjusted']:.1f}%）"
    )

    return f"""
    <div class="race-card">
      <div class="race-head">
        <span class="venue">{venue_name}</span>
        <span class="raceno">{info['race_no']}R</span>
        <span class="title">{title}</span>
      </div>
      <div class="{banner_class}">{banner_text}</div>
      {close_note}
      <table class="main">
        <thead><tr><th>号車</th><th>選手</th><th>級班</th><th>予測決まり手</th><th>ライン</th><th>予測1着率</th><th>信頼度</th></tr></thead>
        <tbody>{rows_html}</tbody>
      </table>
      <div class="sub-wrap">{second_html}{third_html}</div>
    </div>"""


def render_report(all_race_data, date=None):
    date = date or datetime.date.today()
    date_str = date.strftime("%Y年%m月%d日")

    # 開催場ごとにグループ化
    by_venue = {}
    for rd in all_race_data:
        v = rd["race_info"]["venue"]
        by_venue.setdefault(v, []).append(rd)

    venue_sections = ""
    for venue, races in by_venue.items():
        races.sort(key=lambda r: r["race_info"]["race_no"])
        venue_name = VENUE_NAMES.get(venue, venue)
        cards = "".join(render_race_card(r) for r in races)
        venue_sections += f"<section class='venue-section'><h2>{venue_name}競輪</h2>{cards}</section>"

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>競輪AI予想 {date_str}</title>
<style>
  body {{ margin:0; background:#f6f3ec; color:#1b2430; font-family:"Hiragino Sans","Yu Gothic",sans-serif; }}
  header {{ background:#0e1b2b; color:#fff; padding:20px 16px; }}
  header h1 {{ margin:0; font-size:20px; }}
  header p {{ margin:6px 0 0; color:#b9c3d4; font-size:13px; }}
  main {{ max-width:720px; margin:0 auto; padding:16px 10px 60px; }}
  .venue-section {{ margin-bottom:28px; }}
  .venue-section h2 {{ font-size:16px; border-bottom:2px solid #0e1b2b; padding-bottom:6px; }}
  .race-card {{ background:#fff; border:1px solid #d8d2c2; border-radius:8px; padding:14px; margin-bottom:14px; }}
  .race-head {{ display:flex; gap:8px; align-items:baseline; margin-bottom:8px; flex-wrap:wrap; }}
  .race-head .venue {{ font-weight:700; }}
  .race-head .raceno {{ background:#0e1b2b; color:#fff; border-radius:4px; padding:1px 8px; font-size:13px; }}
  .race-head .title {{ color:#5b6472; font-size:13px; }}
  .banner-high {{ background:#fff4de; border:1px solid #d8a94a; border-radius:6px; padding:8px 10px; font-size:13.5px; margin-bottom:8px; }}
  .banner-normal {{ background:#f0ece0; border-radius:6px; padding:8px 10px; font-size:13.5px; margin-bottom:8px; }}
  .note {{ font-size:12px; color:#b5482f; margin:4px 0; }}
  table.main {{ width:100%; border-collapse:collapse; font-size:12px; }}
  table.main th, table.main td {{ border:1px solid #d8d2c2; padding:5px; text-align:center; }}
  table.main th {{ background:#f0ece0; }}
  .car {{ display:inline-flex; align-items:center; justify-content:center; width:20px; height:20px; border-radius:50%; font-size:11px; font-weight:700; border:1px solid rgba(0,0,0,.15); }}
  .sub-wrap {{ display:flex; gap:16px; margin-top:10px; flex-wrap:wrap; }}
  .sub-wrap h4 {{ font-size:12px; margin:0 0 4px; color:#5b6472; }}
  table.sub {{ font-size:12px; border-collapse:collapse; }}
  table.sub td {{ padding:2px 8px 2px 0; }}
  footer {{ text-align:center; color:#5b6472; font-size:11px; padding:20px; }}
  @media (max-width:420px) {{
    table.main {{ font-size:10.5px; }}
    table.main th, table.main td {{ padding:3px; }}
  }}
</style>
</head>
<body>
<header>
  <h1>競輪AI予想 {date_str}</h1>
  <p>毎朝自動更新・全開催場のレースを掲載しています。閾値を超えた本命がいない場合は「拮抗レース」と表示されます。</p>
</header>
<main>
{venue_sections if venue_sections else "<p style='text-align:center;color:#5b6472;'>本日は取得できたレースがありませんでした。</p>"}
</main>
<footer>このページはGitHub Actionsにより毎朝自動生成されています。予測はAIモデルによる参考情報であり、的中を保証するものではありません。</footer>
</body>
</html>"""
