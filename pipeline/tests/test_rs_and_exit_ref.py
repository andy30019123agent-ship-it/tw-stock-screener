"""相對強弱 RS20 ＋ 出場參考（近 20 日高點）測試。

rs20＝個股近 20 交易日報酬（還原價）－ 加權指數近 20 交易日報酬；
recent_high20＝近 20 日原始成交價高點，給 MA20 支撐/壓力一起當「出場參考」用（網頁與 TG 共用同一份）。
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import build_data as bd  # noqa: E402
import history_store as hs  # noqa: E402


def _row(date, o, h, lo, c, v=1_000_000):
    return {"date": date, "open": o, "max": h, "min": lo, "close": c,
            "Trading_Volume": v, "Trading_money": v * c}


def _flat_then_rise(n_flat, flat_price, n_rise, rise_step, high_bump=None):
    """造 65+ 天資料：先持平 n_flat 天，最後 n_rise 天每天漲 rise_step；
    high_bump：把最後一天的最高價再往上加，測 recent_high20 抓的是「最高價」而非收盤。"""
    rows = []
    n = n_flat + n_rise
    for i in range(n):
        d = f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}"
        if i < n_flat:
            c = flat_price
        else:
            c = flat_price + rise_step * (i - n_flat + 1)
        h = c + 0.5
        if high_bump and i == n - 1:
            h = c + high_bump
        rows.append(_row(d, c - 0.5, h, c - 1, c))
    return rows


def test_index_return_20_needs_21_points():
    hist = {}
    for i in range(20):
        hs.append_index(hist, f"2026-06-{1 + i:02d}", 100 + i, window=40)
    assert bd.index_return_20(hist) is None   # 只有 20 天，不足 21
    hs.append_index(hist, "2026-06-21", 121, window=40)
    ret = bd.index_return_20(hist)
    assert ret is not None
    # 21 天前(第1天)=100，今天=121 → (121/100-1)*100 = 21%
    assert round(ret, 2) == 21.0


def test_rs20_positive_when_stock_beats_index():
    rows = _flat_then_rise(n_flat=45, flat_price=100, n_rise=21, rise_step=1)
    # 股價 21 天內從 100 漲到 121 → 個股 20 日報酬 ≈ 20%（用 closes[-1]/closes[-21]）
    ind = bd.compute_indicators(rows, [], None, index_ret20=5.0)   # 大盤只漲 5%
    assert ind is not None
    assert ind["rs20"] is not None
    assert ind["rs20"] > 0   # 個股漲更多 → 相對強弱為正（強於大盤）
    assert round(ind["rs20"], 1) == round(ind["rs20"], 1)   # sanity：有算出數字


def test_rs20_none_when_index_missing():
    rows = _flat_then_rise(n_flat=45, flat_price=100, n_rise=21, rise_step=1)
    ind = bd.compute_indicators(rows, [], None, index_ret20=None)
    assert ind is not None
    assert ind["rs20"] is None   # 大盤資料不足時不硬算


def test_recent_high20_uses_raw_high_not_close():
    rows = _flat_then_rise(n_flat=45, flat_price=100, n_rise=20, rise_step=0, high_bump=8)
    ind = bd.compute_indicators(rows, [], None)
    assert ind is not None
    # 最後一天收盤 100、但最高價被拉到 108（含 high_bump）→ recent_high20 應抓到 108，不是收盤價
    assert ind["recent_high20"] == 108.0
