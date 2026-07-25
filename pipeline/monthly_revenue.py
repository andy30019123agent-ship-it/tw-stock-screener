#!/usr/bin/env python3
"""月營收年增率（YoY）過濾用資料源（免費 OpenAPI，月更即可）。

上市 TWSE OpenAPI `opendata/t187ap05_L`、上櫃 TPEX OpenAPI `openapi/v1/mopsfin_t187ap05_O`，
兩者欄位相同，取「營業收入-去年同月增減(%)」= 近月營收 YoY。

快取到 pipeline/revenue_cache.json，同一日曆月沿用（月營收約每月 10 號公布上月數字，月更足夠）。
抓不到時回傳既有快取（沒有就空 dict），呼叫端據此「不過濾並標營收資料缺」。
"""
import os
import sys
import json
import datetime as dt

sys.path.insert(0, os.path.dirname(__file__))
import market_sources as ms  # noqa: E402

HERE = os.path.dirname(__file__)
CACHE_PATH = os.path.join(HERE, "revenue_cache.json")
# 逐月快照（2026-07-25 起累積）：見 record_snapshot 的說明——這是唯一能讓「營收年減剔除」
# 將來可被回測驗證的東西，因為官方 OpenAPI 只回**最新一期**，過去的月份無法補抓。
HISTORY_PATH = os.path.join(HERE, "revenue_history.json")

TWSE_REVENUE = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
TPEX_REVENUE = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"
YOY_KEY = "營業收入-去年同月增減(%)"


def fetch_revenue_yoy(status=None):
    """抓上市＋上櫃最新月營收 YoY。回 {sid: {"yoy": float, "ym": "11505"}}。單邊失敗只印警告。

    status（可選 dict）：填入 {"listed": bool, "otc": bool} 讓呼叫端知道各市場成功了沒——
    單邊失敗時若直接用結果覆蓋快取，會把另一市場的 last-good 資料整批抹掉（2026-07-25 Codex 指出）。
    """
    out = {}
    if status is None:
        status = {}
    for key, name, url in (("listed", "上市", TWSE_REVENUE), ("otc", "上櫃", TPEX_REVENUE)):
        status.setdefault(key, False)
        try:
            n = 0
            for r in ms.get_json(url):
                sid = str(r.get("公司代號", "")).strip()
                if not ms.is_common_stock(sid):
                    continue
                yoy = ms._f(r.get(YOY_KEY))
                if yoy is None:
                    continue
                # 標記來源市場：判斷快取新鮮度時要能分市場（代號規則不可靠，抓取時記下才準）
                out[sid] = {"yoy": round(yoy, 2), "ym": str(r.get("資料年月", "")).strip(), "mkt": key}
                n += 1
            status[key] = n > 0
        except Exception as e:
            print(f"  ⚠️ {name}月營收抓取失敗（該市場本次不過濾營收）：{e}")
    return out


def record_snapshot(data, today=None, path=None):
    """把「這個月看到的營收 YoY」存成一份逐月快照，回傳 (新增的月份, 總月份數)。

    **為什麼一定要存**：官方 OpenAPI 只回最新一期，過去月份抓不回來。2026-07-25 回測整套
    選股程序時，「營收年減剔除」這條濾網**完全無法驗證**——因為 revenue_cache.json 只有當期
    快照。也就是說這條濾網一直開著、但沒人知道它有效還是有害。不從現在開始存，這個洞永遠補不上。

    設計上的兩個關鍵：
    1. **同一個月份只記第一次看到的值**（保留 first_seen 日期）。之後官方修正數字也不覆蓋，
       因為回測要問的是「當時能拿到什麼」——用後來修正過的數字回測＝偷看未來。
       修正次數記在 revisions 供追溯。
    2. **逐市場筆數**也記下來（mkt_n）：某個月上櫃抓失敗只有半個市場，回測時必須看得出來，
       否則會把「資料缺一半」誤當成「這些股票沒有營收年減」。
    """
    today = today or dt.date.today()
    path = path or HISTORY_PATH
    hist = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                hist = json.load(f) or {}
        except Exception as e:
            # 讀不到就停手，不要覆蓋——這是無法重建的資料，寧可這次不記也不能弄壞既有的
            print(f"   ⚠️ 營收快照檔讀取失敗，本次不寫入（避免覆蓋無法重建的歷史）：{e}")
            return None, 0
    months = hist.setdefault("months", {})

    by_ym = {}
    for sid, v in (data or {}).items():
        if not isinstance(v, dict) or not v.get("ym") or v.get("yoy") is None:
            continue
        by_ym.setdefault(v["ym"], {})[sid] = (v["yoy"], v.get("mkt"))

    added = []
    for ym, rows in by_ym.items():
        if ym in months:
            # 已記錄過 → 只算修正次數，不動原值（見上面第 1 點）
            old = months[ym].get("yoy") or {}
            rev = sum(1 for sid, (yoy, _) in rows.items() if sid in old and old[sid] != yoy)
            if rev:
                months[ym]["revisions"] = months[ym].get("revisions", 0) + rev
                months[ym]["revised_at"] = today.isoformat()
            # 新增的公司（例如某市場上次抓失敗、這次補到）可以補進去，那不是「修正」而是「補齊」
            new_sids = {sid: yoy for sid, (yoy, _) in rows.items() if sid not in old}
            if new_sids:
                old.update(new_sids)
                months[ym]["yoy"] = old
                months[ym]["backfilled_at"] = today.isoformat()
                mkt_n = months[ym].setdefault("mkt_n", {})
                for sid, (_, mkt) in rows.items():
                    if sid in new_sids and mkt:
                        mkt_n[mkt] = mkt_n.get(mkt, 0) + 1
            continue
        mkt_n = {}
        for _, (_, mkt) in rows.items():
            if mkt:
                mkt_n[mkt] = mkt_n.get(mkt, 0) + 1
        months[ym] = {
            "first_seen": today.isoformat(),
            "n": len(rows),
            "mkt_n": mkt_n,
            "yoy": {sid: yoy for sid, (yoy, _) in rows.items()},
        }
        added.append(ym)

    if added or any(m.get("revised_at") == today.isoformat() or m.get("backfilled_at") == today.isoformat()
                    for m in months.values()):
        hist["updated"] = today.isoformat()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(hist, f, ensure_ascii=False, separators=(",", ":"))
    if added:
        print(f"   📸 月營收快照新增 {'、'.join(sorted(added))}（累積 {len(months)} 個月）")
    return (added[0] if added else None), len(months)


def _latest_ym_by_market(data):
    """逐市場的最新資料年月：{"listed": "11506", "otc": "11505"}。

    為什麼要分市場：兩個來源各自可能失敗，用「全市場最大 ym」判斷快取新鮮度會被成功的那一邊
    蓋過去，失敗市場的舊資料就永遠不再重試（2026-07-25 Codex 指出）。
    市場來源取自抓取時寫入的 `mkt` 欄位（不用代號規則猜——代號規則不可靠）。
    舊快取沒有 `mkt` 就會判定「未達預期月份」而整批重抓一次，之後就有了。保守但正確。
    """
    out = {}
    for v in (data or {}).values():
        if not isinstance(v, dict) or not v.get("ym"):
            continue
        key = v.get("mkt")
        if key not in ("listed", "otc"):
            continue          # 舊快取沒有 mkt 欄位 → 不計入，下面會判定未達 want 而重抓（保守）
        if not out.get(key) or v["ym"] > out[key]:
            out[key] = v["ym"]
    return out


def _latest_ym(data):
    """快取資料裡最新的『資料年月』（民國 YYYMM 字串，可字串比大小）。"""
    yms = [v.get("ym") for v in (data or {}).values() if isinstance(v, dict) and v.get("ym")]
    return max(yms) if yms else None


def _expected_ym(today):
    """今天『應該』已公布到哪一個月的營收（民國 YYYMM）。

    台股規定每月 10 日前公布上月營收 → 10 日之後就該有上月資料；10 日之前只保證有上上月。
    回傳保守值（不會催一個還沒公布的月份），這樣「該重抓」的判斷不會每天都成立。
    """
    y, m = today.year, today.month
    back = 1 if today.day >= 11 else 2
    m -= back
    while m <= 0:
        m += 12
        y -= 1
    return f"{y - 1911}{m:02d}"


def _load_cache():
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def load_or_fetch(today=None):
    """回傳 {sid: {"yoy", "ym"}}。**依「資料本身的年月」判斷新舊**，不是抓取日的日曆月。

    ⚠️ 2026-07-25 修（Codex 指出）：原本用 `fetched_month == 今年今月` 當快取命中條件 →
    月初抓到的舊月份資料會被鎖死一整個月。實測：快取 7/3 建立、1966 筆全是 11505（2026-05），
    於是整個 7 月的 Top5「營收年減剔除」都在用兩個月前的營收。
    現在改成：快取的最新資料年月 ≥ 今天『應該已公布』的月份才算命中，否則每天重試直到抓到。

    單邊市場失敗時**只合併成功的那邊**，保留另一市場的 last-good，不整批覆蓋。
    """
    today = today or dt.date.today()
    cache = _load_cache()
    cached = cache.get("data") or {}
    want = _expected_ym(today)
    # 🔴 2026-07-25 修（Codex 指出）：原本用「全市場最大 ym」判斷命中 → 上市成功、上櫃失敗後，
    # 只要上市已有新月份就整體命中快取，**上櫃的舊資料再也不會被重試**。
    # 逐來源檢查：兩個市場都達到 want 才算命中（市場別取自抓取時寫入的 mkt 欄位）。
    per = _latest_ym_by_market(cached)
    if cached and all(per.get(k) and per[k] >= want for k in ("listed", "otc")):
        record_snapshot(cached, today)   # 命中快取也要記：不然「當期」這個月永遠不會被存下來
        return cached
    if cached:
        lag = [f"{k}={per.get(k) or '無'}" for k in ("listed", "otc") if not (per.get(k) and per[k] >= want)]
        print(f"   月營收有市場未達 {want}（{'、'.join(lag)}）→ 重抓")

    status = {}
    fresh = fetch_revenue_yoy(status)
    if not fresh:
        record_snapshot(cached, today)
        return cached          # 兩邊都失敗 → 沿用舊快取，不要整批標成「營收資料缺」

    # 單邊失敗時保留另一市場的舊資料（fresh 只含成功市場的代號）
    merged = dict(cached)
    merged.update(fresh)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump({"fetched_month": today.strftime("%Y-%m"),
                   "fetched_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                   "data_ym": _latest_ym(merged),      # 資料本身的年月＝下次判斷新舊的依據
                   "expected_ym": want,
                   "source_status": dict(status),      # 哪個市場成功，供除錯與降級判斷
                   "data": merged}, f, ensure_ascii=False, separators=(",", ":"))
    if not (status.get("listed") and status.get("otc")):
        miss = [k for k in ("listed", "otc") if not status.get(k)]
        print(f"   ⚠️ 月營收有市場抓取失敗（{'、'.join(miss)}），已保留該市場舊資料")
    record_snapshot(merged, today)
    return merged


if __name__ == "__main__":
    d = load_or_fetch()
    print(f"月營收 YoY：{len(d)} 檔")
    for sid in list(d)[:5]:
        print(f"  {sid}: {d[sid]}")
