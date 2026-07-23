#!/usr/bin/env python3
"""用 FinMind 補 bt_price.json 的缺口（TWSE 對某天永久回空時的「獨立備援」）。

## 這支跟 backfill_bt.py 的分工
- **backfill_bt.py（主力）**：TWSE/TPEX「逐交易日、全市場」抓長歷史，一天只花 2 個請求，
  已內建「缺哪天補哪天」＋失敗自動重試。日常補洞就靠它。
- **finmind_fill.py（備援，本檔）**：萬一 TWSE 對「某一天」永久回空（極少，2024-09-24 踩過），
  就沒有第二來源。FinMind 是這個獨立備援；也可拿來便宜地補「個別股票」的零星缺口。

## 免費層限制（2026-07-24 實測）
FinMind 免費層**不能**「省略 data_id 拿全市場單日」——實測回 `Your level is free`。
只能**逐檔拿區間**（`data_id=2330`，一次一檔、多天）。所以：
  - 補「一整天的洞」→ 得逐檔跑整個宇宙（~1500 檔 = ~1500 請求，free 600/hr → 約 3 小時）。
    這種情況「優先用 TWSE」，FinMind 只在 TWSE 永久失敗時才動用。
  - 補「個別股票零星缺口」→ FinMind 很划算（1 檔 1 請求）。

## 安全設計
1. **只填缺格、不覆蓋既有 TWSE 資料**——保持單一真值，避免兩個源的微小差異互相污染。
2. **`--stocks` 模式不新增全域日期**——只跑幾檔時，若允許新增日期會讓那天只有幾檔有值、
   其餘全 None，直接污染回測。故只有「全宇宙」模式才准新增日期（補整日洞）。
3. 可續跑、每 N 檔存一次；被限流自動退避。token 選填（GitHub Secret FINMIND_TOKEN，帶了額度較高）。

## 為什麼「整日洞」要明確指定，不自動偵測
「某股某天 close 是 None」有兩種可能：那天整天沒進 bt（整日洞），或那股當天沒交易（本來就該缺）。
光看 bt 分不出來，也不知道哪天「該存在卻整天缺」——那需要另接一份交易日曆。與其多綁一個
脆弱依賴去猜，不如：整日洞用 `--dates 2024-09-24` 明確指定（你知道 TWSE 對那天永久失敗才動用），
日常自動補的只有「個股在既有日期的零星缺格」。FinMind 只對「它真的有回傳的日期」補值，所以
「該股那天到底有沒有交易」由 FinMind 有沒有回傳天然過濾——沒交易就不會被亂填。

用法：
  python3 finmind_fill.py                       # 自動補「個股在既有日期的零星缺格」（便宜）
  python3 finmind_fill.py --dates 2024-09-24    # 备援：TWSE 對這天永久失敗 → 全宇宙逐檔補這天
  python3 finmind_fill.py --stocks 2330,0050    # 只補指定股票（不新增全域日期）
  python3 finmind_fill.py --dry-run             # 只報告缺哪些，不動檔
"""
import argparse
import os
import time
import urllib.parse
import urllib.request
import json

import history_store as hs

HERE = os.path.dirname(__file__)
BT_PATH = os.path.join(HERE, "history", "bt_price.json")
FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
SAVE_EVERY = 50            # 每補幾檔存一次檔（長跑中途中斷也不白費）
RATE_SLEEP = 0.25          # 每個請求之間的基本間隔秒數
BACKOFF_SLEEP = 65         # 撞到額度上限時退避秒數（free 600/hr，等一分鐘再試）


def fetch_stock_range(sid, start_iso, end_iso, token="", retries=4):
    """打 FinMind 拿單檔區間 OHLCV。回 [{date, open, max, min, close, Trading_Volume(股)}, ...]。
    撞到額度上限（status != 200 且訊息含 limit/level）會退避重試。"""
    params = {"dataset": "TaiwanStockPrice", "data_id": sid,
              "start_date": start_iso, "end_date": end_iso}
    if token:
        params["token"] = token
    url = f"{FINMIND_URL}?{urllib.parse.urlencode(params)}"
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                d = json.loads(r.read().decode("utf-8"))
        except Exception as e:                          # 網路層錯誤：短退避重試
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))
            continue
        if d.get("status") == 200:
            return d.get("data") or []
        msg = str(d.get("msg", ""))
        # 撞額度上限 → 長退避再試；權限不足（免費層拿全市場那種）→ 直接拋，不重試
        if "limit" in msg.lower() and attempt < retries - 1:
            time.sleep(BACKOFF_SLEEP)
            continue
        raise RuntimeError(f"FinMind {sid} 失敗：{msg}")
    return []


def plan_targets(bt, sids, extra_dates):
    """算出「每檔要嘗試補的日期集合」。回 {sid: set(dates)}。
    - 個股缺格：該股在既有 bt 日期上 close 為 None（一律列入）。
    - extra_dates（--dates 指定的整日洞）：對「宇宙裡每一檔」都列入，且 bt 尚未有該股該日者。
    只納入「候選」，真正有沒有值由 FinMind 有無回傳決定（沒交易就不會被填）。
    """
    dates = bt.get("dates") or []
    have = set(dates)
    stocks = bt.get("stocks") or {}
    date_idx = {d: i for i, d in enumerate(dates)}
    want = {}
    for sid in sids:
        cols = stocks.get(sid)
        missing = set()
        if cols:
            close = cols[3]
            for d, i in date_idx.items():
                if close[i] is None:                    # 既有日期上的個股缺格
                    missing.add(d)
            for ed in extra_dates:                      # 指定整日洞：該股還沒這天就列入
                if ed not in have or close[date_idx[ed]] is None:
                    missing.add(ed)
        elif extra_dates:                               # 完全不在 bt 的股票只在补整日洞時才有意義
            missing.update(extra_dates)
        if missing:
            want[sid] = missing
    return want


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", default="", help="逗號分隔的日期（YYYY-MM-DD），补 TWSE 永久失敗的整日洞")
    ap.add_argument("--stocks", default="", help="逗號分隔的股票代號；留空＝掃 bt 宇宙全部")
    ap.add_argument("--dry-run", action="store_true", help="只報告缺口，不動檔")
    ap.add_argument("--sleep", type=float, default=RATE_SLEEP, help="每個請求間隔秒數")
    args = ap.parse_args()

    token = os.environ.get("FINMIND_TOKEN", "")
    bt = hs.load(BT_PATH) or hs.bt_empty()
    dates = bt.get("dates") or []
    if not dates:
        print("❌ bt_price.json 是空的，請先跑 backfill_bt.py 建底。")
        return
    extra_dates = [d.strip() for d in args.dates.split(",") if d.strip()]

    # 只跑幾檔時不准新增全域日期：否則那天只有幾檔有值、其餘全 None，直接污染回測（安全設計 2）
    if args.stocks:
        sids = [s.strip() for s in args.stocks.split(",") if s.strip()]
        if extra_dates and any(d not in set(dates) for d in extra_dates):
            print("⚠️ --stocks 模式不補「新的整日洞」（會讓那天只有幾檔有值）；"
                  "补整日洞請不加 --stocks 跑全宇宙。已忽略不存在的日期。")
            extra_dates = [d for d in extra_dates if d in set(dates)]
    else:
        sids = sorted((bt.get("stocks") or {}).keys())

    # 補整日洞需要全宇宙逐檔（每檔貢獻那天一根 K），這裡先估算成本讓人有心理準備
    start_iso, end_iso = dates[0], dates[-1]
    for ed in extra_dates:
        start_iso, end_iso = min(start_iso, ed), max(end_iso, ed)
    print(f"📦 bt 現況：{len(dates)} 個交易日（{dates[0]}~{dates[-1]}）、{len(bt.get('stocks') or {})} 檔")
    if extra_dates:
        print(f"🩹 补整日洞：{extra_dates}（免費層逐檔 → 約 {len(sids)} 個請求，可能跨多個限流窗口）")

    want = plan_targets(bt, sids, extra_dates)
    total = sum(len(v) for v in want.values())
    print(f"🔎 待補股票 {len(want)} 檔、候選缺格 {total}（實際填幾格看 FinMind 有無回傳）")
    if not want:
        print("✅ 沒有可補的缺口。")
        return
    if args.dry_run:
        for sid in list(want)[:20]:
            ds = sorted(want[sid])
            print(f"   {sid}：{len(ds)} 天，如 {ds[:3]}{'…' if len(ds) > 3 else ''}")
        print(f"（dry-run，未動檔。合計 {len(want)} 檔待補）")
        return

    pending, filled_cells, done, failed = {}, 0, 0, []
    for sid, missing in want.items():
        try:
            rows = fetch_stock_range(sid, start_iso, end_iso, token)
        except Exception as e:
            failed.append((sid, str(e)[:60]))
            time.sleep(args.sleep)
            continue
        for r in rows:
            d = r.get("date")
            if d not in missing:                        # 只填我們認定的缺格，其餘一律不碰
                continue
            row = {"open": r["open"], "max": r["max"], "min": r["min"],
                   "close": r["close"], "Trading_Volume": r.get("Trading_Volume") or 0}
            pending.setdefault(d, {})[sid] = row
            filled_cells += 1
        done += 1
        time.sleep(args.sleep)
        if done % SAVE_EVERY == 0:
            hs.bt_merge_days(bt, pending)
            hs.save(BT_PATH, bt)
            pending = {}
            print(f"   …已處理 {done}/{len(want)} 檔，累計填入 {filled_cells} 格，"
                  f"檔案 {os.path.getsize(BT_PATH)/1e6:.1f}MB")

    if pending:
        hs.bt_merge_days(bt, pending)
        hs.save(BT_PATH, bt)

    size = os.path.getsize(BT_PATH) / 1e6 if os.path.exists(BT_PATH) else 0
    print(f"\n✅ 處理 {done} 檔，實際填入 {filled_cells} 格 → "
          f"長歷史共 {len(bt['dates'])} 個交易日、{len(bt['stocks'])} 檔、{size:.1f}MB")
    if failed:
        print(f"⚠️ {len(failed)} 檔失敗（再跑一次會自動重試）：")
        for sid, why in failed[:10]:
            print(f"   {sid} {why}")


if __name__ == "__main__":
    main()
