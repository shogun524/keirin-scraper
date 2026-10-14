# -*- coding: utf-8 -*-
"""テスト用の固定データ（乱数は種を固定するので毎回同じ）。"""
import random
import math
import datetime


def make_race(seed, n=7, line="1-2-3,4-5,6-7", spread=1.0, rank="S1"):
    rnd = random.Random(seed)
    racers = []
    for car in range(1, n + 1):
        sc = 8.8 - (car - 1) * 0.25 * spread + rnd.uniform(-0.4, 0.4)
        k = {"逃": rnd.randint(2, 30), "捲": rnd.randint(2, 28), "差": rnd.randint(2, 20), "マ": rnd.randint(2, 25)}
        racers.append(dict(car=car, name=f"選手{car}", mark="", rank=rank, tactic=rnd.choice(["逃", "捲", "差", "マ"]),
                           souhyou=0, waku=car, gear=3.92, score=sc * 10, age=30, period=1, kimarite=k,
                           finishes={"f1": rnd.randint(2, 12), "f2": rnd.randint(2, 10), "f3": rnd.randint(2, 10), "fo": rnd.randint(4, 14)}))
    return racers, line


def synth_log(n_days=10, per_day=40, beta_true=0.0, seed=1, n_cars=7):
    """予測確率pと方程式evから勝者を生成した擬似ログ（真のバフ強さ beta_true を仕込める）。"""
    rnd = random.Random(seed)
    log = {}
    base = datetime.date(2026, 9, 1)
    for d in range(n_days):
        day = (base + datetime.timedelta(days=d)).isoformat()
        for i in range(per_day):
            cars = list(range(1, n_cars + 1))
            raw = [rnd.random() ** 1.5 + 0.05 for _ in cars]
            s = sum(raw)
            p = [x / s * 100 for x in raw]
            ev = [[c, 100 + rnd.gauss(0, 12)] for c in cars]
            vals = [t for _, t in ev]
            m = sum(vals) / n_cars
            sd = (sum((v - m) ** 2 for v in vals) / n_cars) ** 0.5
            z = [(t - m) / sd for _, t in ev]
            w = [pi * math.exp(beta_true * zi) for pi, zi in zip(p, z)]
            win = rnd.choices(cars, weights=w)[0]
            rest = [c for c in cars if c != win]
            rnd.shuffle(rest)
            order = [c for c, _ in sorted(zip(cars, p), key=lambda x: -x[1])]
            log[f"{day}_omiya_{i + 1}"] = {
                "date": day, "venue": "omiya", "race_no": i + 1, "deadline": "12:00",
                "rec_at": f"{day} 06:00", "late": False, "n_cars": n_cars,
                "order": order, "top_adj": round(max(p), 2), "is_high": False, "is_close": False,
                "trifecta": [[order[0], order[1], order[2]]],
                "probs": [[c, round(pp, 2), 30.0] for c, pp in zip(cars, p)], "sf": 1.75, "ev": ev,
                "result": {"finish_order": [win] + rest, "ranks": list(range(1, n_cars + 1))},
                "attempts": 0, "parser_v": 4,
            }
    return log
