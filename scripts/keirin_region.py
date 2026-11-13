# -*- coding: utf-8 -*-
"""
選手の府県 → 地区、ラインの「地区のまとまり」。

検証(2025年1月〜2026年11月、wt_entries の並び予想・確定オッズ):
  印で並べたラインの並び通り3連単を、ラインの前3人が「全員同じ地区」か「ばらばら」かで分けると、
    ルールD(2番目のライン・10〜30倍): 3人同地区 1255点 回収率123%(2025年118%・2026年133%、上位5本を除いても112%)
                                        それ以外  2296点 回収率102%
    ルールF(3番目のライン・30〜300倍): 3人同地区 1354点 回収率192%(上位5本を除くと105%) / それ以外 87%
    ルールC(7車・3番目のライン):       3人同地区 1189点 回収率180%(上位5本を除くと84%) / それ以外 75%
  同じ地区のラインは「並び通りに決まる」ことが市場の見込みより多い(番手が前を残しにいく・3番手が仕事をする)。
  A・B(9車)では差が出なかった(年によって逆)。
  同県の2人(先頭と番手)だけでは差は小さい(番手が市場より約1ポイント勝たず、先頭が約1ポイント多く勝つ程度)。
"""
REGIONS = {
    "北日本": "北海道 青森 岩手 宮城 秋田 山形 福島",
    "関東": "茨城 栃木 群馬 埼玉 新潟 長野",
    "南関東": "千葉 東京 神奈川 静岡 山梨",
    "中部": "富山 石川 岐阜 愛知 三重",
    "近畿": "福井 滋賀 京都 大阪 兵庫 奈良 和歌山",
    "中国": "鳥取 島根 岡山 広島 山口",
    "四国": "徳島 香川 愛媛 高知",
    "九州": "福岡 佐賀 長崎 熊本 大分 宮崎 鹿児島 沖縄",
}
PREF_REGION = {p: r for r, ps in REGIONS.items() for p in ps.split()}


def region_of(pref):
    p = str(pref or "").strip()
    for suffix in ("県", "府", "都"):
        if p.endswith(suffix) and p != "京都":
            p = p[: -len(suffix)]
    return PREF_REGION.get(p)


def line_relation(prefs):
    """ラインの選手の府県(前から順) -> dict(same3=前3人が同じ地区か, label=表示, region=地区名)"""
    prefs = [str(p or "") for p in prefs]
    regs = [region_of(p) for p in prefs]
    if len(prefs) >= 3 and regs[0] and len(set(regs[:3])) == 1:
        return dict(same3=True, label=f"3人同地区({regs[0]})", region=regs[0])
    if len(prefs) >= 2 and prefs[0] and prefs[0] == prefs[1]:
        return dict(same3=False, label="前2人同県", region=regs[0])
    if len(prefs) >= 2 and regs[0] and regs[0] == regs[1]:
        return dict(same3=False, label="前2人同地区", region=regs[0])
    return dict(same3=False, label="地区ばらばら" if len(prefs) >= 2 else "", region=None)


JIRIKI_WORDS = ("自力", "自分で", "自分から", "前々", "先行", "カマシ", "カマす", "主導権", "逃げ")


def says_jiriki(comment):
    c = str(comment or "")
    return any(w in c for w in JIRIKI_WORDS)
