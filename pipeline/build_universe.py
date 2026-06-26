#!/usr/bin/env python3
"""產生「全市場」清單 universe.json（上市+上櫃普通股，含市場別與產業）。

資料源全免費（TWSE/TPEX），不用 FinMind。新架構算指標不再逐檔打 API，
故清單收錄全部可交易普通股，量的篩選交給 build_data 輸出時處理。

用法：python3 build_universe.py
"""
import datetime as dt
import json
import os

import market_sources as ms

HERE = os.path.dirname(__file__)

# MOPS / 證交所「產業別」代碼 → 名稱（上市上櫃共用此分類）
INDUSTRY_NAMES = {
    "01": "水泥", "02": "食品", "03": "塑膠", "04": "紡織纖維", "05": "電機機械",
    "06": "電器電纜", "08": "玻璃陶瓷", "09": "造紙", "10": "鋼鐵", "11": "橡膠",
    "12": "汽車", "14": "建材營造", "15": "航運", "16": "觀光餐旅", "17": "金融保險",
    "18": "貿易百貨", "19": "綜合", "20": "其他", "21": "化學工業", "22": "生技醫療",
    "23": "油電燃氣", "24": "半導體", "25": "電腦及週邊設備", "26": "光電",
    "27": "通信網路", "28": "電子零組件", "29": "電子通路", "30": "資訊服務",
    "31": "其他電子", "32": "文化創意", "33": "農業科技", "34": "電子商務",
    "35": "綠能環保", "36": "數位雲端", "37": "運動休閒", "38": "居家生活",
    "80": "管理股票",
}


def _listed_company_info():
    """上市公司：{id: (簡稱, 產業代碼)}。"""
    rows = ms.get_json("https://openapi.twse.com.tw/v1/opendata/t187ap03_L")
    return {r["公司代號"]: (r.get("公司簡稱", ""), str(r.get("產業別", "")).strip())
            for r in rows if ms.is_common_stock(r.get("公司代號", ""))}


def _otc_company_info():
    """上櫃公司：{id: (簡稱, 產業代碼)}。"""
    rows = ms.get_json("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O")
    out = {}
    for r in rows:
        sid = r.get("SecuritiesCompanyCode", "")
        if ms.is_common_stock(sid):
            out[sid] = (r.get("CompanyAbbreviation", ""),
                        str(r.get("SecuritiesIndustryCode", "")).strip())
    return out


def _industry_name(code):
    return INDUSTRY_NAMES.get(str(code).zfill(2), "其他")


def main():
    print("📡 取得全市場可交易普通股清單（TWSE/TPEX，免費）…")
    date_iso, listed_ohlc = ms.fetch_listed_ohlc_latest()
    otc_ohlc = ms.fetch_otc_ohlc(date_iso)
    print(f"   最新交易日 {date_iso}：上市 {len(listed_ohlc)}、上櫃 {len(otc_ohlc)}")

    listed_info = _listed_company_info()
    otc_info = _otc_company_info()

    stocks = []
    for sid in sorted(listed_ohlc):
        name, code = listed_info.get(sid, (sid, ""))
        stocks.append({"id": sid, "name": name or sid, "market": "上市",
                       "industry": _industry_name(code)})
    for sid in sorted(otc_ohlc):
        name, code = otc_info.get(sid, (sid, ""))
        stocks.append({"id": sid, "name": name or sid, "market": "上櫃",
                       "industry": _industry_name(code)})

    out = {"updated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
           "trade_date": date_iso, "count": len(stocks), "stocks": stocks}
    path = os.path.join(HERE, "universe.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\n✅ 全市場 {len(stocks)} 檔 → {os.path.relpath(path)}")


if __name__ == "__main__":
    main()
