#!/usr/bin/env python3
"""漏抓交易日自動回補（2026-11-13）。

## 為什麼需要
daily_update.py 每天只抓「最新交易日」（STOCK_DAY_ALL 不吃日期）。某天抓失敗，那天就
永久缺——2026-08-18～08-20 三個交易日就這樣漏掉（證交所月報顯示正常成交），回測持有期
被拉長、指標跨過斷層。這支每天在 daily_update 之後跑：對照「應有交易日」找缺口，用吃 date
參數的全市場端點補抓，插回歷史正確位置。

## 應有交易日從哪來（基準）
TWSE FMTQIK（市場成交資訊，一請求一個月）。**不能用 index.json**——加權指數是 daily_update
同一步抓的，每日那條路失敗它也一起缺（08-18～08-20 index.json 同樣沒有）。

## 做什麼、不做什麼
- 只看最近 AUTO_WINDOW_DAYS 個交易日（自動）；更舊的洞用 --dates 手動指定（例 08-18～08-20）。
- 每次最多補 MAX_DAYS_PER_RUN 天、請求間隔 REQUEST_SLEEP 秒；沒補完的記進狀態檔，下次接著補。
- 不造假：某天任一必要部分（上市/上櫃 OHLCV、籌碼視窗內的法人、除權息）失敗或回空 →
  那天整天不寫，記「待補」。基準清單裡沒有的日子（真休市）不算缺口；基準本身抓不到的月份
  記「基準未知」、該月不判斷。
- 寫入順序：除權息 → 法人 → 指數 → bt_price → price（price 是缺口偵測的依據，最後寫）。
  中途中斷時 price 還沒有那天 → 下次仍判成缺口、整天重抓重寫（覆寫是冪等的）。
- 狀態寫進 pipeline/backfill_state.json：已回補（含來源、筆數）/ 待補 / 放棄 / 基準狀態。

用法：
  python3 pipeline/gap_backfill.py --dry-run                     # 只偵測、不寫檔
  python3 pipeline/gap_backfill.py --dates 2026-08-18:2026-08-20 # 手動指定區間
（平常由 daily_update.py 呼叫 safe_run，不用單獨跑。）
"""
import argparse
import datetime as dt
import json
import os
import time
import traceback

import history_store as hs
import market_sources as ms

HERE = os.path.dirname(__file__)
PRICE_PATH = os.path.join(HERE, "history", "price.json")
CHIP_PATH = os.path.join(HERE, "history", "chip.json")
DIV_PATH = os.path.join(HERE, "history", "dividends.json")
INDEX_PATH = os.path.join(HERE, "history", "index.json")
BT_PATH = os.path.join(HERE, "history", "bt_price.json")
STATE_PATH = os.path.join(HERE, "backfill_state.json")

# 自動檢查最近 20 個交易日：= CHIP_WINDOW（法人歷史只留 20 天，更舊的洞補了法人也會被修剪），
# 約 4 週、涵蓋春節等長假後的連續失敗；基準只需 1～2 個月的 FMTQIK（每天多 1～2 個請求）。
# 更舊的洞（像 08-18～08-20）用 --dates 手動補，避免每天為舊月份多打請求。
AUTO_WINDOW_DAYS = 20
MAX_DAYS_PER_RUN = 3        # 每次最多補幾天（每天約 2～4 個請求），避免被 TWSE 限流
REQUEST_SLEEP = 2.0         # 每個請求之間的間隔秒數
MAX_ATTEMPTS = 10           # 同一天連續失敗這麼多次就「放棄自動重試」（仍標未解決，不算已處理）
# 「回空」判定門檻：正常交易日上市 ~1,000、上櫃 ~860 檔普通股（2026-11-13 實測 08-19：1091／862）。
# 少於門檻視為不完整（限流／資料未出），整天不寫——寧可缺，不要寫半套。
MIN_LISTED_ROWS = 500
MIN_OTC_ROWS = 300
MIN_CHIP_ROWS = 300         # 各市場法人資料最少列數
MIN_PRESENT_ROWS = 500      # 歷史檔裡某日「算有資料」的最少檔數（排除只剩零星下市股的舊日期）

# 只把這幾類當「網路／資料」預期錯誤：get_text 失敗丟 RuntimeError、JSON 壞掉丟 ValueError、
# 底層連線丟 OSError。其他例外（KeyError/TypeError…）視為程式錯誤，讓測試直接紅。
FETCH_ERRORS = (RuntimeError, ValueError, OSError)


def default_fetchers():
    return {
        "baseline_month": ms.fetch_trading_days_month,
        "listed_ohlc": ms.fetch_listed_ohlc,
        "otc_ohlc": ms.fetch_otc_ohlc,
        "listed_chip": ms.fetch_listed_chip,
        "otc_chip": ms.fetch_otc_chip,
        "dividends": ms.fetch_ex_dividend_events,
    }


def now_taipei():
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d %H:%M")
    except Exception:   # 沒有時區資料庫的環境：退回 UTC+8 固定位移
        return (dt.datetime.utcnow() + dt.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")


# ── 純函式：日期工具 ───────────────────────────────────────────────────
def parse_dates_arg(s):
    """'2026-08-18:2026-08-20'（含頭尾）或 '2026-08-18,2026-08-20' → 排序後的日期字串 list。
    區間只展開「日曆日」；哪些是交易日由基準決定。"""
    if not s or not s.strip():
        return []
    out = set()
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            a, b = (dt.date.fromisoformat(x.strip()) for x in part.split(":", 1))
            if b < a:
                a, b = b, a
            d = a
            while d <= b:
                out.add(d.isoformat())
                d += dt.timedelta(days=1)
        else:
            out.add(dt.date.fromisoformat(part).isoformat())
    return sorted(out)


def month_of(date_iso):
    return date_iso[:4] + date_iso[5:7]


def prev_month(ym):
    y, m = int(ym[:4]), int(ym[4:])
    m -= 1
    if m == 0:
        y, m = y - 1, 12
    return f"{y}{m:02d}"


def date_counts(hist):
    """{sid: {date: ...}} → {date: 有資料的檔數}。"""
    c = {}
    for by in (hist or {}).values():
        if not isinstance(by, dict):
            continue
        for d in by:
            c[d] = c.get(d, 0) + 1
    return c


def present_dates(hist, min_rows=MIN_PRESENT_ROWS):
    return {d for d, n in date_counts(hist).items() if n >= min_rows}


# ── 基準交易日 ─────────────────────────────────────────────────────────
def load_baseline(months, fetch_month, sleep=time.sleep, gap=REQUEST_SLEEP):
    """逐月抓 FMTQIK。回 (baseline {date: taiex}, months_ok, months_failed)。
    失敗或回空的月份＝「基準未知」，那個月的日子一律不判斷（不當成缺、也不當成休市）。"""
    baseline, ok, failed = {}, [], []
    for i, ym in enumerate(sorted(set(months))):
        if i:
            sleep(gap)
        try:
            got = fetch_month(ym) or {}
        except FETCH_ERRORS as e:
            print(f"  ⚠️ 交易日基準 {ym} 抓取失敗：{e}")
            failed.append(ym)
            continue
        if not got:
            print(f"  ⚠️ 交易日基準 {ym} 回空（限流或資料未出）→ 該月不判斷缺口")
            failed.append(ym)
            continue
        baseline.update(got)
        ok.append(ym)
    return baseline, ok, failed


# ── 缺口偵測（純函式，不打網路）──────────────────────────────────────────
def detect_gaps(baseline, price, chip, index_hist, bt, extra_dates=(),
                window=AUTO_WINDOW_DAYS, price_window=hs.PRICE_WINDOW,
                chip_window=hs.CHIP_WINDOW):
    """回 (gaps, info)。gaps＝{date: set(需要補的部分)}，部分有：
      "price"（上市+上櫃 OHLCV，連帶除權息）、"chip"（三大法人）、"index"（加權指數，基準就有值）。
    檢查範圍＝基準裡 ≤ 歷史最新日的最近 window 個交易日 ∪ extra_dates（手動/待補佇列）。
    extra_dates 必須在基準裡（或之前已被基準確認，呼叫端負責），不在的不算缺口。"""
    have_price = present_dates(price)
    info = {"latest": None, "price_window_start": None, "out_of_window": [],
            "in_history_not_in_baseline": []}
    if not have_price:
        return {}, info
    latest = max(have_price)
    info["latest"] = latest
    price_sorted = sorted(have_price)
    price_start = price_sorted[-price_window] if len(price_sorted) >= price_window else price_sorted[0]
    info["price_window_start"] = price_start
    base_days = sorted(d for d in baseline if d <= latest)
    auto = base_days[-window:] if window else []
    # 法人視窗起點看 chip.json 自己（每檔只留 chip_window 天，比這更舊的補進去也會立刻被修剪）
    have_chip = present_dates(chip)
    chip_sorted = sorted(have_chip)
    chip_start = (chip_sorted[-chip_window] if len(chip_sorted) >= chip_window
                  else (chip_sorted[0] if chip_sorted else latest))
    bt_dates = set((bt or {}).get("dates") or [])
    bt_start = min(bt_dates) if bt_dates else None

    # 基準自己可能缺（月份抓到一半、當天還沒更新）：歷史有、基準在同月份卻沒有 → 記下來追查
    loaded_months = {month_of(d) for d in baseline}
    info["in_history_not_in_baseline"] = sorted(
        d for d in have_price if month_of(d) in loaded_months and d not in baseline and d <= latest)

    gaps = {}
    for d in sorted(set(auto) | {x for x in extra_dates if x <= latest}):
        needs = set()
        if d >= price_start:
            if d not in have_price:
                needs.add("price")
            if d not in (index_hist or {}) and baseline.get(d) is not None:
                needs.add("index")
        elif bt_start and d >= bt_start:
            # 比 price.json 視窗舊、但仍在回測長歷史範圍：只補 bt_price.json
            if d not in bt_dates:
                needs.add("price")
        else:
            info["out_of_window"].append(d)
            continue
        if d >= chip_start and ("price" in needs or d not in have_chip):
            needs.add("chip")
        if needs:
            gaps[d] = needs
    return gaps, info


# ── 執行回補 ───────────────────────────────────────────────────────────
def _merge_day_rows(listed, otc):
    rows = dict(listed)
    rows.update(otc)
    return rows


def _fetch_day(d, needs, f, sleep):
    """抓某天需要的部分。任一必要部分失敗/不足 → raise _DayFailed（整天不寫）。"""
    got = {}
    if "price" in needs:
        listed = f["listed_ohlc"](d)
        sleep(REQUEST_SLEEP)
        if len(listed or {}) < MIN_LISTED_ROWS:
            raise _DayFailed(f"上市 OHLCV 只有 {len(listed or {})} 檔（<{MIN_LISTED_ROWS}，限流或資料未出）")
        otc = f["otc_ohlc"](d)
        sleep(REQUEST_SLEEP)
        if len(otc or {}) < MIN_OTC_ROWS:
            raise _DayFailed(f"上櫃 OHLCV 只有 {len(otc or {})} 檔（<{MIN_OTC_ROWS}）")
        got["listed"], got["otc"] = listed, otc
    if "chip" in needs:
        lc = f["listed_chip"](d)
        sleep(REQUEST_SLEEP)
        if len(lc or {}) < MIN_CHIP_ROWS:
            raise _DayFailed(f"上市法人只有 {len(lc or {})} 檔（<{MIN_CHIP_ROWS}）")
        oc = f["otc_chip"](d)
        sleep(REQUEST_SLEEP)
        if len(oc or {}) < MIN_CHIP_ROWS:
            raise _DayFailed(f"上櫃法人只有 {len(oc or {})} 檔（<{MIN_CHIP_ROWS}）")
        got["chip"] = _merge_day_rows(lc, oc)
    return got


class _DayFailed(Exception):
    pass


def _load_state(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def run(dates_arg="", dry_run=False, fetchers=None, sleep=time.sleep, paths=None,
        max_days=MAX_DAYS_PER_RUN, window=AUTO_WINDOW_DAYS):
    """偵測＋回補一次。回本次狀態 dict（也寫進 backfill_state.json，dry_run 時不寫任何檔）。"""
    f = dict(default_fetchers())
    f.update(fetchers or {})
    p = {"price": PRICE_PATH, "chip": CHIP_PATH, "div": DIV_PATH, "index": INDEX_PATH,
         "bt": BT_PATH, "state": STATE_PATH}
    p.update(paths or {})

    prev = _load_state(p["state"])
    price = hs.load(p["price"])
    chip = hs.load(p["chip"])
    index_hist = hs.load(p["index"])
    bt = hs.load(p["bt"]) or hs.bt_empty()

    manual = parse_dates_arg(dates_arg)
    queue_prev = list(prev.get("queue") or [])       # 之前已被基準確認、還沒補完的日子
    gave_up = dict(prev.get("gave_up") or {})
    attempts = {d: v.get("attempts", 0) for d, v in (prev.get("pending") or {}).items()}

    have_price = present_dates(price)
    latest = max(have_price) if have_price else None
    if latest is None:
        print("  ⚠️ 回補：price.json 沒有任何完整交易日，略過")
        return {"checked_at": now_taipei(), "skipped": "price.json 為空"}

    # 基準月份：自動視窗（最新日所在月＋前一月，20 個交易日最多跨 2 個月）＋手動日期的月份。
    # 待補佇列裡的日子之前已被基準確認過，不重抓它們的月份（省請求）。
    months = {month_of(latest), prev_month(month_of(latest))} if window else set()
    months |= {month_of(d) for d in manual}
    baseline, months_ok, months_failed = load_baseline(sorted(months), f["baseline_month"], sleep)
    for d in queue_prev:   # 佇列日已確認是交易日；指數值沿用之前存的
        baseline.setdefault(d, (prev.get("queue_index") or {}).get(d))

    manual_ok = [d for d in manual if d in baseline]
    manual_not_trading = [d for d in manual if d not in baseline and month_of(d) in months_ok]
    manual_unknown = [d for d in manual if month_of(d) in months_failed]
    # 自動視窗只有在兩個月份都拿到時才完整；缺一個月時仍用拿到的那部分判斷（缺的月份不判斷）
    extra = sorted(set(manual_ok) | set(queue_prev))
    for d in manual_ok:   # 手動指定＝重新給機會：從「放棄」名單拿掉、失敗次數歸零
        if d in gave_up:
            gave_up.pop(d)
            attempts.pop(d, None)

    gaps, info = detect_gaps(baseline, price, chip, index_hist, bt, extra_dates=extra, window=window)
    # 放棄的日子不再自動嘗試（除非手動重新指定）
    gaps = {d: n for d, n in gaps.items() if d not in gave_up}

    fetch_days = [d for d, n in gaps.items() if n & {"price", "chip"}]
    manual_set = set(manual_ok)
    fetch_days.sort(key=lambda d: (d not in manual_set, attempts.get(d, 0), d))
    todo = fetch_days[:max_days]
    index_only = [d for d, n in gaps.items() if n == {"index"}]

    print(f"🩹 漏抓回補：歷史最新 {latest}、基準月份 OK {months_ok or '無'}"
          + (f"、失敗 {months_failed}" if months_failed else "")
          + f"；缺口 {len(gaps)} 天（要抓 {len(fetch_days)}、只缺指數 {len(index_only)}）")
    for d in sorted(gaps):
        print(f"   缺 {d}：{'、'.join(sorted(gaps[d]))}")

    state = {
        "checked_at": now_taipei(),
        "window_days": window,
        "latest_in_history": latest,
        "baseline": {"months_ok": months_ok, "months_failed": months_failed},
        "gaps_detected": {d: sorted(n) for d, n in sorted(gaps.items())},
        "manual_requested": manual,
        "manual_not_trading_day": manual_not_trading,
        "manual_baseline_unknown": manual_unknown,
        "out_of_window": info["out_of_window"],
        "in_history_not_in_baseline": info["in_history_not_in_baseline"],
        "backfilled": dict(prev.get("backfilled") or {}),
        "filled_this_run": [],
        "last_error": None,
    }
    if dry_run:
        state["dry_run"] = True
        state["would_fetch"] = todo
        return state

    # 1) 除權息：一次區間請求涵蓋本次所有要補 price 的日子；兩市場都成功才算數，否則這批 price 日先不補
    price_days = [d for d in todo if "price" in gaps[d]]
    div_events, div_ok, errors = {}, True, {}
    if price_days:
        src = {}
        try:
            div_events = f["dividends"](min(price_days), max(price_days), src) or {}
        except FETCH_ERRORS as e:
            src = {}
            errors["dividends"] = str(e)[:200]
        sleep(REQUEST_SLEEP)
        div_ok = bool(src.get("listed")) and bool(src.get("otc"))
        if not div_ok:
            errors.setdefault("dividends", f"除權息來源不完整：{src}")
            print(f"  ⚠️ 除權息區間 {min(price_days)}~{max(price_days)} 抓取不完整 → 本次不補這些日子的價格")

    # 2) 逐日抓
    done = {}
    for d in todo:
        needs = gaps[d]
        if "price" in needs and not div_ok:
            attempts[d] = attempts.get(d, 0) + 1
            errors[d] = errors.get("dividends")
            continue
        try:
            done[d] = _fetch_day(d, needs, f, sleep)
        except (_DayFailed,) + FETCH_ERRORS as e:
            attempts[d] = attempts.get(d, 0) + 1
            errors[d] = str(e)[:200]
            print(f"  ⚠️ 回補 {d} 失敗（第 {attempts[d]} 次）：{e} → 記待補，不寫入")

    # 3) 寫檔（順序：除權息 → 法人 → 指數 → bt → price）
    ts = state["checked_at"]
    if any("listed" in g for g in done.values()):
        div_hist = hs.load(p["div"])
        evs = {sid: [e for e in lst if e.get("date") in done]
               for sid, lst in div_events.items()}
        evs = {sid: lst for sid, lst in evs.items() if lst}
        hs.append_dividends(div_hist, evs)
        for sid in evs:
            div_hist[sid] = hs.sort_by_date(div_hist[sid])
        hs.save(p["div"], div_hist)
    if any("chip" in g for g in done.values()):
        for d, g in done.items():
            if "chip" in g:
                hs.append_chip(chip, d, g["chip"])
        for sid in chip:
            chip[sid] = hs.sort_by_date(chip[sid])
        hs.save(p["chip"], chip)
    idx_days = [d for d in index_only] + [d for d in done if "index" in gaps[d]]
    if idx_days:
        for d in idx_days:
            hs.append_index(index_hist, d, baseline.get(d))
        hs.save(p["index"], hs.sort_by_date(index_hist))
    price_done = {d: _merge_day_rows(g["listed"], g["otc"]) for d, g in done.items() if "listed" in g}
    if price_done:
        bt_dates = bt.get("dates") or []
        bt_rows = {d: rows for d, rows in price_done.items() if bt_dates and d >= bt_dates[0]}
        if bt_rows:
            hs.bt_merge_days(bt, bt_rows)
            hs.save(p["bt"], bt)
        start = info["price_window_start"]
        for d, rows in price_done.items():
            if d >= start:
                hs.append_price(price, d, rows)
        for sid in price:
            price[sid] = hs.sort_by_date(price[sid])
        hs.save(p["price"], price)

    # 4) 狀態
    for d, g in done.items():
        state["backfilled"][d] = {
            "at": ts,
            "parts": sorted(gaps[d]),
            "listed": len(g.get("listed") or {}) or None,
            "otc": len(g.get("otc") or {}) or None,
            "chip": len(g.get("chip") or {}) or None,
            "div_events": sum(1 for lst in div_events.values() for e in lst if e.get("date") == d)
            if "listed" in g else None,
            "source": "TWSE MI_INDEX/T86 + TPEX dailyQuotes/insti（gap_backfill）",
        }
        attempts.pop(d, None)
    for d in index_only:
        state["backfilled"][d] = {"at": ts, "parts": ["index"], "source": "TWSE FMTQIK 加權指數"}
    state["filled_this_run"] = sorted(list(done) + index_only)

    pending = {}
    for d in sorted(set(fetch_days) - set(done)):
        if attempts.get(d, 0) >= MAX_ATTEMPTS:
            gave_up[d] = {"at": ts, "attempts": attempts[d], "last_error": errors.get(d)}
            print(f"  🔴 {d} 已連續失敗 {attempts[d]} 次 → 停止自動重試（未解決，可用 --dates 手動重試）")
            continue
        pending[d] = {"needs": sorted(gaps[d]), "attempts": attempts.get(d, 0),
                      "last_error": errors.get(d)}
    state["pending"] = pending
    state["gave_up"] = gave_up
    # 佇列：基準已確認、仍未補完、而且自動視窗下次可能看不到的日子（手動指定的舊日子）→ 下次接著補
    state["queue"] = sorted(pending)
    state["queue_index"] = {d: baseline.get(d) for d in state["queue"]}
    if errors.get("dividends"):
        state["last_error"] = f"dividends: {errors['dividends']}"
    hs.save(p["state"], state)
    print(f"   本次補好 {len(state['filled_this_run'])} 天 {state['filled_this_run'] or ''}；"
          f"待補 {len(pending)} 天 {sorted(pending) or ''}")
    return state


def safe_run(dates_arg="", **kw):
    """給 daily_update 呼叫的保護殼：回補任何失敗都不能擋到當天的正常更新／build／部署／TG。
    預期的網路/資料錯誤在 run() 裡逐日處理；這裡兜底的是**非預期**例外（程式錯誤、資料格式
    大改）——印完整 traceback 並寫進狀態檔 last_error 讓它看得見，但不往外丟。
    邏輯錯誤靠測試直接呼叫 run()（沒有這層保護）抓出來。"""
    try:
        return run(dates_arg, **kw)
    except Exception as e:   # noqa: BLE001 —— 刻意兜底，理由見 docstring
        print(f"  🔴 漏抓回補發生非預期錯誤（不影響今天的更新與部署）：{type(e).__name__}: {e}")
        traceback.print_exc()
        path = (kw.get("paths") or {}).get("state", STATE_PATH)
        try:
            st = _load_state(path)
            st["last_error"] = f"crash {now_taipei()}: {type(e).__name__}: {e}"[:300]
            hs.save(path, st)
        except Exception as e2:   # noqa: BLE001
            print(f"  ⚠️ 連狀態檔都寫不進去：{e2}")
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", default="", help="手動指定日期：2026-08-18:2026-08-20 或逗號分隔")
    ap.add_argument("--dry-run", action="store_true", help="只偵測缺口、不抓個股、不寫任何檔")
    ap.add_argument("--max-days", type=int, default=MAX_DAYS_PER_RUN)
    args = ap.parse_args()
    st = run(args.dates, dry_run=args.dry_run, max_days=args.max_days)
    if args.dry_run:
        print(json.dumps(st, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
