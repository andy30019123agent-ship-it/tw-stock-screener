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


def test_otc_chip_maps_columns(monkeypatch):
    # TPEX insti：外資合計 = [10]，投信 = [13]
    row = ["6488", "環球晶", "1", "1", "0", "0", "0", "0",
           "0", "0", "4,000", "0", "0", "12,000",
           "0", "0", "0", "0", "0", "0", "0", "0", "0", "16000"]
    monkeypatch.setattr(ms, "get_json", lambda url: {"tables": [{"data": [row]}]})
    out = ms.fetch_otc_chip("2026-06-01")
    assert out == {"6488": {"Foreign_Investor": 4000.0, "Investment_Trust": 12000.0}}
