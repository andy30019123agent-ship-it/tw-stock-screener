import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import market_sources as ms  # noqa: E402


def test_roc_to_iso():
    assert ms.roc_to_iso("115/06/01") == "2026-06-01"
    assert ms.roc_to_iso("1150626") == "2026-06-26"


def test_is_common_stock():
    assert ms.is_common_stock("2330")
    assert not ms.is_common_stock("00400A")   # 主動式 ETF（6 碼含字母）
    assert not ms.is_common_stock("006201")   # 6 碼 ETF
    assert not ms.is_common_stock("2330B")    # 特別股


def test_f_cleans_numbers():
    assert ms._f("1,234.5") == 1234.5
    assert ms._f("+0.79") == 0.79
    assert ms._f("--") is None
    assert ms._f("") is None


def test_f_zero_string_is_valid_zero_not_none():
    # TWSE 對零股/極低量成交回 "0.00"，_f 要老實轉成 0.0（不是 None）——
    # 擋零價污染的責任在 _ohlc，不是在 _f 把它誤判成缺值。
    assert ms._f("0.00") == 0.0
    assert ms._f("0") == 0.0


def test_ohlc_drops_row_when_close_is_zero_or_negative():
    # 根因案例：低量股（例 1213 單日成交 1 張、金額 7 元）TWSE 回 close="0.00"，
    # 不擋的話會被寫進歷史當成「跌到 0 元」，污染漲跌幅與指標。
    assert ms._ohlc("2026-07-16", "10", "10", "10", "0.00", "1", "7") is None
    assert ms._ohlc("2026-07-16", "10", "10", "10", "0", "1", "7") is None


def test_ohlc_keeps_valid_positive_close():
    row = ms._ohlc("2026-07-16", "10.0", "10.5", "9.8", "10.2", "1000", "10200")
    assert row is not None
    assert row["close"] == 10.2


def test_listed_chip_sums_foreign(monkeypatch):
    # T86：外資 = [4]外陸資 + [7]外資自營；投信 = [10]
    payload = {"data": [
        ["2330", "台積電", "0", "0", "-3,311,663", "0", "0", "0",
         "722,215", "264,000", "458,215", "0", "0", "0", "0", "0", "0", "0", "0"],
        ["006201", "ETF", "0", "0", "999", "0", "0", "0", "0", "0", "888",
         "0", "0", "0", "0", "0", "0", "0", "0"],   # 非 4 碼數字 → 濾掉
    ]}
    monkeypatch.setattr(ms, "get_json", lambda url: payload)
    out = ms.fetch_listed_chip("2026-06-01")
    assert out == {"2330": {"Foreign_Investor": -3311663.0, "Investment_Trust": 458215.0}}


def test_fetch_taiex_close_parses_index_row(monkeypatch):
    # MI_INDEX type=IND：多張表，要找到「發行量加權股價指數」那一列的收盤指數
    payload = {"tables": [
        {"fields": ["指數", "收盤指數", "漲跌(+/-)", "漲跌點數", "漲跌百分比(%)", "備註"],
         "data": [["寶島股價指數", "52,351.49", "+", "960.26", "1.87", ""],
                  ["發行量加權股價指數", "47,018.99", "+", "893.08", "1.94", ""]]},
        {},
    ]}
    monkeypatch.setattr(ms, "get_json", lambda url: payload)
    assert ms.fetch_taiex_close("2026-07-01") == 47018.99


def test_fetch_taiex_close_no_data_on_non_trading_day(monkeypatch):
    monkeypatch.setattr(ms, "get_json", lambda url: {"tables": [{"data": []}, {}]})
    assert ms.fetch_taiex_close("2026-06-28") is None


def test_fetch_trading_days_month_parses_fmtqik(monkeypatch):
    # FMTQIK：日期(民國)/成交股數/成交金額/成交筆數/加權指數/漲跌點數（2026-11-13 實測 202608 格式）
    payload = {"stat": "OK", "data": [
        ["115/08/18", "10,333,808,272", "1,007,881,760,816", "5,224,454", "45,308.68", "-548.59"],
        ["115/08/19", "10,230,116,335", "890,269,743,542", "4,880,908", "44,719.35", "-589.33"],
    ]}
    monkeypatch.setattr(ms, "get_json", lambda url: payload)
    assert ms.fetch_trading_days_month("202608") == {"2026-08-18": 45308.68, "2026-08-19": 44719.35}


def test_fetch_trading_days_month_empty_is_empty(monkeypatch):
    # 限流/夜間回空 → 回 {}，由呼叫端當成「基準未知」，不能當成整月休市
    monkeypatch.setattr(ms, "get_json", lambda url: {"stat": "很抱歉，沒有符合條件的資料!"})
    assert ms.fetch_trading_days_month("202608") == {}


def test_otc_chip_maps_columns(monkeypatch):
    # TPEX insti：外資合計 = [10]，投信 = [13]
    row = ["6488", "環球晶", "1", "1", "0", "0", "0", "0",
           "0", "0", "4,000", "0", "0", "12,000",
           "0", "0", "0", "0", "0", "0", "0", "0", "0", "16000"]
    monkeypatch.setattr(ms, "get_json", lambda url: {"tables": [{"data": [row]}]})
    out = ms.fetch_otc_chip("2026-06-01")
    assert out == {"6488": {"Foreign_Investor": 4000.0, "Investment_Trust": 12000.0}}


# ── 回應日期比對（2026-11-13：官方回了別天的資料，不可蓋上請求日期寫進歷史）──────────
# 結構照 2026-11-13 實測：TWSE MI_INDEX type=ALL 個股表標題「115年11月11日 每日收盤行情(全部)」；
# TPEX dailyQuotes 表內 date="115/11/11"（頂層 date 只回聲請求參數，不採信）。
_TWSE_ROW = ["2330", "台積電", "30,000,000", "50,000", "30,000,000,000", "1,000.00", "1,010.00",
             "990.00", "1,005.00", "+", "5.00", "", "", "", "", ""]
_TPEX_ROW = ["6488", "環球晶", "400.00", "+1.00", "398.00", "402.00", "397.00", "400.00",
             "1,000,000", "400,000,000"]


def _twse_all(roc_label):
    return {"stat": "OK", "date": "20261112", "tables": [
        {"title": f"{roc_label} 價格指數(臺灣證券交易所)", "fields": ["指數"], "data": []},
        {"title": f"{roc_label} 每日收盤行情(全部)",
         "fields": ["證券代號", "證券名稱", "成交股數", "成交筆數", "成交金額", "開盤價", "最高價",
                    "最低價", "收盤價"], "data": [_TWSE_ROW]}]}


def test_listed_ohlc_rejects_response_for_another_day(monkeypatch):
    monkeypatch.setattr(ms, "get_json", lambda url: _twse_all("115年11月11日"))
    assert ms.fetch_listed_ohlc("2026-11-12") == {}
    assert ms.fetch_listed_ohlc("2026-11-11")["2330"]["close"] == 1005.0


def test_listed_ohlc_without_date_in_title_still_parses(monkeypatch):
    payload = _twse_all("115年11月11日")
    payload["tables"][1]["title"] = "每日收盤行情(全部)"            # 標題沒日期 → 無從比對，照收
    monkeypatch.setattr(ms, "get_json", lambda url: payload)
    assert "2330" in ms.fetch_listed_ohlc("2026-11-12")


def test_otc_ohlc_rejects_response_for_another_day(monkeypatch):
    payload = {"date": "20261112", "stat": "ok",
               "tables": [{"title": "上櫃股票行情", "date": "115/11/11", "data": [_TPEX_ROW]}]}
    monkeypatch.setattr(ms, "get_json", lambda url: payload)
    assert ms.fetch_otc_ohlc("2026-11-12") == {}
    assert ms.fetch_otc_ohlc("2026-11-11")["6488"]["close"] == 400.0


def test_dividend_reports_raw_row_counts(monkeypatch):
    # 限流樣態：回 JSON 但 0 列 → listed=True 但 listed_rows=0（呼叫端據此判「未確認」）
    def fake(url):
        if "TWT49U" in url:
            return {"stat": "OK", "data": []}
        return {"tables": [{"data": [["115/08/19", "6488", "環球晶", "400", "390"]]}]}
    monkeypatch.setattr(ms, "get_json", fake)
    src = {}
    ev = ms.fetch_ex_dividend_events("2026-08-18", "2026-08-20", src)
    assert src["listed"] and src["otc"] and src["listed_rows"] == 0 and src["otc_rows"] == 1
    assert ev == {"6488": [{"date": "2026-08-19", "ratio": 390 / 400}]}


def test_http_limits_shortens_and_restores(monkeypatch):
    seen = []

    def fail(url):
        seen.append((ms.CURL_MAX_TIME, ms.URLLIB_TIMEOUT))
        raise OSError("timeout")
    monkeypatch.setattr(ms, "_curl", fail)
    monkeypatch.setattr(ms, "_urllib", fail)
    monkeypatch.setattr(ms.time, "sleep", lambda s: None)
    with ms.http_limits(20, 10, 1):
        try:
            ms.get_text("http://x")
        except RuntimeError:
            pass
    assert seen == [(20, 10), (20, 10)]                           # 只跑 1 輪（curl＋urllib 各一次）
    assert (ms.CURL_MAX_TIME, ms.URLLIB_TIMEOUT, ms.HTTP_RETRIES) == (40, 20, 3)   # 離開就還原


def test_otc_ohlc_unparseable_date_does_not_raise_and_still_collects(monkeypatch, capsys):
    # 日期欄格式改版（多了星期）→ 當成「無法比對日期」：不丟例外、資料照收、印 warning
    payload = {"date": "20261112", "stat": "ok",
               "tables": [{"title": "上櫃股票行情", "date": "115/11/11 (三)", "data": [_TPEX_ROW]}]}
    monkeypatch.setattr(ms, "get_json", lambda url: payload)
    out = ms.fetch_otc_ohlc("2026-11-12")
    assert out["6488"]["close"] == 400.0
    assert "無法解析" in capsys.readouterr().out


def test_otc_ohlc_table_without_date_is_skipped_but_dated_table_collected(monkeypatch):
    # 真實上櫃回應含一張沒 date 的「管理股票」表：沒 date＝略過日期比對（不當成不符），不能讓整包歸零
    other = ["6489", "管理股", "50.00", "+1.00", "49.00", "51.00", "48.00", "50.00",
             "1,000,000", "50,000,000"]
    payload = {"date": "20261112", "stat": "ok", "tables": [
        {"title": "管理股票", "data": [other]},
        {"title": "上櫃股票行情", "date": "115/11/12", "data": [_TPEX_ROW]}]}
    monkeypatch.setattr(ms, "get_json", lambda url: payload)
    out = ms.fetch_otc_ohlc("2026-11-12")
    assert "6488" in out                                     # 有 date 且相符的表正常收
    assert "6489" in out                                     # 沒 date 的表不比對、照收（不歸零）
