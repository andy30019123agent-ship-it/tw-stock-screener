#!/usr/bin/env python3
"""偵測 bt_price.json 裡「不是真實漲跌」的單日巨幅跳動（分割/減資造成的假訊號）。

背景：TWT49U／exDailyQ 這兩個除權息端點涵蓋不到股票分割、現金減資——這類事件會讓
收盤價單日跳動 ±50% 以上（例：0050 分割 2025-06-18 −74%、2380 減資 2026-06-29 +279%），
回測若照單全收，會把這種假漲跌算進訊號的勝率與報酬統計，直接污染戰績。

規則式偵測：單日 |漲跌幅| 超過門檻（預設 40%），且當天/前一交易日查無對應除權息事件
（真除息通常跌不到 40%，但保留這道檢查避免誤殺極端除息案例）→ 判定為「價格斷點」。

刻意不做的事：不嘗試還原分割/減資的比例——規則五花八門（分割比例、減資退還比例都不固定）
還原容易做錯，不如老實列出「這天不能信」，回測直接排除樣本。

用法：python3 pipeline/price_breaks.py   # 讀 bt_price.json + dividends.json，寫 price_breaks.json
"""
import json
import os

import history_store as hs

HERE = os.path.dirname(__file__)
BT_PATH = os.path.join(HERE, "history", "bt_price.json")
DIV_PATH = os.path.join(HERE, "history", "dividends.json")
BREAKS_PATH = os.path.join(HERE, "history", "price_breaks.json")

THRESHOLD = 0.40  # 單日漲跌幅超過此比例視為可疑斷點


def detect_price_breaks(bt, div_hist, threshold=THRESHOLD):
    """掃 bt（bt_price.json 結構）找 (sid, date) 級的可疑斷點。回傳依日期排序的 list[dict]。

    每筆：sid、date（斷點發生日）、prev_date（前一個有資料的交易日）、
    prev_close、close、pct（漲跌幅，正負皆有）。
    """
    dates = bt.get("dates") or []
    breaks = []
    for sid, cols in (bt.get("stocks") or {}).items():
        if not cols or len(cols) < 4:
            continue
        c = cols[3]
        div_dates = {e["date"] for e in hs.to_div_events((div_hist or {}).get(sid))}
        prev_close, prev_date = None, None
        for i, d in enumerate(dates):
            close = c[i] if i < len(c) else None
            if close is None:
                continue
            if prev_close is not None and prev_close > 0:
                pct = (close - prev_close) / prev_close
                if abs(pct) > threshold and d not in div_dates and prev_date not in div_dates:
                    breaks.append({
                        "sid": sid, "date": d, "prev_date": prev_date,
                        "prev_close": prev_close, "close": close,
                        "pct": round(pct * 100, 1),
                    })
            prev_close, prev_date = close, d
    breaks.sort(key=lambda b: (b["date"], b["sid"]))
    return breaks


def load_breaks(path=BREAKS_PATH):
    """讀 price_breaks.json，回傳 {(sid, date)} 集合，給 is_broken() 查詢用。
    檔案不存在時回空集合（沒跑過偵測，不擋任何樣本，行為等同「還沒做這件事」）。"""
    data = hs.load(path)
    if not data:
        return set()
    return {(b["sid"], b["date"]) for b in data.get("breaks", [])}


def is_broken(breaks_set, sid, date):
    """查 (sid, date) 這天是不是已知的價格斷點（分割/減資造成的假漲跌）。"""
    return (sid, date) in breaks_set


def main():
    bt = hs.load(BT_PATH) or hs.bt_empty()
    div_hist = hs.load(DIV_PATH) or {}
    breaks = detect_price_breaks(bt, div_hist)
    out = {
        "threshold_pct": THRESHOLD * 100,
        "count": len(breaks),
        "breaks": breaks,
    }
    with open(BREAKS_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"), indent=None)
    print(f"✅ 偵測到 {len(breaks)} 筆可疑價格斷點 → {os.path.relpath(BREAKS_PATH)}")
    for b in breaks[:10]:
        print(f"   {b['sid']} {b['date']}：{b['prev_close']} → {b['close']}（{b['pct']:+.1f}%）")


if __name__ == "__main__":
    main()
