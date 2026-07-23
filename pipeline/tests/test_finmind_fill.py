"""FinMind 補洞工具（finmind_fill.py）。

重點：它是「TWSE 對某天永久回空時的獨立備援」，必須守住三條安全線——
1. 只填缺格，不覆蓋既有 TWSE 資料（單一真值）。
2. FinMind 沒回傳的日期不亂填（該股那天沒交易時，缺格就該留著）。
3. `--stocks` 只跑幾檔時，不新增全域日期（否則那天只有幾檔有值、其餘 None，污染回測）。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import history_store as hs
import finmind_fill as ff


def row(o, h, l, c, vol_lots=5000):
    return {"open": o, "max": h, "min": l, "close": c, "Trading_Volume": vol_lots * 1000}


def fm_bar(date, c):
    """一根 FinMind K 線（Trading_Volume 是股數）。"""
    return {"date": date, "open": c, "max": c + 1, "min": c - 1, "close": c,
            "Trading_Volume": 5000 * 1000}


def make_bt():
    """A、B 在 07-01/07-03 都有；C 只有 07-03（07-01 是個股缺格）。07-02 整天不存在（整日洞）。"""
    bt = hs.bt_empty()
    hs.bt_merge_days(bt, {
        "2026-07-01": {"A": row(10, 11, 9, 10), "B": row(20, 21, 19, 20)},
        "2026-07-03": {"A": row(12, 13, 11, 12), "B": row(22, 23, 21, 22),
                       "C": row(30, 31, 29, 30)},
    })
    return bt


def run_main(tmp_path, monkeypatch, bt, fm_data, argv):
    """把 bt 寫到暫存檔、假掉 FinMind、跑 main()，回傳補完的 bt。"""
    p = tmp_path / "bt_price.json"
    hs.save(str(p), bt)
    monkeypatch.setattr(ff, "BT_PATH", str(p))
    monkeypatch.setattr(ff, "fetch_stock_range",
                        lambda sid, s, e, token="", retries=4: fm_data.get(sid, []))
    monkeypatch.setattr(ff, "SAVE_EVERY", 1)          # 每檔就存，順便驗中途存檔不爆
    monkeypatch.setattr(sys, "argv", ["finmind_fill.py", "--sleep", "0"] + argv)
    ff.main()
    return hs.load(str(p))


def test_補個股既有日期的缺格(tmp_path, monkeypatch):
    bt = make_bt()
    fm = {"C": [fm_bar("2026-07-01", 28), fm_bar("2026-07-03", 30)]}
    out = run_main(tmp_path, monkeypatch, bt, fm, [])
    back = hs.bt_to_price_hist(out)
    assert "2026-07-01" in back["C"]                   # C 的 07-01 缺格被補上
    assert back["C"]["2026-07-01"][3] == 28
    assert out["dates"] == ["2026-07-01", "2026-07-03"]  # 沒有無中生有的日期


def test_不覆蓋既有資料(tmp_path, monkeypatch):
    bt = make_bt()
    # FinMind 給 A 一組「不一樣」的 07-01 收盤；A 那格已有值，不該被動到
    fm = {"A": [fm_bar("2026-07-01", 999), fm_bar("2026-07-03", 999)]}
    out = run_main(tmp_path, monkeypatch, bt, fm, ["--stocks", "A"])
    assert hs.bt_to_price_hist(out)["A"]["2026-07-01"][3] == 10  # 保留原值 10


def test_FinMind沒回傳就不亂填(tmp_path, monkeypatch):
    bt = make_bt()
    # C 缺 07-01，但 FinMind 只回 07-03（模擬 C 當天真的沒交易）→ 07-01 應維持缺
    fm = {"C": [fm_bar("2026-07-03", 30)]}
    out = run_main(tmp_path, monkeypatch, bt, fm, [])
    assert "2026-07-01" not in hs.bt_to_price_hist(out).get("C", {})


def test_dates備援補整日洞_全宇宙(tmp_path, monkeypatch):
    bt = make_bt()
    fm = {
        "A": [fm_bar("2026-07-02", 111)],
        "B": [fm_bar("2026-07-02", 222)],
        "C": [fm_bar("2026-07-02", 333), fm_bar("2026-07-01", 28)],
    }
    out = run_main(tmp_path, monkeypatch, bt, fm, ["--dates", "2026-07-02"])
    assert out["dates"] == ["2026-07-01", "2026-07-02", "2026-07-03"]  # 新增整日
    back = hs.bt_to_price_hist(out)
    assert back["A"]["2026-07-02"][3] == 111          # 每檔都貢獻了那天的 K
    assert back["B"]["2026-07-02"][3] == 222
    assert back["C"]["2026-07-02"][3] == 333


def test_stocks模式不新增全域日期(tmp_path, monkeypatch):
    bt = make_bt()
    # 想用 --stocks A 补一個「新的整日洞」07-02 → 應被拒（會讓那天只有 A 有值）
    fm = {"A": [fm_bar("2026-07-02", 111)]}
    out = run_main(tmp_path, monkeypatch, bt, fm, ["--stocks", "A", "--dates", "2026-07-02"])
    assert "2026-07-02" not in out["dates"]            # 沒有被新增
