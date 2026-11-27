"""診断: Kドリームスのレースページで選手コメントがどこにあるか調べる"""
import sys, os, json, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import scraper
url = sys.argv[1]
r = scraper._get(url)
html = r.text if hasattr(r, "text") else r
open("/tmp/kd_page.html", "w", encoding="utf-8").write(html)
txt = scraper._clean_text(html)
out = {"len": len(html), "comment_hits": [m.start() for m in re.finditer("コメント", html)][:20],
       "text_around": [txt[max(0, m.start() - 300): m.start() + 900] for m in re.finditer("コメント|談話|短評", txt)][:6]}
json.dump(out, open("/tmp/kd_probe.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False)[:3000])
