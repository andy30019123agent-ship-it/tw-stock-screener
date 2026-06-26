#!/usr/bin/env python3
"""一次性回填全市場歷史（OHLCV + 三大法人），之後改由每日累積維護。

- 上市 OHLCV：逐檔單股月表 STOCK_DAY 抓近 N 個月（~1000 檔 × N 請求，一次性較久、可續跑）。
- 上櫃 OHLCV：逐「交易日」抓 TPEX dailyQuotes（每日一支、全上櫃）。
- 三大法人：逐「交易日」抓 TWSE T86 + TPEX insti（留近 ~20 日）。

續跑：上市部分會跳過 price 歷史已足夠的股票；每 25 檔存一次檔。
用法：python3 backfill.py [--months 6] [--chip-days 20] [--sleep 0.6] [--limit N]
"""
import argparse
import datetime as dt
import os
import time

import history_store as hs
import market_sources as ms

HERE = os.path.dirname(__file__)
PRICE_PATH = os.path.join(HERE, "history", "price.json")
CHIP_PATH = os.path.join(HERE, "history", "chip.json")


def recent_months(n):
    today = dt.date.today()
    y, m, out = today.year, today.month, []
    for _ in range(n):
        out.append(f"{y}{m:02d}")
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return list(reversed(out))


def trading_days(months):
    """交易日清單＝FMTQIK（成交統計）各月的日期列（指數級端點、不受逐檔限流）。"""
    days = set()
    for ym in months:
        d = ms.get_json(f"{ms.TWSE_AT}/FMTQIK?date={ym}01&response=json")
        for r in d.get("data", []) or []:
            iso = ms.roc_to_iso(r[0])
            if iso:
                days.add(iso)
        time.sleep(0.3)
    return sorted(days)


def backfill_price_by_day(days, sleep, price):
    """逐交易日抓「全上市(MI_INDEX type=ALL)+全上櫃(TPEX dailyQuotes)」OHLCV，併入歷史。
    兩者皆「一請求一天、全市場」，快且不被限流。"""
    for i, day in enumerate(days, 1):
        try:
            hs.append_price(price, day, ms.fetch_listed_ohlc(day))
        except Exception as e:
            print(f"  ⚠️ 上市 {day} 失敗：{e}")
        try:
            hs.append_price(price, day, ms.fetch_otc_ohlc(day))
        except Exception as e:
            print(f"  ⚠️ 上櫃 {day} 失敗：{e}")
        time.sleep(sleep)
        if i % 20 == 0:
            hs.save(PRICE_PATH, price)
            print(f"  價格 {i}/{len(days)} 日")
    hs.save(PRICE_PATH, price)


def backfill_chip(days, sleep, chip):
    for i, day in enumerate(days, 1):
        try:
            hs.append_chip(chip, day, ms.fetch_listed_chip(day))
        except Exception as e:
            print(f"  ⚠️ 上市法人 {day} 失敗：{e}")
        try:
            hs.append_chip(chip, day, ms.fetch_otc_chip(day))
        except Exception as e:
            print(f"  ⚠️ 上櫃法人 {day} 失敗：{e}")
        time.sleep(sleep)
    hs.save(CHIP_PATH, chip)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=6)
    ap.add_argument("--chip-days", type=int, default=20)
    ap.add_argument("--sleep", type=float, default=0.5)
    args = ap.parse_args()

    months = recent_months(args.months)
    print(f"📅 月份：{months}")
    days = trading_days(months)
    print(f"   交易日 {len(days)} 天（{days[0]}~{days[-1]}）")

    price = hs.load(PRICE_PATH)
    chip = hs.load(CHIP_PATH)

    print("📈 回填全市場 OHLCV（逐日：上市 MI_INDEX + 上櫃 dailyQuotes）…")
    backfill_price_by_day(days[-hs.PRICE_WINDOW:], args.sleep, price)
    print("💰 回填三大法人（逐日：T86 + insti）…")
    backfill_chip(days[-args.chip_days:], args.sleep, chip)

    print(f"\n✅ 回填完成：price {len(price)} 檔、chip {len(chip)} 檔")


if __name__ == "__main__":
    main()
