"""診断: wt-odds-live の nk_live_*.jsonl.gz に出てくるレースの3連単の結果を netkeirin から取って /tmp/nk_results.json に書く(オッズ急落の検証用・11/26)"""
import gzip, json, os, subprocess, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import nk_api
days = sys.argv[1].split(",")
rids = set()
for d in days:
    f = f"/tmp/nk_live_{d}.jsonl.gz"
    subprocess.run(["gh", "release", "download", "wt-odds-live", "--pattern", os.path.basename(f), "--dir", "/tmp", "--clobber"], check=False)
    if not os.path.exists(f):
        continue
    for l in gzip.open(f, "rt", encoding="utf-8"):
        rids.add(json.loads(l)["rid"])
out = {}
for rid in sorted(rids):
    try:
        p = nk_api.result(rid)
    except Exception as e:  # noqa: BLE001
        print("NG", rid, e); continue
    if p:
        out[rid] = {k: v for k, v in p.items() if k in ("3連単", "2車単")}
json.dump(out, open("/tmp/nk_results.json", "w"), ensure_ascii=False)
print(len(rids), len(out))
