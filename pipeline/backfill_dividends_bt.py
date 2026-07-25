#!/usr/bin/env python3
"""一次性補齊「回測長歷史」同期間的除權息事件（dividends.json）。

背景：bt_price.json 兩年回測歷史從 2024-08-01 開始，但 dividends.json 的除權息事件
一直到 2026-01-13 才有第一筆——代表前面約 350 個交易日的除息/除權全部被回測當成
「真實下跌」，直接污染所有訊號的勝率與權重（daily_update.py 每天只累積「今天」的
事件，從沒有回頭補過歷史）。

抓法：TWSE TWT49U + TPEX exDailyQ 都吃日期區間、一次全市場，但區間太長怕被截斷，
所以逐「月」分批查（一次抓一整年份的實測：2 個月一次查沒問題，見開發時的驗證）。

🚨 **一定要在 GitHub Actions 跑，不要在本機跑**：跟 backfill_bt.py 同一條鐵律，本機
   連續打 TWSE 會被限流回空，補出「看起來成功但其實有空洞」的資料。

可續跑：dividends.json 用「同股同日覆蓋」合併，重跑不會重複；跑完會把
coverage_start/coverage_end 寫回 dividends.json，讓下游知道「這段日期已經查過」
（不是没東西才是空的，是還沒查）。

用法：python3 pipeline/backfill_dividends_bt.py [--start 2024-08-01] [--end 2026-07-24]
      [--chunk-months 2] [--sleep 1.0]
     不給 --start/--end 時預設吃 bt_price.json 的 dates[0]~dates[-1]。
"""
import argparse
import datetime as dt
import os
import time

import history_store as hs
import market_sources as ms

HERE = os.path.dirname(__file__)
BT_PATH = os.path.join(HERE, "history", "bt_price.json")
DIV_PATH = os.path.join(HERE, "history", "dividends.json")


def month_chunks(start_iso, end_iso, chunk_months=2):
    """把 [start_iso, end_iso] 切成連續、不重疊的月份區間（每段約 chunk_months 個月）。"""
    start = dt.date.fromisoformat(start_iso)
    end = dt.date.fromisoformat(end_iso)
    out = []
    cur = dt.date(start.year, start.month, 1)
    while cur <= end:
        y, m = cur.year, cur.month + chunk_months
        y += (m - 1) // 12
        m = (m - 1) % 12 + 1
        nxt = dt.date(y, m, 1)
        chunk_start = max(cur, start)
        chunk_end = min(nxt - dt.timedelta(days=1), end)
        if chunk_start <= chunk_end:
            out.append((chunk_start.isoformat(), chunk_end.isoformat()))
        cur = nxt
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=None, help="回填起日（預設吃 bt_price.json dates[0]）")
    ap.add_argument("--end", default=None, help="回填迄日（預設吃 bt_price.json dates[-1]）")
    ap.add_argument("--chunk-months", type=int, default=2, help="每次查詢的月數區間")
    ap.add_argument("--sleep", type=float, default=1.0, help="每個區間查詢間的間隔秒數")
    args = ap.parse_args()

    bt = hs.load(BT_PATH) or hs.bt_empty()
    dates = bt.get("dates") or []
    start_iso = args.start or (dates[0] if dates else None)
    end_iso = args.end or (dates[-1] if dates else None)
    if not start_iso or not end_iso:
        raise SystemExit("❌ 沒有可用的日期區間：bt_price.json 是空的，且未指定 --start/--end")

    print(f"📅 回填除權息事件區間：{start_iso} ~ {end_iso}")
    chunks = month_chunks(start_iso, end_iso, args.chunk_months)
    print(f"   切成 {len(chunks)} 段（每段 ~{args.chunk_months} 個月）")

    div_hist = hs.load(DIV_PATH) or {}
    prev_start, prev_end = hs.get_div_coverage(div_hist)
    if prev_start:
        print(f"   既有涵蓋範圍：{prev_start} ~ {prev_end}")

    total_events, total_sids = 0, set()
    for i, (cs, ce) in enumerate(chunks, 1):
        try:
            events = ms.fetch_ex_dividend_events(cs, ce)
        except Exception as e:
            print(f"  ⚠️ {cs}~{ce} 抓取失敗：{e}")
            events = {}
        n = sum(len(v) for v in events.values())
        total_events += n
        total_sids |= set(events.keys())
        hs.append_dividends(div_hist, events)
        print(f"   [{i}/{len(chunks)}] {cs}~{ce}：{n} 筆事件、{len(events)} 檔")
        # 涵蓋範圍隨進度往前推，就算中途中斷也知道「已經查到哪」
        new_start = min(prev_start, start_iso) if prev_start else start_iso
        hs.set_div_coverage(div_hist, new_start, ce)
        hs.save(DIV_PATH, div_hist)
        if i < len(chunks):
            time.sleep(args.sleep)

    print(f"\n✅ 回填完成：{total_events} 筆除權息事件、{len(total_sids)} 檔（本次查詢涵蓋的區間）")
    print(f"   dividends.json coverage：{hs.get_div_coverage(div_hist)}")


if __name__ == "__main__":
    main()
