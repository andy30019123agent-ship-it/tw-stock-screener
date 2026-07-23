#!/usr/bin/env python3
"""一次性補齊「回測專用長歷史」bt_price.json（約兩年交易日的 OHLCV）。

為什麼需要：線上用的 price.json 只滾動保留 110 個交易日，扣掉指標暖身 65 天與 20 天
持有期後，真正能回測的只剩約 25 天，而且全部落在同一段市況裡——這種樣本量下，任何
訊號的勝率都不足以當證據（2026-07-23 實測就踩到這個坑：破底翻在該區間絕對勝率 59.7%，
換成超額報酬其實是 −2.02pp）。

抓法：逐「交易日」各一次請求拿全市場，不逐檔打 API。
  - 交易日清單：TWSE FMTQIK（成交統計，每月一次請求）
  - 上市 OHLCV：TWSE MI_INDEX?type=ALL（一次一天、全上市）
  - 上櫃 OHLCV：TPEX dailyQuotes（一次一天、全上櫃）

🚨 **一定要在 GitHub Actions 跑，不要在本機跑**：TWSE 對本機連續快速請求會限流回空，
   歷史會補成一堆空洞（這條教訓寫在專案記憶檔裡，踩過一次了）。

可續跑：已存在的日期直接跳過，中途中斷再跑一次即可接上。每 20 天存一次檔。

用法：python3 pipeline/backfill_bt.py [--months 24] [--sleep 0.8]
"""
import argparse
import os
import time

import history_store as hs
import market_sources as ms
from backfill import recent_months, trading_days

HERE = os.path.dirname(__file__)
BT_PATH = os.path.join(HERE, "history", "bt_price.json")
SAVE_EVERY = 20


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=24, help="往回補幾個月（預設 24）")
    ap.add_argument("--sleep", type=float, default=0.8, help="每個請求之間的間隔秒數")
    ap.add_argument("--limit", type=int, default=0, help="最多補幾天（0=不限，除錯用）")
    args = ap.parse_args()

    bt = hs.load(BT_PATH) or hs.bt_empty()
    have = set(bt.get("dates") or [])
    print(f"📦 長歷史現況：{len(have)} 個交易日、{len(bt.get('stocks') or {})} 檔")

    print(f"📅 取得近 {args.months} 個月的交易日清單…")
    days = trading_days(recent_months(args.months))
    todo = [d for d in days if d not in have][-hs.BT_WINDOW:]
    if args.limit:
        todo = todo[-args.limit:]
    print(f"   共 {len(days)} 個交易日，待補 {len(todo)} 天")
    if not todo:
        print("✅ 已是最新，無需補齊。")
        return

    pending, done, failed = {}, 0, []
    for d in todo:
        try:
            listed = ms.fetch_listed_ohlc(d)
            time.sleep(args.sleep)
            otc = ms.fetch_otc_ohlc(d)
            time.sleep(args.sleep)
        except Exception as e:                      # 單日失敗不中斷整批，記下來最後回報
            failed.append((d, str(e)[:60]))
            continue
        # 兩邊都空 → 多半是被限流或當天沒開盤，記為失敗不要寫進去（寧可缺，不要寫錯）
        if not listed and not otc:
            failed.append((d, "兩市場都回空（限流或非交易日）"))
            continue
        merged = dict(listed)
        merged.update(otc)
        pending[d] = merged
        done += 1
        if len(pending) >= SAVE_EVERY:
            hs.bt_merge_days(bt, pending)
            hs.save(BT_PATH, bt)
            pending = {}
            print(f"   …已補 {done}/{len(todo)} 天（{d}），檔案 {os.path.getsize(BT_PATH)/1e6:.1f}MB")

    if pending:
        hs.bt_merge_days(bt, pending)
        hs.save(BT_PATH, bt)

    size = os.path.getsize(BT_PATH) / 1e6 if os.path.exists(BT_PATH) else 0
    print(f"\n✅ 補齊 {done} 天 → 長歷史共 {len(bt['dates'])} 個交易日、"
          f"{len(bt['stocks'])} 檔、{size:.1f}MB")
    if failed:
        print(f"⚠️ {len(failed)} 天抓取失敗（再跑一次會自動重試）：")
        for d, why in failed[:10]:
            print(f"   {d} {why}")


if __name__ == "__main__":
    main()
