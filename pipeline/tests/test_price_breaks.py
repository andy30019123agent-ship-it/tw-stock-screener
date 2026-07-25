"""價格斷點偵測（分割/現金減資造成的假漲跌，除權息端點涵蓋不到）。"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import price_breaks as pb  # noqa: E402


def _cols(closes):
    """closes: list[float|None]，其餘 OHLC 欄位跟著 close 走（測試不在乎細節）。"""
    n = len(closes)
    o = [c if c is not None else None for c in closes]
    h, lo, v = list(o), list(o), [1000] * n
    return [o, h, lo, closes, v]


def test_detects_single_day_big_drop():
    bt = {
        "dates": ["2026-01-01", "2026-01-02", "2026-01-03"],
        "stocks": {"9999": _cols([100.0, 25.0, 25.5])},  # -75% 分割
    }
    breaks = pb.detect_price_breaks(bt, {})
    assert len(breaks) == 1
    b = breaks[0]
    assert b["sid"] == "9999" and b["date"] == "2026-01-02"
    assert b["prev_close"] == 100.0 and b["close"] == 25.0
    assert b["pct"] == -75.0


def test_ignores_normal_moves_under_threshold():
    bt = {
        "dates": ["2026-01-01", "2026-01-02"],
        "stocks": {"2330": _cols([100.0, 110.0])},  # +10%，正常漲停內
    }
    assert pb.detect_price_breaks(bt, {}) == []


def test_excludes_move_covered_by_ex_dividend_event():
    # 除息當天跌 45%（極端案例，實務不會這麼多，但用來驗證排除邏輯本身）
    bt = {
        "dates": ["2026-01-01", "2026-01-02"],
        "stocks": {"2603": _cols([100.0, 55.0])},
    }
    div_hist = {"2603": {"2026-01-02": 0.55}}
    assert pb.detect_price_breaks(bt, div_hist) == []


def test_handles_gaps_without_misaligning():
    # 中間停牌一天（None），不該把停牌前後誤判成單日跳動
    bt = {
        "dates": ["2026-01-01", "2026-01-02", "2026-01-03"],
        "stocks": {"2330": _cols([100.0, None, 102.0])},
    }
    assert pb.detect_price_breaks(bt, {}) == []


def test_is_broken_query():
    breaks_set = {("9999", "2026-01-02")}
    assert pb.is_broken(breaks_set, "9999", "2026-01-02")
    assert not pb.is_broken(breaks_set, "9999", "2026-01-03")
    assert not pb.is_broken(breaks_set, "2330", "2026-01-02")


def test_load_breaks_missing_file_returns_empty_set(tmp_path):
    assert pb.load_breaks(str(tmp_path / "nope.json")) == set()


def test_load_breaks_roundtrip(tmp_path):
    import json
    path = tmp_path / "price_breaks.json"
    path.write_text(json.dumps({
        "breaks": [{"sid": "9999", "date": "2026-01-02", "prev_close": 100.0,
                    "close": 25.0, "pct": -75.0}],
    }), encoding="utf-8")
    breaks_set = pb.load_breaks(str(path))
    assert breaks_set == {("9999", "2026-01-02")}
