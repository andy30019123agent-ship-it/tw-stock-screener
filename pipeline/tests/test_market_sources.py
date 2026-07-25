import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import market_sources as ms  # noqa: E402


def test_roc_to_iso():
    assert ms.roc_to_iso("115/06/01") == "2026-06-01"
    assert ms.roc_to_iso("1150626") == "2026-06-26"


def test_is_common_stock():
    assert ms.is_common_stock("2330")
    assert not ms.is_common_stock("00400A")   # 主動式 ETF（6 碼含字母）
    assert not ms.is_common_stock("006201")   # 6 碼 ETF
    assert not ms.is_common_stock("2330B")    # 特別股


def test_f_cleans_numbers():
    assert ms._f("1,234.5") == 1234.5
    assert ms._f("+0.79") == 0.79
    assert ms._f("--") is None
    assert ms._f("") is None


def test_f_zero_string_is_valid_zero_not_none():
    # TWSE 對零股/極低量成交回 "0.00"，_f 要老實轉成 0.0（不是 None）——
    # 擋零價污染的責任在 _ohlc，不是在 _f 把它誤判成缺值。
    assert ms._f("0.00") == 0.0
    assert ms._f("0") == 0.0


def test_ohlc_drops_row_when_close_is_zero_or_negative():
    # 根因案例：低量股（例 1213 單日成交 1 張、金額 7 元）TWSE 回 close="0.00"，
    # 不擋的話會被寫進歷史當成「跌到 0 元」，污染漲跌幅與指標。
    assert ms._ohlc("2026-07-16", "10", "10", "10", "0.00", "1", "7") is None
    assert ms._ohlc("2026-07-16", "10", "10", "10", "0", "1", "7") is None


def test_ohlc_keeps_valid_positive_close():
    row = ms._ohlc("2026-07-16", "10.0", "10.5", "9.8", "10.2", "1000", "10200")
    assert row is not None
    assert row["close"] == 10.2


def test_listed_chip_sums_foreign(monkeypatch):
    # T86：外資 = [4]外陸資 + [7]外資自營；投信 = [10]
    payload = {"data": [
        ["2330", "台積電", "0", "0", "-3,311,663", "0", "0", "0",
         "722,215", "264,000", "458,215", "0", "0", "0", "0", "0", "0", "0", "0"],
        ["006201", "ETF", "0", "0", "999", "0", "0", "0", "0", "0", "888",
         "0", "0", "0", "0", "0", "0", "0", "0"],   # 非 4 碼數字 → 濾掉
    ]}
    monkeypatch.setattr(ms, "get_json", lambda url: payload)
    out = ms.fetch_listed_chip("2026-06-01")
    assert out == {"2330": {"Foreign_Investor": -3311663.0, "Investment_Trust": 458215.0}}


def test_fetch_taiex_close_parses_index_row(monkeypatch):
    # MI_INDEX type=IND：多張表，要找到「發行量加權股價指數」那一列的收盤指數
    payload = {"tables": [
        {"fields": ["指數", "收盤指數", "漲跌(+/-)", "漲跌點數", "漲跌百分比(%)", "備註"],
         "data": [["寶島股價指數", "52,351.49", "+", "960.26", "1.87", ""],
                  ["發行量加權股價指數", "47,018.99", "+", "893.08", "1.94", ""]]},
        {},
    ]}
    monkeypatch.setattr(ms, "get_json", lambda url: payload)
    assert ms.fetch_taiex_close("2026-07-01") == 47018.99


def test_fetch_taiex_close_no_data_on_non_trading_day(monkeypatch):
    monkeypatch.setattr(ms, "get_json", lambda url: {"tables": [{"data": []}, {}]})
    assert ms.fetch_taiex_close("2026-06-28") is None


def test_otc_chip_maps_columns(monkeypatch):
    # TPEX insti：外資合計 = [10]，投信 = [13]
    row = ["6488", "環球晶", "1", "1", "0", "0", "0", "0",
           "0", "0", "4,000", "0", "0", "12,000",
           "0", "0", "0", "0", "0", "0", "0", "0", "0", "16000"]
    monkeypatch.setattr(ms, "get_json", lambda url: {"tables": [{"data": [row]}]})
    out = ms.fetch_otc_chip("2026-06-01")
    assert out == {"6488": {"Foreign_Investor": 4000.0, "Investment_Trust": 12000.0}}
