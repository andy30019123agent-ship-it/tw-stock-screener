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
                out[sid] = {"yoy": round(yoy, 2), "ym": str(r.get("資料年月", "")).strip()}
                n += 1
            status[key] = n > 0
        except Exception as e:
            print(f"  ⚠️ {name}月營收抓取失敗（該市場本次不過濾營收）：{e}")
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
    have = _latest_ym(cached)
    if cached and have and have >= want:
        return cached

    if cached:
        print(f"   月營收快取只到 {have}、應已公布到 {want} → 重抓")
    status = {}
    fresh = fetch_revenue_yoy(status)
    if not fresh:
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
    return merged


if __name__ == "__main__":
    d = load_or_fetch()
    print(f"月營收 YoY：{len(d)} 檔")
    for sid in list(d)[:5]:
        print(f"  {sid}: {d[sid]}")
