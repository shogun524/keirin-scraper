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
from bs4 import BeautifulSoup, NavigableString

BASE = "https://keirin.kdreams.jp"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}
REQUEST_INTERVAL_SEC = 1.5  # サイトへの負荷を抑えるための最低待機時間


def _get(url, bust_cache=False, **kwargs):
    headers = dict(HEADERS)
    if bust_cache:
        # 中間キャッシュ（CDN等）が古いページを返している疑いがある場合に使う。
        # クエリパラメータで実質的に別URL扱いにしつつ、明示的にキャッシュ無効化も指定する。
        headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        headers["Pragma"] = "no-cache"
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}_ts={int(time.time())}"
    resp = requests.get(url, headers=headers, timeout=20, **kwargs)
    resp.raise_for_status()
    # 文字コードは明示的にUTF-8固定にする。
    # resp.apparent_encoding（chardet等によるヒューリスティック自動判定）は、
    # 日本語UTF-8ページを誤ってキリル文字系エンコーディング等と誤判定し、
    # ページ全体が文字化けすることがあった（このサイトはUTF-8で配信されるため、
    # 自動判定に頼らずUTF-8で固定する方が確実）。
    resp.encoding = "utf-8"
    time.sleep(REQUEST_INTERVAL_SEC)
    return resp.text


def _page_shows_date(html, date):
    """
    ページ内に「本日 YYYY年M月D日」という表記があれば、それが期待する日付と
    一致するかを確認する。表記が見つからない場合は None（判定不能）を返す。
    """
    m = re.search(r"本日[^\d]{0,80}(\d{4})年(\d{1,2})月(\d{1,2})日", html)
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return (y, mo, d) == (date.year, date.month, date.day)


def _extract_todays_links_from_kaisai_html(html):
    """
    ページのHTMLから、競輪場ごとに「本日」の racecard リンクを抽出する。

    以前は「本日」という文字列に近いリンクを探す方式だったが、正確なDOM構造への
    依存が強く、G1等の複数日開催で誤ったリンクを拾ってしまうことがあった。
    実際にトップページ（https://keirin.kdreams.jp/）を直接確認したところ、
    「本日の開催」欄では、競輪場ごとに「今日の日程」のracecardリンクのみが
    存在し、過去の日程には「結果」リンクしか無いことが分かった
    （つまり racecard リンクは1競輪場につき1つしか出ない）。
    そのため、競輪場の見出しリンク（"?l-id=..." のクエリパラメータが付くことが
    ある）を区切りとしてブロックに分割し、各ブロック内の racecard リンクを
    そのまま採用する（「本日」の文字列検索には依存しない）。
    """
    venues = {}
    heading_pattern = re.compile(r'href="https://keirin\.kdreams\.jp/([a-z]+)/(?:\?[^"]*)?"')
    headings = [(m.start(), m.group(1)) for m in heading_pattern.finditer(html)]

    racecard_pattern = re.compile(r'href="[^"]*/([a-z]+)/racecard/(\d{14})/[^"]*"')

    for idx, (pos, slug) in enumerate(headings):
        if slug in venues:
            continue
        block_start = pos
        block_end = headings[idx + 1][0] if idx + 1 < len(headings) else len(html)
        block = html[block_start:block_end]

        for m in racecard_pattern.finditer(block):
            if m.group(1) == slug:
                venues[slug] = m.group(2)
                break

    return venues


def find_todays_venues(date=None):
    """
    当日開催されている競輪場スラッグと kaisaiDateId の組を抽出する。

    重要な注意点：kaisaiDateId に埋め込まれている日付は「開催が始まった日
    （初日の日付）」であり、複数日開催（2日目・最終日など）では「今日の日付」
    と一致しない。そのため日付の突き合わせでは判定しない。

    情報源は /kaisai/YYYY/MM/DD/ を主とする。このURL自体に日付が明示されている
    ため、CDN等にキャッシュされていても「違う日の内容」を掴む心配が無い
    （トップページの「本日の開催」は、URLが日付非依存のため、キャッシュされると
    古い日の内容のまま返ってくることがあり、実際に運用中に発生した）。
    トップページは補完用としてのみ使う。

    戻り値: [{"venue": "gifu", "kaisai_date_id": "43202608120100"}, ...]
    """
    date = date or datetime.date.today()
    venues = {}  # slug -> kaisai_date_id

    try:
        kaisai_url = f"{BASE}/kaisai/{date.strftime('%Y/%m/%d')}/"
        html = _get(kaisai_url)
        venues = _extract_todays_links_from_kaisai_html(html)
        print(f"[INFO] 開催一覧ページ（{date}）から {len(venues)} 開催を検出しました。")
    except requests.RequestException as e:
        print(f"[WARN] 開催一覧ページの取得に失敗しました: {e}")

    # 補完用：トップページの「本日の開催」欄にしか出ていない競輪場があれば追加で拾う。
    # トップページはURLが日付非依存でキャッシュに弱いため、表示日付を検証し、
    # ズレていればキャッシュ回避して再取得する。
    try:
        html2 = _get(BASE + "/")
        date_ok = _page_shows_date(html2, date)
        if date_ok is False:
            print(f"[WARN] トップページに表示されている日付が本日({date})と一致しません。キャッシュ回避して再取得します。")
            html2 = _get(BASE + "/", bust_cache=True)
            date_ok = _page_shows_date(html2, date)
            if date_ok is False:
                print("[WARN] 再取得後も日付が一致しませんでした。トップページの補完はスキップします。")
                html2 = None

        if html2 is not None:
            today_pos = html2.find("本日の開催")
            tomorrow_pos = html2.find("明日の開催")
            extra = {}
            if today_pos != -1:
                end = tomorrow_pos if tomorrow_pos != -1 and tomorrow_pos > today_pos else len(html2)
                extra = _extract_todays_links_from_kaisai_html(html2[today_pos:end])
            added = 0
            for slug, kdid in extra.items():
                if slug not in venues:
                    venues[slug] = kdid
                    added += 1
            if added:
                print(f"[INFO] トップページから追加で {added} 開催を検出しました。")
    except requests.RequestException as e:
        print(f"[WARN] トップページの取得に失敗しました: {e}")

    result = [{"venue": slug, "kaisai_date_id": kdid} for slug, kdid in venues.items() if slug]
    print(f"[INFO] 本日開催中と判定した競輪場: {[r['venue'] for r in result]}")
    return result


def find_race_urls_for_venue(venue, kaisai_date_id):
    """
    venue の racecard 一覧ページから、その日の各レースの racedetail URL を取得する。
    戻り値: [{"race_no": 1, "url": "https://.../gifu/racedetail/.../"}, ...]

    注意：racecard ページには「他の日程のレースへのショートカットリンク」等、
    今回リクエストした日程（kaisai_date_id）以外のレースへのリンクが紛れ込んでいる
    ことがある。race_no（末尾2桁）だけで辞書に格納すると、後から現れた別日程の
    リンクに上書きされて、日程がズレたレースを取得してしまう危険があるため、
    race_id の先頭14桁が今回リクエストした kaisai_date_id と一致するものだけを採用する。
    """
    url = f"{BASE}/{venue}/racecard/{kaisai_date_id}/"
    html = _get(url)
    soup = BeautifulSoup(html, "html.parser")

    races = {}
    skipped_other_day = 0
    for a in soup.find_all("a", href=True):
        m = re.search(rf"/{venue}/racedetail/(\d{{14,18}})/?(?:\?|$)", a["href"])
        if not m:
            continue
        race_id = m.group(1)
        if len(race_id) < 16 or race_id[:14] != kaisai_date_id:
            skipped_other_day += 1
            continue
        race_no = int(race_id[-2:])
        if 1 <= race_no <= 12:
            races[race_no] = f"{BASE}/{venue}/racedetail/{race_id}/"

    if skipped_other_day:
        print(f"[INFO] {venue}: 別日程宛と判定して読み飛ばしたリンクが {skipped_other_day} 件ありました。")
    print(f"[INFO] {venue}: racecard一覧から {len(races)} レース分のURLを検出しました。")
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
    # ライン予想（並び予想／ライン予想／隊列予想など）以降（コメント・オッズ等）は解析対象から除外
    body = full_text
    for lbl in ("並び予想", "ライン予想", "予想ライン", "隊列予想"):
        body = body.split(lbl)[0]
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

    deadline_match = re.search(r"締切(?:時間)?\s*(\d{1,2}:\d{2})", full_text)
    deadline = deadline_match.group(1) if deadline_match else None

    # 並び予想の役割語（サイトの表記ゆれに対応：追い上げ／追上 など）
    ROLE_WORDS = "先行|追込|押え先|自在|追い上げ|追上|捲|差|逃"
    line_role_re = re.compile(rf"\d+\s*(?:{ROLE_WORDS})")
    seq_re = re.compile(rf"((?:\d+\s*(?:{ROLE_WORDS})\s*){{3,}})")

    line_pred_text = ""
    line_labels = ("並び予想", "ライン予想", "予想ライン", "隊列予想")
    label_pos = None
    for lbl in line_labels:
        p = full_text.find(lbl)
        if p != -1 and (label_pos is None or p < label_pos):
            label_pos = p

    if label_pos is not None:
        # ラベル発見位置以降のテキストから、決まり手の並び（数字+役割語が3つ以上連続する箇所）を探す。
        # サイトによっては「4」「自在」のように数字と役割語が別々の行になっているが、
        # full_text は行を半角スペースで連結したものなので、"4 自在" のように1個のスペースを挟んだ
        # 形で連続しており、\s* を挟む正規表現でそのまま拾える。
        after_label = full_text[label_pos:]
        m = seq_re.search(after_label)
        if m:
            line_pred_text = m.group(1).strip()

    if not line_pred_text:
        # ラベル自体が見つからなかった場合の最終手段：
        # ページ全体から「数字+役割語」が3つ以上連続する箇所を並び予想とみなす
        m = seq_re.search(full_text)
        if m:
            line_pred_text = m.group(1).strip()

    racers = parse_racer_tokens(full_text)

    if not racers:
        # 選手データが1件も取れなかった場合の診断ログ：
        # print() 表示自体の文字コードで文字化けして見える可能性があるため、
        # unicode_escape で機種依存しない形式でも併記する
        snippet = re.sub(r"\s+", " ", full_text[:600])
        snippet_escaped = snippet.encode("unicode_escape").decode("ascii")
        print(f"[DEBUG] {venue} {race_no}R: 選手データの解析に失敗しました。テキスト冒頭600文字: {snippet}")
        print(f"[DEBUG] {venue} {race_no}R: 同内容をunicode_escapeで表示: {snippet_escaped[:600]}")

    # 重複除去（車番ベース、最初の一致を優先）
    seen = set()
    unique_racers = []
    for r in racers:
        if r["car"] in seen:
            continue
        seen.add(r["car"])
        unique_racers.append(r)
    unique_racers.sort(key=lambda r: r["car"])

    race_info = {"venue": venue, "race_no": race_no, "title": race_title, "deadline": deadline}
    return race_info, unique_racers, line_pred_text


def fetch_race(venue, race_no, url):
    html = _get(url)

    # 文字コード診断：既知の日本語文字列（"選手名"）が正しく含まれているかを確認する。
    # 含まれていなければ、_get() のUTF-8固定が効いていないか、そもそもサイト側の
    # 応答内容自体が想定と異なっている可能性が高い。
    if "選手名" not in html and "レース" not in html:
        sample = html[:120].encode("unicode_escape").decode("ascii")
        print(f"[DEBUG] {venue} {race_no}R: 既知の日本語文字列を検出できませんでした。"
              f"文字コード診断が必要かもしれません。冒頭120文字(unicode_escape): {sample}")

    race_info, racers, line_pred_text = parse_race_detail(html, venue, race_no)

    if not line_pred_text:
        # 診断用ログ：なぜ拾えなかったのか手がかりを残す
        in_raw_html = "並び予想" in html
        print(f"[DEBUG] {venue} {race_no}R: 並び予想を検出できませんでした。"
              f"（生HTML内に文字列「並び予想」を含むか: {in_raw_html}）")
        if in_raw_html:
            pos = html.find("並び予想")
            snippet = re.sub(r"\s+", " ", html[pos:pos + 300])
            print(f"[DEBUG] 該当箇所の生HTML抜粋: {snippet}")
        else:
            # 「並び」だけでも探してみる（表記ゆれの可能性）
            if "並び" in html:
                pos = html.find("並び")
                snippet = re.sub(r"\s+", " ", html[pos:pos + 200])
                print(f"[DEBUG] 「並び」を含む箇所の生HTML抜粋: {snippet}")
            else:
                print("[DEBUG] 生HTML内に「並び」という文字列自体が見つかりませんでした。")

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
        venue_success = 0
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
            venue_success += 1
        print(f"[INFO] {v['venue']}: {venue_success}/{len(race_urls)} レースの取得に成功しました。")
    print(f"[INFO] 合計 {len(all_races)} レース分のデータを取得しました（開催 {len(venues)} 場）。")
    return all_races
