"""全市場歷史累積（取代 FinMind 的逐檔歷史）。

每天把全市場快照 append 進歷史，rolling 保留固定視窗；算指標時還原成
compute_indicators 吃的 row 格式。歷史檔每天 commit 回 repo 保存（runner 會清空）。

結構（緊湊、以日期為鍵自動去重）：
  price[sid] = { "YYYY-MM-DD": [open, high, low, close, volume股, money元], ... }
  chip[sid]  = { "YYYY-MM-DD": [foreign_net股, trust_net股], ... }
  index      = { "YYYY-MM-DD": close, ... }   （加權指數，單一序列、無 sid 這層）
"""
import json
import os

PRICE_WINDOW = 110   # 算 MA60 + 突破回看需 ~65+，留 110 個交易日緩衝
CHIP_WINDOW = 20     # 連續買超天數判斷，留 20 個交易日
DIV_WINDOW = 130     # 除權息事件視窗（曆日），稍寬於 PRICE_WINDOW 防止邊界漏接


def load(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save(path, hist):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, separators=(",", ":"))


def _prune(by_date, window):
    if len(by_date) > window:
        for k in sorted(by_date)[:-window]:
            del by_date[k]


def append_price(hist, date_iso, ohlc_map, window=PRICE_WINDOW):
    """把某交易日的全市場 OHLCV（{sid: row}）併入歷史。同日覆蓋、超窗修剪。"""
    for sid, r in ohlc_map.items():
        d = hist.setdefault(sid, {})
        d[date_iso] = [r["open"], r["max"], r["min"], r["close"],
                       r["Trading_Volume"], r["Trading_money"]]
        _prune(d, window)


def append_chip(hist, date_iso, chip_map, window=CHIP_WINDOW):
    """把某交易日的全市場三大法人（{sid: {Foreign_Investor, Investment_Trust}}）併入歷史。"""
    for sid, c in chip_map.items():
        d = hist.setdefault(sid, {})
        d[date_iso] = [c.get("Foreign_Investor", 0), c.get("Investment_Trust", 0)]
        _prune(d, window)


def append_dividends(hist, events_by_sid, window=DIV_WINDOW):
    """把一批除權息事件（{sid: [{date, ratio}, ...]}）併入歷史（同股同日覆蓋、超窗修剪）。"""
    for sid, evs in events_by_sid.items():
        d = hist.setdefault(sid, {})
        for e in evs:
            d[e["date"]] = e["ratio"]
        _prune(d, window)


def to_div_events(stock_hist):
    """還原成 compute_indicators 吃的除權息事件 list（依日期排序）。"""
    if not stock_hist:
        return []
    return [{"date": d, "ratio": stock_hist[d]} for d in sorted(stock_hist)]


def to_price_rows(stock_hist):
    """還原成 compute_indicators 吃的 price_rows（依日期排序）。"""
    rows = []
    for date in sorted(stock_hist):
        o, h, lo, c, v, m = stock_hist[date]
        rows.append({"date": date, "open": o, "max": h, "min": lo, "close": c,
                     "Trading_Volume": v, "Trading_money": m})
    return rows


def append_index(hist, date_iso, value, window=PRICE_WINDOW):
    """把單一數值（如加權指數收盤）併入以日期為鍵的歷史（同日覆蓋、超窗修剪）。value 為 None
    （非交易日抓不到）時不動歷史，跟其他 fetch 失敗時的處理一致。"""
    if value is None:
        return
    hist[date_iso] = value
    _prune(hist, window)


def to_index_series(hist):
    """還原成 [(日期, 值), ...]，依日期排序（RS20 等報酬計算用）。"""
    return [(d, hist[d]) for d in sorted(hist)]


def to_chip_rows(stock_hist):
    """還原成 compute_indicators 吃的 chip_rows（每日兩列：外資、投信；net 放 buy、sell=0）。"""
    rows = []
    for date in sorted(stock_hist):
        f, t = stock_hist[date]
        rows.append({"date": date, "name": "Foreign_Investor", "buy": f, "sell": 0})
        rows.append({"date": date, "name": "Investment_Trust", "buy": t, "sell": 0})
    return rows
