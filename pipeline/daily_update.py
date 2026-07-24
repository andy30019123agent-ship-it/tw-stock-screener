#!/usr/bin/env python3
"""每日累積：抓「最新交易日」全市場 OHLCV + 三大法人，append 進歷史檔。

回填(backfill.py)建好初始歷史後，之後每天只需跑這支（最新一日、幾個請求）。
排程在收盤後跑，資料已齊。歷史每天由 workflow commit 回 main 保存。
"""
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


def write_fetch_state(ok):
    """記下這次「抓最新交易日」成功與否，給 build_data.py 併進 screener.json，
    讓前端的資料過期警告有依據（而不是只能默默沿用舊資料、卻顯示「剛剛更新」）。"""
    state = {"ok": ok, "checked_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M")}
    with open(FETCH_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)


def main():
    # 抓最新交易日：TWSE 偶爾會擋 runner IP、收盤資料未出、或「連線逾時」→ 一律優雅跳過本次
    # 累積，用現有歷史繼續 build+部署，不讓整個流程崩掉；下次排程 TWSE 恢復後自動補上。
    # ⚠️ 逾時是「raise 例外」（非回空），一定要 try 起來——否則例外會在下面的空值檢查之前
    #    就炸掉，連帶擋掉整包部署（含跟資料無關的前端改動）。2026-07-24 踩過一次。
    try:
        date_iso, listed = ms.fetch_listed_ohlc_latest()   # 最新交易日 + 全上市
    except Exception as e:
        print(f"  ⚠️ 抓最新交易日失敗（{e}）→ 跳過本次累積，用現有歷史繼續建置。")
        write_fetch_state(False)
        return
    # 空值檢查要在 len() 之前——fetch 若回 (None, None) 不丟例外，len(None) 會炸（Codex 2026-07-24 指出）。
    if not date_iso or not listed:
        print("  ⚠️ 上市最新交易日抓不到 → 跳過本次累積，用現有歷史繼續建置。")
        write_fetch_state(False)
        return
    print(f"📅 最新交易日 {date_iso}：上市 {len(listed)} 檔")
    # 上櫃也要包起來：TPEX 逾時同樣會炸整包部署（跟上市同一類雷）。失敗就整次降級、不寫「只有
    # 上市」的半套資料（避免上市新/上櫃舊卻標 fetch_ok=True 誤導前端）；下次排程自動補上。
    try:
        otc = ms.fetch_otc_ohlc(date_iso)
    except Exception as e:
        print(f"  ⚠️ 上櫃 {date_iso} 抓取失敗（{e}）→ 跳過本次累積（避免上市/上櫃不一致），用現有歷史繼續。")
        write_fetch_state(False)
        return
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

    write_fetch_state(True)
    print(f"✅ 已累積 {date_iso}：price {len(price)} 檔、chip {len(chip)} 檔、dividends {len(div_hist)} 檔、index {len(index_hist)} 天")


if __name__ == "__main__":
    main()
