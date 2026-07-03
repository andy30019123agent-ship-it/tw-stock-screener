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


def fetch_revenue_yoy():
    """抓上市＋上櫃最新月營收 YoY。回 {sid: {"yoy": float, "ym": "11505"}}。單邊失敗只印警告。"""
    out = {}
    for name, url in (("上市", TWSE_REVENUE), ("上櫃", TPEX_REVENUE)):
        try:
            for r in ms.get_json(url):
                sid = str(r.get("公司代號", "")).strip()
                if not ms.is_common_stock(sid):
                    continue
                yoy = ms._f(r.get(YOY_KEY))
                if yoy is None:
                    continue
                out[sid] = {"yoy": round(yoy, 2), "ym": str(r.get("資料年月", "")).strip()}
        except Exception as e:
            print(f"  ⚠️ {name}月營收抓取失敗（該市場本次不過濾營收）：{e}")
    return out


def _load_cache():
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def load_or_fetch(today=None):
    """回傳 {sid: {"yoy", "ym"}}。同一日曆月已抓過就沿用快取，否則重抓並寫回快取。
    抓取失敗（拿到空）時沿用舊快取，避免整批標成『營收資料缺』。"""
    today = today or dt.date.today()
    month_key = today.strftime("%Y-%m")
    cache = _load_cache()
    if cache.get("fetched_month") == month_key and cache.get("data"):
        return cache["data"]

    data = fetch_revenue_yoy()
    if data:
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump({"fetched_month": month_key,
                       "fetched_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                       "data": data}, f, ensure_ascii=False, separators=(",", ":"))
        return data
    return cache.get("data") or {}


if __name__ == "__main__":
    d = load_or_fetch()
    print(f"月營收 YoY：{len(d)} 檔")
    for sid in list(d)[:5]:
        print(f"  {sid}: {d[sid]}")
