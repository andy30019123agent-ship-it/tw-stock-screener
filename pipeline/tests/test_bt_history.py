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


# ── 插入中間日期（漏抓回補，2026-11-13 驗收後）────────────────────────────
# 根因：bt_merge_days 每次都重跑整段流動性門檻、並把那天的列寫給「所有」股票 → 晚收錄的股票
# 多出孤立的舊列＋一大段洞，邊緣股被重篩刪掉整段歷史。插入模式只補「已收錄、範圍涵蓋那天」的格子。
def _bt_with(days_by_sid, vol=5000):
    """{sid: [日期...]} → bt（每格收盤 = 日期的日數，方便辨認）。"""
    allday = sorted({d for ds in days_by_sid.values() for d in ds})
    bt = hs.bt_empty()
    hs.bt_merge_days(bt, {d: {s: row(1, 2, 0.5, int(d[-2:]), vol)
                              for s, ds in days_by_sid.items() if d in ds} for d in allday})
    return bt


def _closes(bt, sid):
    return {d: c for d, c in zip(bt["dates"], bt["stocks"][sid][3]) if c is not None}


def test_插入舊日期_只補範圍涵蓋的股票_晚收錄的不製造孤立列():
    early = ["2026-07-01", "2026-07-02", "2026-07-06", "2026-07-07"]
    bt = _bt_with({"2330": early, "6957": ["2026-07-06", "2026-07-07"]})   # 6957 07-06 才收錄
    before_2330 = _closes(bt, "2330")
    n = hs.bt_insert_days(bt, {"2026-07-03": {"2330": row(1, 2, 0.5, 99, 5000),
                                              "6957": row(1, 2, 0.5, 99, 5000),
                                              "1111": row(1, 2, 0.5, 99, 5000)}})   # 1111 根本沒收錄
    assert n == 1
    assert bt["dates"] == ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-06", "2026-07-07"]
    assert _closes(bt, "2330") == {**before_2330, "2026-07-03": 99}            # 涵蓋 → 補上
    assert _closes(bt, "6957") == {"2026-07-06": 6, "2026-07-07": 7}            # 晚收錄 → 不補、無孤立列
    assert "1111" not in bt["stocks"]                                          # 不新增股票


def test_插入舊日期_不重跑流動性篩選_邊緣股歷史不被刪():
    days = ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-06"]
    bt = _bt_with({"2330": days})
    # 插入那天量是 0：若重跑平均量門檻，2330 平均會掉到 200 張以下被刪
    hs.bt_insert_days(bt, {"2026-07-05": {"2330": row(1, 2, 0.5, 5, 0)}})
    assert "2330" in bt["stocks"] and len(_closes(bt, "2330")) == 5


def test_插入舊日期_維持視窗_最舊的滑出():
    days = ["2026-07-01", "2026-07-02", "2026-07-06", "2026-07-07"]
    bt = _bt_with({"2330": days})
    hs.bt_insert_days(bt, {"2026-07-03": {"2330": row(1, 2, 0.5, 3, 5000)}}, window=4)
    assert bt["dates"] == ["2026-07-02", "2026-07-03", "2026-07-06", "2026-07-07"]
    assert all(len(c) == 4 for c in bt["stocks"]["2330"])


def test_插入已存在的日期_補空格不動其他格_而且冪等():
    import copy
    days = ["2026-07-01", "2026-07-02", "2026-07-03"]
    bt = _bt_with({"2330": days, "6488": ["2026-07-01", "2026-07-03"]})   # 6488 07-02 是空格
    hs.bt_insert_days(bt, {"2026-07-02": {"6488": row(1, 2, 0.5, 42, 5000)}})
    assert _closes(bt, "6488") == {"2026-07-01": 1, "2026-07-02": 42, "2026-07-03": 3}
    assert _closes(bt, "2330") == {"2026-07-01": 1, "2026-07-02": 2, "2026-07-03": 3}
    snap = copy.deepcopy(bt)
    hs.bt_insert_days(bt, {"2026-07-02": {"6488": row(1, 2, 0.5, 42, 5000)}})
    assert bt == snap


def test_插入模式不處理比最新日還新的日期():
    bt = _bt_with({"2330": ["2026-07-01", "2026-07-02"]})
    assert hs.bt_insert_days(bt, {"2026-07-03": {"2330": row(1, 2, 0.5, 3, 5000)}}) == 0
    assert bt["dates"] == ["2026-07-01", "2026-07-02"]


def test_每週合併遇到回補的舊日期_走插入模式_不製造孤立列():
    # 情境：回補把 07-03 寫進 price.json（bt 沒有）；6957 07-06 才收錄。每週合併同時遇到
    # 「舊日期 07-03」與「新日期 07-08」。舊的走插入模式、新的照原本路徑。
    many = {f"{3000 + i}": ["2026-07-01", "2026-07-02", "2026-07-06", "2026-07-07"]
            for i in range(hs.BT_INSERT_MIN_ROWS)}
    bt = _bt_with({**many, "6957": ["2026-07-06", "2026-07-07"]})
    price = {s: {"2026-07-03": [1, 2, 0.5, 33, 5_000_000, 0], "2026-07-08": [1, 2, 0.5, 8, 5_000_000, 0]}
             for s in list(many) + ["6957"]}
    added = hs.bt_merge_from_price(bt, price)
    assert added == 2
    assert "2026-07-03" in bt["dates"] and bt["dates"][-1] == "2026-07-08"
    assert _closes(bt, "6957") == {"2026-07-06": 6, "2026-07-07": 7, "2026-07-08": 8}   # 沒有 07-03 孤立列
    assert _closes(bt, "3000")["2026-07-03"] == 33


def test_每週合併_零星幾檔的舊日期不插():
    bt = _bt_with({"2330": ["2026-07-01", "2026-07-02", "2026-07-06"]})
    price = {"2330": {"2026-07-03": [1, 2, 0.5, 33, 5_000_000, 0]}}   # 只有 1 檔（殘留列樣態）
    assert hs.bt_merge_from_price(bt, price) == 0
    assert "2026-07-03" not in bt["dates"]
