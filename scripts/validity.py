# -*- coding: utf-8 -*-
"""結果（着順）が信頼できるかの検査。評価・学習・結果の再取得で共通に使う。"""


def finish_order_ok(entry):
    """
    着順が壊れていないか。次のどれかなら False:
      ・3着ぶん無い / 同じ車番が重複 / 出走表にない車番が混ざる
      ・着順の数が出走数より少なく、かつ先頭が「着順数+1」
        （結果ページの見出し行の数字を車番と読み違えたときの典型的な壊れ方。15/15件がこの形だった）
    結果が未取得(None)のものは True（別の理由 "pending" で扱う）。
    """
    res = entry.get("result")
    if not res:
        return True
    fo = res.get("finish_order") or []
    if len(fo) < 3 or len(set(fo)) != len(fo):
        return False
    cars = (entry.get("cond") or {}).get("cars")
    if not cars and entry.get("probs"):
        cars = [int(p[0]) for p in entry["probs"]]
    if not cars and entry.get("order"):
        cars = list(entry["order"])
    if cars:
        if not set(fo) <= set(cars):
            return False
        if len(fo) < len(cars) and fo[0] == len(fo) + 1:
            return False
    return True
