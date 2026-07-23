"""回測專用長歷史（bt_price.json）的欄式儲存。

重點：欄式格式是為了省空間（全域共用一份日期、丟掉成交金額、量改存張），
但**還原後必須跟原本的 price.json 等價**，否則回測讀到的資料就跟線上算的不一樣。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import history_store as hs


def row(o, h, l, c, vol_lots):
    return {"open": o, "max": h, "min": l, "close": c, "Trading_Volume": vol_lots * 1000}


def test_併入後可原樣還原():
    bt = hs.bt_empty()
    hs.bt_merge_days(bt, {
        "2026-07-01": {"2330": row(100, 105, 99, 104, 5000)},
        "2026-07-02": {"2330": row(104, 108, 103, 107, 6000)},
    })
    back = hs.bt_to_price_hist(bt)
    assert sorted(back["2330"]) == ["2026-07-01", "2026-07-02"]
    o, h, l, c, v, _money = back["2330"]["2026-07-02"]
    assert (o, h, l, c) == (104, 108, 103, 107)
    assert v == 6_000_000        # 張還原回股


def test_同日重複併入是覆蓋不是重複():
    bt = hs.bt_empty()
    hs.bt_merge_days(bt, {"2026-07-01": {"2330": row(100, 105, 99, 104, 5000)}})
    hs.bt_merge_days(bt, {"2026-07-01": {"2330": row(1, 2, 0.5, 1.5, 5000)}})
    assert bt["dates"] == ["2026-07-01"]
    assert hs.bt_to_price_hist(bt)["2330"]["2026-07-01"][3] == 1.5


def test_補進更早的日期會排到前面():
    bt = hs.bt_empty()
    hs.bt_merge_days(bt, {"2026-07-02": {"2330": row(104, 108, 103, 107, 6000)}})
    hs.bt_merge_days(bt, {"2026-07-01": {"2330": row(100, 105, 99, 104, 5000)}})
    assert bt["dates"] == ["2026-07-01", "2026-07-02"]
    assert hs.bt_to_price_hist(bt)["2330"]["2026-07-01"][3] == 104


def test_超過視窗只留最近的():
    bt = hs.bt_empty()
    days = {f"2026-07-{d:02d}": {"2330": row(10, 11, 9, 10 + d, 5000)} for d in range(1, 11)}
    hs.bt_merge_days(bt, days, window=3)
    assert bt["dates"] == ["2026-07-08", "2026-07-09", "2026-07-10"]


def test_量太低的殭屍股不收錄():
    bt = hs.bt_empty()
    hs.bt_merge_days(bt, {"2026-07-01": {
        "2330": row(100, 105, 99, 104, 5000),      # 5000 張，收
        "9999": row(10, 11, 9, 10, 5),             # 5 張，不收
    }})
    assert "2330" in bt["stocks"]
    assert "9999" not in bt["stocks"]


def test_停牌那天留空_不會錯位():
    bt = hs.bt_empty()
    hs.bt_merge_days(bt, {
        "2026-07-01": {"2330": row(100, 105, 99, 104, 5000), "2454": row(50, 51, 49, 50, 3000)},
        "2026-07-02": {"2330": row(104, 108, 103, 107, 6000)},   # 2454 這天停牌
        "2026-07-03": {"2330": row(107, 109, 106, 108, 5500), "2454": row(50, 52, 50, 52, 3000)},
    })
    back = hs.bt_to_price_hist(bt)
    assert sorted(back["2454"]) == ["2026-07-01", "2026-07-03"]   # 停牌日不會冒出假資料
    assert back["2454"]["2026-07-03"][3] == 52                     # 也沒有錯位


def test_從_price_json_併入新日期():
    bt = hs.bt_empty()
    hs.bt_merge_days(bt, {"2026-07-01": {"2330": row(100, 105, 99, 104, 5000)}})
    price = {"2330": {
        "2026-07-01": [100, 105, 99, 104, 5_000_000, 1e9],   # 已有，不重複
        "2026-07-02": [104, 108, 103, 107, 6_000_000, 1e9],  # 新的
    }}
    added = hs.bt_merge_from_price(bt, price)
    assert added == 1
    assert bt["dates"] == ["2026-07-01", "2026-07-02"]
