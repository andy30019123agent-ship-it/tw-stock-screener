#!/usr/bin/env python3
"""
台股電子股選股 — 資料管線
抓 FinMind 全電子股的價格＋三大法人，算技術＋籌碼指標，輸出前端用的 JSON。

用法：
    FINMIND_TOKEN=xxx python3 build_data.py            # 跑全部電子股
    python3 build_data.py --sample 2330,2317,2454      # 只跑指定股票（驗證用）
    python3 build_data.py --limit 15                   # 只跑前 N 檔（驗證用）

免費版沒 token 也能跑（單檔查詢），但有額度限制；要每天自動跑全電子股建議用
FinMind 贊助者(backer)等級的 token。
"""
import os
import sys
import json
import time
import argparse
import datetime as dt
from urllib.parse import urlencode
from urllib.request import urlopen, Request

API = "https://api.finmindtrade.com/api/v4/data"
TOKEN = os.environ.get("FINMIND_TOKEN", "")

# 電子相關產業（上市 + 上櫃命名都涵蓋）
ELECTRONICS = {
    "電子工業", "半導體業", "電子零組件業", "光電業", "電腦及週邊設備業",
    "通信網路業", "其他電子業", "資訊服務業", "電子通路業",
    "數位雲端", "數位雲端類", "其他電子類",
}

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "public", "data")


def api_get(dataset, params=None, retries=3):
    q = {"dataset": dataset}
    if params:
        q.update(params)
    if TOKEN:
        q["token"] = TOKEN
    url = f"{API}?{urlencode(q)}"
    for attempt in range(retries):
        try:
            req = Request(url, headers={"User-Agent": "tw-screener/1.0"})
            with urlopen(req, timeout=30) as r:
                j = json.loads(r.read().decode())
            if j.get("status") == 200 or j.get("msg") == "success":
                return j.get("data", [])
            # 額度用盡 → 等一下重試
            if "level" in str(j.get("msg", "")).lower() or "limit" in str(j.get("msg", "")).lower():
                print(f"  ⚠️ 額度限制：{j.get('msg')}")
                time.sleep(8)
                continue
            return []
        except Exception as e:
            print(f"  ⚠️ 第 {attempt+1} 次失敗：{e}")
            time.sleep(3)
    return []


def get_universe():
    """取得電子股清單（排除 ETF、權證、存託憑證；只留 4 碼純數字代號）。"""
    rows = api_get("TaiwanStockInfo")
    seen = {}
    for x in rows:
        sid = x["stock_id"]
        if x.get("industry_category") not in ELECTRONICS:
            continue
        if not (len(sid) == 4 and sid.isdigit()):
            continue
        seen[sid] = {"id": sid, "name": x["stock_name"],
                     "industry": x["industry_category"],
                     "market": x.get("type", "twse")}
    return list(seen.values())


def sma(vals, n):
    if len(vals) < n:
        return None
    return sum(vals[-n:]) / n


def sma_series(closes, n):
    out = []
    for i in range(len(closes)):
        if i + 1 < n:
            out.append(None)
        else:
            out.append(sum(closes[i + 1 - n:i + 1]) / n)
    return out


def compute_indicators(price_rows, chip_rows):
    """從原始資料算出該股的指標字典；資料不足回 None。"""
    price_rows = sorted(price_rows, key=lambda r: r["date"])
    closes = [r["close"] for r in price_rows if r.get("close")]
    if len(closes) < 65:
        return None

    dates = [r["date"] for r in price_rows]
    last_close = closes[-1]
    prev_close = closes[-2]
    change = round(last_close - prev_close, 2)
    change_pct = round(change / prev_close * 100, 2) if prev_close else 0
    volume = price_rows[-1].get("Trading_Volume", 0)

    # 20 日均量（張 = 股數 / 1000），用來判斷「有沒有量」
    vols = [r.get("Trading_Volume", 0) or 0 for r in price_rows[-20:]]
    avg_vol_lots = round(sum(vols) / len(vols) / 1000) if vols else 0
    # 20 日均成交額（億元）
    moneys = [r.get("Trading_money", 0) or 0 for r in price_rows[-20:]]
    avg_money_e = round(sum(moneys) / len(moneys) / 1e8, 2) if moneys else 0

    ma5s = sma_series(closes, 5)
    ma10s = sma_series(closes, 10)
    ma20s = sma_series(closes, 20)
    ma60s = sma_series(closes, 60)
    ma5, ma10, ma20, ma60 = ma5s[-1], ma10s[-1], ma20s[-1], ma60s[-1]

    # 均線離散度（發散/糾結程度）：(最大MA − 最小MA) / 收盤
    def dispersion(i):
        vals = [ma5s[i], ma10s[i], ma20s[i], ma60s[i]]
        if any(v is None for v in vals):
            return None
        return (max(vals) - min(vals)) / closes[i]

    disp_now = dispersion(len(closes) - 1)

    # 多頭排列：MA5>MA10>MA20>MA60
    bull_aligned = ma5 > ma10 > ma20 > ma60

    # 均線上彎：每條 MA 高於 3 天前
    def rising(series):
        return series[-1] is not None and series[-4] is not None and series[-1] > series[-4]
    ma_rising = all(rising(s) for s in (ma5s, ma10s, ma20s))

    # 近 20 天內是否出現過「糾結」（離散度 < 3%）
    SQUEEZE_TH = 0.03
    squeeze_days = []
    for i in range(max(0, len(closes) - 20), len(closes)):
        d = dispersion(i)
        if d is not None and d < SQUEEZE_TH:
            squeeze_days.append(i)
    squeeze_recent = len(squeeze_days) > 0
    min_squeeze_disp = min((dispersion(i) for i in squeeze_days), default=None)

    # 黃金交叉：MA5 近 10 天內由下往上穿過 MA20
    golden_cross_recent = False
    for i in range(max(1, len(closes) - 10), len(closes)):
        if (ma5s[i] is not None and ma20s[i] is not None
                and ma5s[i - 1] is not None and ma20s[i - 1] is not None):
            if ma5s[i - 1] <= ma20s[i - 1] and ma5s[i] > ma20s[i]:
                golden_cross_recent = True
                break

    # 發散：現在離散度 > 糾結時的離散度（代表從糾結放大開來）
    diverging = (disp_now is not None and min_squeeze_disp is not None
                 and disp_now > min_squeeze_disp)

    # 綜合訊號：近期糾結 → 黃金交叉 → 多頭發散
    signal_ma = bool(squeeze_recent and golden_cross_recent
                     and bull_aligned and ma_rising and diverging)

    # ── 籌碼：外資 / 投信 連續買超天數 ──
    by_date = {}
    for c in chip_rows:
        nm, d = c.get("name"), c.get("date")
        net = (c.get("buy", 0) or 0) - (c.get("sell", 0) or 0)
        by_date.setdefault(d, {})[nm] = net
    chip_dates = sorted(by_date.keys())

    def streak(investor):
        s = 0
        for d in reversed(chip_dates):
            if by_date[d].get(investor, 0) > 0:
                s += 1
            else:
                break
        return s

    foreign_streak = streak("Foreign_Investor")
    trust_streak = streak("Investment_Trust")
    foreign_net = by_date[chip_dates[-1]].get("Foreign_Investor", 0) if chip_dates else 0
    trust_net = by_date[chip_dates[-1]].get("Investment_Trust", 0) if chip_dates else 0

    return {
        "close": round(last_close, 2),
        "change": change,
        "change_pct": change_pct,
        "volume": volume,
        "avg_vol_lots": avg_vol_lots,
        "avg_money_e": avg_money_e,
        "ma5": round(ma5, 2), "ma10": round(ma10, 2),
        "ma20": round(ma20, 2), "ma60": round(ma60, 2),
        "dispersion_pct": round(disp_now * 100, 2) if disp_now is not None else None,
        "bull_aligned": bull_aligned,
        "ma_rising": ma_rising,
        "squeeze_recent": squeeze_recent,
        "golden_cross_recent": golden_cross_recent,
        "diverging": diverging,
        "signal_ma": signal_ma,
        "foreign_net": foreign_net,
        "trust_net": trust_net,
        "foreign_streak": foreign_streak,
        "trust_streak": trust_streak,
        # 給前端畫迷你走勢圖用（最後 60 個收盤）
        "spark": [round(c, 2) for c in closes[-60:]],
        # 給彈窗畫 K 線用（最後 80 根：日期, 開, 高, 低, 收, 量張）
        "ohlc": [
            {
                "t": r["date"],
                "o": round(r["open"], 2), "h": round(r["max"], 2),
                "l": round(r["min"], 2), "c": round(r["close"], 2),
                "v": round((r.get("Trading_Volume", 0) or 0) / 1000),
            }
            for r in price_rows[-80:]
            if r.get("open") and r.get("close")
        ],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", help="只跑指定股票代號（逗號分隔）")
    ap.add_argument("--universe-file", help="從 JSON 檔讀股票清單（{ids:[...]}）")
    ap.add_argument("--limit", type=int, help="只跑前 N 檔")
    ap.add_argument("--days", type=int, default=130, help="抓幾天歷史（預設 130）")
    ap.add_argument("--sleep", type=float, default=0.4, help="每次請求間隔秒數")
    ap.add_argument("--min-vol", type=int, default=500,
                    help="只輸出 20 日均量 ≥ N 張的「有量」電子股（預設 500）")
    args = ap.parse_args()

    today = dt.date.today()
    start = (today - dt.timedelta(days=int(args.days * 1.6))).isoformat()
    end = today.isoformat()
    chip_start = (today - dt.timedelta(days=40)).isoformat()

    print(f"📡 取得電子股清單…（token：{'有' if TOKEN else '無，用免費額度'}）")
    universe = get_universe()
    print(f"   電子股共 {len(universe)} 檔")

    if args.universe_file:
        with open(args.universe_file, encoding="utf-8") as f:
            ids = set(json.load(f).get("ids", []))
        universe = [u for u in universe if u["id"] in ids]
        print(f"   依清單篩選 → {len(universe)} 檔")
    if args.sample:
        ids = set(s.strip() for s in args.sample.split(","))
        universe = [u for u in universe if u["id"] in ids]
    if args.limit:
        universe = universe[:args.limit]
    print(f"   本次處理 {len(universe)} 檔\n")

    results = []
    for i, stock in enumerate(universe, 1):
        sid = stock["id"]
        print(f"[{i}/{len(universe)}] {sid} {stock['name']}", end="  ")
        price = api_get("TaiwanStockPrice",
                        {"data_id": sid, "start_date": start, "end_date": end})
        time.sleep(args.sleep)
        chip = api_get("TaiwanStockInstitutionalInvestorsBuySell",
                       {"data_id": sid, "start_date": chip_start, "end_date": end})
        time.sleep(args.sleep)
        ind = compute_indicators(price, chip)
        if ind is None:
            print("資料不足，略過")
            continue
        if ind["avg_vol_lots"] < args.min_vol:
            print(f"量太小（{ind['avg_vol_lots']} 張），略過")
            continue
        ind.update(stock)
        results.append(ind)
        tags = []
        if ind["signal_ma"]:
            tags.append("✨糾結後多頭")
        if ind["bull_aligned"]:
            tags.append("多頭排列")
        if ind["foreign_streak"] >= 3:
            tags.append(f"外資連買{ind['foreign_streak']}")
        if ind["trust_streak"] >= 3:
            tags.append(f"投信連買{ind['trust_streak']}")
        print(", ".join(tags) if tags else "—")

    os.makedirs(OUT_DIR, exist_ok=True)
    out = {
        "updated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "count": len(results),
        "expected": len(universe),   # 本次清單原本要處理的檔數，前端用來判斷是否抓太少
        "stocks": results,
    }
    path = os.path.join(OUT_DIR, "screener.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\n✅ 完成，輸出 {len(results)} 檔 → {os.path.relpath(path)}")


if __name__ == "__main__":
    main()
