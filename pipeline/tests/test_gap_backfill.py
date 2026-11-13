"""漏抓交易日回補（gap_backfill.py）測試：全部用假的 fetch 注入，不打真實網路。"""
import datetime as dt
import json
import os
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import gap_backfill as gb  # noqa: E402
import history_store as hs  # noqa: E402


def _bdays(start, n):
    """從 start 起 n 個平日（假交易日曆）。"""
    out, d = [], dt.date.fromisoformat(start)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += dt.timedelta(days=1)
    return out


def _rows(sids, close=10.0):
    return {s: {"open": close, "max": close + 1, "min": close - 1, "close": close,
                "Trading_Volume": 500_000, "Trading_money": 5_000_000} for s in sids}


LISTED = [f"{1000 + i}" for i in range(gb.MIN_LISTED_ROWS + 5)]
OTC = [f"{6000 + i}" for i in range(gb.MIN_OTC_ROWS + 5)]
ALL = LISTED + OTC
UNIVERSE = {"stocks": [{"id": s, "market": "上市"} for s in LISTED] + [{"id": s, "market": "上櫃"} for s in OTC]}
MARKETS = {s["id"]: s["market"] for s in UNIVERSE["stocks"]}


def _write(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def _setup(tmp_path, days, missing, chip_days=None, bt_days=None):
    """建一份「days 中扣掉 missing」的歷史檔組。回 paths。"""
    have = [d for d in days if d not in missing]
    price, chip, index = {}, {}, {}
    for d in have:
        hs.append_price(price, d, _rows(ALL))
        index[d] = 100.0
    for d in (chip_days if chip_days is not None else have[-hs.CHIP_WINDOW:]):
        hs.append_chip(chip, d, {s: {"Foreign_Investor": 1, "Investment_Trust": 1} for s in ALL})
    bt = hs.bt_empty()
    hs.bt_merge_days(bt, {d: _rows(ALL) for d in (bt_days if bt_days is not None else have)})
    paths = {k: str(tmp_path / f"{k}.json") for k in ("price", "chip", "div", "index", "bt", "state", "universe")}
    _write(paths["universe"], UNIVERSE)
    _write(paths["price"], price)
    _write(paths["chip"], chip)
    _write(paths["index"], index)
    _write(paths["bt"], bt)
    _write(paths["div"], {})
    return paths


class FakeNet:
    """可設定哪天哪個端點失敗/回空的假網路，順便記錄呼叫次數。"""

    def __init__(self, days, fail=None, empty=None, div_fail=False, month_fail=(), div_empty=(),
                 empty_months=()):
        self.days = set(days)
        self.fail = fail or {}        # {(kind, date): Exception}
        self.empty = empty or set()   # {(kind, date)}
        self.div_fail = div_fail
        self.month_fail = set(month_fail)
        self.empty_months = set(empty_months)
        self.div_empty = set(div_empty)   # {"listed","otc"}：該市場回 JSON 但 0 列（限流樣態）
        self.calls = []

    def _hit(self, kind, d):
        self.calls.append((kind, d))
        if (kind, d) in self.fail:
            raise self.fail[(kind, d)]
        return (kind, d) not in self.empty

    def fetchers(self):
        def month(ym):
            self.calls.append(("month", ym))
            if ym in self.month_fail:
                raise RuntimeError("限流")
            if ym in self.empty_months:
                return {}
            return {d: 123.0 + i for i, d in enumerate(sorted(self.days)) if gb.month_of(d) == ym}

        def listed(d):
            return _rows(LISTED, 20.0) if self._hit("listed", d) else {}

        def otc(d):
            return _rows(OTC, 30.0) if self._hit("otc", d) else {}

        def lchip(d):
            return ({s: {"Foreign_Investor": 7, "Investment_Trust": 8} for s in LISTED}
                    if self._hit("lchip", d) else {})

        def ochip(d):
            return ({s: {"Foreign_Investor": 7, "Investment_Trust": 8} for s in OTC}
                    if self._hit("ochip", d) else {})

        def div(start, end, src):
            self.calls.append(("div", start, end))
            if self.div_fail:
                src["listed"], src["otc"] = True, False
                return {}
            src["listed"] = src["otc"] = True
            src["listed_rows"] = 0 if "listed" in self.div_empty else 2
            src["otc_rows"] = 0 if "otc" in self.div_empty else 1
            if self.div_empty:
                return {}
            return {"1000": [{"date": start, "ratio": 0.97}], "1001": [{"date": "1999-01-01", "ratio": 0.5}]}

        return {"baseline_month": month, "listed_ohlc": listed, "otc_ohlc": otc,
                "listed_chip": lchip, "otc_chip": ochip, "dividends": div}


def _run(paths, net, **kw):
    return gb.run(fetchers=net.fetchers(), sleep=lambda s: None, paths=paths, **kw)


DAYS = _bdays("2026-09-01", 40)   # 2026-09-01 ~ 2026-10-26


# ── 缺口偵測 ───────────────────────────────────────────────────────────
def test_detect_finds_missing_trading_day_and_ignores_holiday():
    days = DAYS
    baseline = {d: 1.0 for d in days if d != days[-5]}     # days[-5] 是休市（基準沒有）
    price, chip, index = {}, {}, {}
    for d in days:
        if d in (days[-3], days[-5]):
            continue
        hs.append_price(price, d, _rows(ALL))
        index[d] = 1.0
    gaps, info = gb.detect_gaps(baseline, price, chip, index, hs.bt_empty())
    assert days[-3] in gaps and "price" in gaps[days[-3]] and "index" in gaps[days[-3]]
    assert days[-5] not in gaps                                 # 休市日不算缺口
    assert info["latest"] == days[-1]


def test_detect_baseline_missing_month_is_not_a_gap():
    # 基準抓不到 10 月（空）→ 10 月的缺不判斷，也不能被當成「休市」記錄為已處理
    baseline = {d: 1.0 for d in DAYS if gb.month_of(d) == "202609"}
    price = {}
    for d in DAYS:
        if d != "2026-10-07":
            hs.append_price(price, d, _rows(ALL))
    gaps, _ = gb.detect_gaps(baseline, price, {}, {d: 1 for d in DAYS}, hs.bt_empty())
    assert "2026-10-07" not in gaps


def test_detect_partial_day_counts_as_missing():
    # 某日只有零星幾檔（< MIN_PRESENT_ROWS）＝不完整，要當缺口
    price = {}
    for d in DAYS:
        hs.append_price(price, d, _rows(ALL if d != DAYS[-2] else ALL[:10]))
    gaps, _ = gb.detect_gaps({d: 1.0 for d in DAYS}, price, {}, {d: 1 for d in DAYS}, hs.bt_empty())
    assert DAYS[-2] in gaps


def test_detect_auto_window_only_recent():
    price = {}
    for d in DAYS:
        if d != DAYS[5]:   # 很舊的洞：自動視窗看不到
            hs.append_price(price, d, _rows(ALL))
    base = {d: 1.0 for d in DAYS}
    gaps, _ = gb.detect_gaps(base, price, {}, {d: 1 for d in DAYS}, hs.bt_empty())
    assert DAYS[5] not in gaps
    gaps, _ = gb.detect_gaps(base, price, {}, {d: 1 for d in DAYS}, hs.bt_empty(), extra_dates=[DAYS[5]])
    assert DAYS[5] in gaps                                      # 手動指定就看得到


def test_parse_dates_arg():
    assert gb.parse_dates_arg("2026-08-18:2026-08-20") == ["2026-08-18", "2026-08-19", "2026-08-20"]
    assert gb.parse_dates_arg("2026-08-20, 2026-08-18") == ["2026-08-18", "2026-08-20"]
    assert gb.parse_dates_arg("") == []


# ── 回補寫入 ───────────────────────────────────────────────────────────
def test_backfill_inserts_in_middle_sorted_unique_and_consistent(tmp_path):
    gap = DAYS[-4]
    paths = _setup(tmp_path, DAYS, {gap})
    net = FakeNet(DAYS)
    st = _run(paths, net)
    assert st["filled_this_run"] == [gap]
    price = hs.load(paths["price"])
    for sid in ("1000", "6000"):
        keys = list(price[sid].keys())
        assert keys == sorted(keys) and len(keys) == len(set(keys))   # 遞增、無重複（檔案本身）
        assert gap in price[sid]
    assert price["1000"][gap][3] == 20.0 and price["6000"][gap][3] == 30.0
    bt = hs.load(paths["bt"])
    assert gap in bt["dates"] and bt["dates"] == sorted(set(bt["dates"]))
    i = bt["dates"].index(gap)
    assert bt["stocks"]["1000"][3][i] == 20.0                     # bt 與 price 同一筆值
    idx = hs.load(paths["index"])
    assert gap in idx and list(idx) == sorted(idx)
    chip = hs.load(paths["chip"])
    assert chip["1000"][gap] == [7, 8] and list(chip["1000"]) == sorted(chip["1000"])
    div = hs.load(paths["div"])
    assert div["1000"] == {gap: 0.97}                             # 只收回補日的事件
    assert "1001" not in div                                      # 不相干日期的事件不寫
    state = json.load(open(paths["state"]))
    assert gap in state["backfilled"] and state["pending"] == {}
    assert "gap_backfill" in state["backfilled"][gap]["source"]
    # 再跑一次：已無缺口、不再抓個股
    net2 = FakeNet(DAYS)
    st2 = _run(paths, net2)
    assert st2["gaps_detected"] == {}
    assert not [c for c in net2.calls if c[0] in ("listed", "otc")]


def test_rolling_windows_preserved(tmp_path):
    days = _bdays("2026-01-05", hs.PRICE_WINDOW + 10)
    gap = days[-3]
    paths = _setup(tmp_path, days, {gap})
    _run(paths, FakeNet(days))
    price = hs.load(paths["price"])
    assert len(price["1000"]) == hs.PRICE_WINDOW                  # 補一天後仍是 110 天
    assert gap in price["1000"]
    chip = hs.load(paths["chip"])
    assert len(chip["1000"]) == hs.CHIP_WINDOW
    assert len(hs.load(paths["index"])) <= hs.PRICE_WINDOW


def test_single_market_failure_writes_nothing_and_marks_pending(tmp_path):
    gap = DAYS[-4]
    paths = _setup(tmp_path, DAYS, {gap})
    before = {k: open(paths[k]).read() for k in ("price", "bt", "chip", "index")}
    net = FakeNet(DAYS, empty={("otc", gap)})                    # 上櫃回空（限流）
    st = _run(paths, net)
    assert st["filled_this_run"] == []
    for k, v in before.items():
        assert open(paths[k]).read() == v                        # 一個 byte 都沒動
    assert gap in st["pending"] and st["pending"][gap]["attempts"] == 1
    assert gap not in st["backfilled"]                           # 失敗不可當成已處理
    # 下次網路恢復 → 補上，待補清空
    st2 = _run(paths, FakeNet(DAYS))
    assert st2["filled_this_run"] == [gap] and st2["pending"] == {}


def test_network_exception_marks_pending(tmp_path):
    gap = DAYS[-4]
    paths = _setup(tmp_path, DAYS, {gap})
    net = FakeNet(DAYS, fail={("listed", gap): RuntimeError("取得失敗（3 次）")})
    st = _run(paths, net)
    assert gap in st["pending"] and "取得失敗" in st["pending"][gap]["last_error"]


def test_dividend_failure_blocks_price_days(tmp_path):
    gap = DAYS[-4]
    paths = _setup(tmp_path, DAYS, {gap})
    st = _run(paths, FakeNet(DAYS, div_fail=True))
    assert st["filled_this_run"] == [] and gap in st["pending"]
    assert gap not in hs.load(paths["price"])["1000"]
    # 是「除權息失敗」擋下的（算一次失敗、記錯誤），不是被當成 0 列未確認或斷路器順手擋掉
    assert st["pending"][gap]["attempts"] == 1 and "dividends" in st["last_error"]
    assert st["div_unconfirmed"] == {}


def test_cap_per_run_and_resume(tmp_path):
    gaps = set(DAYS[-6:-1])                                      # 5 天缺
    paths = _setup(tmp_path, DAYS, gaps)
    st = _run(paths, FakeNet(DAYS), max_days=3)
    assert len(st["filled_this_run"]) == 3 and len(st["pending"]) == 2
    st2 = _run(paths, FakeNet(DAYS), max_days=3)
    assert len(st2["filled_this_run"]) == 2 and st2["pending"] == {}
    assert set(json.load(open(paths["state"]))["backfilled"]) == gaps


def test_manual_old_dates_queue_until_done(tmp_path):
    old = DAYS[3:6]                                              # 自動視窗外的舊洞
    paths = _setup(tmp_path, DAYS, set(old))
    st = _run(paths, FakeNet(DAYS), dates_arg=f"{old[0]}:{old[-1]}", max_days=2)
    assert st["filled_this_run"] == old[:2]
    assert st["queue"] == [old[2]]
    # 下次不帶 --dates、基準月份「回空」（不是網路錯誤）→ 仍從佇列接著補
    st2 = _run(paths, FakeNet(DAYS, empty_months={"202609", "202610"}))
    assert st2["filled_this_run"] == [old[2]]


def test_manual_non_trading_day_reported(tmp_path):
    paths = _setup(tmp_path, DAYS, set())
    st = _run(paths, FakeNet(DAYS), dates_arg="2026-09-05")     # 星期六
    assert st["manual_not_trading_day"] == ["2026-09-05"] and st["filled_this_run"] == []


def test_gives_up_after_max_attempts(tmp_path, monkeypatch):
    monkeypatch.setattr(gb, "MAX_ATTEMPTS", 2)
    gap = DAYS[-4]
    paths = _setup(tmp_path, DAYS, {gap})
    net = FakeNet(DAYS, empty={("listed", gap)})
    _run(paths, net)
    st = _run(paths, net)
    assert gap in st["gave_up"] and gap not in st["pending"] and gap not in st["backfilled"]
    st3 = _run(paths, FakeNet(DAYS))                             # 放棄後不再自動重試
    assert st3["filled_this_run"] == []
    st4 = _run(paths, FakeNet(DAYS), dates_arg=gap)              # 手動指定＝重新給機會
    assert st4["filled_this_run"] == [gap]


def test_dry_run_writes_nothing(tmp_path):
    gap = DAYS[-4]
    paths = _setup(tmp_path, DAYS, {gap})
    before = {k: open(paths[k]).read() for k in ("price", "bt", "chip", "index")}
    net = FakeNet(DAYS)
    st = gb.run(dry_run=True, fetchers=net.fetchers(), sleep=lambda s: None, paths=paths)
    assert st["would_fetch"] == [gap]
    assert not os.path.exists(paths["state"])
    for k, v in before.items():
        assert open(paths[k]).read() == v
    assert not [c for c in net.calls if c[0] not in ("month",)]


def test_logic_error_raises_in_run_but_safe_run_swallows(tmp_path):
    gap = DAYS[-4]
    paths = _setup(tmp_path, DAYS, {gap})
    net = FakeNet(DAYS, fail={("listed", gap): KeyError("schema changed")})
    with pytest.raises(KeyError):                                # 非預期錯誤：run 直接紅
        _run(paths, net)
    assert gb.safe_run(fetchers=net.fetchers(), sleep=lambda s: None, paths=paths) is None
    assert "KeyError" in json.load(open(paths["state"]))["last_error"]


def test_daily_update_main_survives_backfill_crash(monkeypatch):
    import daily_update as du
    calls = []
    monkeypatch.setattr(du, "update_latest", lambda: calls.append("latest"))

    def boom(*a, **k):
        raise TypeError("bug")
    monkeypatch.setattr(gb, "run", boom)
    monkeypatch.setattr(gb, "STATE_PATH", "/nonexistent-dir/x/state.json")
    du.main([])                                                  # 不可往外丟
    assert calls == ["latest"]


def test_atomic_save_keeps_old_file_on_failure(tmp_path):
    path = str(tmp_path / "h.json")
    hs.save(path, {"a": 1})

    class Bad:
        pass
    with pytest.raises(TypeError):
        hs.save(path, {"a": Bad()})                              # 序列化到一半失敗
    assert json.load(open(path)) == {"a": 1}                     # 舊檔完好
    assert not os.path.exists(path + ".tmp")                     # 暫存檔有清掉


def test_atomic_save_never_opens_target_for_writing(tmp_path, monkeypatch):
    # 原子寫入的前提：正式檔只會被 os.replace 整個換掉，從來不會被直接打開來寫（寫到一半就壞）
    path = str(tmp_path / "h.json")
    opened = []
    real_open = open

    def spy(p, mode="r", *a, **k):
        if "w" in mode:
            opened.append(str(p))
        return real_open(p, mode, *a, **k)
    monkeypatch.setattr(hs, "open", spy, raising=False)
    hs.save(path, {"a": 1})
    assert opened == [path + ".tmp"] and json.load(open(path)) == {"a": 1}


# ── 驗收後修正（2026-11-13 第二輪）──────────────────────────────────────
def test_backfill_bt_does_not_add_rows_for_late_included_stock(tmp_path):
    # 🔴1：回補日早於某股的 bt 起點（晚收錄）→ 不能幫它寫孤立列；也不重篩、不增減股票
    gap = DAYS[10]
    paths = _setup(tmp_path, DAYS, {gap})
    bt = hs.load(paths["bt"])
    late = "1003"
    i0 = bt["dates"].index(DAYS[20])
    for j in range(5):                                           # 讓 1003 從 DAYS[20] 才開始有資料
        bt["stocks"][late][j][:i0] = [None] * i0
    _write(paths["bt"], bt)
    before = hs.load(paths["bt"])
    st = _run(paths, FakeNet(DAYS), dates_arg=gap)
    assert st["filled_this_run"] == [gap]
    after = hs.load(paths["bt"])
    assert set(after["stocks"]) == set(before["stocks"])
    k = after["dates"].index(gap)
    assert after["stocks"][late][3][k] is None                  # 晚收錄 → 不補
    assert after["stocks"]["1000"][3][k] == 20.0                # 涵蓋 → 補
    for sid in before["stocks"]:                                # 回補日以外逐格不變
        for d, i in ((d, i) for i, d in enumerate(before["dates"])):
            assert [c[i] for c in before["stocks"][sid]] == [c[after["dates"].index(d)] for c in after["stocks"][sid]]


def test_gap_older_than_price_window_but_inside_bt_writes_bt_only(tmp_path):
    # 回補日比 price.json 視窗舊、但在 bt_price.json 範圍內 → 只補 bt、不寫 price；bt 無空洞、股票數不變
    days = _bdays("2026-01-05", hs.PRICE_WINDOW + 20)
    gap = days[10]                                            # 早於 price 視窗起點（days[20]）
    paths = _setup(tmp_path, days, {gap})
    price_before = hs.load(paths["price"])
    assert gap < min(price_before["1000"])                    # 前提：確實比 price 視窗舊
    bt_before = hs.load(paths["bt"])
    assert gap not in bt_before["dates"] and bt_before["dates"][0] < gap
    st = _run(paths, FakeNet(days), dates_arg=gap)
    assert st["filled_this_run"] == [gap]
    price = hs.load(paths["price"])
    assert all(gap not in price[sid] for sid in price)        # price 不寫
    assert price == price_before
    bt = hs.load(paths["bt"])
    assert gap in bt["dates"] and bt["dates"] == sorted(set(bt["dates"]))
    assert len(bt["dates"]) == len(bt_before["dates"]) + 1
    assert set(bt["stocks"]) == set(bt_before["stocks"])      # 股票數不變
    k = bt["dates"].index(gap)
    for sid in bt["stocks"]:                                  # 每檔每欄都有長度＝日期數、補的那格有值（無空洞）
        assert all(len(col) == len(bt["dates"]) for col in bt["stocks"][sid])
        assert bt["stocks"][sid][3][k] is not None
    assert bt["stocks"]["1000"][3][k] == 20.0


def test_detect_otc_missing_day_is_gap_when_markets_known():
    # 🟡6：某天只有上市（上櫃回空時 daily_update 只寫上市）→ 總數 >500 但要算缺口
    price = {}
    for d in DAYS:
        hs.append_price(price, d, _rows(LISTED if d == DAYS[-3] else ALL))
    base = {d: 1.0 for d in DAYS}
    gaps, _ = gb.detect_gaps(base, price, {}, {d: 1 for d in DAYS}, hs.bt_empty(), markets=MARKETS)
    assert DAYS[-3] in gaps and "price" in gaps[DAYS[-3]]
    gaps, _ = gb.detect_gaps(base, price, {}, {d: 1 for d in DAYS}, hs.bt_empty())   # 沒市場別＝舊行為
    assert DAYS[-3] not in gaps


def test_half_market_day_gets_otc_filled(tmp_path):
    gap = DAYS[-4]
    paths = _setup(tmp_path, DAYS, set())
    price = hs.load(paths["price"])
    for s in OTC:
        del price[s][gap]
    _write(paths["price"], price)
    st = _run(paths, FakeNet(DAYS))
    assert st["filled_this_run"] == [gap]
    assert hs.load(paths["price"])["6000"][gap][3] == 30.0


def test_dividend_zero_rows_is_unconfirmed_then_accepted(tmp_path):
    # 🟡2：除權息回 0 列（限流樣態）→ 第一次不寫價格、記未確認；連續第 2 次才接受
    gap = DAYS[-4]
    paths = _setup(tmp_path, DAYS, {gap})
    before = {k: open(paths[k]).read() for k in ("price", "bt", "div")}
    net = FakeNet(DAYS, div_empty={"listed"})
    st = _run(paths, net)
    assert st["filled_this_run"] == [] and gap in st["pending"]
    assert st["div_unconfirmed"][gap]["runs"] == 1 and st["div_unconfirmed"][gap]["markets"] == ["listed"]
    assert st["pending"][gap]["attempts"] == 0                    # 不算失敗
    assert not [c for c in net.calls if c[0] in ("listed", "otc")]   # 價格這次不抓
    for k, v in before.items():
        assert open(paths[k]).read() == v
    st2 = _run(paths, FakeNet(DAYS, div_empty={"listed"}))
    assert st2["filled_this_run"] == [gap] and st2["div_unconfirmed"] == {}
    assert st2["backfilled"][gap]["div_confirmed_empty"] == ["listed"]


def test_dividend_accepted_empty_survives_price_fetch_failure(tmp_path):
    # 已接受「確實沒有除權息」、但當次價格抓失敗 → 下次不必再從頭數 0 列次數
    gap = DAYS[-4]
    paths = _setup(tmp_path, DAYS, {gap})
    _run(paths, FakeNet(DAYS, div_empty={"otc"}))
    st = _run(paths, FakeNet(DAYS, div_empty={"otc"}, empty={("listed", gap)}))
    assert st["filled_this_run"] == [] and gap in st["div_unconfirmed"]
    st3 = _run(paths, FakeNet(DAYS, div_empty={"otc"}))
    assert st3["filled_this_run"] == [gap] and st3["backfilled"][gap]["div_confirmed_empty"] == ["otc"]


def test_dividend_zero_then_real_events_next_run(tmp_path):
    gap = DAYS[-4]
    paths = _setup(tmp_path, DAYS, {gap})
    _run(paths, FakeNet(DAYS, div_empty={"listed", "otc"}))
    st = _run(paths, FakeNet(DAYS))                               # 第二次查到事件 → 照常寫，含事件
    assert st["filled_this_run"] == [gap] and st["div_unconfirmed"] == {}
    assert hs.load(paths["div"])["1000"] == {gap: 0.97}
    assert "div_confirmed_empty" not in st["backfilled"][gap]


def test_dividend_legacy_interface_without_row_counts(tmp_path):
    # 沒回列數的 fetch（舊介面／驗收腳本的假網路）：整包 0 筆也要當未確認
    gap = DAYS[-4]
    paths = _setup(tmp_path, DAYS, {gap})
    net = FakeNet(DAYS)
    f = net.fetchers()

    def div(start, end, src):
        src["listed"] = src["otc"] = True
        return {}
    f["dividends"] = div
    st = gb.run(fetchers=f, sleep=lambda s: None, paths=paths)
    assert st["filled_this_run"] == [] and gap in st["div_unconfirmed"]


def test_breaker_stops_after_first_network_error(tmp_path):
    # 🟡4：第一個網路錯誤就停掉本次回補；沒輪到的日子不算失敗次數
    gaps = DAYS[-6:-3]
    paths = _setup(tmp_path, DAYS, set(gaps))
    net = FakeNet(DAYS, fail={("listed", gaps[0]): RuntimeError("取得失敗（1 次）：timeout")})
    st = _run(paths, net)
    assert [c for c in net.calls if c[0] == "listed"] == [("listed", gaps[0])]   # 之後一個都沒打
    assert not [c for c in net.calls if c[0] in ("otc", "lchip", "ochip")]
    assert st["pending"][gaps[0]]["attempts"] == 1
    assert st["pending"][gaps[1]]["attempts"] == 0 and st["pending"][gaps[2]]["attempts"] == 0
    assert "listed_ohlc" in st["breaker"]
    st2 = _run(paths, FakeNet(DAYS))                              # 下次網路好了 → 全部補上
    assert sorted(st2["filled_this_run"]) == sorted(gaps)


def test_breaker_time_budget(tmp_path):
    gaps = DAYS[-6:-3]
    paths = _setup(tmp_path, DAYS, set(gaps))
    net = FakeNet(DAYS)
    t = {"now": 0.0}

    def clock():
        t["now"] += 40.0                                          # 每看一次錶就過 40 秒
        return t["now"]
    st = gb.run(fetchers=net.fetchers(), sleep=lambda s: None, paths=paths, clock=clock)
    assert "預算" in st["breaker"]
    assert not [c for c in net.calls if c[0] in ("listed", "otc")]
    assert all(v["attempts"] == 0 for v in st["pending"].values())


def test_budget_running_out_mid_day_does_not_count_as_failure(tmp_path):
    gap = DAYS[-4]
    paths = _setup(tmp_path, DAYS, {gap})
    net = FakeNet(DAYS)
    f = net.fetchers()
    t = {"now": 0.0}
    real_listed = f["listed_ohlc"]

    def listed(d):                                                # 抓完上市後時間就用完了
        t["now"] = 10_000.0
        return real_listed(d)
    f["listed_ohlc"] = listed
    st = gb.run(fetchers=f, sleep=lambda s: None, paths=paths, clock=lambda: t["now"])
    assert "預算" in st["breaker"] and st["pending"][gap]["attempts"] == 0
    assert not [c for c in net.calls if c[0] == "otc"]


def test_pending_since_kept_across_runs_and_warns_when_stale(tmp_path, monkeypatch, capsys):
    gap = DAYS[-4]
    paths = _setup(tmp_path, DAYS, {gap})
    monkeypatch.setattr(gb, "now_taipei", lambda: "2026-11-01 18:30")
    _run(paths, FakeNet(DAYS, empty={("listed", gap)}))
    monkeypatch.setattr(gb, "now_taipei", lambda: "2026-11-05 18:30")
    st = _run(paths, FakeNet(DAYS, empty={("listed", gap)}))
    assert st["pending"][gap]["since"] == "2026-11-01 18:30"     # 第一次記下的時間，不會每天重設
    assert f"待補超過 3 天還沒補上 ['{gap}']" in capsys.readouterr().out


def test_baseline_empty_month_counts_as_failed():
    # 突變 M7b：回空的月份要算「基準未知」，不能當 OK（否則整月會被當成休市）
    base, ok, failed = gb.load_baseline(["202609", "202610"], lambda ym: {} if ym == "202610" else {"2026-09-01": 1.0},
                                        sleep=lambda s: None)
    assert ok == ["202609"] and failed == ["202610"]


def test_baseline_uses_prefetched_month_without_request():
    calls = []
    base, ok, failed = gb.load_baseline(["202611"], lambda ym: calls.append(ym) or {},
                                        sleep=lambda s: None, prefetched={"202611": {"2026-11-13": 1.0}})
    assert calls == [] and ok == ["202611"] and "2026-11-13" in base


def test_manual_date_with_unknown_baseline_is_retried_not_dropped(tmp_path):
    # 🟡3＋突變 M7：手動日期所在月份基準抓不到 → 不可說「不是交易日」，要進 manual_retry 下次再試
    old = DAYS[4]
    paths = _setup(tmp_path, DAYS, {old})
    st = _run(paths, FakeNet(DAYS, empty_months={"202609"}), dates_arg=old)
    assert st["manual_not_trading_day"] == [] and old in st["manual_baseline_unknown"]
    assert old in st["manual_retry"] and st["filled_this_run"] == []
    st2 = _run(paths, FakeNet(DAYS))                              # 下次不帶日期也會再試
    assert st2["filled_this_run"] == [old] and st2["manual_retry"] == {}


def test_bad_manual_input_keeps_auto_check(tmp_path, capsys):
    gap = DAYS[-4]
    paths = _setup(tmp_path, DAYS, {gap})
    st = _run(paths, FakeNet(DAYS), dates_arg="2026/08/18;rm -rf /")
    assert st["filled_this_run"] == [gap]                         # 自動檢查照跑
    assert st["manual_input_error"] and st["manual_requested"] == []
    assert "::warning::手動回補日期沒有採用" in capsys.readouterr().out


def test_too_wide_manual_range_rejected(tmp_path):
    paths = _setup(tmp_path, DAYS, set())
    st = _run(paths, FakeNet(DAYS), dates_arg="2025-01-01:2026-10-01")
    assert st["manual_requested"] == [] and "個月" in st["manual_input_error"]


def test_index_only_gap_is_written(tmp_path):
    # 突變 M15：只缺指數的日子也要補（用基準的加權指數值）
    paths = _setup(tmp_path, DAYS, set())
    idx = hs.load(paths["index"])
    del idx[DAYS[-4]]
    _write(paths["index"], idx)
    net = FakeNet(DAYS)
    st = _run(paths, net)
    assert st["filled_this_run"] == [DAYS[-4]]
    assert DAYS[-4] in hs.load(paths["index"])
    assert not [c for c in net.calls if c[0] in ("listed", "otc")]


def test_bt_written_before_price(tmp_path, monkeypatch):
    # 突變 M9：寫 bt 失敗時 price 還不能有那天（price 是缺口偵測依據，最後寫）
    gap = DAYS[-4]
    paths = _setup(tmp_path, DAYS, {gap})
    real = hs.save

    def bad(path, obj):
        if path == paths["bt"]:
            raise OSError(28, "No space left on device")
        return real(path, obj)
    monkeypatch.setattr(hs, "save", bad)
    with pytest.raises(OSError):
        _run(paths, FakeNet(DAYS))
    assert gap not in hs.load(paths["price"])["1000"]


def test_state_write_failure_after_history_leaves_audit_and_no_duplicate(tmp_path, monkeypatch, capsys):
    gap = DAYS[-4]
    paths = _setup(tmp_path, DAYS, {gap})
    real = hs.save

    def bad(path, obj):
        if path == paths["state"]:
            raise OSError(28, "No space left on device")
        return real(path, obj)
    monkeypatch.setattr(hs, "save", bad)
    assert gb.safe_run(fetchers=FakeNet(DAYS).fetchers(), sleep=lambda s: None, paths=paths) is None
    out = capsys.readouterr().out
    assert "回補稽核紀錄" in out and gap in out                   # 稽核紀錄留在 log
    assert gap in hs.load(paths["price"])["1000"]
    monkeypatch.setattr(hs, "save", real)
    net = FakeNet(DAYS)
    st = _run(paths, net)                                         # 下次：已有那天 → 不重複回補
    assert st["gaps_detected"] == {} and not [c for c in net.calls if c[0] == "listed"]


def test_warnings_and_maintenance_hint():
    ok = {"checked_at": "2026-11-13 18:30", "pending": {"2026-11-12": {"since": "2026-11-13 18:30"}},
          "gave_up": {}, "last_error": None}
    assert gb.warning_lines(ok) == [] and gb.maintenance_hint(ok) == ""   # 剛記待補＝正常，不吵
    bad = {"checked_at": "2026-11-13 18:30",
           "pending": {"2026-11-05": {"since": "2026-11-09 18:30"}, "2026-11-12": {"since": "2026-11-13 18:30"}},
           "gave_up": {"2026-08-19": {}}, "last_error": None}
    lines = gb.warning_lines(bad)
    assert any("放棄" in x for x in lines) and any("超過 3 天" in x and "2026-11-05" in x for x in lines)
    assert gb.maintenance_hint(bad) == "資料回補：2 天待補、1 天已放棄（詳見 Actions log）"
    assert "出錯" in gb.maintenance_hint({"last_error": "crash", "checked_at": "2026-11-13 18:30"})


def test_run_prints_actions_warning_on_give_up(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(gb, "MAX_ATTEMPTS", 1)
    gap = DAYS[-4]
    paths = _setup(tmp_path, DAYS, {gap})
    _run(paths, FakeNet(DAYS, empty={("listed", gap)}))
    assert "::warning::資料回補有 1 天已放棄" in capsys.readouterr().out


def test_safe_run_crash_prints_actions_warning(tmp_path, capsys):
    gap = DAYS[-4]
    paths = _setup(tmp_path, DAYS, {gap})
    gb.safe_run(fetchers=FakeNet(DAYS, fail={("listed", gap): KeyError("x")}).fetchers(),
                sleep=lambda s: None, paths=paths)
    assert "::warning::資料回補發生非預期錯誤" in capsys.readouterr().out


def test_daily_update_survives_backfill_import_failure(monkeypatch, capsys):
    # 🟢1：回補模組 import 失敗不可讓每日步驟掛掉
    import builtins
    import daily_update as du
    monkeypatch.setattr(du, "update_latest", lambda: {})
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "gap_backfill":
            raise SyntaxError("broken")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    du.main([])
    assert "::warning::漏抓回補模組載入失敗" in capsys.readouterr().out


def test_check_stale():
    import daily_update as du
    calls = []

    def month(ym):
        calls.append(ym)
        return {"2026-11-12": 1.0, "2026-11-13": 2.0}
    assert du.check_stale("2026-11-13", today="2026-11-13", fetch_month=month) == (False, {})
    assert calls == []                                            # 資料是今天的 → 不多打請求
    stale, pre = du.check_stale("2026-11-12", today="2026-11-13", fetch_month=month)
    assert stale is True and pre == {"202611": {"2026-11-12": 1.0, "2026-11-13": 2.0}}
    # 今天不在官方清單（假日／盤中資料未出）→ 不判過期
    assert du.check_stale("2026-11-13", today="2026-11-14", fetch_month=month)[0] is False

    def boom(ym):
        raise RuntimeError("timeout")
    assert du.check_stale("2026-11-12", today="2026-11-13", fetch_month=boom) == (False, {})


def _patch_daily(monkeypatch, tmp_path, listed_date, otc_n):
    import daily_update as du
    import market_sources as ms
    for name in ("PRICE_PATH", "CHIP_PATH", "DIV_PATH", "INDEX_PATH", "FETCH_STATE_PATH"):
        monkeypatch.setattr(du, name, str(tmp_path / f"{name}.json"))
    monkeypatch.setattr(du, "today_taipei", lambda: "2026-11-13")
    monkeypatch.setattr(ms, "fetch_listed_ohlc_latest", lambda: (listed_date, _rows(LISTED)))
    monkeypatch.setattr(ms, "fetch_otc_ohlc", lambda d: _rows(OTC[:otc_n]))
    monkeypatch.setattr(ms, "fetch_trading_days_month", lambda ym: {"2026-11-12": 1.0, "2026-11-13": 2.0})
    monkeypatch.setattr(ms, "fetch_listed_chip", lambda d: {})
    monkeypatch.setattr(ms, "fetch_otc_chip", lambda d: {})
    monkeypatch.setattr(ms, "fetch_ex_dividend_events", lambda a, b: {})
    monkeypatch.setattr(ms, "fetch_taiex_close", lambda d: 1.0)
    return du


def test_daily_update_marks_stale_when_official_data_is_old(monkeypatch, tmp_path):
    # 🟡7：今天有開盤、端點卻回昨天的資料 → fetch_state 標過期；基準交給回補沿用
    du = _patch_daily(monkeypatch, tmp_path, "2026-11-12", len(OTC))
    pre = du.update_latest()
    assert json.load(open(du.FETCH_STATE_PATH))["ok"] is False
    assert "202611" in pre
    du = _patch_daily(monkeypatch, tmp_path, "2026-11-13", len(OTC))
    assert du.update_latest() == {}
    assert json.load(open(du.FETCH_STATE_PATH))["ok"] is True


def test_daily_update_otc_empty_marks_not_ok(monkeypatch, tmp_path):
    du = _patch_daily(monkeypatch, tmp_path, "2026-11-13", 0)
    du.update_latest()
    assert json.load(open(du.FETCH_STATE_PATH))["ok"] is False
