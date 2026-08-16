# -*- coding: utf-8 -*-
"""
全国43競輪場のバンク（走路）データ。
出典: keirin-brother.com「競輪場のバンクの特徴」（調査日: 2026年2月25日、元データは KEIRIN.JP）
     決まり手出現率は 競輪CLUB データ分析（集計期間 2021/1/1〜2025/12/31, A級7車）
このデータは施設の物理的特性なので、頻繁には変わらない。日々のスクレイピングとは
独立した静的データとして持っておく。

各フィールド:
  circumference: 周長（バンク一周の長さ）
  literal_straight: みなし直線（ゴール前の直線の長さ、m）
  center_cant: センター部路面傾斜（カント。コーナーの傾き）
  straight_cant: 直線部路面傾斜
  home_width / back_width / center_width: コース幅員
  record_time / record_holder / record_date: バンクレコード（上がりタイム最高記録）
  nige_1st / sashi_1st / makuri_1st: 1着の決まり手出現率（A級7車、%）
"""

VENUE_BANK_DATA = {
    "hakodate": {"circumference": "400m", "literal_straight": 51.3, "center_cant": "30°36′51″", "straight_cant": "3°26′1″",
                 "home_width": 10.8, "back_width": 9.8, "center_width": 7.8,
                 "record_time": "10.6秒", "record_holder": "脇本雄太", "record_date": "2023/07/16",
                 "nige_1st": 30.0, "sashi_1st": 44.9, "makuri_1st": 24.9,
                 "nige_2nd": 20.4, "sashi_2nd": 25.2, "makuri_2nd": 12.0, "mark_2nd": 42.5},
    "aomori": {"circumference": "400m", "literal_straight": 58.9, "center_cant": "32°15′07″", "straight_cant": "2°51′45″",
               "home_width": 10.8, "back_width": 9.8, "center_width": 7.8,
               "record_time": "10.5秒", "record_holder": "ベイリー", "record_date": "2004/04/18",
               "nige_1st": 24.8, "sashi_1st": 49.2, "makuri_1st": 25.7,
               "nige_2nd": 20.3, "sashi_2nd": 25.4, "makuri_2nd": 12.1, "mark_2nd": 42.0},
    "iwakitaira": {"circumference": "400m", "literal_straight": 62.7, "center_cant": "32°54′45″", "straight_cant": "3°26′1″",
                   "home_width": 10.0, "back_width": 10.0, "center_width": 7.3,
                   "record_time": "10.5秒", "record_holder": "山崎芳仁", "record_date": "2010/09/04",
                   "nige_1st": 25.5, "sashi_1st": 50.1, "makuri_1st": 24.6,
                   "nige_2nd": 20.7, "sashi_2nd": 26.7, "makuri_2nd": 11.7, "mark_2nd": 40.7},
    "yahiko": {"circumference": "400m", "literal_straight": 63.1, "center_cant": "32°24′17″", "straight_cant": "2°51′45″",
               "home_width": 10.1, "back_width": 9.0, "center_width": 7.3,
               "record_time": "10.6秒", "record_holder": "山崎芳仁", "record_date": "2010/06/15",
               "nige_1st": 24.8, "sashi_1st": 50.4, "makuri_1st": 24.7,
               "nige_2nd": 21.5, "sashi_2nd": 28.0, "makuri_2nd": 11.2, "mark_2nd": 39.3},
    "maebashi": {"circumference": "333m", "literal_straight": 46.7, "center_cant": "36°0′0″", "straight_cant": "4°0′0″",
                 "home_width": 9.9, "back_width": 9.9, "center_width": 9.9,
                 "record_time": "8.8秒", "record_holder": "中川誠一郎", "record_date": "2014/09/13",
                 "nige_1st": 37.6, "sashi_1st": 34.7, "makuri_1st": 27.5,
                 "nige_2nd": 24.3, "sashi_2nd": 17.9, "makuri_2nd": 9.2, "mark_2nd": 48.4},
    "toride": {"circumference": "400m", "literal_straight": 54.8, "center_cant": "31°30′25″", "straight_cant": "2°51′44″",
               "home_width": 10.0, "back_width": 10.0, "center_width": 7.5,
               "record_time": "10.7秒", "record_holder": "吉岡稔真", "record_date": "1998/06/20",
               "nige_1st": 28.9, "sashi_1st": 45.2, "makuri_1st": 26.1,
               "nige_2nd": 20.4, "sashi_2nd": 26.4, "makuri_2nd": 13.1, "mark_2nd": 40.2},
    "utsunomiya": {"circumference": "500m", "literal_straight": 63.3, "center_cant": "25°47′44″", "straight_cant": "2°51′44″",
                   "home_width": 10.3, "back_width": 11.3, "center_width": 8.3,
                   "record_time": "13.1秒", "record_holder": "中川誠一郎", "record_date": "2018/06/28",
                   "nige_1st": 28.1, "sashi_1st": 47.8, "makuri_1st": 24.3,
                   "nige_2nd": 17.6, "sashi_2nd": 27.8, "makuri_2nd": 11.2, "mark_2nd": 43.2},
    "omiya": {"circumference": "500m", "literal_straight": 66.7, "center_cant": "26°16′40″", "straight_cant": "3°26′1″",
              "home_width": 10.3, "back_width": 9.3, "center_width": 7.5,
              "record_time": "12.8秒", "record_holder": "ブフリ", "record_date": "2017/07/19",
              "nige_1st": 25.6, "sashi_1st": 51.3, "makuri_1st": 23.0,
              "nige_2nd": 17.2, "sashi_2nd": 33.8, "makuri_2nd": 9.5, "mark_2nd": 39.2},
    "seibuen": {"circumference": "400m", "literal_straight": 47.6, "center_cant": "29°26′54″", "straight_cant": "2°51′45″",
                "home_width": 11.0, "back_width": 10.0, "center_width": 7.5,
                "record_time": "10.6秒", "record_holder": "會田正一", "record_date": "1996/04/29",
                "nige_1st": 33.4, "sashi_1st": 42.7, "makuri_1st": 23.9,
                "nige_2nd": 21.6, "sashi_2nd": 24.9, "makuri_2nd": 9.6, "mark_2nd": 43.1},
    "keiokaku": {"circumference": "400m", "literal_straight": 51.5, "center_cant": "32°10′34″", "straight_cant": "2°51′44″",
                 "home_width": 10.3, "back_width": 9.0, "center_width": 7.5,
                 "record_time": "10.4秒", "record_holder": "パーキンス", "record_date": "2015/08/14",
                 "nige_1st": 28.0, "sashi_1st": 46.2, "makuri_1st": 25.8,
                 "nige_2nd": 20.7, "sashi_2nd": 28.0, "makuri_2nd": 10.7, "mark_2nd": 40.6},
    "tachikawa": {"circumference": "400m", "literal_straight": 58.0, "center_cant": "31°13′6″", "straight_cant": "2°17′27″",
                  "home_width": 9.7, "back_width": 8.7, "center_width": 7.7,
                  "record_time": "10.6秒", "record_holder": "深谷知広", "record_date": "2013/03/23",
                  "nige_1st": 26.9, "sashi_1st": 48.1, "makuri_1st": 25.2,
                  "nige_2nd": 19.8, "sashi_2nd": 29.4, "makuri_2nd": 12.5, "mark_2nd": 38.2},
    "matsudo": {"circumference": "333m", "literal_straight": 38.2, "center_cant": "29°44′42″", "straight_cant": "3°1′2″",
                "home_width": 11.1, "back_width": 9.6, "center_width": 8.1,
                "record_time": "9.0秒", "record_holder": "中村浩士", "record_date": "2008/08/13",
                "nige_1st": 35.9, "sashi_1st": 32.9, "makuri_1st": 31.3,
                "nige_2nd": 23.0, "sashi_2nd": 19.5, "makuri_2nd": 11.4, "mark_2nd": 46.3},
    "chiba": {"circumference": None, "literal_straight": None, "center_cant": None, "straight_cant": None,
              "home_width": None, "back_width": None, "center_width": None,
              "record_time": None, "record_holder": None, "record_date": None,
              "nige_1st": None, "sashi_1st": None, "makuri_1st": None,
              "nige_2nd": None, "sashi_2nd": None, "makuri_2nd": None, "mark_2nd": None,
              "note": "250競走のみ開催のためバンクデータなし"},
    "kawasaki": {"circumference": "400m", "literal_straight": 58.0, "center_cant": "32°10′14″", "straight_cant": "3°26′1″",
                 "home_width": 10.3, "back_width": 9.3, "center_width": 8.3,
                 "record_time": "10.5秒", "record_holder": "脇本雄太", "record_date": "2025/04/20",
                 "nige_1st": 28.9, "sashi_1st": 44.6, "makuri_1st": 25.9,
                 "nige_2nd": 18.9, "sashi_2nd": 27.1, "makuri_2nd": 12.8, "mark_2nd": 40.4},
    "hiratsuka": {"circumference": "400m", "literal_straight": 54.2, "center_cant": "31°28′37″", "straight_cant": "3°26′1″",
                  "home_width": 11.0, "back_width": 9.3, "center_width": 7.5,
                  "record_time": "10.4秒", "record_holder": "荒井崇博", "record_date": "2018/05/01",
                  "nige_1st": 27.1, "sashi_1st": 45.6, "makuri_1st": 27.3,
                  "nige_2nd": 19.6, "sashi_2nd": 25.7, "makuri_2nd": 12.5, "mark_2nd": 42.0},
    "odawara": {"circumference": "333m", "literal_straight": 36.1, "center_cant": "35°34′12″", "straight_cant": "3°26′1″",
                "home_width": 11.3, "back_width": 9.0, "center_width": 7.5,
                "record_time": "8.7秒", "record_holder": "ボティシャー", "record_date": "2014/07/15",
                "nige_1st": 29.1, "sashi_1st": 42.8, "makuri_1st": 28.1,
                "nige_2nd": 24.0, "sashi_2nd": 20.8, "makuri_2nd": 12.4, "mark_2nd": 42.9},
    "ito": {"circumference": "333m", "literal_straight": 46.6, "center_cant": "34°41′9″", "straight_cant": "3°26′1″",
            "home_width": 11.0, "back_width": 9.3, "center_width": 7.8,
            "record_time": "8.9秒", "record_holder": "山田庸平", "record_date": "2025/03/23",
            "nige_1st": 31.2, "sashi_1st": 39.3, "makuri_1st": 29.5,
            "nige_2nd": 21.5, "sashi_2nd": 22.5, "makuri_2nd": 12.3, "mark_2nd": 43.9},
    "shizuoka": {"circumference": "400m", "literal_straight": 56.4, "center_cant": "30°43′22″", "straight_cant": "2°51′45″",
                 "home_width": 10.3, "back_width": 9.3, "center_width": 7.5,
                 "record_time": "10.8秒", "record_holder": "佐藤仁", "record_date": "1989/06/25",
                 "nige_1st": 26.6, "sashi_1st": 44.7, "makuri_1st": 28.3,
                 "nige_2nd": 21.8, "sashi_2nd": 26.5, "makuri_2nd": 12.0, "mark_2nd": 39.2},
    "nagoya": {"circumference": "400m", "literal_straight": 58.8, "center_cant": "34°1′47″", "straight_cant": "2°51′45″",
               "home_width": 10.3, "back_width": 9.3, "center_width": 7.3,
               "record_time": "10.4秒", "record_holder": "パーキンス", "record_date": "2013/09/08",
               "nige_1st": 26.8, "sashi_1st": 44.9, "makuri_1st": 28.6,
               "nige_2nd": 22.4, "sashi_2nd": 23.6, "makuri_2nd": 11.6, "mark_2nd": 42.4},
    "gifu": {"circumference": "400m", "literal_straight": 59.3, "center_cant": "32°15′7″", "straight_cant": "2°51′45″",
             "home_width": 10.2, "back_width": 9.0, "center_width": 7.4,
             "record_time": "10.7秒", "record_holder": "伊勢崎彰大", "record_date": "2004/08/14",
             "nige_1st": 26.8, "sashi_1st": 46.8, "makuri_1st": 26.3,
             "nige_2nd": 21.4, "sashi_2nd": 26.4, "makuri_2nd": 12.4, "mark_2nd": 39.5},
    "ogaki": {"circumference": "400m", "literal_straight": 56.0, "center_cant": "30°37′8″", "straight_cant": "2°51′45″",
              "home_width": 10.2, "back_width": 9.0, "center_width": 7.4,
              "record_time": "10.5秒", "record_holder": "ネイワンド", "record_date": "1994/05/08",
              "nige_1st": 27.9, "sashi_1st": 45.4, "makuri_1st": 26.4,
              "nige_2nd": 21.7, "sashi_2nd": 24.6, "makuri_2nd": 12.2, "mark_2nd": 41.0},
    "toyohashi": {"circumference": "400m", "literal_straight": 60.3, "center_cant": "33°50′22″", "straight_cant": "2°17′26″",
                  "home_width": 10.3, "back_width": 9.3, "center_width": 7.8,
                  "record_time": "10.5秒", "record_holder": "金子貴志", "record_date": "2013/07/21",
                  "nige_1st": 25.9, "sashi_1st": 45.3, "makuri_1st": 28.8,
                  "nige_2nd": 21.9, "sashi_2nd": 24.6, "makuri_2nd": 12.8, "mark_2nd": 40.7},
    "toyama": {"circumference": "333m", "literal_straight": 43.0, "center_cant": "33°41′24″", "straight_cant": "3°26′1″",
               "home_width": 10.2, "back_width": 9.2, "center_width": 6.4,
               "record_time": "8.8秒", "record_holder": "山口拳矢", "record_date": "2025/08/03",
               "nige_1st": 30.1, "sashi_1st": 36.9, "makuri_1st": 33.4,
               "nige_2nd": 22.0, "sashi_2nd": 20.3, "makuri_2nd": 14.2, "mark_2nd": 43.2},
    "matsusaka": {"circumference": "400m", "literal_straight": 61.5, "center_cant": "34°25′29″", "straight_cant": "2°51′45″",
                  "home_width": 10.9, "back_width": 9.0, "center_width": 7.7,
                  "record_time": "10.4秒", "record_holder": "井上昌己", "record_date": "2014/05/11",
                  "nige_1st": 25.5, "sashi_1st": 47.6, "makuri_1st": 27.0,
                  "nige_2nd": 18.6, "sashi_2nd": 28.1, "makuri_2nd": 13.4, "mark_2nd": 39.9},
    "yokkaichi": {"circumference": "400m", "literal_straight": 62.4, "center_cant": "32°15′7″", "straight_cant": "2°51′45″",
                  "home_width": 13.3, "back_width": 11.5, "center_width": 8.5,
                  "record_time": "10.5秒", "record_holder": "ボス", "record_date": "2019/08/20",
                  "nige_1st": 26.3, "sashi_1st": 46.3, "makuri_1st": 27.1,
                  "nige_2nd": 19.8, "sashi_2nd": 25.4, "makuri_2nd": 13.5, "mark_2nd": 40.7},
    "fukui": {"circumference": "400m", "literal_straight": 52.8, "center_cant": "31°28′37″", "straight_cant": "2°51′45″",
              "home_width": 10.5, "back_width": 9.0, "center_width": 7.5,
              "record_time": "10.5秒", "record_holder": "脇本雄太", "record_date": "2025/09/13",
              "nige_1st": 29.6, "sashi_1st": 40.4, "makuri_1st": 29.6,
              "nige_2nd": 21.4, "sashi_2nd": 23.1, "makuri_2nd": 12.7, "mark_2nd": 42.4},
    "nara": {"circumference": "333m", "literal_straight": 38.0, "center_cant": "33°25′47″", "straight_cant": "4°51′48″",
             "home_width": 10.8, "back_width": 7.8, "center_width": 7.8,
             "record_time": "8.9秒", "record_holder": "太田海也", "record_date": "2022/08/16",
             "nige_1st": 36.8, "sashi_1st": 31.8, "makuri_1st": 30.3,
             "nige_2nd": 20.9, "sashi_2nd": 17.8, "makuri_2nd": 11.8, "mark_2nd": 48.5},
    "mukomachi": {"circumference": "400m", "literal_straight": 47.3, "center_cant": "30°29′7″", "straight_cant": "3°26′1″",
                  "home_width": 10.3, "back_width": 9.3, "center_width": 7.6,
                  "record_time": "10.4秒", "record_holder": "深谷知広", "record_date": "2014/08/01",
                  "nige_1st": 28.9, "sashi_1st": 45.2, "makuri_1st": 24.2,
                  "nige_2nd": 20.8, "sashi_2nd": 24.6, "makuri_2nd": 13.7, "mark_2nd": 39.4},
    "wakayama": {"circumference": "400m", "literal_straight": 59.9, "center_cant": "32°15′7″", "straight_cant": "2°51′45″",
                 "home_width": 11.4, "back_width": 9.3, "center_width": 7.7,
                 "record_time": "10.6秒", "record_holder": "ペルビス", "record_date": "2014/05/13",
                 "nige_1st": 23.9, "sashi_1st": 49.2, "makuri_1st": 25.9,
                 "nige_2nd": 20.9, "sashi_2nd": 23.6, "makuri_2nd": 15.5, "mark_2nd": 39.3},
    "kishiwada": {"circumference": "400m", "literal_straight": 56.7, "center_cant": "30°56′0″", "straight_cant": "2°51′45″",
                  "home_width": 10.2, "back_width": 10.1, "center_width": 7.3,
                  "record_time": "10.3秒", "record_holder": "ペルビス", "record_date": "2014/07/23",
                  "nige_1st": 28.0, "sashi_1st": 43.0, "makuri_1st": 28.7,
                  "nige_2nd": 20.8, "sashi_2nd": 23.1, "makuri_2nd": 13.0, "mark_2nd": 42.8},
    "tamano": {"circumference": "400m", "literal_straight": 47.9, "center_cant": "30°37′33″", "straight_cant": "3°26′1″",
               "home_width": 10.3, "back_width": 9.3, "center_width": 7.5,
               "record_time": "10.5秒", "record_holder": "太田竜馬", "record_date": "2016/08/14",
               "nige_1st": 26.6, "sashi_1st": 45.5, "makuri_1st": 27.7,
               "nige_2nd": 20.1, "sashi_2nd": 25.8, "makuri_2nd": 13.0, "mark_2nd": 40.6},
    "hiroshima": {"circumference": "400m", "literal_straight": 57.9, "center_cant": "32°31′40″", "straight_cant": "3°26′1″",
                  "home_width": 10.5, "back_width": 8.5, "center_width": 7.3,
                  "record_time": "10.8秒", "record_holder": "石橋慎太郎", "record_date": "2008/06/13",
                  "nige_1st": 20.4, "sashi_1st": 47.5, "makuri_1st": 32.3,
                  "nige_2nd": 19.7, "sashi_2nd": 28.3, "makuri_2nd": 11.8, "mark_2nd": 40.5},
    "hofu": {"circumference": "333m", "literal_straight": 42.5, "center_cant": "34°41′9″", "straight_cant": "4°34′26″",
             "home_width": 10.2, "back_width": 9.1, "center_width": 7.4,
             "record_time": "8.8秒", "record_holder": "新田祐大", "record_date": "2015/04/27",
             "nige_1st": 32.2, "sashi_1st": 34.2, "makuri_1st": 32.7,
             "nige_2nd": 20.1, "sashi_2nd": 20.3, "makuri_2nd": 12.4, "mark_2nd": 46.2},
    "takamatsu": {"circumference": "400m", "literal_straight": 54.8, "center_cant": "33°15′50″", "straight_cant": "2°51′45″",
                  "home_width": 11.0, "back_width": 9.0, "center_width": 8.0,
                  "record_time": "10.6秒", "record_holder": "高城信雄", "record_date": "2000/07/27",
                  "nige_1st": 26.0, "sashi_1st": 44.3, "makuri_1st": 29.4,
                  "nige_2nd": 20.8, "sashi_2nd": 25.8, "makuri_2nd": 11.8, "mark_2nd": 41.3},
    "komatsushima": {"circumference": "400m", "literal_straight": 55.5, "center_cant": "29°46′27″", "straight_cant": "2°51′45″",
                      "home_width": 10.3, "back_width": 9.3, "center_width": 8.3,
                      "record_time": "10.5秒", "record_holder": "吉村和之", "record_date": "2004/07/05",
                      "nige_1st": 25.2, "sashi_1st": 46.9, "makuri_1st": 27.9,
                      "nige_2nd": 19.9, "sashi_2nd": 29.5, "makuri_2nd": 12.6, "mark_2nd": 38.0},
    "kochi": {"circumference": "500m", "literal_straight": 52.0, "center_cant": "24°29′51″", "straight_cant": "3°26′1″",
              "home_width": 11.3, "back_width": 10.8, "center_width": 7.8,
              "record_time": "13.1秒", "record_holder": "島川将貴", "record_date": "2021/07/31",
              "nige_1st": 22.9, "sashi_1st": 51.3, "makuri_1st": 25.1,
              "nige_2nd": 16.8, "sashi_2nd": 29.4, "makuri_2nd": 13.2, "mark_2nd": 39.6},
    "matsuyama": {"circumference": "400m", "literal_straight": 58.6, "center_cant": "34°1′48″", "straight_cant": "2°51′45″",
                  "home_width": 10.3, "back_width": 9.3, "center_width": 7.3,
                  "record_time": "10.5秒", "record_holder": "ペルビス", "record_date": "2013/05/15",
                  "nige_1st": 25.7, "sashi_1st": 46.2, "makuri_1st": 28.5,
                  "nige_2nd": 19.3, "sashi_2nd": 25.4, "makuri_2nd": 12.8, "mark_2nd": 42.3},
    "kokura": {"circumference": "400m", "literal_straight": 56.9, "center_cant": "34°1′48″", "straight_cant": "3°26′1″",
               "home_width": 11.0, "back_width": 10.0, "center_width": 8.0,
               "record_time": "10.5秒", "record_holder": "エスクレド", "record_date": "2006/07/06",
               "nige_1st": 27.2, "sashi_1st": 43.7, "makuri_1st": 28.7,
               "nige_2nd": 22.7, "sashi_2nd": 22.2, "makuri_2nd": 12.7, "mark_2nd": 42.0},
    "kurume": {"circumference": "400m", "literal_straight": 50.7, "center_cant": "31°28′37″", "straight_cant": "3°26′1″",
               "home_width": 11.0, "back_width": 10.0, "center_width": 9.0,
               "record_time": "10.4秒", "record_holder": "グレーツァー", "record_date": "2019/05/22",
               "nige_1st": 27.6, "sashi_1st": 41.6, "makuri_1st": 30.0,
               "nige_2nd": 19.8, "sashi_2nd": 23.6, "makuri_2nd": 12.0, "mark_2nd": 43.7},
    "takeo": {"circumference": "400m", "literal_straight": 64.4, "center_cant": "32°0′19″", "straight_cant": "2°17′26″",
              "home_width": 9.7, "back_width": 8.7, "center_width": 7.4,
              "record_time": "10.6秒", "record_holder": "寺崎浩平", "record_date": "2025/04/13",
              "nige_1st": 24.4, "sashi_1st": 46.5, "makuri_1st": 28.6,
              "nige_2nd": 20.0, "sashi_2nd": 24.7, "makuri_2nd": 13.1, "mark_2nd": 41.5},
    "sasebo": {"circumference": "400m", "literal_straight": 40.2, "center_cant": "31°28′37″", "straight_cant": "3°26′1″",
               "home_width": 10.0, "back_width": 9.0, "center_width": 7.5,
               "record_time": "10.6秒", "record_holder": "中川誠一郎", "record_date": "2022/07/24",
               "nige_1st": 26.5, "sashi_1st": 45.4, "makuri_1st": 27.6,
               "nige_2nd": 22.2, "sashi_2nd": 20.8, "makuri_2nd": 15.0, "mark_2nd": 41.2},
    "beppu": {"circumference": "400m", "literal_straight": 59.9, "center_cant": "33°41′24″", "straight_cant": "2°51′45″",
              "home_width": 10.0, "back_width": 9.0, "center_width": 8.0,
              "record_time": "10.5秒", "record_holder": "ボス", "record_date": "2019/09/19",
              "nige_1st": 29.4, "sashi_1st": 41.1, "makuri_1st": 29.1,
              "nige_2nd": 20.1, "sashi_2nd": 23.3, "makuri_2nd": 13.5, "mark_2nd": 42.5},
    "kumamoto": {"circumference": "400m", "literal_straight": 60.3, "center_cant": "34°15′29″", "straight_cant": "2°51′45″",
                 "home_width": 10.0, "back_width": 9.0, "center_width": 8.0,
                 "record_time": "10.7秒", "record_holder": "嘉永泰斗", "record_date": "2024/07/21",
                 "nige_1st": 28.2, "sashi_1st": 42.8, "makuri_1st": 28.7,
                 "nige_2nd": 20.5, "sashi_2nd": 23.8, "makuri_2nd": 12.8, "mark_2nd": 42.2},
}


def kimarite_venue_average(slug):
    """
    そのレース場の「決まり手構成の場平均」を返す（1着ベース、逃・捲・差・マの4区分）。
    元データは逃げ・差し・捲りの1着出現率のみ（マークは1着区分として集計されていない
    ＝「決まり手集計が平均ではなかった」ケースにあたる）ため、マークの平均は
    100%からの残差として別途算出する。
    戻り値: {"逃":x,"捲":x,"差":x,"マ":x} または None（データが無い場合）
    """
    d = VENUE_BANK_DATA.get(slug)
    if not d or d.get("nige_1st") is None:
        return None
    nige, sashi, makuri = d["nige_1st"], d["sashi_1st"], d["makuri_1st"]
    mark = max(0.0, round(100 - nige - sashi - makuri, 1))
    return {"逃": nige, "捲": makuri, "差": sashi, "マ": mark}


def bank_class(circumference):
    """周長からバンククラス（333/400/500）を返す"""
    if not circumference:
        return None
    if circumference.startswith("333") or circumference.startswith("335"):
        return "333"
    if circumference.startswith("400"):
        return "400"
    if circumference.startswith("500"):
        return "500"
    return None


def straight_tendency(literal_straight):
    """みなし直線の長さから傾向（逃げ・差しどちらが有利か）を簡易判定する"""
    if literal_straight is None:
        return None
    if literal_straight <= 45:
        return "逃げ・捲り有利"
    if literal_straight >= 58:
        return "差し有利"
    return "標準"
