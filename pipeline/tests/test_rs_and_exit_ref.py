"""相對強弱 RS20 ＋ 出場參考（近 20 日高點）測試。

rs20＝個股近 20 交易日報酬（還原價）－ 加權指數近 20 交易日報酬；兩序列各自轉成
{date: close} 後取「日期交集」對齊，用交集排序後最後 21 個共同交易日一起算（起訖日一致）。
交集不足 21 天則 rs20 為 None。這樣避免個股或指數其中一端缺資料（抓取失敗/停牌）時，
若用「位置對齊」（兩邊各自取最後 21 筆相除）會把不同天的價格錯配在一起、靜默算錯
（見 test_rs20_date_alignment_* 系列，示範位置對齊在缺資料時會算出明顯錯誤的數字）。

recent_high20＝近 20 日原始成交價高點，給 MA20 支撐/壓力一起當「出場參考」用（網頁與 TG 共用同一份）。
"""
import datetime as dt
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


def _iso(i, base=dt.date(2026, 1, 1)):
    """真實連續日曆日（i=0 起），確保 ISO 字串排序＝時間排序，日期交集比對才準。"""
    return (base + dt.timedelta(days=i)).isoformat()


def _stock_rows(n, close_fn):
    """造 n 天個股 price_rows，收盤價由 close_fn(i) 決定。"""
    rows = []
    for i in range(n):
        c = close_fn(i)
        rows.append(_row(_iso(i), c - 0.5, c + 0.5, c - 1, c))
    return rows


def _index_series(n, close_fn, skip=()):
    """造 index_series（見 history_store.to_index_series 的輸出格式：[(date, close), ...]）。
    skip 裡的 i 不產生該天資料，模擬指數某天抓不到/缺資料。"""
    return [(_iso(i), close_fn(i)) for i in range(n) if i not in skip]


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
    n = 90
    stock = _stock_rows(n, lambda i: 100 + i)                 # 個股：每天 +1
    index_series = _index_series(n, lambda i: 300 + 0.2 * i)  # 大盤：每天 +0.2，漲得比個股慢
    ind = bd.compute_indicators(stock, [], None, index_series=index_series)
    assert ind is not None
    assert ind["rs20"] is not None
    assert ind["rs20"] > 0   # 個股漲更多 → 相對強弱為正（強於大盤）


def test_rs20_none_when_index_missing():
    n = 90
    stock = _stock_rows(n, lambda i: 100 + i)
    ind = bd.compute_indicators(stock, [], None, index_series=None)
    assert ind is not None
    assert ind["rs20"] is None   # 沒有大盤序列時不硬算


def test_rs20_none_when_common_dates_below_21():
    """兩邊日期交集不足 21 天：即使兩邊各自都有 65+/21+ 筆資料，交集不夠也該回 None，不能硬湊。"""
    n = 90
    stock = _stock_rows(n, lambda i: 100 + i)
    # 指數只有最後 10 天有資料 → 跟個股（每天都有）的交集只有 10 個共同交易日，不足 21
    index_series = _index_series(n, lambda i: 300 + i, skip=[i for i in range(n) if i < n - 10])
    ind = bd.compute_indicators(stock, [], None, index_series=index_series)
    assert ind is not None
    assert ind["rs20"] is None


def test_rs20_date_alignment_stock_missing_last_day():
    """個股缺最後一天：若用「位置對齊」（兩邊各自取最後 21 筆相除），大盤那側會錯抓到個股沒有
    的那天；日期交集對齊則正確地把交集的最後 21 個共同交易日（即少了最後一天）拿來比較。"""
    n = 90
    # 大盤：i=0..88 全部平盤 300，只有最後一天（i=89，個股沒有這天）跳空到 600（模擬資料突波/失真）
    index_series = _index_series(n, lambda i: 600 if i == n - 1 else 300)
    # 個股：每天 +1，但缺最後一天 → 只給到 i=88
    stock = _stock_rows(n - 1, lambda i: 100 + i)

    ind = bd.compute_indicators(stock, [], None, index_series=index_series)
    assert ind is not None
    # 日期交集對齊（正確）：共同交易日排除 i=89 → 最後 21 天＝ i=68..88，大盤這段全平盤 300
    # → 大盤報酬 0%；個股 100+68=168 → 100+88=188 → 報酬 (188/168-1)*100 ≈ 11.90%；rs20 ≈ 11.90
    # （若用位置對齊：大盤自己「最後 21 筆」＝ i=69..89，會把跳空的 600 算進去，
    #  大盤報酬變成 (600/300-1)*100=100%，rs20 會被錯算成約 -88，天差地遠）
    assert round(ind["rs20"], 2) == 11.9


def test_rs20_date_alignment_index_missing_middle_day():
    """大盤缺中間一天：位置對齊時，個股（無缺資料）自己的「最後 21 筆」窗口，跟大盤因為少一天
    而往前多挪一天的窗口，起訖日並不一致；日期交集對齊則保證兩邊用同一組日期。"""
    n = 90
    # 個股：每天 +1，沒有缺資料；但第 i=68 天出現一次性資料異常（跳空到 500）
    stock = _stock_rows(n, lambda i: 500 if i == 68 else 100 + i)
    # 大盤：全程平盤 300，但中間第 75 天（交集視窗內、非頭尾）缺資料
    index_series = _index_series(n, lambda i: 300, skip=[75])

    ind = bd.compute_indicators(stock, [], None, index_series=index_series)
    assert ind is not None
    # 日期交集對齊（正確）：排除 i=75 後，最後 21 個共同交易日＝ {68..74, 76..89}，
    # 個股第 68 天的異常值(500)確實落在這個交集窗口內 → 個股報酬 (189/500-1)*100 = -62.2%；
    # 大盤全平盤 → 報酬 0%；rs20 = -62.2
    # （若用位置對齊：個股自己「最後 21 筆」是 69..89（不含 68，因為個股本身沒有缺資料，
    #  不會往前挪），完全漏看第 68 天的異常值，報酬變成 (189/169-1)*100≈11.83%，
    #  rs20 會被錯算成約 11.83，跟正確答案 -62.2 天差地遠）
    assert round(ind["rs20"], 2) == -62.2


def test_recent_high20_uses_raw_high_not_close():
    rows = _flat_then_rise(n_flat=45, flat_price=100, n_rise=20, rise_step=0, high_bump=8)
    ind = bd.compute_indicators(rows, [], None)
    assert ind is not None
    # 最後一天收盤 100、但最高價被拉到 108（含 high_bump）→ recent_high20 應抓到 108，不是收盤價
    assert ind["recent_high20"] == 108.0


# ── Phase C：暴走股旗標 ＋ 市場廣度（build_data）─────────────────────────
def _smooth(n, start=100.0, step=0.01):
    return [start + i * step for i in range(n)]


def test_runaway_flags_乖離分級():
    closes = _smooth(30)                       # 平滑上漲、波動極低 → 旗標由 bias 驅動
    assert bd.runaway_flags(closes, 0.05)["runaway_warn"] is False    # 乖離 5% 正常
    warn = bd.runaway_flags(closes, 0.20)      # 乖離 20% → 警示但非極端
    assert warn["runaway_warn"] is True and warn["runaway_extreme"] is False
    ext = bd.runaway_flags(closes, 0.30)       # 乖離 30% → 極端
    assert ext["runaway_extreme"] is True
    crash = bd.runaway_flags(closes, -0.20)    # 乖離 −20% → 暴跌警示（跟追高分開）
    assert crash["crash_warn"] is True and crash["runaway_warn"] is False


def test_runaway_flags_資料不足回False():
    r = bd.runaway_flags(_smooth(10), 0.30)    # <21 根 → 不硬算
    assert r["runaway_warn"] is False and r["rv20_pct"] is None


def test_market_breadth_綠與紅():
    green = [{"close": 110, "ma20": 100, "ret20_pct": 3.0} for _ in range(150)]
    g = bd.market_breadth(green)
    assert g["status"] == "green" and g["breadth20"] == 1.0
    red = [{"close": 90, "ma20": 100, "ret20_pct": -3.0} for _ in range(150)]
    assert bd.market_breadth(red)["status"] == "red"


def test_market_breadth_樣本不足回unknown():
    assert bd.market_breadth([{"close": 110, "ma20": 100, "ret20_pct": 1.0}] * 50)["status"] == "unknown"
