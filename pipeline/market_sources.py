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
import re
import subprocess
import time
import urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

TWSE_AT = "https://www.twse.com.tw/rwd/zh/afterTrading"
TWSE_FUND = "https://www.twse.com.tw/rwd/zh/fund"
TPEX = "https://www.tpex.org.tw/www/zh-tw"
TWSE_OPENAPI = "https://openapi.twse.com.tw/v1"
TPEX_OPENAPI = "https://www.tpex.org.tw/openapi/v1"


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


def roc_label_to_iso(s):
    """民國「115年07月03日」格式（TWT49U 除權除息表用）→ 西元 ISO。"""
    m = re.match(r"(\d+)年(\d+)月(\d+)日", str(s).strip())
    if not m:
        return None
    y, mo, d = m.groups()
    return f"{int(y) + 1911:04d}-{int(mo):02d}-{int(d):02d}"


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


def fetch_listed_ohlc(date_iso):
    """指定日全上市個股 OHLCV（MI_INDEX type=ALL 的個股表，吃過去 date）。回 {sid: row}。
    比逐檔 STOCK_DAY 快太多、且不會被 TWSE 限流（一請求一天、全市場）。"""
    ymd = date_iso.replace("-", "")
    d = get_json(f"{TWSE_AT}/MI_INDEX?date={ymd}&type=ALL&response=json")
    out = {}
    for t in d.get("tables", []) or []:
        f = [str(x) for x in t.get("fields", [])]
        if not (f and f[0] == "證券代號" and any("收盤價" in x for x in f)):
            continue
        # 欄位：證券代號,證券名稱,成交股數,成交筆數,成交金額,開盤價,最高價,最低價,收盤價,…
        for r in t.get("data", []) or []:
            sid = str(r[0]).strip()
            if not is_common_stock(sid):
                continue
            row = _ohlc(date_iso, r[5], r[6], r[7], r[8], r[2], r[4])
            if row:
                out[sid] = row
        break
    return out


def fetch_taiex_close(date_iso):
    """指定日加權指數（TAIEX）收盤（MI_INDEX type=IND，吃過去 date，跟 fetch_listed_ohlc 同端點家族）。
    給相對強弱 RS 計算用的大盤基準。非交易日（假日/週末）資料表是空的，回 None。"""
    ymd = date_iso.replace("-", "")
    d = get_json(f"{TWSE_AT}/MI_INDEX?date={ymd}&type=IND&response=json")
    for t in d.get("tables", []) or []:
        for r in t.get("data", []) or []:
            if r and r[0] == "發行量加權股價指數":
                return _f(r[1])
    return None


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


# ── 估值指標（本益比 / 本淨比 / 現金殖利率）──────────────────────────
def fetch_valuation():
    """全市場每股估值：本益比 pe / 本淨比 pb / 現金殖利率 yield_pct(%)。回 {sid: {...}}。
    上市 TWSE OpenAPI BWIBBU_ALL、上櫃 TPEX OpenAPI peratio_analysis，皆免費、每日更新。
    本益比為空（無獲利）時 pe = None。"""
    out = {}
    # 上市
    try:
        for r in get_json(f"{TWSE_OPENAPI}/exchangeReport/BWIBBU_ALL"):
            sid = str(r.get("Code", "")).strip()
            if not is_common_stock(sid):
                continue
            out[sid] = {"pe": _f(r.get("PEratio")), "pb": _f(r.get("PBratio")),
                        "yield_pct": _f(r.get("DividendYield"))}
    except Exception as e:
        print(f"  ⚠️ 上市估值抓取失敗：{e}")
    # 上櫃
    try:
        for r in get_json(f"{TPEX_OPENAPI}/tpex_mainboard_peratio_analysis"):
            sid = str(r.get("SecuritiesCompanyCode", "")).strip()
            if not is_common_stock(sid):
                continue
            out[sid] = {"pe": _f(r.get("PriceEarningRatio")), "pb": _f(r.get("PriceBookRatio")),
                        "yield_pct": _f(r.get("YieldRatio"))}
    except Exception as e:
        print(f"  ⚠️ 上櫃估值抓取失敗：{e}")
    return out


# ── 除權息事件（技術指標還原權息用）──────────────────────────────────
def fetch_ex_dividend_events(start_iso, end_iso):
    """區間內全市場（上市+上櫃）除權息事件：{sid: [{"date": iso, "ratio": float}, ...]}。
    ratio = 除權息參考價 / 除權息前收盤價（<1 代表除息/除權讓價格機械性下修，用來把
    事件日「之前」的歷史價格 back-adjust 回同一把尺，避免均線/黃金交叉誤判）。
    上市 TWSE TWT49U、上櫃 TPEX exDailyQ_result.php 皆吃日期區間、一次全市場一次全區間，
    不像逐日 OHLCV 那樣要一天一天抓。"""
    out = {}

    def add(sid, date_iso, pre, ref):
        pre_f, ref_f = _f(pre), _f(ref)
        if not pre_f or pre_f <= 0 or ref_f is None:
            return
        out.setdefault(sid, []).append({"date": date_iso, "ratio": ref_f / pre_f})

    # 上市：TWT49U，欄位 資料日期(民國"115年07月03日")/股票代號/股票名稱/除權息前收盤價/除權息參考價/…
    try:
        sd, ed = start_iso.replace("-", ""), end_iso.replace("-", "")
        d = get_json(f"https://www.twse.com.tw/rwd/zh/exRight/TWT49U?startDate={sd}&endDate={ed}&response=json")
        for r in d.get("data", []) or []:
            sid = str(r[1]).strip()
            if not is_common_stock(sid):
                continue
            date_iso = roc_label_to_iso(r[0])
            if date_iso:
                add(sid, date_iso, r[3], r[4])
    except Exception as e:
        print(f"  ⚠️ 上市除權息抓取失敗：{e}")

    # 上櫃：exDailyQ_result.php，欄位 除權息日期(民國"115/07/03")/代號/名稱/除權息前收盤價/除權息參考價/…
    try:
        sy, sm, sday = start_iso.split("-")
        ey, em, eday = end_iso.split("-")
        url = ("https://www.tpex.org.tw/web/stock/exright/dailyquo/exDailyQ_result.php"
               f"?l=zh-tw&d={sy}/{sm}/{sday}&ed={ey}/{em}/{eday}")
        d = get_json(url)
        for t in d.get("tables", []) or []:
            for r in t.get("data", []) or []:
                sid = str(r[1]).strip()
                if not is_common_stock(sid):
                    continue
                date_iso = roc_to_iso(r[0])
                if date_iso:
                    add(sid, date_iso, r[3], r[4])
    except Exception as e:
        print(f"  ⚠️ 上櫃除權息抓取失敗：{e}")
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
