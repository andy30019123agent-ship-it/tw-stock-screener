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

sys.path.insert(0, os.path.dirname(__file__))
import history_store as hs  # noqa: E402  （同目錄）

API = "https://api.finmindtrade.com/api/v4/data"
TOKEN = os.environ.get("FINMIND_TOKEN", "")
HERE = os.path.dirname(__file__)

# FinMind 額度防護：連續這麼多次 API 回報「額度用盡」就中止整個 run，避免 token 失效時
# 空轉跑完上千檔、燒光配額還產出殘缺資料。build_universe.py 共用 api_get 故一併受保護。
MAX_QUOTA_FAILS = 8
_quota_fails = 0

# 電子相關產業（上市 + 上櫃命名都涵蓋）
ELECTRONICS = {
    "電子工業", "半導體業", "電子零組件業", "光電業", "電腦及週邊設備業",
    "通信網路業", "其他電子業", "資訊服務業", "電子通路業",
    "數位雲端", "數位雲端類", "其他電子類",
}

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "public", "data")


def api_get(dataset, params=None, retries=3):
    global _quota_fails
    q = {"dataset": dataset}
    if params:
        q.update(params)
    if TOKEN:
        q["token"] = TOKEN
    url = f"{API}?{urlencode(q)}"
    hit_limit = False
    for attempt in range(retries):
        try:
            req = Request(url, headers={"User-Agent": "tw-screener/1.0"})
            with urlopen(req, timeout=30) as r:
                j = json.loads(r.read().decode())
            if j.get("status") == 200 or j.get("msg") == "success":
                _quota_fails = 0  # 成功一次就把連續計數歸零
                return j.get("data", [])
            # 額度用盡 → 等一下重試
            if "level" in str(j.get("msg", "")).lower() or "limit" in str(j.get("msg", "")).lower():
                print(f"  ⚠️ 額度限制：{j.get('msg')}")
                hit_limit = True
                time.sleep(8)
                continue
            return []
        except Exception as e:
            print(f"  ⚠️ 第 {attempt+1} 次失敗：{e}")
            time.sleep(3)
    # 重試用盡：若是「額度用盡」造成的，累計連續次數，超過上限就中止整個 run
    if hit_limit:
        _quota_fails += 1
        if _quota_fails >= MAX_QUOTA_FAILS:
            sys.exit(
                f"\n⛔ FinMind 連續 {_quota_fails} 次額度用盡（或 token 失效），中止本次執行以免"
                f"空轉跑完上千檔、燒光配額還產出殘缺資料。\n"
                f"   解法：改用 FinMind backer 等級 token，或等額度恢復後再跑。"
            )
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

    # ── 爆量突破起漲：悶久 → 帶量突破創新高 → 站上均線 ──
    # 對最近 5 個交易日逐日找「結構上合格的突破日」，吐候選給前端讓量倍數/回看天數可即時調。
    # 結構條件（與旋鈕無關，pipeline 先過濾好）：
    #   ① 突破前 20 日內曾糾結（dispersion < SQUEEZE_TH）
    #   ② 當日收盤創「前 20 日新高」（突破盤整上緣）
    #   ③ 當日收盤站上 MA5/10/20/60
    # 候選附帶：ago（幾天前，0=今天）、vr（當日量 ÷ 前 20 日均量 = 爆量倍數）
    vols_all = [r.get("Trading_Volume", 0) or 0 for r in price_rows]
    n = len(closes)
    breakout_cands = []
    for i in range(max(0, n - 5), n):
        if any(s[i] is None for s in (ma5s, ma10s, ma20s, ma60s)):
            continue
        ci = closes[i]
        above_all = ci > ma5s[i] and ci > ma10s[i] and ci > ma20s[i] and ci > ma60s[i]
        prior = closes[max(0, i - 20):i]
        new_high = len(prior) >= 10 and ci > max(prior)
        squeeze_before = any(
            (dispersion(j) is not None and dispersion(j) < SQUEEZE_TH)
            for j in range(max(0, i - 20), i)
        )
        if not (above_all and new_high and squeeze_before):
            continue
        prior_vols = vols_all[max(0, i - 20):i]
        avg_v = sum(prior_vols) / len(prior_vols) if prior_vols else 0
        vr = round(vols_all[i] / avg_v, 2) if avg_v else 0
        breakout_cands.append({"ago": n - 1 - i, "vr": vr})

    # 預設門檻（量 ≥ 1.8 倍、最近 3 天內）下是否成立 → 給標籤與 TG 評分用
    signal_breakout = bool(
        bull_aligned and ma_rising
        and any(c["ago"] <= 3 and c["vr"] >= 1.8 for c in breakout_cands)
    )

    # ── 小詩技術形態（布林軌道系列 + K 線形態）─────────────────────
    # 依「可轉債小詩」技術分析講義實作，全部只用價量、且需發生在最近 3 個交易日內才算。
    # 布林軌道：中軌 = 20MA，上/下軌 = 中軌 ± 2 標準差（講義的標準架構）。
    bars = [r for r in price_rows if r.get("close")]
    opens = [r.get("open") for r in bars]
    highs = [r.get("max") for r in bars]
    lows = [r.get("min") for r in bars]
    vols_bar = [(r.get("Trading_Volume", 0) or 0) for r in bars]
    BOLL_N, BOLL_K = 20, 2
    SN_RECENT = 3   # 形態需發生在最近 3 個交易日內

    def boll(i):
        """回傳 (中軌, 上軌, 下軌, 帶寬)；資料不足回 None。帶寬 = (上軌−下軌)/中軌。"""
        if i + 1 < BOLL_N:
            return None
        win = closes[i + 1 - BOLL_N:i + 1]
        m = sum(win) / BOLL_N
        sd = (sum((x - m) ** 2 for x in win) / BOLL_N) ** 0.5
        up, lo = m + BOLL_K * sd, m - BOLL_K * sd
        return m, up, lo, ((up - lo) / m if m else None)

    boll_cache = [boll(i) for i in range(n)]

    def avg_vol_before(i, w=20):
        seg = vols_bar[max(0, i - w):i]
        return sum(seg) / len(seg) if seg else 0

    def is_red(i):
        return opens[i] is not None and closes[i] > opens[i]

    def is_black(i):
        return opens[i] is not None and closes[i] < opens[i]

    # 縮口判斷門檻：以該股自身近 60 日「布林帶寬」的第 30 百分位為相對低檔
    bw_hist = [b[3] for b in boll_cache if b and b[3] is not None]
    bw_recent = sorted(bw_hist[-60:])
    bw_th = bw_recent[max(0, int(len(bw_recent) * 0.3) - 1)] if bw_recent else None

    sn = {"squeeze_breakout": False, "lower_reversal": False,
          "break_low_recover": False, "immortal_guide": False,
          "volume_support": False}

    for i in range(max(BOLL_N, n - SN_RECENT), n):
        b = boll_cache[i]
        if not b or opens[i] is None or highs[i] is None or lows[i] is None:
            continue
        mid, up, lo, _bw = b
        av = avg_vol_before(i)
        vr = (vols_bar[i] / av) if av else 0
        body = abs(closes[i] - opens[i])
        rng = highs[i] - lows[i]

        # 1. 縮口帶量突破：前 20 日內帶寬曾壓縮到相對低檔 → 當日帶量收上上軌
        if bw_th is not None:
            prior_bw = [boll_cache[j][3] for j in range(max(0, i - 20), i)
                        if boll_cache[j] and boll_cache[j][3] is not None]
            if any(x <= bw_th for x in prior_bw) and closes[i] > up and vr >= 1.5:
                sn["squeeze_breakout"] = True

        # 2. 連續黑K跌破下軌後翻紅：近幾日有黑K跌破下軌，當日翻紅站回軌內
        if is_red(i) and closes[i] > lo:
            broke = sum(1 for j in range(max(0, i - 4), i)
                        if boll_cache[j] and closes[j] < boll_cache[j][2])
            blacks = sum(1 for j in range(max(0, i - 4), i) if is_black(j))
            if broke >= 1 and blacks >= 2:
                sn["lower_reversal"] = True

        # 3. 破底翻：跌破前段區間低點後又迅速站回
        base = [x for x in lows[max(0, i - 40):max(0, i - 5)] if x is not None]
        if base:
            base_low = min(base)
            dip = min(x for x in lows[max(0, i - 8):i + 1] if x is not None)
            if dip < base_low and closes[i] > base_low:
                sn["break_low_recover"] = True

        # 4. 仙人指路：帶量(不爆量)長上影小實體K、位階不高、貼近前壓力區
        prior_high = max([h for h in highs[max(0, i - 20):i] if h is not None], default=None)
        if rng > 0 and prior_high:
            upper_shadow = highs[i] - max(opens[i], closes[i])
            if (body <= 0.035 * closes[i]                 # 小實體
                    and upper_shadow >= 2 * body and upper_shadow >= 0.5 * rng  # 長上影
                    and 1.2 <= vr <= 2.5                  # 帶量但不爆量
                    and closes[i] >= 0.95 * prior_high    # 貼近前壓力
                    and mid and closes[i] <= mid * 1.12): # 位階不高（未大幅偏離中軌）
                sn["immortal_guide"] = True

        # 5. 大量低點防守：近 20 日出現「大量紅K」(量≥2.5倍且收紅)，當日拉回貼著其低點 2% 內守住
        #    （小詩：大量紅K的低點是多數人的成本，守住不破＝主力洗盤喝了再上）
        for j in range(max(0, i - 20), i):
            avj = avg_vol_before(j)
            if avj and vols_bar[j] >= 2.5 * avj and is_red(j) and lows[j] is not None:
                sup = lows[j]
                if sup <= closes[i] <= sup * 1.02:
                    sn["volume_support"] = True
                    break

    SN_LABELS = {
        "squeeze_breakout": "縮口帶量突破", "lower_reversal": "破下軌翻紅",
        "break_low_recover": "破底翻", "immortal_guide": "仙人指路",
        "volume_support": "大量撐",
    }
    sn_tags = [SN_LABELS[k] for k in SN_LABELS if sn[k]]
    signal_shishi = len(sn_tags) > 0

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
        "breakout_cands": breakout_cands,
        "signal_breakout": signal_breakout,
        # 小詩技術形態（布林軌道系列）
        "sn_squeeze_breakout": sn["squeeze_breakout"],
        "sn_lower_reversal": sn["lower_reversal"],
        "sn_break_low_recover": sn["break_low_recover"],
        "sn_immortal_guide": sn["immortal_guide"],
        "sn_volume_support": sn["volume_support"],
        "sn_tags": sn_tags,
        "signal_shishi": signal_shishi,
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


# ── 集保千張大戶（TDCC 股權分散表，免費 OpenData）────────────────
# 持股分級 15 = 1,000,001 股以上 = 1000 張以上 = 千張大戶
TDCC_OPENDATA = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
BIG_HOLDER_LEVEL = "15"
HOLDER_HISTORY_PATH = os.path.join(os.path.dirname(__file__), "holders_history.json")
HOLDER_MAX_WEEKS = 12   # 歷史只留最近 N 週


def fetch_tdcc_big_holders():
    """下載集保最新一週股權分散表，回傳 (週日期YYYYMMDD, {股票代號: 千張大戶占比%})。失敗回 (None, {})。"""
    import csv, io
    try:
        req = Request(TDCC_OPENDATA, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=90) as r:
            raw = r.read().decode("utf-8-sig", errors="replace")
    except Exception as e:
        print(f"  ⚠️ 集保資料下載失敗：{e}")
        return None, {}
    week, pct_by_id = None, {}
    for row in csv.reader(io.StringIO(raw)):
        if len(row) < 6 or row[2].strip() != BIG_HOLDER_LEVEL:
            continue
        week = row[0].strip()
        try:
            pct_by_id[row[1].strip()] = float(row[5])
        except ValueError:
            pass
    return week, pct_by_id


def update_holder_history(week, pct_by_id):
    """把本週千張大戶占比併入歷史檔（同週去重、只留最近 N 週），回傳 history dict。"""
    history = {}
    if os.path.exists(HOLDER_HISTORY_PATH):
        try:
            with open(HOLDER_HISTORY_PATH, encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = {}
    if not week or not pct_by_id:
        return history   # 沒抓到資料就不動歷史
    for sid, pct in pct_by_id.items():
        lst = [e for e in history.get(sid, []) if e["w"] != week]
        lst.append({"w": week, "pct": pct})
        lst.sort(key=lambda e: e["w"])             # 舊 → 新
        history[sid] = lst[-HOLDER_MAX_WEEKS:]
    with open(HOLDER_HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, separators=(",", ":"))
    return history


def holder_signal(hist):
    """從某股歷史算千張大戶指標，回傳 dict。週數 < 2 時 rising = None（資料不足）。"""
    lst = hist or []
    pct = lst[-1]["pct"] if len(lst) >= 1 else None
    prev = lst[-2]["pct"] if len(lst) >= 2 else None
    rising = (pct > prev) if len(lst) >= 2 else None
    return {
        "holder_pct": pct,
        "holder_prev": prev,
        "holder_rising": rising,
        "holder_weeks": len(lst),
        "holder_hist": [e["pct"] for e in lst[-8:]],   # 給前端畫趨勢用
    }


def load_universe_file():
    with open(os.path.join(HERE, "universe.json"), encoding="utf-8") as f:
        return json.load(f)["stocks"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", help="只跑指定股票代號（逗號分隔）")
    ap.add_argument("--limit", type=int, help="只跑前 N 檔")
    ap.add_argument("--min-vol", type=int, default=500,
                    help="只輸出 20 日均量 ≥ N 張的「有量」股（預設 500）")
    args = ap.parse_args()

    print("📡 載入全市場清單與歷史（TWSE/TPEX 免費源，不用 FinMind）…")
    universe = load_universe_file()
    if args.sample:
        ids = set(s.strip() for s in args.sample.split(","))
        universe = [u for u in universe if u["id"] in ids]
    if args.limit:
        universe = universe[:args.limit]
    print(f"   全市場 {len(universe)} 檔")

    # 集保千張大戶：下載最新一週、併入歷史檔（每週累積）— 不變
    print("📦 取得集保千張大戶（TDCC）…")
    holder_week, holder_pct = fetch_tdcc_big_holders()
    holder_history = update_holder_history(holder_week, holder_pct)
    print(f"   集保資料週：{holder_week or '無'}，本市場 {len(holder_pct)} 檔")

    price_hist = hs.load(os.path.join(HERE, "history", "price.json"))
    chip_hist = hs.load(os.path.join(HERE, "history", "chip.json"))
    print(f"   歷史：price {len(price_hist)} 檔、chip {len(chip_hist)} 檔\n")

    charts_dir = os.path.join(OUT_DIR, "charts")
    os.makedirs(charts_dir, exist_ok=True)
    results = []
    data_dates = []   # 全市場最後一根 K 線日期 → 這份資料的交易日
    for stock in universe:
        sid = stock["id"]
        pr = hs.to_price_rows(price_hist.get(sid, {}))
        if len(pr) < 65:                          # 歷史不足算不了 MA60 → 略過
            continue
        cr = hs.to_chip_rows(chip_hist.get(sid, {}))
        ind = compute_indicators(pr, cr)
        if ind is None or ind["avg_vol_lots"] < args.min_vol:
            continue
        ohlc = ind.pop("ohlc")                    # K 線拆到 charts/<id>.json（前端按需載入）
        if ohlc:
            data_dates.append(ohlc[-1]["t"])      # 拆出前先記下交易日（給 notify 閘門用）
        ind.update(stock)                         # id, name, market, industry
        ind.update(holder_signal(holder_history.get(sid)))
        results.append(ind)
        with open(os.path.join(charts_dir, f"{sid}.json"), "w", encoding="utf-8") as f:
            json.dump({"id": sid, "name": stock["name"], "ohlc": ohlc}, f,
                      ensure_ascii=False, separators=(",", ":"))

    os.makedirs(OUT_DIR, exist_ok=True)
    holder_ready = max((r["holder_weeks"] for r in results), default=0) >= 2
    out = {
        "updated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "data_date": max(data_dates) if data_dates else None,   # 資料交易日（notify 只推新交易日用）
        "count": len(results),
        "universe_count": len(universe),    # 全市場掃描檔數（資訊用）
        "holder_ready": holder_ready,
        "holder_week": holder_week,
        "stocks": results,
    }
    path = os.path.join(OUT_DIR, "screener.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    size_mb = round(os.path.getsize(path) / 1e6, 2)
    print(f"✅ 完成，輸出 {len(results)} 檔（screener.json {size_mb}MB）+ {len(results)} 個 charts/")


if __name__ == "__main__":
    main()
