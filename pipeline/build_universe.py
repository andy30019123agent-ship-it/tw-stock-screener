#!/usr/bin/env python3
"""
重新產生「有量電子股」清單 universe.json。
掃描全部電子股，抓最近 25 天價格算均量，只留 20 日均量 ≥ 門檻者。

⚠️ 全電子股約 1200 檔、免費版 600 次/小時，跑完約 2 小時。偶爾跑一次即可。

用法：
    FINMIND_TOKEN=xxx python3 build_universe.py --min-vol 500
"""
import os
import json
import time
import argparse
import datetime as dt

from build_data import api_get, get_universe  # 共用同一套抓取邏輯

HERE = os.path.dirname(__file__)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-vol", type=int, default=500, help="20 日均量門檻（張）")
    ap.add_argument("--sleep", type=float, default=0.4)
    args = ap.parse_args()

    today = dt.date.today()
    start = (today - dt.timedelta(days=40)).isoformat()
    end = today.isoformat()

    universe = get_universe()
    print(f"電子股全體 {len(universe)} 檔，開始掃均量…")

    keep = []
    for i, s in enumerate(universe, 1):
        rows = api_get("TaiwanStockPrice",
                       {"data_id": s["id"], "start_date": start, "end_date": end})
        time.sleep(args.sleep)
        vols = [r.get("Trading_Volume", 0) or 0 for r in rows[-20:]]
        avg = (sum(vols) / len(vols) / 1000) if vols else 0
        if avg >= args.min_vol:
            keep.append(s["id"])
        if i % 50 == 0:
            print(f"  {i}/{len(universe)}，目前留 {len(keep)} 檔")

    out = {
        "_note": f"有量電子股清單（20日均量≥{args.min_vol}張），產生於 {end}",
        "ids": sorted(keep),
    }
    path = os.path.join(HERE, "universe.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 共留 {len(keep)} 檔 → {path}")


if __name__ == "__main__":
    main()
