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
BT_WINDOW = 500      # 回測專用長歷史：約兩年交易日（見 bt_* 函式）
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


DIV_META_KEY = "__meta__"   # 保留鍵：sid 一律是數字代號，永不撞到


def set_div_coverage(hist, coverage_start, coverage_end):
    """記錄 dividends.json 的除權息回填涵蓋區間（哪段日期已經完整查過，不是「剛好沒事件」）。
    寫在跟 sid 同一層的保留鍵，讀取端（to_div_events 等）只會用 hist.get(sid) 存取，不受影響。"""
    hist[DIV_META_KEY] = {"coverage_start": coverage_start, "coverage_end": coverage_end}


def get_div_coverage(hist):
    """回 (coverage_start, coverage_end)；沒記錄過回 (None, None)。"""
    meta = (hist or {}).get(DIV_META_KEY) or {}
    return meta.get("coverage_start"), meta.get("coverage_end")


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


# ── 回測專用長歷史（bt_price.json）────────────────────────────────────
# 為什麼要另存一份：110 個交易日扣掉指標暖身 65 天、再扣 20 天持有期，真正能回測的只剩
# 約 25 天，而且全部落在同一段市況裡——樣本不足以判斷任何訊號的好壞。但把 price.json
# 直接拉長到兩年會變成 40MB+ 且每天 commit，repo 會迅速肥掉。
#
# 折衷：另存一份「欄式、精簡」的長歷史，只給回測用：
#   1. 全域共用一份 dates 陣列 —— 原格式每檔股票都重複存一次日期字串，光日期就佔 1/4。
#   2. 丟掉成交金額（只有 avg_money_e 用得到，回測不需要）。
#   3. 成交量改存「張」的整數（30386718 股 → 30386 張），位數少一半。
#   4. 只收有基本流動性的股票（殭屍股回測本來就會被 BACKTEST_MIN_VOL 濾掉）。
# 實測：110 天從 11.9MB 降到 4.6MB；500 天約 17.9MB、git 內約 5.2MB。
#
# 維護方式：**不是每天寫**，而是每週重算權重時，從 price.json 把新出現的日期併進來
# （price.json 保有 110 天，遠大於一週，不會漏接）。初始資料由 backfill_bt.py 一次性補齊。

BT_MIN_AVG_LOTS = 200   # 收錄門檻：期間平均量（張）。低於此的殭屍股不進長歷史


def bt_empty():
    return {"dates": [], "stocks": {}}


def bt_merge_days(bt, day_rows, window=BT_WINDOW):
    """把 {date_iso: {sid: row}} 併入長歷史（同日覆蓋），並修剪到 window 天。

    row 吃 append_price 那套（open/max/min/close/Trading_Volume）。回傳併入的天數。
    欄式儲存的代價是「插入一天要動到每檔的陣列」，所以這裡一次併多天再重建，不逐日重寫。
    """
    if not day_rows:
        return 0
    # 先攤平成 {sid: {date: [o,h,l,c,vol_lots]}}，跟既有內容合併後再重建欄式結構
    flat = {}
    dates_old = bt.get("dates") or []
    for sid, cols in (bt.get("stocks") or {}).items():
        o, h, l, c, v = cols
        d = {}
        for i, dt_iso in enumerate(dates_old):
            if c[i] is not None:
                d[dt_iso] = [o[i], h[i], l[i], c[i], v[i]]
        flat[sid] = d

    added = 0
    for date_iso, ohlc_map in day_rows.items():
        added += 1
        for sid, r in ohlc_map.items():
            flat.setdefault(sid, {})[date_iso] = [
                round(r["open"], 2), round(r["max"], 2), round(r["min"], 2),
                round(r["close"], 2), int((r.get("Trading_Volume") or 0) // 1000),
            ]

    dates = sorted({d for v in flat.values() for d in v})[-window:]
    keep = set(dates)
    idx = {d: i for i, d in enumerate(dates)}
    n = len(dates)

    stocks = {}
    for sid, by_date in flat.items():
        rows = {d: r for d, r in by_date.items() if d in keep}
        if not rows:
            continue
        # 流動性門檻：整段期間平均量太低就不收（省空間，回測本來也會濾掉）
        if sum(r[4] for r in rows.values()) / len(rows) < BT_MIN_AVG_LOTS:
            continue
        cols = [[None] * n for _ in range(5)]
        for d, r in rows.items():
            i = idx[d]
            for j in range(5):
                cols[j][i] = r[j]
        stocks[sid] = cols

    bt["dates"] = dates
    bt["stocks"] = stocks
    return added


def bt_merge_from_price(bt, price_hist, window=BT_WINDOW):
    """把 price.json（滾動 110 天）裡「長歷史還沒有」的日期併進來。每週跑一次即可——
    price.json 的視窗遠大於一週，不會漏接。回傳併入天數。"""
    have = set(bt.get("dates") or [])
    day_rows = {}
    for sid, by_date in price_hist.items():
        for d, r in by_date.items():
            if d in have:
                continue
            day_rows.setdefault(d, {})[sid] = {
                "open": r[0], "max": r[1], "min": r[2], "close": r[3],
                "Trading_Volume": r[4],
            }
    return bt_merge_days(bt, day_rows, window)


def bt_to_price_hist(bt):
    """還原成 price.json 那種 {sid: {date: [o,h,l,c,vol股,money元]}}，讓回測不必改讀法。
    成交金額補 0——回測用不到（avg_money_e 只影響顯示）。"""
    dates = bt.get("dates") or []
    out = {}
    for sid, cols in (bt.get("stocks") or {}).items():
        o, h, l, c, v = cols
        d = {}
        for i, dt_iso in enumerate(dates):
            if c[i] is None:
                continue
            d[dt_iso] = [o[i], h[i], l[i], c[i], (v[i] or 0) * 1000, 0]
        if d:
            out[sid] = d
    return out
