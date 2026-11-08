# -*- coding: utf-8 -*-
"""
検証ページ docs/edge.html（と docs/_edge_report.json）を作る。
「控除（約25%）を超えて儲かる」と言える根拠が揃っているかを、回収率の信頼区間・前向き検証・
オッズ帯別・CLV・仮想資金の推移で示す。集計は edge_lab.py、配分は staking.py。
"""
import json
import os

import closing_odds
import edge_lab
import staking

REPORT_NAME = "_edge_report.json"
PLAN_LABEL = {"syn1.5": "合成1.5倍", "syn2": "合成2倍", "top3": "上位3点", "top5": "上位5点",
              "top8": "上位8点", "top10": "上位10点"}
STYLE = """
  main.wide{ max-width:860px; }
  h2.section{ font-size:14px; color:var(--ink-soft); margin:22px 0 8px; }
  .rs-tiles{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:8px; margin:0 0 6px; }
  .rs-tile{ background:#fff; border:1px solid var(--border); border-radius:8px; padding:10px 12px; }
  .rs-label{ font-size:11.5px; color:var(--ink-soft); }
  .rs-value{ font-size:22px; font-weight:800; color:var(--brick); margin-top:2px; font-variant-numeric:tabular-nums; }
  .rs-sub{ font-size:11px; color:var(--ink-soft); margin-top:2px; min-height:14px; }
  .kf-note{ font-size:12px; color:var(--ink-soft); line-height:1.7; margin:4px 0 8px; }
  .delta-up{ color:var(--pine); font-weight:700; } .delta-down{ color:var(--brick); font-weight:700; }
  .dim{ color:var(--ink-soft); font-size:11.5px; }
"""


def _pct(x, d=1):
    return "—" if x is None else f"{x:.{d}f}%"


def _cls(x, base=100.0):
    return "" if x is None else ("delta-up" if x >= base else "delta-down")


def _table(head, rows):
    th = "".join(f"<th>{h}</th>" for h in head)
    return f'<div class="ov-scroll"><table class="ov"><thead><tr>{th}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def _roi_cell(s):
    if not s or not s.get("races"):
        return "—"
    return (f'<span class="{_cls(s["roi"])}">{_pct(s["roi"], 0)}</span>'
            f'<br><span class="dim">{_pct(s["lo"], 0)}〜{_pct(s["hi"], 0)}</span>')


def _grid_section(rep):
    rows = []
    for t in ("全体",) + edge_lab.TYPES:
        g = rep["grid"].get(t) or {}
        if not g:
            continue
        n = next(iter(g.values()))["races"]
        cells = []
        for p in edge_lab.PLANS:
            ok = (rep["gates"].get(t, {}).get(p) or {}).get("pass")
            cells.append(f"<td>{_roi_cell(g.get(p))}{' ✅' if ok else ''}</td>")
        rows.append(f'<tr><td class="l"><b>{t}</b><br><span class="dim">{n}レース</span></td>{"".join(cells)}</tr>')
    head = ["型"] + [PLAN_LABEL[p] for p in edge_lab.PLANS]
    best = max(((t, p, s) for t, gg in rep["grid"].items() for p, s in gg.items() if s.get("p_gt") is not None and t != "全体"),
               key=lambda x: x[2]["p_gt"], default=None)
    note = ""
    if best:
        t, p, s = best
        note = (f'<p class="kf-note">いちばん良く見えるのは「{t}×{PLAN_LABEL[p]}」で回収率{_pct(s["roi"], 0)}'
                f'（90%区間 {_pct(s["lo"], 0)}〜{_pct(s["hi"], 0)}、100%超えの確からしさ{s["p_gt"] * 100:.0f}%）。'
                f'ただし{len(edge_lab.TYPES) * len(edge_lab.PLANS)}通りを見比べているので、良い結果が偶然混ざります。'
                '下側が100%を超えるまでは「儲かる」とは言えません。</p>')
    return ('<h2 class="section">買い方別の回収率（90%信頼区間つき）</h2>'
            '<p class="kf-note">各買い目に100円ずつ、記録した締切前のオッズで計算。大きい数字が回収率、小さい数字が90%区間。'
            '✅は「件数・区間の下側・前向き検証・CLV」が全部そろった買い方です。</p>'
            + _table(head, rows) + note)


def _wf_section(rep):
    wf, ar = rep["walk_forward"], rep["auto_replay"]
    rows = []
    for label, s in (("現行の自動おすすめ（10/24〜26で決めたルール）", ar),
                     ("前向き検証：毎日、前日までで最良の買い方を選ぶ（同額配分）", wf["equal"]),
                     ("前向き検証：同（払戻が同額になる配分）", wf["payout"])):
        pg = "—" if s.get("p_gt") is None else "%d%%" % round(s["p_gt"] * 100)
        rows.append(f'<tr><td class="l">{label}</td><td>{s["bet_races"]}</td><td>{s["skipped_races"]}</td>'
                    f'<td>{_roi_cell({"races": s["bet_races"], **s})}</td><td>{pg}</td></tr>')
    return ('<h2 class="section">前向き検証（選び方の偏りを除いた成績）</h2>'
            '<p class="kf-note">買い方を「過去の成績が良かったもの」から選ぶと、その選び方自体が偶然に合わせてしまいます。'
            'ここでは<b>その日より前のデータだけ</b>で型ごとに買い方を選び、過去の回収率が100%に届かない型は見送り、その日を評価しています。</p>'
            + _table(["ルール", "賭けたレース", "見送り", "回収率", "100%超えの確からしさ"], rows))


def _band_section(rep):
    rows = []
    for b in rep["bands"]:
        lab = f'{b["lo"]}〜{b["hi"]}倍' if b["hi"] else f'{b["lo"]}倍〜'
        rows.append(f'<tr><td class="l">{lab}</td><td>{b["tickets"]}</td><td>{_pct(b["hit_pct"], 2)}</td>'
                    f'<td>{_roi_cell({"races": 1, "roi": b["roi"], "lo": b["roi_lo"], "hi": b["roi_hi"]})}</td></tr>')
    return ('<h2 class="section">オッズ帯別の回収率（人気薄は損か）</h2>'
            '<p class="kf-note">記録している上位40点を全部100円ずつ買った場合。人気薄ほど回収率が下がる傾向があれば、'
            '買い目は人気側に寄せるほうが控除の影響を受けにくい、という目安になります。</p>'
            + _table(["オッズ", "点数", "的中率", "回収率"], rows))


def _clv_section(rep):
    rows = []
    for p, c in rep["clv"].items():
        if not c.get("races"):
            rows.append(f'<tr><td class="l">{PLAN_LABEL.get(p, p)}</td><td colspan="4" class="dim">まだ比較できる記録がありません</td></tr>')
            continue
        src = c["sources"]
        rows.append(f'<tr><td class="l">{PLAN_LABEL.get(p, p)}</td><td>{c["races"]}</td>'
                    f'<td><span class="{_cls(c["mean_pct"], 0)}">{c["mean_pct"]:+.1f}%</span>'
                    f'<br><span class="dim">{c["lo_pct"]:+.1f}〜{c["hi_pct"]:+.1f}%</span></td>'
                    f'<td>{c["pos_share"]:.0f}%</td>'
                    f'<td class="dim">直前{src.get("close", 0)}／毎時{src.get("last", 0)}</td></tr>')
    return ('<h2 class="section">CLV（最初に見たオッズ÷締切のオッズ）</h2>'
            '<p class="kf-note">プラスなら、最初に見た時点のほうが締切時より良い値段だった＝市場があとから同じ方向に動いた、という意味です。'
            '当たり外れに左右されないので、回収率より少ない件数で傾向が見えます。'
            '「直前」は締切の1〜12分前に取ったオッズ（closing.yml）、「毎時」は最後の毎時記録（最大1時間前）で、後者は精度が落ちます。</p>'
            + _table(["買い方", "レース", "平均CLV(90%区間)", "プラスの割合", "比較先"], rows))


def _svg(series, w=520, h=150):
    pts = [(d["date"], d["cum"]) for s in series.values() for d in s["days"]]
    if not pts:
        return ""
    ys = [y for _, y in pts] + [0]
    lo, hi = min(ys), max(ys)
    span = (hi - lo) or 1
    dates = sorted({d for d, _ in pts})
    xi = {d: i for i, d in enumerate(dates)}
    px = lambda d: 30 + (w - 40) * (xi[d] / max(1, len(dates) - 1))
    py = lambda y: 10 + (h - 30) * (1 - (y - lo) / span)
    colors = ["#a33b2a", "#3b5b7a"]
    out = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="仮想資金の損益の推移">',
           f'<line x1="30" x2="{w - 10}" y1="{py(0):.1f}" y2="{py(0):.1f}" stroke="#999" stroke-dasharray="3 3"/>']
    for (name, s), col in zip(series.items(), colors):
        line = " ".join(f"{px(d['date']):.1f},{py(d['cum']):.1f}" for d in s["days"])
        out.append(f'<polyline fill="none" stroke="{col}" stroke-width="2" points="{line}"/>')
    out.append(f'<text x="2" y="{py(hi):.0f}" font-size="9" fill="#666">{hi:+,}</text>'
               f'<text x="2" y="{py(lo):.0f}" font-size="9" fill="#666">{lo:+,}</text>')
    out.append("</svg>")
    return "".join(out)


def _paper_section(rep):
    names = {"auto": "現行の自動おすすめに従う（見送り型は賭けない）", "top5_all": "全レースで上位5点（比較用）"}
    series = {names[k]: v for k, v in rep["paper"].items()}
    legend = "".join(f'<span style="color:{c}">■</span> {n}　' for n, c in zip(series, ["#a33b2a", "#3b5b7a"]))
    rows = [f'<tr><td class="l">{n}</td><td>{s["bets"]}</td><td>{s["stake"]:,}円</td>'
            f'<td><span class="{_cls(s["profit"], 0)}">{s["profit"]:+,}円</span></td><td>{_pct(s["roi"], 0)}</td>'
            f'<td>{s["max_dd"]:,}円</td></tr>' for n, s in series.items()]
    return ('<h2 class="section">仮想資金での損益（ペーパートレード）</h2>'
            '<p class="kf-note">1レース1,000円、当たった買い目に関わらず払戻が同額になる配分で、記録した締切前のオッズで買ったと仮定。実際のお金は動いていません。'
            '最大ドローダウン＝それまでの最高値からの最大の落ち込みです。</p>'
            f'<div class="rs-tile">{_svg(series)}<div class="dim">{legend}</div></div>'
            + _table(["ルール", "賭けたレース", "投下", "損益", "回収率", "最大ドローダウン"], rows))


def _stake_section(rep, es):
    ok = [(t, p) for t, g in rep["gates"].items() for p, x in g.items() if x["pass"]]
    ex = ""
    if es:
        v = es[-1]
        sel, od = edge_lab._select(v["items"], "top5")
        odds = [od[k] for k in sel]
        budget = 5000
        st = staking.equal_payout_stakes(odds, budget)
        pays = [round(x * o) for x, o in zip(st, odds) if x]
        lines = "、".join(f"{k} {o}倍→{x:,}円" for k, o, x in zip(sel, odds, st))
        ex = (f'<p class="kf-note">配分の例（直近の記録 {v["venue"]} {v["race_no"]}R の上位5点・{budget:,}円）：{lines}。'
              f'当たった買い目による払戻は{min(pays):,}〜{max(pays):,}円。同額ずつ（各{budget // len(odds):,}円）買うと'
              f'{round(budget // len(odds) * min(odds)):,}〜{round(budget // len(odds) * max(odds)):,}円とブレが大きくなります'
              '（金額は100円単位に丸めるため、完全には揃いません）。</p>')
    verdict = (f'検証の条件を満たした買い方が{len(ok)}個あります。資金の最大2%、ケリー基準の1/4を上限に賭け金を出せます。'
               if ok else
               '<b>検証の条件を満たした買い方はまだありません。よって推奨する賭け金は0円（見送り）です。</b>')
    return ('<h2 class="section">資金管理</h2>'
            f'<p class="hp-lead">{verdict}<br>ケリー基準は「本当の的中率」が分かっているときの式なので、推定が甘いと賭けすぎて資金を減らします。'
            'そのため的中率は信頼区間の下側で見積もり、ケリーの1/4、1レース最大でも資金の2%に抑えます。</p>' + ex)


def render_edge_page(rep, es, date=None):
    from report import _fmt_date_jp, _page_shell
    if not rep.get("races"):
        body = '<p class="hp-lead">検証できる記録（締切前のオッズと確定結果）がまだありません。</p>'
    else:
        n_gate = sum(1 for g in rep["gates"].values() for x in g.values() if x["pass"])
        tiles = "".join(
            f'<div class="rs-tile"><div class="rs-label">{a}</div><div class="rs-value">{b}</div><div class="rs-sub">{c}</div></div>'
            for a, b, c in [("検証したレース", f'{rep["races"]}', f'{rep["dates"][0]}〜{rep["dates"][1]}'),
                            ("根拠がそろった買い方", f"{n_gate}", "全18通り（3型×6買い方）中"),
                            ("全レース上位5点の回収率", _pct(rep["grid"]["全体"]["top5"]["roi"], 0),
                             f'下側90% {_pct(rep["grid"]["全体"]["top5"]["lo"], 0)}')])
        body = ('<p class="hp-lead">オッズの動きで当てることと、儲かることは別です。馬券は控除（約25%）が引かれるので、'
                '市場どおりに買うと平均で約75%しか戻りません。このページは「控除を超える」と言える根拠が実際に揃っているかを測ります。'
                '<b>回収率の信頼区間の下側が100%を超えるまでは、儲かるとは言いません。</b></p>'
                f'<div class="rs-tiles">{tiles}</div>'
                + _grid_section(rep) + _wf_section(rep) + _band_section(rep) + _clv_section(rep)
                + _paper_section(rep) + _stake_section(rep, es)
                + '<p class="kf-note">限界：記録しているオッズは締切前の最後の実行時点（最大1時間前）で、確定オッズとは違います。'
                  '上位40点しか保存していないため、保存外の出目が来たレースは外れ扱いです。期間が短く、日ごとの偏りが大きいので、'
                  '数週間単位で見てください。</p>')
    return _page_shell(title="検証・資金管理", heading="検証・資金管理", date_str=_fmt_date_jp(date),
                       tagline="オッズ変動の先読みは本当に儲かるのか。根拠が揃うまで賭け金は出しません。",
                       body=body, current="edge.html", extra_style=STYLE)


def build(docs, today):
    """run_daily から呼ぶ。docs/_edge_report.json と docs/edge.html を書く。戻り値は集計結果。"""
    import buy_stats
    log = buy_stats.load(docs)
    es = edge_lab.settled(log)
    rep = edge_lab.build_report(log, closing_odds.load(docs))
    with open(os.path.join(docs, REPORT_NAME), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(docs, "edge.html"), "w", encoding="utf-8") as f:
        f.write(render_edge_page(rep, es, today))
    return rep
