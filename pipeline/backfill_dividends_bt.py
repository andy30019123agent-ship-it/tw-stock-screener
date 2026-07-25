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
    # 邊界驗證（2026-07-25 Codex 指出）：chunk_months=0 會讓 month_chunks 無限迴圈；
    # start>end 會零工作量卻印出成功訊息，看起來像補完了。
    if args.chunk_months < 1:
        raise SystemExit("❌ --chunk-months 必須 ≥1（0 會無限迴圈）")
    if start_iso > end_iso:
        raise SystemExit(f"❌ 起日晚於迄日（{start_iso} > {end_iso}），沒有任何區間可補")

    print(f"📅 回填除權息事件區間：{start_iso} ~ {end_iso}")
    chunks = month_chunks(start_iso, end_iso, args.chunk_months)
    print(f"   切成 {len(chunks)} 段（每段 ~{args.chunk_months} 個月）")

    div_hist = hs.load(DIV_PATH) or {}
    prev_start, prev_end = hs.get_div_coverage(div_hist)
    if prev_start:
        print(f"   既有涵蓋範圍：{prev_start} ~ {prev_end}")

    total_events, total_sids = 0, set()
    # 🔑 涵蓋範圍只能推進到「連續成功」的最後一段。抓取失敗或回 0 筆就停止推進——
    # 否則會標成「這段查過了」但其實是空的，正是本檔開頭警告的「看起來成功但有空洞」。
    # 台股 2 個月區間幾乎不可能真的一筆除權息都沒有（7~8 月更是除息旺季），回 0 筆要當異常看。
    covered_until = None      # 連續成功推進到哪
    holes = []                # 有疑問的區間，最後一次列出來
    for i, (cs, ce) in enumerate(chunks, 1):
        ok = True
        src = {}
        try:
            # 🔑 2026-07-25 Codex 指出：兩個市場的例外在 fetch 內各自被吞掉，只要一邊成功外層
            # 就看不出另一邊掛了 → 會把「缺半個市場」的區間標成完整涵蓋。要逐來源檢查。
            events = ms.fetch_ex_dividend_events(cs, ce, sources_ok=src)
        except Exception as e:
            print(f"  ⚠️ {cs}~{ce} 抓取失敗：{e}")
            events, ok = {}, False
        if ok and not (src.get("listed") and src.get("otc")):
            missing = [k for k in ("listed", "otc") if not src.get(k)]
            print(f"  ⚠️ {cs}~{ce} 有市場抓取失敗（{'、'.join(missing)}）——不可視為已涵蓋")
            ok = False
        n = sum(len(v) for v in events.values())
        if ok and n == 0:
            print(f"  ⚠️ {cs}~{ce} 回 0 筆——2 個月完全沒有除權息不合常理，很可能是被限流回空")
            ok = False
        total_events += n
        total_sids |= set(events.keys())
        hs.append_dividends(div_hist, events)   # 有抓到多少就存多少（只加不覆蓋既有）
        print(f"   [{i}/{len(chunks)}] {cs}~{ce}：{n} 筆事件、{len(events)} 檔")
        if not ok:
            holes.append(f"{cs}~{ce}")
        elif not holes:
            covered_until = ce   # 只在「從頭到這裡都成功」時推進；出現過洞就不再往後標
        hs.save(DIV_PATH, div_hist)
        if i < len(chunks):
            time.sleep(args.sleep)

    # 起日：跟既有涵蓋取聯集的較早者（既有若是 2026-01，補完 2024-08 後應該記成 2024-08）。
    # 迄日**不可縮短**（2026-07-25 Codex 指出）：重跑一段較早的區間時，covered_until 會是那段的
    # 結尾，若直接寫入就把既有更晚的涵蓋範圍往前縮＝謊報「後面那段沒查過」。
    if covered_until:
        new_start = min(prev_start, start_iso) if prev_start else start_iso
        new_end = max(prev_end, covered_until) if prev_end else covered_until
        hs.set_div_coverage(div_hist, new_start, new_end)
        hs.save(DIV_PATH, div_hist)

    print(f"\n{'⚠️ 部分區間有問題' if holes else '✅'} 回填：{total_events} 筆除權息事件、{len(total_sids)} 檔")
    print(f"   已標記涵蓋：{hs.get_div_coverage(div_hist)}")
    if holes:
        print(f"   🚨 這些區間沒抓到東西，涵蓋範圍不會推進過去，請重跑：{', '.join(holes)}")
        raise SystemExit(1)   # 讓 workflow 紅燈，不要以為補完了


if __name__ == "__main__":
    main()
