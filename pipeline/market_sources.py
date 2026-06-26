"""免費官方資料源（TWSE 上市 / TPEX 上櫃），取代 FinMind。

把各端點正規化成 build_data.compute_indicators 吃的格式：
- OHLCV row: {date(ISO), open, max, min, close, Trading_Volume(股), Trading_money(元)}
- chip:      {sid: {"Foreign_Investor": net股, "Investment_Trust": net股}}

端點皆每日收盤資料、免費無額度。日期吃法：
- TWSE  用 YYYYMMDD；TPEX 用 YYYY/MM/DD；回應日期多為民國 "115/06/01" 或 "1150601"。
- ⚠️ TWSE STOCK_DAY_ALL 只回「最新交易日」（不吃過去 date）；回填上市歷史改用單股月表 STOCK_DAY。
"""
import csv
import io
import json
import subprocess
import time
import urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

TWSE_AT = "https://www.twse.com.tw/rwd/zh/afterTrading"
TWSE_FUND = "https://www.twse.com.tw/rwd/zh/fund"
TPEX = "https://www.tpex.org.tw/www/zh-tw"


# ── HTTP（curl 優先、urllib 後備、重試退避；跨環境最穩）────────────────
def _curl(url):
    out = subprocess.run(
        ["curl", "-s", "--http1.1", "-4", "-L", "--max-time", "40", "-A", UA, url],
        capture_output=True, text=True, timeout=50,
    )
    if out.returncode != 0 or not out.stdout:
        raise RuntimeError(f"curl rc={out.returncode}")
    return out.stdout


def _urllib(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8")


def get_text(url, retries=3):
    last = None
    for i in range(retries):
        for fn in (_curl, _urllib):
            try:
                return fn(url)
            except Exception as e:
                last = e
        time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"取得失敗（{retries} 次）：{last}")


def get_json(url):
    return json.loads(get_text(url))


# ── 工具 ──────────────────────────────────────────────────────────────
def _f(x):
    """容錯轉 float：去逗號/空白/色碼，'--'/'X'/'----' 視為 None。"""
    s = str(x).replace(",", "").replace("+", "").strip()
    if s in ("", "--", "---", "----", "X", "x", "N/A", "null"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def roc_to_iso(s):
    """民國日期 → 西元 ISO。接受 '115/06/01' 或 '1150601'。"""
    s = str(s).strip()
    if "/" in s:
        y, m, d = s.split("/")
    elif len(s) in (7, 8) and s.isdigit():           # 1150601 / 1150601
        y, m, d = s[:-4], s[-4:-2], s[-2:]
    else:
        return None
    return f"{int(y) + 1911:04d}-{int(m):02d}-{int(d):02d}"


def is_common_stock(sid):
    """只留 4 碼純數字普通股（排除 ETF/ETN/權證/DR/特別股等非 4 碼數字代號）。"""
    sid = str(sid).strip()
    return len(sid) == 4 and sid.isdigit()


def _ohlc(date_iso, o, h, lo, c, vol, money):
    o, h, lo, c = _f(o), _f(h), _f(lo), _f(c)
    if None in (o, h, lo, c):
        return None
    return {"date": date_iso, "open": o, "max": h, "min": lo, "close": c,
            "Trading_Volume": int(_f(vol) or 0), "Trading_money": _f(money) or 0}


# ── 上市 OHLCV ────────────────────────────────────────────────────────
def fetch_listed_ohlc_latest():
    """最新交易日全上市個股 OHLCV（STOCK_DAY_ALL，CSV）。回 (date_iso, {sid: row})。"""
    text = get_text(f"{TWSE_AT}/STOCK_DAY_ALL?date=&response=csv")
    rows = [r for r in csv.reader(io.StringIO(text)) if r and len(r) >= 9]
    out, date_iso = {}, None
    # 表頭：日期,證券代號,證券名稱,成交股數,成交金額,開盤價,最高價,最低價,收盤價,漲跌價差,成交筆數
    for r in rows[1:]:
        sid = r[1].strip()
        if not is_common_stock(sid):
            continue
        date_iso = roc_to_iso(r[0])
        row = _ohlc(date_iso, r[5], r[6], r[7], r[8], r[3], r[4])
        if row:
            out[sid] = row
    return date_iso, out


def fetch_listed_ohlc_month(sid, yyyymm):
    """單一上市股某月各日 OHLCV（STOCK_DAY，吃 date；回填上市歷史用）。回 list[row]。"""
    url = f"{TWSE_AT}/STOCK_DAY?stockNo={sid}&date={yyyymm}01&response=json"
    d = get_json(url)
    # fields：日期,成交股數,成交金額,開盤價,最高價,最低價,收盤價,漲跌價差,成交筆數
    out = []
    for r in d.get("data", []) or []:
        iso = roc_to_iso(r[0])
        row = _ohlc(iso, r[3], r[4], r[5], r[6], r[1], r[2])
        if row:
            out.append(row)
    return out


# ── 上櫃 OHLCV ────────────────────────────────────────────────────────
def fetch_otc_ohlc(date_iso):
    """指定日全上櫃個股 OHLCV（TPEX dailyQuotes，吃 date）。回 {sid: row}。"""
    y, m, d = date_iso.split("-")
    url = f"{TPEX}/afterTrading/dailyQuotes?date={y}/{m}/{d}&type=EW&response=json"
    data = get_json(url)
    tables = data.get("tables") or []
    out = {}
    # fields：代號,名稱,收盤,漲跌,開盤,最高,最低,均價,成交股數,成交金額(元)
    for t in tables:
        for r in t.get("data", []) or []:
            sid = str(r[0]).strip()
            if not is_common_stock(sid):
                continue
            row = _ohlc(date_iso, r[4], r[5], r[6], r[2], r[8], r[9])
            if row:
                out[sid] = row
    return out


# ── 三大法人（外資/投信 net 股數）────────────────────────────────────
def fetch_listed_chip(date_iso):
    """指定日全上市個股三大法人（T86，吃 date）。回 {sid: {Foreign_Investor, Investment_Trust}}。"""
    ymd = date_iso.replace("-", "")
    d = get_json(f"{TWSE_FUND}/T86?date={ymd}&selectType=ALLBUT0999&response=json")
    out = {}
    # [4]外陸資買賣超 [7]外資自營商買賣超 [10]投信買賣超（股）
    for r in d.get("data", []) or []:
        sid = str(r[0]).strip()
        if not is_common_stock(sid):
            continue
        foreign = (_f(r[4]) or 0) + (_f(r[7]) or 0)
        trust = _f(r[10]) or 0
        out[sid] = {"Foreign_Investor": foreign, "Investment_Trust": trust}
    return out


def fetch_otc_chip(date_iso):
    """指定日全上櫃個股三大法人（TPEX insti，吃 date）。回 {sid: {Foreign_Investor, Investment_Trust}}。"""
    y, m, d = date_iso.split("-")
    url = f"{TPEX}/insti/dailyTrade?date={y}/{m}/{d}&type=Daily&sect=EW&response=json"
    data = get_json(url)
    out = {}
    # [10]外資及陸資合計買賣超 [13]投信買賣超（股）
    for t in data.get("tables") or []:
        for r in t.get("data", []) or []:
            sid = str(r[0]).strip()
            if not is_common_stock(sid) or len(r) < 14:
                continue
            out[sid] = {"Foreign_Investor": _f(r[10]) or 0,
                        "Investment_Trust": _f(r[13]) or 0}
    return out
