"""
競輪: 「ラインの並び通り」買い(3連単 先頭→番手→3番手 / 3連複 ライン3車)の回収率を、ライン数・ラインの人気順・車立て・級班別に集計。
ラインの人気順 = ライン内の選手の市場1着率(2車単オッズの逆数和)の合計で並べた順位。
使い方: python scripts/wt_line_bets.py data/   (wt_races.csv と wt_odds.jsonl.gz を読む)
"""
import sys
import pandas as pd, numpy as np, gzip, json
r=pd.read_csv(f'{sys.argv[1]}/wt_races.csv',dtype={'race_id':str,'date':str}); r['race_id']=r.race_id.str.zfill(12); r=r.drop_duplicates('race_id').set_index('race_id')
odds={}
with gzip.open(f'{sys.argv[1]}/wt_odds.jsonl.gz','rt') as f:
    for l in f:
        o=json.loads(l); odds[str(o['race_id']).zfill(12)]=o
rows=[]
for rid,t in r.iterrows():
    o=odds.get(rid)
    if not o or not o.get('final') or not isinstance(t.line_text,str): continue
    lines=[[int(x) for x in s.split('-')] for s in t.line_text.split(',') if s]
    # 市場の1着率(2車単逆数和)
    mw={}
    for c,od,*_ in o['odds'].get('2車単',[]):
        try: a=int(c.split('.')[0]); x=float(od)
        except: continue
        if x>0: mw[a]=mw.get(a,0)+1/x
    tot=sum(mw.values()) or 1
    lm=sorted([(sum(mw.get(c,0) for c in L)/tot,i) for i,L in enumerate(lines)],reverse=True)
    lrank={i:k+1 for k,(_,i) in enumerate(lm)}
    O3={c:float(od) for c,od,*_ in o['odds'].get('3連単',[]) if od}
    Q3={c:float(od) for c,od,*_ in o['odds'].get('3連複',[]) if od}
    for i,L in enumerate(lines):
        if len(L)<3: continue
        k3='.'.join(map(str,L[:3])); kq='.'.join(map(str,sorted(L[:3])))
        rows.append(dict(rid=rid,date=t.date,lt=t.line_type,grade=t.grade,cls=t['class'],n=t.entries,lrank=lrank[i],lsize=len(L),
            lshare=lm[lrank[i]-1][0], o3=O3.get(k3,np.nan), oq=Q3.get(kq,np.nan),
            p3=float(o['payoff'].get('3連単',{}).get(k3,0) or 0), pq=float(o['payoff'].get('3連複',{}).get(kq,0) or 0)))
D=pd.DataFrame(rows); D['half']=np.where(D.date<'20260101','2025','2026')
print(len(D), D.rid.nunique())
def show(by):
    g=D.groupby(by).agg(bets=('rid','size'),roi3=('p3',lambda s:s.sum()/len(s)/100),roiq=('pq',lambda s:s.sum()/len(s)/100),hitq=('pq',lambda s:(s>0).mean()))
    print(g.round(3).to_string()); print()
show(['half']); show(['lrank','half']); show(['lt','half']); show(['n','half']); show(['cls','half'])
D['oqb']=pd.cut(D.oq,[0,5,10,20,50,100,1e9]); show(['oqb','half'])
D['o3b']=pd.cut(D.o3,[0,10,30,100,300,1e9]); 
g=D.groupby(['o3b','half']).agg(bets=('rid','size'),roi3=('p3',lambda s:s.sum()/len(s)/100)); print(g.round(3).to_string())
D.drop(columns=["oqb","o3b"]).to_pickle(f'{sys.argv[1]}/line_bets.pkl')
