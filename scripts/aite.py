"""
AI相手選び(11/27)。舟券サイトの「アタマの相手」「AI相手選び」を参考にした機能。
  write(all_race_data, today, docs)  … docs/aite_data.json(全レースの3連単の出目確率とオッズ)と docs/aite.html を書く
  card_html(info)                    … トップのレースカードに入れる「アタマの相手」(開くと読み込む)と「AI相手選び」へのリンク
  INDEX_JS                           … トップページで「アタマの相手」を描くスクリプト
確率は予想ページと同じ3連単の出目確率(オッズがあるときはオッズ・ラインと合わせたもの、無いときはAIだけ)。
"""
import datetime
import json
import os
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
CAR_COLORS = {
    1: ("#ffffff", "#1b2430"), 2: ("#1b1b1b", "#ffffff"), 3: ("#d8322a", "#ffffff"),
    4: ("#1f5fc4", "#ffffff"), 5: ("#e8c221", "#1b2430"), 6: ("#2f8f4e", "#ffffff"),
    7: ("#e07a1f", "#ffffff"), 8: ("#e2699a", "#ffffff"), 9: ("#8a5fb0", "#ffffff"),
}


def race_key(info):
    return f'{info["venue"]}_{int(info["race_no"])}'


def _venue_order(all_race_data):
    """トップページ(render_jra_index)と同じ会場の並び → {venue: 番号}"""
    by = {}
    for rd in all_race_data:
        by.setdefault(rd["race_info"]["venue"], []).append(rd)
    order = sorted(by, key=lambda v: min((rd["race_info"].get("deadline") or "99") for rd in by[v]))
    return {v: i for i, v in enumerate(order)}


def _girls(res, info):
    try:
        from report import _is_girls
        return _is_girls(res["rows"], info.get("title") or "")
    except Exception:  # noqa: BLE001
        return "ガールズ" in (info.get("title") or "")


# おまかせ(11/27): 本命の1着率×頭数・ガールズの形ごとに、2025・2026年の約5万レースで
# 「どちらの年も的中30%以上」の中から回収率(10万で頭打ち)の低い方の年が一番良いフォーメーションを選んだもの。
# 集合: all=全員 / p1,a,b=1着率の(a+1)〜b位 / t3,a,b=3着内率の(a+1)〜b位。
# 別の年で選んで確かめると全体で回収率73%前後(的中31〜33%)。100%は超えない。
AUTO = {"70": {"f": [["p1", 0, 3], ["t3", 0, 3], ["all"]], "pts": 32.1, "hit": 0.357, "roi": [0.822, 0.812], "R": 507}, "71": {"f": [["p1", 0, 5], ["p1", 1, 4], ["t3", 0, 4]], "pts": 28.3, "hit": 0.315, "roi": [0.768, 0.778], "R": 7670}, "72": {"f": [["p1", 0, 2], ["p1", 0, 4], ["t3", 2, 5]], "pts": 13.7, "hit": 0.338, "roi": [0.788, 0.787], "R": 11811}, "73": {"f": [["p1", 0, 3], ["t3", 0, 3], ["t3", 0, 4]], "pts": 13.3, "hit": 0.429, "roi": [0.764, 0.774], "R": 9559}, "74": {"f": [["t3", 0, 1], ["t3", 0, 2], ["all"]], "pts": 4.9, "hit": 0.396, "roi": [0.772, 0.805], "R": 12542}, "90": {"f": [["p1", 0, 5], ["t3", 0, 5], ["t3", 0, 4]], "pts": 49.8, "hit": 0.342, "roi": [0.874, 0.842], "R": 260}, "91": {"f": [["t3", 0, 3], ["t3", 0, 5], ["t3", 0, 5]], "pts": 36.0, "hit": 0.359, "roi": [0.772, 0.744], "R": 1509}, "92": {"f": [["p1", 0, 2], ["t3", 0, 5], ["t3", 0, 4]], "pts": 18.0, "hit": 0.303, "roi": [0.823, 0.852], "R": 1379}, "93": {"f": [["t3", 0, 5], ["t3", 1, 3], ["t3", 0, 5]], "pts": 24.0, "hit": 0.329, "roi": [0.91, 0.911], "R": 765}, "94": {"f": [["p1", 0, 3], ["p1", 0, 3], ["t3", 0, 4]], "pts": 12.6, "hit": 0.359, "roi": [1.04, 0.989], "R": 647}, "G1": {"f": [["p1", 0, 5], ["t3", 0, 4], ["t3", 1, 3]], "pts": 18.0, "hit": 0.321, "roi": [1.07, 1.049], "R": 131}, "G2": {"f": [["t3", 0, 2], ["p1", 0, 5], ["p1", 3, 6]], "pts": 19.7, "hit": 0.313, "roi": [0.952, 0.953], "R": 409}, "G3": {"f": [["t3", 0, 1], ["all"], ["t3", 2, 5]], "pts": 14.6, "hit": 0.32, "roi": [1.299, 1.119], "R": 603}, "G4": {"f": [["t3", 0, 3], ["p1", 1, 4], ["t3", 1, 3]], "pts": 6.0, "hit": 0.379, "roi": [0.837, 0.869], "R": 2958}}


def build_data(all_race_data, today):
    from report import VENUE_NAMES
    vo = _venue_order(all_race_data)
    races = []
    for rd in all_race_data:
        info, res = rd.get("race_info") or {}, rd.get("prediction")
        if not res or not res.get("rows"):
            continue
        combos = (res.get("trifecta") or {}).get("combos") or []
        tot = sum(c["prob"] for c in combos) or 0
        if not tot:
            continue
        od = res.get("tri_odds") or {}
        j = []
        for c in combos:
            k = (c["first"], c["second"], c["third"])
            o = od.get(k)
            j.append([k[0], k[1], k[2], round(c["prob"] / tot * 1e5), round(o, 1) if o else 0])
        races.append(dict(
            k=race_key(info), v=VENUE_NAMES.get(info["venue"], info["venue"]), vi=vo.get(info["venue"], 0),
            no=int(info["race_no"]), t=info.get("title") or "", dl=info.get("deadline") or "",
            mode="odds" if res.get("fix_mode") == "odds" else "ai", g=1 if _girls(res, info) else 0,
            cars=[[r["car"], r.get("name") or "", str(r.get("rank") or "")] for r in sorted(res["rows"], key=lambda r: r["car"])],
            j=j))
    races.sort(key=lambda r: (r["vi"], r["no"]))
    now = datetime.datetime.now(JST)
    return dict(date=today.isoformat(), updated=now.strftime("%H:%M"), races=races, auto=AUTO)


def write(all_race_data, today, docs):
    data = build_data(all_race_data, today)
    with open(os.path.join(docs, "aite_data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(docs, "aite.html"), "w", encoding="utf-8") as f:
        f.write(PAGE.replace("__COLORS__", json.dumps({str(k): v for k, v in CAR_COLORS.items()})))
    print(f"[INFO] AI相手選び: {len(data['races'])}レース分の出目確率を書き出しました")


def card_html(info):
    k = race_key(info)
    return (f'<details class="aite-fold" data-k="{k}"><summary>アタマの相手 <small>頭ごとの2着率・3着率</small></summary>'
            f'<div class="aite-body">読み込み中…</div></details>'
            f'<a class="aite-link" href="aite.html?k={k}">AI相手選び <small>頭・BOX・あるなしで買い目を作る</small> ›</a>')


INDEX_CSS = """
  .card-extra { padding: 0 14px 12px; }
  .aite-fold { border-top: 1px solid var(--paper-line); margin-top: 6px; }
  .aite-fold > summary { cursor: pointer; list-style: none; padding: 10px 0 8px; font-weight: 700; font-size: .88rem;
    display: flex; align-items: center; gap: 6px; }
  .aite-fold > summary::-webkit-details-marker { display: none; }
  .aite-fold > summary::after { content: "開く ▼"; margin-left: auto; font-size: .75rem; font-weight: 500; color: var(--ink-soft); }
  .aite-fold[open] > summary::after { content: "閉じる ▲"; }
  .aite-fold > summary small { font-weight: 400; color: var(--ink-soft); font-size: .72rem; }
  .ah-heads { display: flex; gap: 6px; flex-wrap: wrap; margin: 2px 0 8px; }
  .ah-heads button { width: 38px; height: 38px; border-radius: 8px; border: 1px solid #0002; font-weight: 700; font-size: 1rem;
    cursor: pointer; opacity: .45; font-family: inherit; }
  .ah-heads button.on { opacity: 1; outline: 3px solid var(--ink); outline-offset: 1px; }
  .ah-cap { font-size: .8rem; margin: 0 0 6px; } .ah-cap b { font-size: .95rem; } .ah-cap small { color: var(--ink-soft); }
  table.ah { width: 100%; border-collapse: collapse; font-size: .85rem; }
  table.ah th { font-size: .7rem; font-weight: 500; color: var(--ink-soft); text-align: left; padding: 2px 4px 4px;
    border-bottom: 2px solid var(--ink); }
  table.ah td { padding: 6px 4px; border-bottom: 1px solid var(--paper-line); vertical-align: middle; }
  .ah-pair { display: inline-flex; min-width: 44px; justify-content: center; padding: 4px 6px; border-radius: 6px;
    font-weight: 700; font-variant-numeric: tabular-nums; }
  .ah-p2 { font-size: 1.05rem; font-weight: 700; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .ah-3 { display: flex; flex-wrap: wrap; gap: 2px 8px; }
  .ah-3 span { white-space: nowrap; font-variant-numeric: tabular-nums; font-weight: 700; }
  .ah-3 i { display: inline-block; min-width: 16px; text-align: center; border-radius: 3px; font-style: normal; font-size: .7rem;
    padding: 0 3px; margin-right: 2px; border: 1px solid #0002; }
  .ah-3 .hi { color: var(--good); } .ah-3 .lo { color: #9a9286; font-weight: 500; }
  tr.ah-faint td { opacity: .45; }
  .ah-axis { margin-top: 10px; } .ah-axis h4 { font-size: .75rem; color: var(--ink-soft); font-weight: 500; margin: 0 0 4px; }
  .ah-bar { display: grid; grid-template-columns: 26px 5.5em 1fr 34px; align-items: center; gap: 6px; font-size: .8rem; padding: 3px 0; }
  .ah-bar .bx { height: 12px; border-radius: 3px; background: #9fb8a9; }
  .ah-bar.top .bx { background: var(--turf); } .ah-bar b { font-variant-numeric: tabular-nums; text-align: right; }
  .ah-bar .nm { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
  .carx { display: inline-flex; width: 22px; height: 22px; align-items: center; justify-content: center; border-radius: 4px;
    font-weight: 700; font-size: .8rem; border: 1px solid #0002; }
  .ah-note { font-size: .7rem; color: var(--ink-soft); margin: 8px 0 0; line-height: 1.6; }
  .aite-link { display: block; margin-top: 8px; padding: 11px 14px; border-radius: 10px; background: var(--turf); color: #fff;
    text-decoration: none; font-weight: 700; font-size: .9rem; }
  .aite-link small { font-weight: 400; color: #CFE3D8; font-size: .72rem; margin-left: 4px; }
"""

INDEX_JS = r"""
<script>
(function(){
  var COL = __COLORS__;
  var P = null;
  function load(){ if (!P) P = fetch('aite_data.json?t=' + Date.now()).then(function(r){ return r.json(); }); return P; }
  function cc(c){ var x = COL[String(c)] || ['#888','#fff']; return 'background:' + x[0] + ';color:' + x[1]; }
  function draw(box, R, h){
    var p1 = {}, p12 = {}, p123 = {}, cars = R.cars.map(function(x){ return x[0]; });
    R.j.forEach(function(t){ var a=t[0], b=t[1], c=t[2], p=t[3]/1e5;
      p1[a] = (p1[a]||0) + p; p12[a+'-'+b] = (p12[a+'-'+b]||0) + p; p123[a+'-'+b+'-'+c] = p; });
    if (h == null) h = cars.slice().sort(function(a,b){ return (p1[b]||0)-(p1[a]||0); })[0];
    var name = {}; R.cars.forEach(function(x){ name[x[0]] = x[1]; });
    var ph = p1[h] || 1e-9;
    var html = '<div class="ah-heads">' + cars.map(function(c){
      return '<button type="button" data-h="' + c + '" class="' + (c==h?'on':'') + '" style="' + cc(c) + '">' + c + '</button>'; }).join('') + '</div>';
    html += '<p class="ah-cap"><b>' + h + 'アタマの相手</b> <small>' + name[h] + '・' + h + '番の1着率 ' + Math.floor(ph*100) + '%</small></p>';
    html += '<table class="ah"><thead><tr><th style="width:56px"></th><th style="width:58px">2着率</th><th>3着率(その並びのとき)</th></tr></thead><tbody>';
    var sec = cars.filter(function(x){ return x!=h; }).sort(function(a,b){ return (p12[h+'-'+b]||0)-(p12[h+'-'+a]||0); });
    sec.forEach(function(x){
      var pp = (p12[h+'-'+x]||0), r2 = pp/ph;
      var th = cars.filter(function(y){ return y!=h && y!=x; }).sort(function(a,b){ return (p123[h+'-'+x+'-'+b]||0)-(p123[h+'-'+x+'-'+a]||0); });
      var chips = th.map(function(y){ var r3 = pp ? Math.floor((p123[h+'-'+x+'-'+y]||0)/pp*100) : 0;
        return '<span class="' + (r3>=31?'hi':(r3<=19?'lo':'')) + '"><i style="' + cc(y) + '">' + y + '</i>' + r3 + '</span>'; }).join('');
      html += '<tr class="' + (r2 < 0.05 ? 'ah-faint' : '') + '"><td><span class="ah-pair" style="' + cc(x) + '">' + h + x + '</span></td>'
            + '<td class="ah-p2">' + Math.floor(r2*100) + '%</td><td><div class="ah-3">' + chips + '</div></td></tr>';
    });
    html += '</tbody></table>';
    var ax = sec.map(function(x){ var s = 0; R.j.forEach(function(t){ if (t[0]==h && (t[1]==x || t[2]==x)) s += t[3]/1e5; });
      return [x, Math.round(s/ph*100)]; }).sort(function(a,b){ return b[1]-a[1]; });
    var mx = Math.max.apply(null, ax.map(function(a){ return a[1]; }).concat([1]));
    html += '<div class="ah-axis"><h4>軸候補 … ' + h + 'が1着のとき2着か3着に来る率(2着率+3着率)</h4>' + ax.map(function(a, i){
      return '<div class="ah-bar' + (i==0?' top':'') + '"><span class="carx" style="' + cc(a[0]) + '">' + a[0] + '</span><span class="nm">' + name[a[0]]
        + '</span><span class="bx" style="width:' + Math.max(2, a[1]/mx*100) + '%"></span><b>' + a[1] + '</b></div>'; }).join('') + '</div>';
    html += '<p class="ah-note">※' + (R.mode=='odds' ? 'AIとオッズ・ラインを合わせた' : 'AIだけの') + '3連単の出目確率から計算(%は切り捨て・' + R_upd + '時点)。'
          + '2着率＝' + h + 'が1着のとき2着に来る率。3着率＝その並び(1着→2着)のとき残りが3着に来る率。緑＝31以上、薄い灰＝19以下、薄い行は2着率5%未満の参考値。</p>';
    box.innerHTML = html;
    box.querySelectorAll('.ah-heads button').forEach(function(b){ b.addEventListener('click', function(){ draw(box, R, +b.dataset.h); }); });
  }
  var R_upd = '';
  function init(){ document.querySelectorAll('details.aite-fold').forEach(function(d){
    d.addEventListener('toggle', function(){
      if (!d.open || d.dataset.done) return;
      var box = d.querySelector('.aite-body');
      load().then(function(D){
        R_upd = D.updated;
        var R = D.races.filter(function(r){ return r.k == d.dataset.k; })[0];
        if (!R) { box.textContent = 'このレースの確率はまだありません'; return; }
        d.dataset.done = 1; draw(box, R, null);
      }).catch(function(){ box.textContent = '読み込めませんでした'; P = null; });
    });
  }); }
  if (document.readyState == 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
</script>
"""

PAGE = r"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI相手選び</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Shippori+Mincho:wght@600;800&family=Noto+Sans+JP:wght@400;500;700&display=swap" rel="stylesheet">
<style>
  :root { --turf:#1F4D3A; --turf-dark:#163A2B; --paper:#F6F1E4; --card:#FBF8F1; --line:#E4DAC0; --ink:#2A2118; --soft:#6B5F4D;
          --good:#2E7D46; --bad:#B0433A; --gold:#B8862B; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--paper); color:var(--ink); font-family:"Noto Sans JP",sans-serif; padding-bottom:96px; }
  header { background:var(--turf); color:#fff; padding:16px 16px 12px; }
  header .in { max-width:720px; margin:0 auto; display:flex; align-items:center; gap:12px; }
  header h1 { font-family:"Shippori Mincho",serif; margin:0; font-size:1.45rem; font-weight:800; }
  header p { margin:2px 0 0; font-size:.78rem; color:#CFE3D8; }
  header .badge { margin-left:auto; background:#fff; color:var(--turf); border-radius:10px; padding:6px 12px; text-align:center;
    font-weight:800; line-height:1.15; font-size:.85rem; }
  header .badge b { display:block; font-size:1.35rem; }
  main { max-width:720px; margin:0 auto; padding:0 16px; }
  .venues { display:flex; gap:6px; overflow-x:auto; padding:12px 0 6px; scrollbar-width:none; }
  .venues::-webkit-scrollbar, .races::-webkit-scrollbar { display:none; }
  .venues button { flex:0 0 auto; border:1px solid var(--line); background:#fff; color:var(--soft); font:inherit; font-weight:700;
    font-size:.82rem; padding:6px 12px; border-radius:8px; cursor:pointer; }
  .venues button.on { background:var(--ink); color:#fff; border-color:var(--ink); }
  .races { display:flex; gap:6px; overflow-x:auto; padding:4px 0 10px; scrollbar-width:none; border-bottom:1px solid var(--line); }
  .races button { flex:0 0 auto; min-width:52px; border:1px solid var(--line); background:#fff; color:var(--soft); font:inherit;
    font-size:.9rem; padding:7px 10px; border-radius:999px; cursor:pointer; }
  .races button.on { background:var(--ink); color:#fff; border-color:var(--ink); font-weight:700; }
  .races button.past { opacity:.45; }
  .rinfo { display:flex; justify-content:space-between; font-size:.8rem; color:var(--soft); padding:10px 0 4px; gap:8px; }
  .rinfo b { color:var(--ink); }
  .modes { display:grid; grid-template-columns:repeat(4,1fr); gap:8px; margin:8px 0 6px; }
  .modes button { border:none; background:#E8E2D3; color:var(--ink); font:inherit; font-size:.88rem; padding:12px 2px; border-radius:999px; cursor:pointer; }
  .modes button.on { background:var(--ink); color:#fff; font-weight:700; }
  .desc { font-size:.8rem; color:var(--soft); line-height:1.7; margin:6px 0 10px; }
  .crumb { font-size:.92rem; margin:6px 0 4px; display:flex; flex-wrap:wrap; gap:4px 10px; align-items:center; }
  .crumb a { color:var(--turf); cursor:pointer; text-decoration:underline; font-size:.8rem; }
  h3 { font-size:1.15rem; margin:16px 0 2px; }
  .sub { font-size:.78rem; color:var(--soft); margin:0 0 6px; }
  .row { display:grid; grid-template-columns:34px 1fr auto 104px; gap:10px; align-items:center; padding:10px 0; border-bottom:1px solid var(--line); }
  .row .nm { font-size:1rem; overflow:hidden; white-space:nowrap; text-overflow:ellipsis; }
  .row .nm small { color:var(--soft); font-size:.72rem; margin-left:4px; }
  .row .pc { font-size:1.2rem; font-weight:700; font-variant-numeric:tabular-nums; text-align:right; }
  .row .pc small { display:block; font-size:.68rem; font-weight:400; color:var(--soft); }
  .row button { border:1px solid var(--turf); background:#fff; color:var(--turf); font:inherit; font-size:.85rem; padding:9px 4px;
    border-radius:8px; cursor:pointer; }
  .row button.on { background:var(--turf); color:#fff; font-weight:700; }
  .row button.off { border-color:var(--bad); color:var(--bad); }
  .row button.off.on { background:var(--bad); color:#fff; }
  .row.dim { opacity:.4; }
  .car { display:inline-flex; width:30px; height:30px; align-items:center; justify-content:center; border-radius:6px; font-weight:700;
    border:1px solid #0002; font-variant-numeric:tabular-nums; }
  .car.s { width:24px; height:24px; font-size:.82rem; border-radius:4px; }
  .prev { margin:14px 0; background:#fff; border:1px solid var(--line); border-radius:12px; padding:12px 14px; }
  .prev .l { display:flex; justify-content:space-between; align-items:baseline; font-size:.85rem; padding:2px 0; }
  .prev .l b { font-size:1.1rem; font-variant-numeric:tabular-nums; }
  .prev .big b { font-size:1.6rem; }
  .prev .good { color:var(--good); } .prev .bad { color:var(--bad); }
  .prev .vt { margin-top:4px; padding-top:6px; border-top:1px dashed var(--line); } .prev .vt b { font-size:1rem; }
  .prev .sm { font-size:.74rem; color:var(--soft); }
  .add { width:100%; margin-top:10px; border:none; background:var(--turf); color:#fff; font:inherit; font-weight:700; font-size:1rem;
    padding:13px; border-radius:10px; cursor:pointer; }
  .add:disabled { background:#bdb5a3; cursor:default; }
  .bar { position:fixed; left:0; right:0; bottom:0; background:#fffdf8ee; backdrop-filter:blur(6px); border-top:1px solid var(--line);
    padding:10px 16px calc(10px + env(safe-area-inset-bottom)); }
  .bar .in { max-width:720px; margin:0 auto; display:flex; gap:8px; }
  .bar button, .bar a { flex:1; text-align:center; border:1px solid var(--turf); background:#fff; color:var(--turf); font:inherit;
    font-weight:700; font-size:.9rem; padding:11px 6px; border-radius:10px; cursor:pointer; text-decoration:none; }
  .bar button.main { background:var(--turf); color:#fff; flex:1.4; }
  .sheet-bg { position:fixed; inset:0; background:#0006; display:none; z-index:10; }
  .sheet { position:fixed; left:0; right:0; bottom:0; max-height:86vh; overflow:auto; background:var(--card); border-radius:18px 18px 0 0;
    z-index:11; transform:translateY(100%); transition:transform .2s; padding:0 16px calc(20px + env(safe-area-inset-bottom)); }
  .sheet.open { transform:none; } .sheet-bg.open { display:block; }
  .sheet .hd { position:sticky; top:0; background:var(--card); display:flex; align-items:center; gap:10px; padding:16px 0 10px;
    border-bottom:3px solid var(--ink); }
  .sheet .hd h2 { margin:0; font-size:1.2rem; } .sheet .hd span { color:var(--soft); font-size:.9rem; }
  .sheet .hd button { margin-left:auto; border:none; background:none; font-size:1.6rem; cursor:pointer; color:var(--ink); }
  .tk { display:flex; align-items:center; gap:8px; padding:6px 0; border-bottom:1px dashed var(--line); }
  .tk .cs { display:flex; align-items:center; gap:3px; flex-wrap:wrap; }
  .tk .cs em { color:var(--soft); font-style:normal; margin:0 1px; }
  .tk .p { margin-left:auto; font-variant-numeric:tabular-nums; font-weight:700; text-align:right; }
  .tk .p small { display:block; font-weight:400; color:var(--soft); font-size:.7rem; }
  .tk button { border:none; background:none; color:var(--soft); font:inherit; font-size:.85rem; cursor:pointer; padding:4px; }
  .empty { color:var(--soft); font-size:.9rem; padding:18px 0; }
  .note { font-size:.74rem; color:var(--soft); line-height:1.7; margin:10px 0; }
  .clear { display:block; margin:10px auto; border:none; background:none; color:var(--turf); font:inherit; text-decoration:underline; cursor:pointer; }
  details.how { font-size:.8rem; color:var(--soft); margin:8px 0; } details.how summary { cursor:pointer; color:var(--turf); }
</style>
</head>
<body>
<header><div class="in">
  <div><h1>AI相手選び</h1><p id="hdate"></p></div>
  <div class="badge" id="hbadge"></div>
</div></header>
<main>
  <nav class="venues" id="venues"></nav>
  <nav class="races" id="races"></nav>
  <div class="rinfo" id="rinfo"></div>
  <div class="modes" id="modes">
    <button type="button" data-m="head">頭を選ぶ</button><button type="button" data-m="box">3車BOX</button><button type="button" data-m="aru">あるなし</button><button type="button" data-m="auto">おまかせ</button>
  </div>
  <div id="body"><p class="empty">読み込み中…</p></div>
  <details class="how"><summary>数字の見方</summary>
    <p>確率はトップページの予想と同じ3連単の出目確率です(オッズがあるときはAIとオッズ・ラインを合わせたもの、まだ無いときはAIだけ)。
    <b>AI的中見込み</b>＝選んだ目の確率の合計(過去5万レースで、見込みと実際の的中はほぼ同じ)。
    <b>平均的な合成</b>＝的中見込みの目に普通つく合成オッズ(競輪の払戻率は約75%なので 0.75÷的中見込み)。今の合成がこれより10%以上高ければ緑「妙味あり」、10%以上低ければ赤「辛い」。
    <b>得になる合成(必要合成オッズ)</b>＝1÷的中見込み。今の合成がこれを超えれば、AIの見立てでは払戻率を差し引いても得。
    オッズは5分おきの更新時点のもので、締切までに変わります。</p></details>
</main>
<div class="bar"><div class="in">
  <a id="back" href="index.html">新聞へ戻る</a>
  <button type="button" class="main" id="openList">買い目の一覧</button>
</div></div>
<div class="sheet-bg" id="sheetBg"></div>
<div class="sheet" id="sheet"></div>
<script>
(function(){
  var COL = __COLORS__;
  var D = null, R = null, mode = 'head', st = {};
  var LK = 'aite-list';
  var list = {};   // {date, races:{k:[ "1-2-3", ...]}}
  function cc(c){ var x = COL[String(c)] || ['#888','#fff']; return 'background:' + x[0] + ';color:' + x[1]; }
  function car(c, s){ return '<span class="car' + (s?' s':'') + '" style="' + cc(c) + '">' + c + '</span>'; }
  function pct(p, d){ return (p*100).toFixed(d==null?1:d) + '%'; }
  function esc(s){ return String(s).replace(/[&<>"]/g, function(m){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]; }); }
  function loadList(){ try { var x = JSON.parse(localStorage.getItem(LK) || 'null'); if (x && x.date == D.date) list = x; else list = {date:D.date, races:{}}; }
                        catch(e){ list = {date:D.date, races:{}}; } }
  function saveList(){ try { localStorage.setItem(LK, JSON.stringify(list)); } catch(e){} }
  function idx(){ // 確率とオッズの表
    var p = {}, o = {}, p1 = {}, p12 = {}, top3 = {};
    R.j.forEach(function(t){ var k = t[0]+'-'+t[1]+'-'+t[2], q = t[3]/1e5; p[k] = q; o[k] = t[4];
      p1[t[0]] = (p1[t[0]]||0) + q; p12[t[0]+'-'+t[1]] = (p12[t[0]+'-'+t[1]]||0) + q;
      [t[0],t[1],t[2]].forEach(function(c){ top3[c] = (top3[c]||0) + q; }); });
    R.P = p; R.O = o; R.p1 = p1; R.p12 = p12; R.top3 = top3;
    R.cars_ = R.cars.map(function(x){ return x[0]; }); R.name = {}; R.rank = {};
    R.cars.forEach(function(x){ R.name[x[0]] = x[1]; R.rank[x[0]] = x[2]; });
  }
  function stats(tks){
    var p = 0, inv = 0, ev = 0, n = 0, no = 0;
    tks.forEach(function(k){ p += R.P[k] || 0; n++; var o = R.O[k]; if (o > 0) { inv += 1/o; ev += (R.P[k]||0) * o; } else no++; });
    return {n:n, p:p, comp: inv ? 1/inv : 0, roi: (n && !no) ? ev/n : 0, no:no};
  }
  function prevHtml(tks, label){
    var s = stats(tks);
    if (!s.n) return '<div class="prev"><div class="l"><span>' + label + '</span><b>0点</b></div></div>';
    var need = s.p ? 1/s.p : 0, avg = need * 0.75;   // 競輪の払戻率は約75% → 普通の合成オッズは 必要×0.75 くらい
    var r = (s.comp && avg) ? s.comp / avg : 0, cls = '', vt = '';
    if (r) {
      var d = Math.round((r - 1) * 100);
      if (r >= 1.3) { cls = 'good'; vt = '平均より' + d + '%甘い(妙味大)'; }
      else if (r >= 1.1) { cls = 'good'; vt = '平均より' + d + '%甘い(妙味あり)'; }
      else if (r > 0.9) { vt = '平均並み'; }
      else { cls = 'bad'; vt = '平均より' + (-d) + '%辛い'; }
    }
    return '<div class="prev"><div class="l"><span>' + label + '</span><b>' + s.n + '点</b></div>'
      + '<div class="l big"><span>AI的中見込み</span><b>' + pct(s.p) + '</b></div>'
      + '<div class="l"><span>今の合成オッズ</span><b class="' + cls + '">' + (s.comp ? s.comp.toFixed(1) + '倍' : 'オッズ待ち') + '</b></div>'
      + '<div class="l"><span>平均的な合成(的中見込みから)</span><b>' + avg.toFixed(1) + '倍</b></div>'
      + (vt ? '<div class="l vt ' + cls + '"><span>オッズの妙味</span><b>' + vt + '</b></div>' : '')
      + '<div class="l sm"><span>得になる合成(必要合成オッズ)</span><span>' + need.toFixed(1) + '倍</span></div>'
      + '</div>';
  }
  function row(c, p, sub, btn, on, dim, cls){
    return '<div class="row' + (dim?' dim':'') + '">' + car(c) + '<div class="nm">' + esc(R.name[c]) + '<small>' + esc(R.rank[c]) + '</small></div>'
      + '<div class="pc">' + pct(p) + (sub ? '<small>' + sub + '</small>' : '') + '</div>'
      + '<button type="button" class="' + (cls||'') + (on?' on':'') + '" data-c="' + c + '">' + btn + '</button></div>';
  }
  // ---- 頭を選ぶ
  function headTickets(){ var t = [];
    if (st.h == null) return t;
    st.s.forEach(function(b){ st.t.forEach(function(c){ if (b!=c && b!=st.h && c!=st.h) t.push(st.h+'-'+b+'-'+c); }); });
    return t; }
  function drawHead(){
    var h = st.h, html = '<p class="desc">頭を1車、2着と3着を好きなだけ選ぶ。頭を変えて追加すれば、いくつもの頭の買い目を一覧に持てます。</p>';
    html += '<div class="crumb">1着 ' + (h!=null ? car(h,1) + ' <a data-act="h0">変更</a>' : '未選択') + '｜2着 ' + (st.s.length ? st.s.map(function(c){ return car(c,1); }).join('') : '未選択')
          + '｜3着 ' + (st.t.length ? st.t.map(function(c){ return car(c,1); }).join('') : '未選択') + '</div>';
    if (h == null) {
      html += '<h3>頭を選ぶ</h3><p class="sub">1着になると思う車を1車(1着率の高い順)</p>';
      R.cars_.slice().sort(function(a,b){ return R.p1[b]-R.p1[a]; }).forEach(function(c){ html += row(c, R.p1[c]||0, '', '頭にする', false); });
    } else {
      html += '<h3>2着を選ぶ</h3><p class="sub">' + h + 'が1着のときの2着率(高い順)。何車でも</p>';
      R.cars_.filter(function(c){ return c!=h; }).sort(function(a,b){ return (R.p12[h+'-'+b]||0)-(R.p12[h+'-'+a]||0); }).forEach(function(c){
        var r2 = (R.p12[h+'-'+c]||0) / (R.p1[h]||1);
        html += row(c, r2, '', st.s.indexOf(c)>=0 ? '2着から外す' : '2着にする', st.s.indexOf(c)>=0, false, 'k2'); });
      if (st.s.length) {
        html += '<h3>3着を選ぶ</h3><p class="sub">' + h + '→' + st.s.join('・') + ' のときの3着率(高い順)。何車でも</p>';
        var base = 0; st.s.forEach(function(b){ base += R.p12[h+'-'+b] || 0; });
        R.cars_.filter(function(c){ return c!=h; }).map(function(c){ var s = 0; st.s.forEach(function(b){ if (b!=c) s += R.P[h+'-'+b+'-'+c] || 0; }); return [c, base ? s/base : 0]; })
          .sort(function(a,b){ return b[1]-a[1]; }).forEach(function(x){
            html += row(x[0], x[1], '', st.t.indexOf(x[0])>=0 ? '3着から外す' : '3着にする', st.t.indexOf(x[0])>=0, st.s.length==1 && st.s[0]==x[0], 'k3'); });
      }
    }
    var tk = headTickets();
    html += prevHtml(tk, h!=null ? h + '頭の買い目' : '買い目') + '<button type="button" class="add" id="add"' + (tk.length?'':' disabled') + '>一覧に追加</button>';
    return [html, tk];
  }
  // ---- 3車BOX
  function boxTickets(){ var t = [], c = st.b;
    c.forEach(function(a){ c.forEach(function(b){ c.forEach(function(d){ if (a!=b && b!=d && a!=d) t.push(a+'-'+b+'-'+d); }); }); }); return t; }
  function drawBox(){
    var html = '<p class="desc">3着以内に来ると思う車を3車以上選ぶと、その車の3連単ボックス(3車で6点・4車で24点)になります。</p>';
    html += '<h3>車を選ぶ</h3><p class="sub">3着以内に来る率の高い順</p>';
    R.cars_.slice().sort(function(a,b){ return R.top3[b]-R.top3[a]; }).forEach(function(c){
      html += row(c, R.top3[c]||0, '3着内', st.b.indexOf(c)>=0 ? '外す' : '入れる', st.b.indexOf(c)>=0, false, 'kb'); });
    var tk = boxTickets();
    html += prevHtml(tk, st.b.length + '車BOX') + '<button type="button" class="add" id="add"' + (tk.length?'':' disabled') + '>一覧に追加</button>';
    return [html, tk];
  }
  // ---- あるなし
  function aruTickets(){ var t = [];
    if (st.a == null) return t;
    R.j.forEach(function(x){ var s = [x[0],x[1],x[2]]; if (s.indexOf(st.a)>=0 && (st.n==null || s.indexOf(st.n)<0)) t.push(s.join('-')); }); return t; }
  function drawAru(){
    var html = '<p class="desc">3着以内に「来る」と思う車を1車、「来ない」と思う車を1車選ぶだけ。その車が1〜3着のどこかに入り、もう1車が外れる3連単を全部買います。頭が決めにくい・荒れそうなレース向き。</p>';
    html += '<h3>あるを選ぶ</h3><p class="sub">3着以内に来る率の高い順</p>';
    R.cars_.slice().sort(function(a,b){ return R.top3[b]-R.top3[a]; }).forEach(function(c){
      html += row(c, R.top3[c]||0, '3着内', st.a==c ? 'あるから外す' : 'あるにする', st.a==c, st.n==c, 'ka'); });
    if (st.a != null) {
      html += '<h3>なしを選ぶ</h3><p class="sub">' + st.a + 'が3着以内のとき、各車が3着以内に来る率(低いほど消しやすい)。選ばなくてもよい</p>';
      var pa = R.top3[st.a] || 1;
      R.cars_.filter(function(c){ return c!=st.a; }).map(function(c){ var s = 0;
        R.j.forEach(function(x){ var y = [x[0],x[1],x[2]]; if (y.indexOf(st.a)>=0 && y.indexOf(c)>=0) s += x[3]/1e5; }); return [c, s/pa]; })
        .sort(function(a,b){ return a[1]-b[1]; }).forEach(function(x){
          html += row(x[0], x[1], '3着内', st.n==x[0] ? 'なしから外す' : 'なしにする', st.n==x[0], false, 'kn off'); });
    }
    var tk = aruTickets();
    html += prevHtml(tk, 'あるなし') + '<button type="button" class="add" id="add"' + (tk.length?'':' disabled') + '>一覧に追加</button>';
    return [html, tk];
  }
  // ---- おまかせ(%の形ごとに過去の結果で選んだフォーメーション)
  var TBN = ['25%未満','25〜35%','35〜45%','45〜55%','55%以上'];
  function autoRule(){
    var r1 = R.cars_.slice().sort(function(a,b){ return R.p1[b]-R.p1[a]; }), r3 = R.cars_.slice().sort(function(a,b){ return R.top3[b]-R.top3[a]; });
    var top = R.p1[r1[0]] || 0, tb = top < .25 ? 0 : top < .35 ? 1 : top < .45 ? 2 : top < .55 ? 3 : 4;
    var kind = R.g ? 'G' : (R.cars_.length >= 8 ? '9' : '7');
    var key = kind + tb, ru = (D.auto || {})[key];
    if (!ru && kind == 'G') { ru = D.auto['G' + Math.max(1, tb)]; key = 'G' + Math.max(1, tb); }
    if (!ru) return null;
    var sets = ru.f.map(function(sp){ return sp[0] == 'all' ? R.cars_.slice() : (sp[0] == 'p1' ? r1 : r3).slice(sp[1], sp[2]); });
    var lab = ru.f.map(function(sp){ return sp[0] == 'all' ? '全員' : (sp[0] == 'p1' ? '1着率' : '3着内率') + (sp[2]-sp[1] > 1 ? (sp[1]+1) + '〜' + sp[2] + '位' : sp[2] + '位'); });
    var tk = [];
    sets[0].forEach(function(a){ sets[1].forEach(function(b){ sets[2].forEach(function(c){ if (a!=b && b!=c && a!=c) tk.push(a+'-'+b+'-'+c); }); }); });
    return {ru:ru, sets:sets, lab:lab, tk:tk, kind:kind, tb:tb, top:top};
  }
  function drawAuto(){
    var x = autoRule(), html = '<p class="desc">本命の1着率と頭数(ガールズ)の形から、過去2年(約5万レース)でどちらの年も的中30%以上だった中で回収率が一番良かったフォーメーションを自動で組みます。</p>';
    if (!x) return ['<p class="empty">このレースの形には、おまかせの組み方がありません</p>', []];
    html += '<div class="prev"><div class="l"><span>このレースの形</span><b>' + (x.kind=='G' ? 'ガールズ' : x.kind + '車') + '・本命' + TBN[x.tb] + '</b></div>'
      + '<div class="l"><span>本命の1着率</span><b>' + pct(x.top) + '</b></div></div>';
    html += '<h3>組み方</h3><p class="sub">' + x.lab.join(' → ') + '</p>';
    ['1着','2着','3着'].forEach(function(nm, i){ html += '<div class="crumb">' + nm + ' ' + x.sets[i].map(function(c){ return car(c,1); }).join('') + '</div>'; });
    html += '<p class="note">この形の過去の成績: ' + x.ru.R + 'レース・平均' + x.ru.pts + '点・的中' + Math.round(x.ru.hit*100) + '%・回収率 '
      + Math.round(x.ru.roi[0]*100) + '%(2025) / ' + Math.round(x.ru.roi[1]*100) + '%(2026)。'
      + 'ただし片方の年で選んだ組み方をもう片方の年で使うと、全体の回収率は73%前後でした(100%は超えません)。</p>';
    html += prevHtml(x.tk, 'おまかせ') + '<button type="button" class="add" id="add"' + (x.tk.length?'':' disabled') + '>一覧に追加</button>';
    return [html, x.tk];
  }
  function draw(){
    document.querySelectorAll('#modes button').forEach(function(b){ b.classList.toggle('on', b.dataset.m == mode); });
    var r = mode == 'head' ? drawHead() : (mode == 'box' ? drawBox() : (mode == 'aru' ? drawAru() : drawAuto()));
    var body = document.getElementById('body'); body.innerHTML = r[0];
    body.querySelectorAll('.row button').forEach(function(b){ b.addEventListener('click', function(){ click(b); }); });
    var h0 = body.querySelector('[data-act="h0"]'); if (h0) h0.addEventListener('click', function(){ st.h = null; st.s = []; st.t = []; draw(); });
    var add = document.getElementById('add');
    if (add) add.addEventListener('click', function(){
      var L = list.races[R.k] || []; r[1].forEach(function(k){ if (L.indexOf(k) < 0) L.push(k); }); list.races[R.k] = L; saveList();
      reset(); draw(); updBar(); openSheet(); });
    updBar();
  }
  function tog(a, c){ var i = a.indexOf(c); if (i>=0) a.splice(i,1); else a.push(c); }
  function click(b){
    var c = +b.dataset.c;
    if (mode == 'head') {
      if (st.h == null) { st.h = c; st.s = []; st.t = []; }
      else if (b.classList.contains('k2')) { tog(st.s, c); st.t = st.t.filter(function(x){ return st.s.length > 1 || st.s.indexOf(x) < 0; }); }
      else if (b.classList.contains('k3')) tog(st.t, c);
    } else if (mode == 'box') tog(st.b, c);
    else if (b.classList.contains('ka')) { st.a = st.a == c ? null : c; if (st.n == st.a) st.n = null; }
    else st.n = st.n == c ? null : c;
    draw();
  }
  function reset(){ st = {h:null, s:[], t:[], b:[], a:null, n:null}; }
  function updBar(){ var L = list.races[R.k] || [];
    document.getElementById('openList').textContent = '買い目の一覧' + (L.length ? '(' + L.length + '点)' : ''); }
  function openSheet(){
    var L = (list.races[R.k] || []).slice().sort(function(a,b){ return (R.P[b]||0)-(R.P[a]||0); });
    var html = '<div class="hd"><h2>買い目の一覧</h2><span>' + esc(R.v) + ' ' + R.no + 'R</span><button type="button" id="close" aria-label="閉じる">×</button></div>';
    if (!L.length) html += '<p class="empty">まだ買い目がありません。頭・BOX・あるなしで選んで「一覧に追加」を押してください。</p>';
    L.forEach(function(k){ var c = k.split('-');
      html += '<div class="tk"><div class="cs">' + car(c[0],1) + '<em>-</em>' + car(c[1],1) + '<em>-</em>' + car(c[2],1) + '</div>'
        + '<div class="p">' + pct(R.P[k]||0) + '<small>' + (R.O[k] ? R.O[k].toFixed(1) + '倍' : 'オッズ待ち') + '</small></div>'
        + '<button type="button" data-k="' + k + '">外す</button></div>'; });
    if (L.length) {
      html += prevHtml(L, '合計');
      html += '<p class="note">同じ目が重なっても1回だけ数えます。一覧はその日いっぱい、このブラウザに残ります。</p><button type="button" class="clear" id="clr">このレースの一覧を全部消す</button>';
    }
    var others = Object.keys(list.races).filter(function(k){ return k != R.k && list.races[k].length; });
    if (others.length) html += '<p class="note">ほかのレースの一覧: ' + others.map(function(k){ var x = D.races.filter(function(r){ return r.k==k; })[0];
      return x ? '<a href="?k=' + k + '">' + esc(x.v) + x.no + 'R(' + list.races[k].length + '点)</a>' : ''; }).join(' ') + '</p>';
    html += '<button type="button" class="add" id="close2">閉じて選ぶに戻る</button>';
    var sh = document.getElementById('sheet'); sh.innerHTML = html; sh.classList.add('open'); document.getElementById('sheetBg').classList.add('open');
    sh.querySelectorAll('.tk button').forEach(function(b){ b.addEventListener('click', function(){
      list.races[R.k] = (list.races[R.k]||[]).filter(function(x){ return x != b.dataset.k; }); saveList(); updBar(); openSheet(); }); });
    var clr = document.getElementById('clr'); if (clr) clr.addEventListener('click', function(){ delete list.races[R.k]; saveList(); updBar(); openSheet(); });
    ['close','close2'].forEach(function(id){ document.getElementById(id).addEventListener('click', closeSheet); });
  }
  function closeSheet(){ document.getElementById('sheet').classList.remove('open'); document.getElementById('sheetBg').classList.remove('open'); }
  document.getElementById('sheetBg').addEventListener('click', closeSheet);
  document.getElementById('openList').addEventListener('click', openSheet);
  document.querySelectorAll('#modes button').forEach(function(b){ b.addEventListener('click', function(){ mode = b.dataset.m; draw(); }); });
  function pick(k){
    R = D.races.filter(function(r){ return r.k == k; })[0] || D.races[0];
    if (!R) { document.getElementById('body').innerHTML = '<p class="empty">今日のレースがありません</p>'; return; }
    idx(); reset();
    var vs = []; D.races.forEach(function(r){ if (vs.indexOf(r.v) < 0) vs.push(r.v); });
    document.getElementById('venues').innerHTML = vs.map(function(v){ var f = D.races.filter(function(r){ return r.v == v; });
      var now = new Date(), hm = ('0'+now.getHours()).slice(-2) + ':' + ('0'+now.getMinutes()).slice(-2);
      var nx = f.filter(function(r){ return r.dl > hm; })[0] || f[f.length-1];
      return '<button type="button" data-k="' + nx.k + '" class="' + (v == R.v ? 'on' : '') + '">' + esc(v) + '</button>'; }).join('');
    var now = new Date(), hm = ('0'+now.getHours()).slice(-2) + ':' + ('0'+now.getMinutes()).slice(-2);
    document.getElementById('races').innerHTML = D.races.filter(function(r){ return r.v == R.v; }).map(function(r){
      return '<button type="button" data-k="' + r.k + '" class="' + (r.k == R.k ? 'on' : '') + (r.dl && r.dl <= hm ? ' past' : '') + '">' + r.no + 'R</button>'; }).join('');
    document.querySelectorAll('#venues button, #races button').forEach(function(b){ b.addEventListener('click', function(){
      history.replaceState(null, '', '?k=' + b.dataset.k); pick(b.dataset.k); }); });
    var on = document.querySelector('#races button.on'); if (on) on.scrollIntoView({inline:'center', block:'nearest'});
    document.getElementById('hbadge').innerHTML = esc(R.v) + '<b>' + R.no + 'R</b>';
    document.getElementById('rinfo').innerHTML = '<span><b>' + esc(R.t) + '</b>　締切 ' + esc(R.dl) + '</span><span>' + (R.mode == 'odds' ? 'AI+オッズ' : 'AIだけ(オッズ待ち)') + '・更新 ' + D.updated + '</span>';
    document.getElementById('back').href = 'index.html?v=' + R.vi + '&r=' + R.no;
    closeSheet(); draw();
  }
  fetch('aite_data.json?t=' + Date.now()).then(function(r){ return r.json(); }).then(function(d){
    D = d; document.getElementById('hdate').textContent = d.date + '・競輪';
    loadList();
    var q = new URLSearchParams(location.search).get('k');
    if (!q) { var now = new Date(), hm = ('0'+now.getHours()).slice(-2) + ':' + ('0'+now.getMinutes()).slice(-2);
      var nx = d.races.filter(function(r){ return r.dl > hm; }).sort(function(a,b){ return a.dl < b.dl ? -1 : 1; })[0]; q = nx ? nx.k : null; }
    pick(q);
  }).catch(function(){ document.getElementById('body').innerHTML = '<p class="empty">読み込めませんでした。少し待ってから開き直してください。</p>'; });
})();
</script>
</body>
</html>
"""
