"""除權息還原測試：back_adjust_rows + history_store 的除權息事件存取。

驗證核心訴求：除息日之後只要有一根「持平或小跌」的 K，指標算出來不該被除息缺口
誤判成跌破均線／翻空；除息日本身與之後的顯示現價（close/change）不受還原影響。
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import build_data as bd  # noqa: E402
import history_store as hs  # noqa: E402


def _row(date, o, h, lo, c, v=1_000_000):
    return {"date": date, "open": o, "max": h, "min": lo, "close": c,
            "Trading_Volume": v, "Trading_money": v * c}


def test_back_adjust_rows_scales_prior_prices():
    rows = [_row("2026-06-15", 100, 101, 99, 100),
            _row("2026-06-16", 100, 101, 99, 100),
            _row("2026-06-17", 93, 94, 92, 93),   # 除息日：參考價 93（ratio=0.93）
            _row("2026-06-18", 93, 95, 92, 94)]
    events = [{"date": "2026-06-17", "ratio": 0.93}]
    out = bd.back_adjust_rows(rows, events)
    # 除息日之前（含 06-16）依 ratio 縮放，除息日當天(含)之後不變
    assert out[0]["close"] == 93.0
    assert out[1]["close"] == 93.0
    assert out[2]["close"] == 93.0   # 除息日本身不再乘一次
    assert out[3]["close"] == 94.0
    # 原始 rows 不被就地修改（新 list、不共用被改動的 dict）
    assert rows[0]["close"] == 100


def test_back_adjust_rows_no_events_returns_input_unchanged():
    rows = [_row("2026-06-15", 100, 101, 99, 100)]
    assert bd.back_adjust_rows(rows, []) is rows
    assert bd.back_adjust_rows(rows, None) is rows


def test_ex_dividend_gap_no_longer_breaks_ma():
    # 65 天持平在 100（可算 MA60），第 61 天除息參考價跌到 93（-7%），之後持平在 93。
    # 不還原的話，除息日當天收盤(93)會跌破用「原始價」算出的 MA5/10/20/60（都還停在 100 附近），
    # 造成假的「跌破均線」；還原後 MA 也一併下修到 93 附近，除息日不再誤判成破線。
    rows = []
    for i in range(60):
        rows.append(_row(f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}", 100, 101, 99, 100))
    ex_date = "2026-03-15"
    rows.append(_row(ex_date, 93, 94, 92, 93))
    for i in range(4):
        rows.append(_row(f"2026-04-{2 + i:02d}", 93, 94, 92, 93))
    events = [{"date": ex_date, "ratio": 0.93}]

    ind_adj = bd.compute_indicators(rows, [], events)
    ind_raw = bd.compute_indicators(rows, [], None)

    assert ind_adj is not None and ind_raw is not None
    # 現價/漲跌一律用原始成交價，還原與否都一樣（不影響顯示給使用者的現價）
    assert ind_adj["close"] == ind_raw["close"] == 93.0
    # 還原後價格序列前後一致(全 93)，MA 應緊貼收盤、幾乎沒有離散度 → 不會誤觸發糾結/黃金交叉假訊號
    assert ind_adj["ma5"] == ind_adj["ma10"] == ind_adj["ma20"]
    # 不還原時 MA 仍卡在還沒消化除息缺口的舊價位，跟收盤價 93 產生「假跌破」的落差
    assert ind_raw["ma20"] > ind_adj["ma20"]


def test_history_store_dividend_roundtrip():
    hist = {}
    hs.append_dividends(hist, {"2603": [{"date": "2026-06-17", "ratio": 0.9274}]})
    hs.append_dividends(hist, {"2603": [{"date": "2026-06-17", "ratio": 0.93}]})  # 同日覆蓋
    events = hs.to_div_events(hist["2603"])
    assert events == [{"date": "2026-06-17", "ratio": 0.93}]
    assert hs.to_div_events(hist.get("9999")) == []
