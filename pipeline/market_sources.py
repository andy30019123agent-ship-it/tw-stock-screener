"""免費官方資料源（TWSE 上市 / TPEX 上櫃），取代 FinMind。

把各端點正規化成 build_data.compute_indicators 吃的格式：
- OHLCV row: {date(ISO), open, max, min, close, Trading_Volume(股), Trading_money(元)}
- chip:      {sid: {"Foreign_Investor": net股, "Investment_Trust": net股}}

端點皆每日收盤資料、免費無額度。日期吃法：
- TWSE  用 YYYYMMDD；TPEX 用 YYYY/MM/DD；回應日期多為民國 "115/06/01" 或 "1150601"。
- ⚠️ TWSE STOCK_DAY_ALL 只回「最新交易日」（不吃過去 date）；回填上市歷史改用單股月表 STOCK_DAY。
"""
import contextlib
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
# 逾時與重試次數放模組層級，讓「不能拖太久」的呼叫端（漏抓回補）用 http_limits 暫時調短；
# 預設值維持原本（curl 40 秒、urllib 20 秒、3 輪），每日主流程與回填腳本的行為不變。
CURL_MAX_TIME = 40
URLLIB_TIMEOUT = 20
HTTP_RETRIES = 3


@contextlib.contextmanager
def http_limits(curl_max_time, urllib_timeout, retries):
    """暫時調短逾時／重試（離開 with 一定還原）。單一 URL 最壞耗時約
    retries×(curl_max_time+urllib_timeout) + 1.5×(1+…+retries) 秒。"""
    global CURL_MAX_TIME, URLLIB_TIMEOUT, HTTP_RETRIES
    old = (CURL_MAX_TIME, URLLIB_TIMEOUT, HTTP_RETRIES)
    CURL_MAX_TIME, URLLIB_TIMEOUT, HTTP_RETRIES = curl_max_time, urllib_timeout, retries
    try:
        yield
    finally:
        CURL_MAX_TIME, URLLIB_TIMEOUT, HTTP_RETRIES = old


def _curl(url):
    out = subprocess.run(
        ["curl", "-s", "--http1.1", "-4", "-L", "--max-time", str(CURL_MAX_TIME), "-A", UA, url],
        capture_output=True, text=True, timeout=CURL_MAX_TIME + 10,
    )
    if out.returncode != 0 or not out.stdout:
        raise RuntimeError(f"curl rc={out.returncode}")
    return out.stdout


def _urllib(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=URLLIB_TIMEOUT) as r:
        return r.read().decode("utf-8")


def get_text(url, retries=None):
    retries = HTTP_RETRIES if retries is None else retries
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
    # close<=0 視為無效整列丟棄：TWSE 對零股/極低量成交會回 "0.00"（_f 視為合法 0.0，不是 None），
    # 若不擋這裡，殭屍股會被寫進歷史當成「跌到 0 元」，污染漲跌幅與指標。
    if None in (o, h, lo, c) or c <= 0:
        return None
    return {"date": date_iso, "open": o, "max": h, "min": lo, "close": c,
            "Trading_Volume": int(_f(vol) or 0), "Trading_money": _f(money) or 0}


def _date_mismatch(date_iso, *candidates):
    """回應裡標的資料日期跟請求的不同 → 回那個日期字串；一致或回應沒標日期 → 回 None。
    candidates 接 ISO 日期（None 會略過）。2026-11-13 實測：TWSE MI_INDEX 的個股表標題含
    「115年11月11日」、TPEX dailyQuotes 的表有 date="115/11/11"（頂層 date 只是回聲請求參數，不採信）。"""
    for c in candidates:
        if c and c != date_iso:
            return c
    return None


def _table_date_or_none(raw, source):
    """把回應裡的民國日期欄解析成 ISO；解析不了（格式改版，例如 '115/11/11 (三)'）→ 印 warning、回 None
    ＝「無法比對日期」，呼叫端照原本行為收資料。只放寬「解析不了」；解析得出來但日期不符仍由
    _date_mismatch 擋。比對日期是新增的保護，不能因它自己壞掉而讓每日更新當掉。"""
    if not raw:
        return None
    try:
        iso = roc_to_iso(raw)
    except (ValueError, TypeError):
        iso = None
    if iso is None:
        print(f"  ⚠️ {source} 日期欄格式無法解析（{raw!r}）→ 無法比對日期，照收資料")
    return iso


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
        # 表標題「115年11月11日 每日收盤行情(全部)」＝這張表實際的資料日；跟請求不同就整包不收
        # （官方回了別天的資料卻被蓋上請求日期，比缺一天更難發現）。
        bad = _date_mismatch(date_iso, roc_label_to_iso(str(t.get("title", "")).split(" ")[0]))
        if bad:
            print(f"  ⚠️ 上市 OHLCV 請求 {date_iso} 卻回 {bad} 的資料 → 不收")
            return {}
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


def fetch_trading_days_month(ym):
    """某月份的「官方交易日清單＋當日加權指數收盤」（TWSE FMTQIK 市場成交資訊，一請求一個月）。
    ym＝"YYYYMM"。回 {date_iso: 加權指數收盤}。

    給漏抓回補（gap_backfill.py）當「應有交易日」基準：它跟每日抓個股的 STOCK_DAY_ALL 是
    不同端點、不同時間抓，每日那條路漏掉的日子，這裡照樣列得出來。
    ⚠️ 回空（{}）≠「那個月沒交易」——限流、夜間維護都會回空；呼叫端要把空當成「基準未知」。"""
    d = get_json(f"{TWSE_AT}/FMTQIK?date={ym}01&response=json")
    out = {}
    # 欄位：日期,成交股數,成交金額,成交筆數,發行量加權股價指數,漲跌點數
    for r in d.get("data", []) or []:
        iso = roc_to_iso(r[0]) if r else None
        if iso:
            out[iso] = _f(r[4]) if len(r) > 4 else None
    return out


# 註：舊的「逐月抓單一上市股 OHLCV」（STOCK_DAY，fetch_listed_ohlc_month）已於 2026-07-25 移除
# ——回填改走逐日全市場的 fetch_listed_ohlc(day)（backfill.py:50），逐檔 STOCK_DAY 還會被 TWSE 限流。


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
        # 表的 date（民國 "115/11/11"）＝實際資料日；跟請求不同就整包不收（理由同 fetch_listed_ohlc）
        bad = _date_mismatch(date_iso, _table_date_or_none(t.get("date"), "上櫃 OHLCV"))
        if bad:
            print(f"  ⚠️ 上櫃 OHLCV 請求 {date_iso} 卻回 {bad} 的資料 → 不收")
            return {}
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
def fetch_ex_dividend_events(start_iso, end_iso, sources_ok=None):
    """區間內全市場（上市+上櫃）除權息事件：{sid: [{"date": iso, "ratio": float}, ...]}。
    ratio = 除權息參考價 / 除權息前收盤價（<1 代表除息/除權讓價格機械性下修，用來把
    事件日「之前」的歷史價格 back-adjust 回同一把尺，避免均線/黃金交叉誤判）。
    上市 TWSE TWT49U、上櫃 TPEX exDailyQ_result.php 皆吃日期區間、一次全市場一次全區間，
    不像逐日 OHLCV 那樣要一天一天抓。

    sources_ok（可選傳入 dict）：呼叫端想知道「上市/上櫃各自成功了嗎」時傳一個 dict 進來，
    函式會填 {"listed": bool, "otc": bool}。⚠️ 2026-07-25 Codex 指出的洞：兩個市場各自
    try/except 印警告後繼續，**只要有一邊成功、外層就看不出另一邊掛了**——回填腳本會把
    「缺了半個市場」的區間標成完整涵蓋。這正是本檔想防的「靜默成功」再深一層。
    """
    out = {}
    if sources_ok is None:
        sources_ok = {}
    sources_ok.setdefault("listed", False)
    sources_ok.setdefault("otc", False)
    # 各市場回應的原始資料列數：TWSE 限流時會「回 JSON 但沒有資料」（backfill_dividends_bt.py 記過），
    # 光看 listed/otc=True 分不出「真的沒除權息」跟「被限流回空」——呼叫端用列數 0 判斷要不要重查。
    sources_ok["listed_rows"] = 0
    sources_ok["otc_rows"] = 0

    def add(sid, date_iso, pre, ref):
        pre_f, ref_f = _f(pre), _f(ref)
        if not pre_f or pre_f <= 0 or ref_f is None:
            return
        out.setdefault(sid, []).append({"date": date_iso, "ratio": ref_f / pre_f})

    # 上市：TWT49U，欄位 資料日期(民國"115年07月03日")/股票代號/股票名稱/除權息前收盤價/除權息參考價/…
    try:
        sd, ed = start_iso.replace("-", ""), end_iso.replace("-", "")
        d = get_json(f"https://www.twse.com.tw/rwd/zh/exRight/TWT49U?startDate={sd}&endDate={ed}&response=json")
        sources_ok["listed_rows"] = len(d.get("data", []) or [])
        for r in d.get("data", []) or []:
            sid = str(r[1]).strip()
            if not is_common_stock(sid):
                continue
            date_iso = roc_label_to_iso(r[0])
            if date_iso:
                add(sid, date_iso, r[3], r[4])
        sources_ok["listed"] = True
    except Exception as e:
        print(f"  ⚠️ 上市除權息抓取失敗：{e}")

    # 上櫃：exDailyQ_result.php，欄位 除權息日期(民國"115/07/03")/代號/名稱/除權息前收盤價/除權息參考價/…
    try:
        sy, sm, sday = start_iso.split("-")
        ey, em, eday = end_iso.split("-")
        url = ("https://www.tpex.org.tw/web/stock/exright/dailyquo/exDailyQ_result.php"
               f"?l=zh-tw&d={sy}/{sm}/{sday}&ed={ey}/{em}/{eday}")
        d = get_json(url)
        sources_ok["otc_rows"] = sum(len(t.get("data", []) or []) for t in d.get("tables", []) or [])
        for t in d.get("tables", []) or []:
            for r in t.get("data", []) or []:
                sid = str(r[1]).strip()
                if not is_common_stock(sid):
                    continue
                date_iso = roc_to_iso(r[0])
                if date_iso:
                    add(sid, date_iso, r[3], r[4])
        sources_ok["otc"] = True
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
