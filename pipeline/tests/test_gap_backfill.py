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
    paths = {k: str(tmp_path / f"{k}.json") for k in ("price", "chip", "div", "index", "bt", "state")}
    _write(paths["price"], price)
    _write(paths["chip"], chip)
    _write(paths["index"], index)
    _write(paths["bt"], bt)
    _write(paths["div"], {})
    return paths


class FakeNet:
    """可設定哪天哪個端點失敗/回空的假網路，順便記錄呼叫次數。"""

    def __init__(self, days, fail=None, empty=None, div_fail=False, month_fail=()):
        self.days = set(days)
        self.fail = fail or {}        # {(kind, date): Exception}
        self.empty = empty or set()   # {(kind, date)}
        self.div_fail = div_fail
        self.month_fail = set(month_fail)
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
    # 下次不帶 --dates、而且基準月份抓不到 → 仍從佇列接著補
    st2 = _run(paths, FakeNet(DAYS, month_fail={"202609", "202610"}))
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
