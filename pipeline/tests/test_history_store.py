import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import history_store as hs  # noqa: E402


def _row(o, h, lo, c, v=1000, m=10000):
    return {"open": o, "max": h, "min": lo, "close": c,
            "Trading_Volume": v, "Trading_money": m}


def test_append_price_dedup_and_prune():
    hist = {}
    hs.append_price(hist, "2026-06-01", {"2330": _row(100, 105, 99, 104)})
    hs.append_price(hist, "2026-06-02", {"2330": _row(104, 110, 103, 109)})
    # 同日再 append → 覆蓋不重複
    hs.append_price(hist, "2026-06-02", {"2330": _row(104, 111, 103, 110)})
    assert len(hist["2330"]) == 2
    assert hist["2330"]["2026-06-02"][3] == 110          # 收盤被覆蓋為新值
    # 超窗修剪：window=2，加第 3 天應丟掉最舊
    hs.append_price(hist, "2026-06-03", {"2330": _row(110, 112, 108, 111)}, window=2)
    assert sorted(hist["2330"]) == ["2026-06-02", "2026-06-03"]


def test_to_price_rows_shape():
    hist = {}
    hs.append_price(hist, "2026-06-02", {"2330": _row(104, 110, 103, 109, v=5000, m=99)})
    hs.append_price(hist, "2026-06-01", {"2330": _row(100, 105, 99, 104)})
    rows = hs.to_price_rows(hist["2330"])
    assert [r["date"] for r in rows] == ["2026-06-01", "2026-06-02"]  # 已排序
    assert rows[1] == {"date": "2026-06-02", "open": 104, "max": 110, "min": 103,
                       "close": 109, "Trading_Volume": 5000, "Trading_money": 99}


def test_to_chip_rows_streak_compatible():
    hist = {}
    hs.append_chip(hist, "2026-06-01", {"2330": {"Foreign_Investor": 500, "Investment_Trust": -100}})
    hs.append_chip(hist, "2026-06-02", {"2330": {"Foreign_Investor": 800, "Investment_Trust": 200}})
    rows = hs.to_chip_rows(hist["2330"])
    # 每日兩列、net 放在 buy（compute_indicators 算 net=buy-sell）
    f = [r for r in rows if r["name"] == "Foreign_Investor"]
    assert [r["buy"] for r in f] == [500, 800]
    assert all(r["sell"] == 0 for r in rows)
