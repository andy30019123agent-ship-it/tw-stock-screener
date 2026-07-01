#!/usr/bin/env python3
"""每日累積：抓「最新交易日」全市場 OHLCV + 三大法人，append 進歷史檔。

回填(backfill.py)建好初始歷史後，之後每天只需跑這支（最新一日、幾個請求）。
排程在收盤後跑，資料已齊。歷史每天由 workflow commit 回 main 保存。
"""
import datetime as dt
import os

import history_store as hs
import market_sources as ms

HERE = os.path.dirname(__file__)
PRICE_PATH = os.path.join(HERE, "history", "price.json")
CHIP_PATH = os.path.join(HERE, "history", "chip.json")


def main():
    date_iso, listed = ms.fetch_listed_ohlc_latest()   # 最新交易日 + 全上市
    print(f"📅 最新交易日 {date_iso}：上市 {len(listed)} 檔")
    # 抓不到最新交易日（TWSE 偶爾會擋 runner IP、或收盤資料未出）→ 優雅跳過本次累積，
    # 用現有歷史繼續 build+部署，不讓整個流程崩掉；下次排程 TWSE 恢復後自動補上。
    if not date_iso or not listed:
        print("  ⚠️ 上市最新交易日抓不到 → 跳過本次累積，用現有歷史繼續建置。")
        return
    otc = ms.fetch_otc_ohlc(date_iso)
    print(f"   上櫃 {len(otc)} 檔")

    price = hs.load(PRICE_PATH)
    hs.append_price(price, date_iso, listed)
    hs.append_price(price, date_iso, otc)
    hs.save(PRICE_PATH, price)

    chip = hs.load(CHIP_PATH)
    try:
        hs.append_chip(chip, date_iso, ms.fetch_listed_chip(date_iso))
    except Exception as e:
        print(f"  ⚠️ 上市法人 {date_iso} 失敗：{e}")
    try:
        hs.append_chip(chip, date_iso, ms.fetch_otc_chip(date_iso))
    except Exception as e:
        print(f"  ⚠️ 上櫃法人 {date_iso} 失敗：{e}")
    hs.save(CHIP_PATH, chip)

    print(f"✅ 已累積 {date_iso}：price {len(price)} 檔、chip {len(chip)} 檔")


if __name__ == "__main__":
    main()
