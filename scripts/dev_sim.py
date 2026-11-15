# -*- coding: utf-8 -*-
"""
展開シミュレーション(11/15 作り直し)。

着順は「3連単の出目確率」(tri_model: オッズ + ラインの決まり方)から1つ引く → 1〜3着は確率どおりの頻度で出る。
動きは競輪のよくある流れで組み立てる(残り2周半ぶん):
  周回中   … 初手の並び(前受け = 2番目のライン、その後ろに3番目以降、先行ライン(主導権を取りにいくライン)は後方)
  赤板〜打鐘 … 先行ラインが外から上がって前に出る(主導権)
  最終周   … 1着の選手が先行ライン以外の先頭なら、バックで外から捲る。番手・3番手なら4コーナーから外に持ち出して差す
  ゴール   … 引いた着順で入線
「別の展開」で引き直すと、確率に応じて別の結果になる。決まり手は1着の選手の位置から付ける(逃げ/捲り/差し/マーク)。
"""
import json
import random

from report import car_color  # noqa: E402  (report から呼ぶときは循環しないよう関数内で使う)


def _leader_line(lines, rows):
    """主導権を取りにいくライン = 先頭の決まり手予測が「逃」で1着率が高いライン(なければ印で一番強いライン)"""
    dom = {r["car"]: r.get("dominant_type") for r in rows}
    p = {r["car"]: r.get("adjusted", 0) for r in rows}
    cand = [i for i, l in enumerate(lines) if len(l) >= 2 and dom.get(l[0]) == "逃"]
    if cand:
        return max(cand, key=lambda i: p.get(lines[i][0], 0))
    return 0


def payload(result):
    rows = result.get("rows") or []
    lm = result.get("line_map") or {}
    jt = result.get("tri_joint")
    if not jt:
        jt = {(c["first"], c["second"], c["third"]): c["prob"] / 100 for c in (result.get("trifecta") or {}).get("combos", [])}
    if not rows or not jt or len(rows) < 3:
        return None
    by = {}
    for car, v in lm.items():
        by.setdefault(v["line_index"], []).append((v["position"], car))
    lines = [[c for _, c in sorted(m)] for _, m in sorted(by.items())]
    cars = [r["car"] for r in rows]
    for c in cars:
        if c not in lm:
            lines.append([c])
    # 印の強さ順(tri_model と同じ)に並べる
    import tri_model
    li = tri_model._lines(lm, [{"car": r["car"], "mark": r.get("mark") or "", "score": r.get("score") or 0} for r in rows])
    lines.sort(key=lambda l: li.get(l[0], (99,))[0])
    lead = _leader_line(lines, rows)
    # 初手: 前受け = 先行ライン以外で一番強いライン → その他 → 先行ライン → 単騎
    others = [i for i in range(len(lines)) if i != lead and len(lines[i]) >= 2]
    solos = [i for i in range(len(lines)) if i != lead and len(lines[i]) == 1]
    start = [c for i in others for c in lines[i]] + lines[lead] + [c for i in solos for c in lines[i]]
    p1 = {r["car"]: r.get("adjusted", 0) / 100 for r in rows}
    combos = sorted(jt.items(), key=lambda kv: -kv[1])[:400]
    return dict(cars=cars, lines=lines, lead=lead, start=start, p1=p1,
                combos=[["-".join(map(str, k)), round(v, 5)] for k, v in combos],
                names={r["car"]: r["name"] for r in rows},
                colors={c: list(car_color(c)) for c in cars})


def render(tab_id, result):
    pl = payload(result)
    if not pl:
        return ""
    sid = f"ds_{tab_id}"
    return f"""
<div class="ds" id="{sid}">
  <div class="mw-label">展開シミュレーション(残り2周半)</div>
  <div class="ds-cap" id="{sid}_cap">▶を押すと再生。着順は3連単の出目確率から引くので、来やすい展開ほどよく出る</div>
  <svg viewBox="0 0 400 260" class="ds-svg">
    <path d="M110,50 L290,50 A80,80 0 0 1 290,210 L110,210 A80,80 0 0 1 110,50 Z" fill="none" stroke="#8a8f98" stroke-width="44"/>
    <path d="M110,50 L290,50 A80,80 0 0 1 290,210 L110,210 A80,80 0 0 1 110,50 Z" fill="none" stroke="#d6d9de" stroke-width="40"/>
    <path d="M110,72 L290,72 A58,58 0 0 1 290,188 L110,188 A58,58 0 0 1 110,72 Z" fill="#5a9a5d"/>
    <line x1="290" y1="190" x2="290" y2="232" stroke="#C8402A" stroke-width="2"/>
    <text x="200" y="135" text-anchor="middle" font-size="12" fill="#fff" id="{sid}_ph"></text>
    <text x="200" y="152" text-anchor="middle" font-size="10" fill="#e8f5e9">ゴール ↘ 右下 / 反時計回り</text>
    <g id="{sid}_cars"></g>
  </svg>
  <div class="ds-btns"><button type="button" id="{sid}_play">▶ 再生</button><button type="button" id="{sid}_again">別の展開</button></div>
  <div class="ds-res" id="{sid}_res"></div>
  <script>(function(){{
  var P={json.dumps(pl, ensure_ascii=False)}, id="{sid}";
  var g=document.getElementById(id+"_cars"), cap=document.getElementById(id+"_cap"), ph=document.getElementById(id+"_ph"), res=document.getElementById(id+"_res");
  var NS="http://www.w3.org/2000/svg", els={{}};
  P.cars.forEach(function(c){{var e=document.createElementNS(NS,"g");var ci=document.createElementNS(NS,"circle");ci.setAttribute("r",7);
    ci.setAttribute("fill",P.colors[c][0]);ci.setAttribute("stroke","#333");ci.setAttribute("stroke-width","0.8");
    var t=document.createElementNS(NS,"text");t.textContent=c;t.setAttribute("text-anchor","middle");t.setAttribute("dy","3.5");t.setAttribute("font-size","9");
    t.setAttribute("font-weight","700");t.setAttribute("fill",P.colors[c][1]);e.appendChild(ci);e.appendChild(t);g.appendChild(e);els[c]=e;}});
  // 走路: 0=ゴール線(右下)から反時計回り。r=レーン(0内,1中,2外)
  function xy(d,lane){{d=((d%1)+1)%1;var R=69+lane*9,S=180,C=Math.PI*R,L=2*S+2*C,s=d*L;
    if(s<C){{var a=Math.PI/2-s/R;return[290+R*Math.cos(a),130+R*Math.sin(a)];}} s-=C;
    if(s<S)return[290-s,130-R]; s-=S; if(s<C){{var a=-Math.PI/2-s/R;return[110+R*Math.cos(a),130+R*Math.sin(a)];}} s-=C; return[110+s,130+R];}}
  function pick(){{var r=Math.random()*P.combos.reduce(function(a,b){{return a+b[1];}},0),acc=0;
    for(var i=0;i<P.combos.length;i++){{acc+=P.combos[i][1];if(acc>=r)return P.combos[i];}} return P.combos[0];}}
  var plan=null, raf=null;
  function lineOf(c){{for(var i=0;i<P.lines.length;i++){{var k=P.lines[i].indexOf(c);if(k>=0)return[i,k];}}return[-1,0];}}
  function makePlan(){{
    var cb=pick(), top=cb[0].split("-").map(Number);
    var rest=P.cars.filter(function(c){{return top.indexOf(c)<0;}}).sort(function(a,b){{return P.p1[b]-P.p1[a];}});
    var fin=top.concat(rest), lead=P.lines[P.lead];
    var after=lead.concat(P.start.filter(function(c){{return lead.indexOf(c)<0;}}));   // 打鐘後: 先行ラインが前
    var w=lineOf(top[0]), kim;
    if(w[0]==P.lead&&w[1]==0)kim="逃げ"; else if(w[1]==0)kim="捲り"; else if(w[0]==P.lead&&w[1]==1)kim="差し(番手)"; else kim=(w[1]>=1?"差し・マーク":"追込");
    var mk=(w[1]==0&&w[0]!=P.lead)?P.lines[w[0]]:[];   // 捲るライン
    return {{fin:fin,after:after,kim:kim,mk:mk,p:cb[1],top:top}};
  }}
  function rankPos(order,c){{return order.indexOf(c);}}
  function frame(t){{  // t: 0..1
    var lead=0.5+2.5*t, tag="";
    P.cars.forEach(function(c){{
      var d,lane=0,r0=rankPos(P.start,c),r1=rankPos(plan.after,c),r2=rankPos(plan.fin,c);
      if(t<0.3){{d=lead-r0*0.03;tag="周回中: 初手の並び";}}
      else if(t<0.45){{var u=(t-0.3)/0.15,e=u*u*(3-2*u);d=lead-((1-e)*r0+e*r1)*0.03;
        if(plan.after.indexOf(c)<P.lines[P.lead].length&&r1<r0)lane=Math.sin(Math.PI*u)*1.6;tag="赤板〜打鐘: 先行ラインが叩いて主導権";}}
      else if(t<0.8){{var u=(t-0.45)/0.35;d=lead-r1*0.03;
        if(plan.mk.indexOf(c)>=0&&u>0.55){{var v=(u-0.55)/0.45;lane=2*Math.min(1,v*2);d=lead-(r1*(1-v)+plan.mk.indexOf(c)*v*0.6)*0.03;}}
        tag=u>0.55&&plan.mk.length?"最終ホーム〜バック: 捲り発進":(u>0.45?"最終周(ジャン)":"打鐘後: 先行ラインが主導権");}}
      else{{var u=(t-0.8)/0.2,e=u*u*(3-2*u),rr=(plan.mk.indexOf(c)>=0?plan.mk.indexOf(c)*0.6:r1);
        d=lead-((1-e)*rr*0.03+e*r2*0.022);
        if(r2<r1)lane=Math.min(2,(r1-r2)*0.6)*Math.sin(Math.PI*Math.min(1,u*1.1));
        if(plan.mk.indexOf(c)>=0)lane=2*(1-e);
        tag=u<0.5?"最終バック〜4コーナー":(u<0.97?"直線":"ゴール");}}
      var p=xy(d,lane);els[c].setAttribute("transform","translate("+p[0].toFixed(1)+","+p[1].toFixed(1)+")");
    }});
    ph.textContent=tag;
  }}
  function play(again){{
    if(!plan||again)plan=makePlan(); if(raf)cancelAnimationFrame(raf);
    res.innerHTML=""; var t0=null,D=9000;
    function step(ts){{if(!t0)t0=ts;var t=Math.min(1,(ts-t0)/D);frame(t);
      if(t<1)raf=requestAnimationFrame(step); else {{var f=plan.fin;
        res.innerHTML="<b>1着 "+f[0]+" "+(P.names[f[0]]||"")+"("+plan.kim+")</b> ・ 2着 "+f[1]+" ・ 3着 "+f[2]+
          " <span class='dim'>(この3連単 "+plan.top.join("-")+" が来る確率 "+(plan.p*100).toFixed(1)+"%)</span>";}}}}
    raf=requestAnimationFrame(step);
  }}
  plan=makePlan(); frame(0);
  document.getElementById(id+"_play").onclick=function(){{play(false);}};
  document.getElementById(id+"_again").onclick=function(){{play(true);}};
  }})();</script>
</div>"""
