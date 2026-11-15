# -*- coding: utf-8 -*-
"""
netkeirin(keirin.netkeiba.com)の API でレース一覧・オッズを取る。

11/15: winticket が GitHub Actions などクラウドからのアクセスを「アクセス制限」(403)で止めたため、
オッズの記録はこちらに切り替えた。netkeirin のオッズ画面が裏で使っている API:
  POST https://keirin.netkeiba.com/api/race/
       input=UTF-8 output=json class=<クラス> method=get compress=0 + クラスごとの引数
  AplRace      (kaisai_date=YYYYMMDD, syusai="")  その日の全場のレース一覧(締切・発走・頭数)
  AplRaceOdds  (race_id)                           全券種のオッズ。official_dt = 公式のオッズ更新時刻
  AplRaceHorse (race_id)                           出走表
  AplNarabiYoso(race_id)                           並び予想
オッズの list_N: 3=枠複 4=枠単 5=2車複 6=2車単 7=ワイド(下限,上限) 8=3連複 9=3連単。組は2桁ずつ("010203")。
"""
import datetime
import time
from zoneinfo import ZoneInfo

import requests

JST = ZoneInfo("Asia/Tokyo")
API = "https://keirin.netkeiba.com/api/race/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
BET_LISTS = {"3": "枠複", "4": "枠単", "5": "2車複", "6": "2車単", "7": "ワイド", "8": "3連複", "9": "3連単"}
_S = requests.Session()
_S.headers.update({"User-Agent": UA, "Accept-Language": "ja", "Referer": "https://keirin.netkeiba.com/race/odds/"})


def call(cls, tries=3, **kw):
    data = {"input": "UTF-8", "output": "json", "class": cls, "method": "get", "compress": "0", **kw}
    last = None
    for i in range(tries):
        try:
            r = _S.post(API, data=data, timeout=15)
            r.raise_for_status()
            j = r.json()
            if j.get("status") == "OK":
                return j.get("data") or {}
            last = RuntimeError(f"{cls}: {j.get('reason')}")
        except (requests.RequestException, ValueError) as e:
            last = e
        time.sleep(2 * (i + 1))
    raise last


def _ts(date8, hhmm):
    try:
        h, m = map(int, str(hhmm).split(":")[:2])
    except ValueError:
        return None
    d = datetime.datetime.strptime(date8, "%Y%m%d").replace(tzinfo=JST)
    t = d + datetime.timedelta(hours=h, minutes=m)   # ミッドナイトの「24:30」なども足し算で翌日になる
    return int(t.timestamp())


def race_list(date8):
    """その日の全レース -> [{race_id, venue, jyo_cd, race_no, close_ts, start_ts, tosu, name, status}]"""
    data = call("AplRace", kaisai_date=date8, syusai="")
    out = []
    for venues in data.values():
        if not isinstance(venues, list):
            continue
        for v in venues:
            for r in v.get("list") or []:
                rid = str(r.get("race_id") or "")
                if len(rid) < 12:
                    continue
                out.append(dict(race_id=rid, venue=r.get("jyo") or "", jyo_cd=r.get("jyo_cd"), race_no=int(rid[-2:]),
                                close_ts=_ts(date8, r.get("close")), start_ts=_ts(date8, r.get("start")),
                                tosu=int(r.get("tosu") or 0), name=(r.get("race_name") or "").replace("　", " "),
                                status=r.get("race_status")))
    out.sort(key=lambda x: (x["close_ts"] or 0, x["venue"]))
    return out


def _combo(k):
    return "-".join(str(int(k[i:i + 2])) for i in range(0, len(k), 2))


def odds(race_id, types=("9",)):
    """オッズ -> {"official_dt": "YYYY-MM-DD HH:MM:SS" or "", "3連単": {"1-2-3": 12.3, ...}, ...}"""
    data = call("AplRaceOdds", race_id=race_id)
    d = data.get(f"nkrace_odds::{race_id}") or {}
    out = {"official_dt": d.get("official_dt") or ""}
    for t in types:
        m = {}
        for row in d.get(f"list_{t}") or []:
            try:
                v = float(row[1])
            except (TypeError, ValueError, IndexError):
                continue
            if v > 0:
                if t == "7":   # ワイドは (下限, 上限)
                    try:
                        hi = float(row[2])
                    except (TypeError, ValueError, IndexError):
                        hi = v
                    m[_combo(row[0])] = (v, hi)
                else:
                    m[_combo(row[0])] = v
        out[BET_LISTS[t]] = m
    return out


RESULT_URL = "https://keirin.netkeiba.com/race/result/?race_id={}"
BET_NAMES = ["枠複", "枠単", "2車複", "2車単", "ワイド", "3連複", "3連単"]


def result(race_id):
    """結果ページの払戻表 -> {"3連単": [("2-6-5", 28260)], "ワイド": [("2-6", 520), ...], ...}。未確定なら None"""
    import html as _h
    import re
    r = _S.get(RESULT_URL.format(race_id), timeout=15)
    h = r.content.decode("utf-8", "replace")
    i = h.find('id="result_payback_section"')
    if i < 0:
        return None
    seg = _h.unescape(re.sub(r"<[^>]+>", " | ", h[i:i + 8000]))
    seg = seg.translate(str.maketrans("０１２３４５６７８９，＞", "0123456789,>"))
    toks = [t.strip() for t in seg.split("|") if t.strip()]
    out, cur = {}, None
    k = 0
    while k < len(toks):
        t = toks[k]
        if t in BET_NAMES:
            cur = t
            out.setdefault(cur, [])
        elif cur and re.fullmatch(r"\d+(?:\s*[->]\s*\d+){1,2}", t) and k + 1 < len(toks):
            m = re.fullmatch(r"([\d,]+)\s*円", toks[k + 1])
            if m:
                combo = "-".join(re.findall(r"\d+", t))
                out[cur].append((combo, int(m.group(1).replace(",", ""))))
                k += 1
        elif t.startswith("$(") or t.startswith("function"):
            break
        k += 1
    return out if out.get("3連単") else None
