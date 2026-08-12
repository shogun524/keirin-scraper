# -*- coding: utf-8 -*-
"""
keirin.kdreams.jp から当日の出走表データを取得するスクレイパー。
- 当日開催されている競輪場・レース一覧を取得
- 各レースの racedetail ページから、選手データ（総評・級班・脚質・ギヤ倍数・
  競走得点・決まり手回数・着度数）と「並び予想」テキストを抽出する

サイトの構造変更に弱い部分があるため、複数のフォールバック手段を用意している。
一定期間ごとに実際の出力を目視確認することをおすすめします。
"""

import re
import time
import datetime
import requests
from bs4 import BeautifulSoup

BASE = "https://keirin.kdreams.jp"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}
REQUEST_INTERVAL_SEC = 1.5  # サイトへの負荷を抑えるための最低待機時間


def _get(url, **kwargs):
    resp = requests.get(url, headers=HEADERS, timeout=20, **kwargs)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    time.sleep(REQUEST_INTERVAL_SEC)
    return resp.text


def find_todays_venues(date=None):
    """
    トップページの「本日の開催」欄から、当日開催中の競輪場スラッグと
    kaisaiDateId の組を抽出する。
    戻り値: [{"venue": "gifu", "kaisai_date_id": "43202608120100", "name": "岐阜"}, ...]
    """
    date = date or datetime.date.today()
    html = _get(BASE + "/")
    soup = BeautifulSoup(html, "html.parser")

    venues = {}
    # 競輪場リンク（例: https://keirin.kdreams.jp/gifu/）から venue slug を取得
    venue_slugs = {}
    for a in soup.find_all("a", href=True):
        m = re.match(r"^https://keirin\.kdreams\.jp/([a-z]+)/$", a["href"])
        if m:
            venue_slugs[m.group(1)] = a.get_text(strip=True)

    # kaisaiDateId を含むリンク（投票・出走表など）から当日の開催情報を推定
    for a in soup.find_all("a", href=True):
        m = re.search(r"kaisaiDateId=(\d{14})", a["href"])
        if not m:
            m = re.search(r"/racecard/(\d{14})/", a["href"])
        if not m:
            continue
        kaisai_date_id = m.group(1)
        # kaisaiDateId の中に YYYYMMDD が埋め込まれている（例: 43 202608 12 0100）
        date_part = kaisai_date_id[2:10]
        if date_part != date.strftime("%Y%m%d"):
            continue
        venue_code = kaisai_date_id[:2]
        # venue slug は URL 内の別リンクから拾う必要があるため、後段で racecard 一覧ページを見て確定させる
        venues.setdefault(kaisai_date_id, venue_code)

    # 開催一覧ページ（/kaisai/YYYY/MM/DD/）からも同様に補完する
    kaisai_url = f"{BASE}/kaisai/{date.strftime('%Y/%m/%d')}/"
    try:
        html2 = _get(kaisai_url)
        soup2 = BeautifulSoup(html2, "html.parser")
        for a in soup2.find_all("a", href=True):
            m = re.search(r"/([a-z]+)/racecard/(\d{14})/", a["href"])
            if m:
                slug, kdid = m.group(1), m.group(2)
                date_part = kdid[2:10]
                if date_part == date.strftime("%Y%m%d"):
                    venues[kdid] = slug
    except requests.RequestException:
        pass

    result = []
    for kdid, slug in venues.items():
        result.append({"venue": slug, "kaisai_date_id": kdid})
    return result


def find_race_urls_for_venue(venue, kaisai_date_id):
    """
    venue の racecard 一覧ページから、その日の各レースの racedetail URL を取得する。
    戻り値: [{"race_no": 1, "url": "https://.../gifu/racedetail/.../"}, ...]
    """
    url = f"{BASE}/{venue}/racecard/{kaisai_date_id}/"
    html = _get(url)
    soup = BeautifulSoup(html, "html.parser")

    races = {}
    for a in soup.find_all("a", href=True):
        m = re.search(rf"/{venue}/racedetail/(\d{{16}})/?$", a["href"])
        if not m:
            # クエリパラメータ付きのURLも許容
            m = re.search(rf"/{venue}/racedetail/(\d{{16}})/?\?", a["href"])
        if m:
            race_id = m.group(1)
            race_no = int(race_id[-2:])
            races[race_no] = f"{BASE}/{venue}/racedetail/{race_id}/"

    return [{"race_no": no, "url": races[no]} for no in sorted(races)]


# ============================================================
# レース詳細ページの解析
# ============================================================
_RANK_RE = r"(?:SS|S1|S2|A1|A2|A3|L1)"
_TACTIC_RE = r"[逃追両]"
_MARK_RE = r"[×▲△○◎注★]"


def _clean_text(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text("\n")
    # 連続する空白/改行を単一スペースへ正規化しつつ、行区切りは保持
    lines = [re.sub(r"[ \t\u3000]+", " ", ln).strip() for ln in text.split("\n")]
    return [ln for ln in lines if ln]


# ============================================================
# 選手データのトークン走査パーサー（keirin_predictor_v2.html の貼り付け解析ロジックと
# 同じ考え方を採用。1つの巨大な正規表現より、種類ごとのトークン判定の方が
# 表記ゆれ（府県名が空白で分割される、級班の位置がずれる等）に強い）
# ============================================================
def _is_mark(t):
    return bool(re.match(rf"^{_MARK_RE}$", t))


def _is_rank(t):
    return bool(re.match(rf"^{_RANK_RE}$", t, re.IGNORECASE))


def _is_tactic(t):
    return bool(re.match(rf"^{_TACTIC_RE}$", t))


def _is_kanji(t):
    return bool(re.match(r"^[一-龥々〆ヵヶぁ-んァ-ヶー・]+$", t))


def _is_num(t):
    return bool(re.match(r"^-?\d+(\.\d+)?$", t))


def _is_int(t):
    return bool(re.match(r"^\d+$", t))


def _is_score_decimal(t):
    return bool(re.match(r"^\d{1,3}\.\d{2}$", t))


def _is_rate_decimal(t):
    return bool(re.match(r"^\d{1,3}\.\d{1}$", t))


def _is_gear(t):
    return bool(re.match(r"^[3-4]\.\d{2}$", t))


def _extract_age_period_rank(t):
    m = re.search(rf"(\d{{1,2}})\s*/\s*(\d{{2,3}})(?:\s*/\s*({_RANK_RE}))?", t, re.IGNORECASE)
    if not m:
        return None
    return {
        "age": float(m.group(1)), "period": float(m.group(2)),
        "rank": m.group(3).upper() if m.group(3) else None,
    }


def parse_racer_tokens(full_text):
    """並び予想より前の本体テーブル部分から、トークン走査で選手データを抽出する"""
    # 「並び予想」以降（コメント・オッズ等）は解析対象から除外
    body = full_text.split("並び予想")[0]
    tokens = body.split()
    racers = []
    pos = 0
    n = len(tokens)

    while pos < n:
        start_pos = pos
        try:
            mark = ""
            if _is_mark(tokens[pos]):
                mark = tokens[pos]
                pos += 1

            if not _is_num(tokens[pos]):
                pos += 1
                continue
            souhyou = float(tokens[pos]); pos += 1
            if not _is_num(tokens[pos]):
                raise ValueError("枠番/車番が見つかりません")
            n1 = float(tokens[pos]); pos += 1
            if pos < n and _is_num(tokens[pos]):
                n2 = float(tokens[pos]); pos += 1
                waku, car = n1, n2
            else:
                waku, car = n1, n1

            name_parts = []
            ap = None
            safety = 0
            while pos < n and safety < 6:
                safety += 1
                t = tokens[pos]
                apm = _extract_age_period_rank(t)
                if apm:
                    ap = apm
                    pos += 1
                    break
                if _is_kanji(t) and not _is_rank(t) and not _is_tactic(t):
                    next_tok = tokens[pos + 1] if pos + 1 < n else None
                    next_ap = _extract_age_period_rank(next_tok) if next_tok else None
                    if len(t) == 1 and next_ap:
                        pos += 1  # 府県名の1文字断片
                    else:
                        name_parts.append(t)
                        pos += 1
                else:
                    break
            name = " ".join(name_parts)
            if not ap:
                raise ValueError("年齢/期別が見つかりません")

            rank = ap["rank"]
            if not rank and pos < n and _is_rank(tokens[pos]):
                rank = tokens[pos].upper()
                pos += 1
            rank = rank or "A3"

            if pos >= n or not _is_tactic(tokens[pos]):
                raise ValueError("脚質が見つかりません")
            tactic = tokens[pos]; pos += 1

            if pos >= n or not (_is_gear(tokens[pos]) or _is_num(tokens[pos])):
                raise ValueError("ギヤ倍数が見つかりません")
            gear = float(tokens[pos]); pos += 1

            if pos >= n or not _is_num(tokens[pos]):
                raise ValueError("競走得点が見つかりません")
            score = float(tokens[pos]); pos += 1

            nums = []
            while pos < n and _is_num(tokens[pos]) and len(nums) < 13:
                nums.append(float(tokens[pos])); pos += 1
            # S,B,逃,捲,差,マ,1着,2着,3着,着外,勝率,2連対率,3連対率
            nige = int(nums[2]) if len(nums) > 2 else 0
            makuri = int(nums[3]) if len(nums) > 3 else 0
            sashi = int(nums[4]) if len(nums) > 4 else 0
            mark_k = int(nums[5]) if len(nums) > 5 else 0
            f1 = int(nums[6]) if len(nums) > 6 else 0
            f2 = int(nums[7]) if len(nums) > 7 else 0
            f3 = int(nums[8]) if len(nums) > 8 else 0
            fo = int(nums[9]) if len(nums) > 9 else 0

            if not (1 <= car <= 9):
                continue

            racers.append({
                "car": int(car), "name": name, "mark": mark, "rank": rank, "tactic": tactic,
                "souhyou": souhyou, "waku": waku, "gear": gear, "score": score,
                "age": ap["age"], "period": ap["period"],
                "kimarite": {"逃": nige, "捲": makuri, "差": sashi, "マ": mark_k},
                "finishes": {"f1": f1, "f2": f2, "f3": f3, "fo": fo},
            })
        except (ValueError, IndexError):
            pos = start_pos + 1

    return racers


def parse_race_detail(html, venue, race_no):
    """
    racedetail ページのHTMLから、選手データと並び予想テキストを抽出する。
    戻り値: (race_info dict, racers list, line_prediction_text str)
    """
    lines = _clean_text(html)
    full_text = " ".join(lines)

    race_title_match = re.search(r"([ＡＢＦS][A-Za-z0-9級予選特選準決勝一般ＧＩＩＩＩＩ　 ]{1,20})", full_text)
    race_title = race_title_match.group(1).strip() if race_title_match else ""

    line_pred_text = ""
    for i, ln in enumerate(lines):
        if "並び予想" in ln:
            candidate = ln.replace("並び予想", "").strip()
            if not candidate and i + 1 < len(lines):
                candidate = lines[i + 1]
            line_pred_text = candidate
            break

    racers = parse_racer_tokens(full_text)

    # 重複除去（車番ベース、最初の一致を優先）
    seen = set()
    unique_racers = []
    for r in racers:
        if r["car"] in seen:
            continue
        seen.add(r["car"])
        unique_racers.append(r)
    unique_racers.sort(key=lambda r: r["car"])

    race_info = {"venue": venue, "race_no": race_no, "title": race_title}
    return race_info, unique_racers, line_pred_text


def fetch_race(venue, race_no, url):
    html = _get(url)
    race_info, racers, line_pred_text = parse_race_detail(html, venue, race_no)
    return race_info, racers, line_pred_text


def fetch_all_todays_races(date=None):
    """
    当日開催されている全レースのデータを取得する。
    戻り値: [{"race_info":..., "racers":[...], "line_prediction_text": "..."}, ...]
    """
    date = date or datetime.date.today()
    venues = find_todays_venues(date)
    all_races = []
    for v in venues:
        try:
            race_urls = find_race_urls_for_venue(v["venue"], v["kaisai_date_id"])
        except requests.RequestException as e:
            print(f"[WARN] {v['venue']} のレース一覧取得に失敗: {e}")
            continue
        for r in race_urls:
            try:
                race_info, racers, line_pred_text = fetch_race(v["venue"], r["race_no"], r["url"])
            except requests.RequestException as e:
                print(f"[WARN] {v['venue']} {r['race_no']}R の取得に失敗: {e}")
                continue
            if len(racers) < 5:
                print(f"[WARN] {v['venue']} {r['race_no']}R: 選手データを{len(racers)}件しか取得できませんでした（スキップ）")
                continue
            all_races.append({
                "race_info": race_info,
                "racers": racers,
                "line_prediction_text": line_pred_text,
                "url": r["url"],
            })
    return all_races
