"""選股母體排除 ETF（00 開頭代號）：0050/0056 這種 4 碼數字代號會被 is_common_stock
放行，混進普通股母體會讓分割/反分割的假漲跌污染選股與回測。"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import build_universe as bu  # noqa: E402
import market_sources as ms  # noqa: E402


def test_is_etf_code():
    assert bu._is_etf_code("0050")
    assert bu._is_etf_code("0056")
    assert bu._is_etf_code("00919")
    assert not bu._is_etf_code("2330")
    assert not bu._is_etf_code("6488")


def test_main_excludes_etf_from_universe(monkeypatch, tmp_path):
    monkeypatch.setattr(bu, "HERE", str(tmp_path))
    monkeypatch.setattr(
        ms, "fetch_listed_ohlc_latest",
        lambda: ("2026-07-24", {"0050": {}, "2330": {}, "2317": {}}),
    )
    monkeypatch.setattr(ms, "fetch_otc_ohlc", lambda date_iso: {"0056": {}, "6488": {}})
    monkeypatch.setattr(
        bu, "_listed_company_info",
        lambda: {"2330": ("台積電", "24"), "2317": ("鴻海", "24")},
    )
    monkeypatch.setattr(bu, "_otc_company_info", lambda: {"6488": ("環球晶", "24")})

    bu.main()

    with open(tmp_path / "universe.json", encoding="utf-8") as f:
        out = json.load(f)
    ids = [s["id"] for s in out["stocks"]]
    assert "0050" not in ids
    assert "0056" not in ids
    assert set(ids) == {"2330", "2317", "6488"}
