#!/usr/bin/env python3
"""每日累積：抓「最新交易日」全市場 OHLCV + 三大法人，append 進歷史檔。

回填(backfill.py)建好初始歷史後，之後每天只需跑這支（最新一日、幾個請求）。
排程在收盤後跑，資料已齊。歷史每天由 workflow commit 回 main 保存。
之後接著跑 gap_backfill.safe_run：對照官方交易日清單補「過去漏抓的日子」（見 gap_backfill.py）。
"""
import argparse
import datetime as dt
import json
import os

import history_store as hs
import market_sources as ms

HERE = os.path.dirname(__file__)
PRICE_PATH = os.path.join(HERE, "history", "price.json")
CHIP_PATH = os.path.join(HERE, "history", "chip.json")
DIV_PATH = os.path.join(HERE, "history", "dividends.json")
INDEX_PATH = os.path.join(HERE, "history", "index.json")
FETCH_STATE_PATH = os.path.join(HERE, "fetch_state.json")
MIN_OTC_ROWS_TODAY = 300   # 同 gap_backfill.MIN_OTC_ROWS（正常約 860 檔）；這裡不 import 回補模組，免得它壞了連帶擋每日累積


def write_fetch_state(ok):
    """記下這次「抓最新交易日」成功與否，給 build_data.py 併進 screener.json，
    讓前端的資料過期警告有依據（而不是只能默默沿用舊資料、卻顯示「剛剛更新」）。"""
    state = {"ok": ok, "checked_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M")}
    with open(FETCH_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)


def today_taipei():
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("Asia/Taipei")).date().isoformat()
    except Exception:   # 沒有時區資料庫：UTC+8 固定位移
        return (dt.datetime.utcnow() + dt.timedelta(hours=8)).date().isoformat()


def check_stale(date_iso, today=None, fetch_month=None):
    """官方端點回的「最新交易日」比今天舊時，查官方交易日清單（FMTQIK 當月）：今天有開盤＝資料過期。
    回 (stale, {ym: 交易日清單})；後者交給漏抓回補沿用、不重打。
    為什麼要查：2026-08-19 STOCK_DAY_ALL 回的其實是 08-17 的資料，照樣標 fetch_ok=True，前端就把舊資料
    當新的顯示（commit 19218f5c2）。只看「抓到的日期 < 今天」會誤判週末／假日／盤中手動觸發——
    FMTQIK 只在當天收盤資料出來後才列出今天，所以盤中、假日都不會被判過期。清單抓不到＝不知道，不判過期。"""
    today = today or today_taipei()
    if not date_iso or date_iso >= today:
        return False, {}
    ym = today[:4] + today[5:7]
    try:
        with ms.http_limits(20, 10, 1):   # 跟回補同一組短逾時：最壞約 32 秒，不拖累每日流程
            days = (fetch_month or ms.fetch_trading_days_month)(ym) or {}
    except Exception as e:
        print(f"  ⚠️ 查官方交易日清單 {ym} 失敗（{e}）→ 無法確認今天有沒有開盤，不標過期")
        return False, {}
    if today in days:
        print(f"  ⚠️ 官方清單顯示今天 {today} 有開盤，但抓到的最新資料仍是 {date_iso} → 標記「資料可能未更新」")
        return True, {ym: days}
    return False, {ym: days}


def update_latest():
    """回 {ym: 交易日清單}（判斷過期時順手抓到的當月 FMTQIK，給回補沿用；沒抓就是 {}）。"""
    # 抓最新交易日：TWSE 偶爾會擋 runner IP、收盤資料未出、或「連線逾時」→ 一律優雅跳過本次
    # 累積，用現有歷史繼續 build+部署，不讓整個流程崩掉；下次排程 TWSE 恢復後自動補上。
    # ⚠️ 逾時是「raise 例外」（非回空），一定要 try 起來——否則例外會在下面的空值檢查之前
    #    就炸掉，連帶擋掉整包部署（含跟資料無關的前端改動）。2026-07-24 踩過一次。
    try:
        date_iso, listed = ms.fetch_listed_ohlc_latest()   # 最新交易日 + 全上市
    except Exception as e:
        print(f"  ⚠️ 抓最新交易日失敗（{e}）→ 跳過本次累積，用現有歷史繼續建置。")
        write_fetch_state(False)
        return {}
    # 空值檢查要在 len() 之前——fetch 若回 (None, None) 不丟例外，len(None) 會炸（Codex 2026-07-24 指出）。
    if not date_iso or not listed:
        print("  ⚠️ 上市最新交易日抓不到 → 跳過本次累積，用現有歷史繼續建置。")
        write_fetch_state(False)
        return {}
    print(f"📅 最新交易日 {date_iso}：上市 {len(listed)} 檔")
    # 上櫃也要包起來：TPEX 逾時同樣會炸整包部署（跟上市同一類雷）。失敗就整次降級、不寫「只有
    # 上市」的半套資料（避免上市新/上櫃舊卻標 fetch_ok=True 誤導前端）；下次排程自動補上。
    try:
        otc = ms.fetch_otc_ohlc(date_iso)
    except Exception as e:
        print(f"  ⚠️ 上櫃 {date_iso} 抓取失敗（{e}）→ 跳過本次累積（避免上市/上櫃不一致），用現有歷史繼續。")
        write_fetch_state(False)
        return {}
    print(f"   上櫃 {len(otc)} 檔")
    stale, prefetched = check_stale(date_iso)
    # 上櫃回空（沒丟例外）時下面仍只寫上市（維持原行為；漏抓回補會分市場判斷、隔天補上上櫃），
    # 但不能再標 fetch_ok=True——前端會以為兩個市場都是新的。
    otc_short = len(otc) < MIN_OTC_ROWS_TODAY
    if otc_short:
        print(f"  ⚠️ 上櫃只有 {len(otc)} 檔（<{MIN_OTC_ROWS_TODAY}）→ 標記「資料可能未更新」，漏抓回補下次會補上櫃")

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

    # 除權息事件（技術指標還原權息用）：每天併入當天，累積成完整事件史
    div_hist = hs.load(DIV_PATH)
    try:
        events = ms.fetch_ex_dividend_events(date_iso, date_iso)
        hs.append_dividends(div_hist, events)
        hs.save(DIV_PATH, div_hist)
        n = sum(len(v) for v in events.values())
        if n:
            print(f"   除權息事件 {n} 筆")
    except Exception as e:
        print(f"  ⚠️ 除權息事件 {date_iso} 抓取失敗：{e}")

    # 加權指數收盤（相對強弱 RS 計算用大盤基準）
    index_hist = hs.load(INDEX_PATH)
    try:
        hs.append_index(index_hist, date_iso, ms.fetch_taiex_close(date_iso))
        hs.save(INDEX_PATH, index_hist)
    except Exception as e:
        print(f"  ⚠️ 加權指數 {date_iso} 抓取失敗：{e}")

    write_fetch_state(not (stale or otc_short))
    print(f"✅ 已累積 {date_iso}：price {len(price)} 檔、chip {len(chip)} 檔、dividends {len(div_hist)} 檔、index {len(index_hist)} 天")
    return prefetched


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill-dates", default=os.environ.get("BACKFILL_DATES", ""),
                    help="手動回補日期：2026-08-18:2026-08-20 或逗號分隔（workflow 走 env BACKFILL_DATES）")
    args = ap.parse_args(argv)
    prefetched = update_latest() or {}
    # 漏抓交易日回補（2026-11-13）：不論上面成功或降級都跑——它補的是「過去」的洞，跟今天
    # 抓不抓得到無關。safe_run 保證任何失敗都不往外丟，不會擋到後面的 build／部署／TG。
    # 在這裡才 import 並包起來：回補模組本身 import 失敗（語法錯、缺檔）也不能讓每日累積掛掉。
    try:
        import gap_backfill
    except Exception as e:   # noqa: BLE001
        print(f"::warning::漏抓回補模組載入失敗（今天的更新不受影響，但沒有做回補）：{type(e).__name__}: {e}")
        return
    gap_backfill.safe_run(args.backfill_dates, prefetched_months=prefetched)


if __name__ == "__main__":
    main()
