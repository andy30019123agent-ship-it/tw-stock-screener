"""月營收快取的回歸測試。

為什麼補這支：2026-07-25 我把快取新鮮度改成逐市場判斷時，留了一行舊碼用到已刪除的變數
（`have`）→ 只要「快取存在且過期」就 NameError。**pipeline 148 個測試全綠、線上卻炸了**，
因為 `monthly_revenue.py` 一個測試都沒有，而那條路只在「有舊快取且過期」時才會走到。
更糟的是 build_data 對機會股引擎 try/except，失敗只印一行警告 → CI 全綠、部署照走，
但 `opportunities.json` 沒產出，網站主功能（今日精華名單）整塊消失。

所以這支測試的重點不是覆蓋率數字，是**把「有舊快取」這個生產環境的常態當成必測前提**：
本機第一次跑、測試環境、CI 都可能沒有快取檔，那條 happy path 反而最不需要測。
"""
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import monthly_revenue as mr  # noqa: E402


def _write_cache(path, data, **extra):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"data": data, **extra}, f, ensure_ascii=False)


def _fake_fetch(listed_ok=True, otc_ok=True, ym="11506"):
    """假的抓取：回傳各市場一檔，並照實填 status（呼叫端靠它判斷單邊失敗）。"""
    def fetch(status=None):
        out = {}
        if status is not None:
            status.update({"listed": listed_ok, "otc": otc_ok})
        if listed_ok:
            out["1101"] = {"yoy": 5.0, "ym": ym, "mkt": "listed"}
        if otc_ok:
            out["6488"] = {"yoy": 8.0, "ym": ym, "mkt": "otc"}
        return out
    return fetch


def test_stale_cache_does_not_crash(tmp_path, monkeypatch):
    """🔴 本體回歸：有舊快取且過期時要能跑完並重抓，不可拋例外。"""
    p = tmp_path / "revenue_cache.json"
    _write_cache(p, {"1101": {"yoy": 1.0, "ym": "11504", "mkt": "listed"},
                     "6488": {"yoy": 2.0, "ym": "11504", "mkt": "otc"}})
    monkeypatch.setattr(mr, "CACHE_PATH", str(p))
    monkeypatch.setattr(mr, "fetch_revenue_yoy", _fake_fetch())
    got = mr.load_or_fetch(dt.date(2026, 7, 25))
    assert got["1101"]["ym"] == "11506", "過期快取必須被新資料覆蓋"


def test_one_market_stale_still_refetches(tmp_path, monkeypatch):
    """上市已是最新、上櫃落後 → 不可整體命中快取（否則上櫃永遠不再重試）。"""
    p = tmp_path / "revenue_cache.json"
    _write_cache(p, {"1101": {"yoy": 1.0, "ym": "11506", "mkt": "listed"},
                     "6488": {"yoy": 2.0, "ym": "11504", "mkt": "otc"}})
    monkeypatch.setattr(mr, "CACHE_PATH", str(p))
    called = {"n": 0}

    def fetch(status=None):
        called["n"] += 1
        return _fake_fetch()(status)

    monkeypatch.setattr(mr, "fetch_revenue_yoy", fetch)
    got = mr.load_or_fetch(dt.date(2026, 7, 25))
    assert called["n"] == 1, "落後的市場必須觸發重抓"
    assert got["6488"]["ym"] == "11506"


def test_both_markets_fresh_hits_cache(tmp_path, monkeypatch):
    """兩市場都已達預期月份 → 命中快取、完全不連網。"""
    p = tmp_path / "revenue_cache.json"
    _write_cache(p, {"1101": {"yoy": 1.0, "ym": "11506", "mkt": "listed"},
                     "6488": {"yoy": 2.0, "ym": "11506", "mkt": "otc"}})
    monkeypatch.setattr(mr, "CACHE_PATH", str(p))

    def boom(status=None):
        raise AssertionError("命中快取時不該抓取")

    monkeypatch.setattr(mr, "fetch_revenue_yoy", boom)
    assert mr.load_or_fetch(dt.date(2026, 7, 25))["1101"]["yoy"] == 1.0


def test_cache_without_mkt_is_treated_as_stale(tmp_path, monkeypatch):
    """舊格式快取（沒有 mkt 欄位）要判為不新鮮而重抓——保守方向，重抓一次就補上標記。"""
    p = tmp_path / "revenue_cache.json"
    _write_cache(p, {"1101": {"yoy": 1.0, "ym": "11506"}})
    monkeypatch.setattr(mr, "CACHE_PATH", str(p))
    monkeypatch.setattr(mr, "fetch_revenue_yoy", _fake_fetch())
    got = mr.load_or_fetch(dt.date(2026, 7, 25))
    assert got["1101"].get("mkt") == "listed", "重抓後每筆都要有市場標記"


def test_single_market_failure_keeps_other_last_good(tmp_path, monkeypatch):
    """上櫃抓取失敗 → 保留上櫃舊資料，不可整批抹掉（否則那半個市場的營收濾網失效）。"""
    p = tmp_path / "revenue_cache.json"
    _write_cache(p, {"6488": {"yoy": 2.0, "ym": "11504", "mkt": "otc"}})
    monkeypatch.setattr(mr, "CACHE_PATH", str(p))
    monkeypatch.setattr(mr, "fetch_revenue_yoy", _fake_fetch(otc_ok=False))
    got = mr.load_or_fetch(dt.date(2026, 7, 25))
    assert got["6488"]["ym"] == "11504", "失敗市場的 last-good 要留著"
    assert got["1101"]["ym"] == "11506"
    saved = json.load(open(p, encoding="utf-8"))
    assert saved["source_status"] == {"listed": True, "otc": False}


def test_both_markets_fail_keeps_cache_and_writes_nothing(tmp_path, monkeypatch):
    """兩邊都失敗 → 沿用舊快取，且不可把快取覆蓋成空的。"""
    p = tmp_path / "revenue_cache.json"
    _write_cache(p, {"1101": {"yoy": 1.0, "ym": "11504", "mkt": "listed"}})
    monkeypatch.setattr(mr, "CACHE_PATH", str(p))
    monkeypatch.setattr(mr, "fetch_revenue_yoy", _fake_fetch(listed_ok=False, otc_ok=False))
    got = mr.load_or_fetch(dt.date(2026, 7, 25))
    assert got["1101"]["yoy"] == 1.0
    assert json.load(open(p, encoding="utf-8"))["data"]["1101"]["ym"] == "11504"


def test_expected_ym_follows_publish_rule():
    """台灣月營收「當月 10 日前公布上月」：10 日前只能期待前兩個月，含跨年。"""
    assert mr._expected_ym(dt.date(2026, 7, 25)) == "11506"   # 7/25 → 期待 6 月
    assert mr._expected_ym(dt.date(2026, 7, 5)) == "11505"    # 7/5 尚未公布 6 月
    assert mr._expected_ym(dt.date(2026, 1, 25)) == "11412"   # 跨年：期待去年 12 月
    assert mr._expected_ym(dt.date(2026, 1, 5)) == "11411"


# ── 逐月快照（record_snapshot）──────────────────────────────────────────────
# 這些測試守的是「無法重建的資料」：官方 OpenAPI 只回最新一期，寫壞了就永遠補不回來。

def test_snapshot_records_month_with_market_counts(tmp_path):
    p = tmp_path / "revenue_history.json"
    data = {"1101": {"yoy": 5.0, "ym": "11506", "mkt": "listed"},
            "6488": {"yoy": -3.0, "ym": "11506", "mkt": "otc"}}
    added, n = mr.record_snapshot(data, dt.date(2026, 7, 25), str(p))
    assert (added, n) == ("11506", 1)
    m = json.load(open(p, encoding="utf-8"))["months"]["11506"]
    assert m["first_seen"] == "2026-07-25"
    assert m["mkt_n"] == {"listed": 1, "otc": 1}, "逐市場筆數要記，否則看不出某月缺半個市場"
    assert m["yoy"] == {"1101": 5.0, "6488": -3.0}


def test_snapshot_never_overwrites_first_observation(tmp_path):
    """官方事後修正數字不可覆蓋——回測要問「當時看到什麼」，用修正值＝偷看未來。"""
    p = tmp_path / "revenue_history.json"
    mr.record_snapshot({"1101": {"yoy": 5.0, "ym": "11506", "mkt": "listed"}},
                       dt.date(2026, 7, 25), str(p))
    mr.record_snapshot({"1101": {"yoy": 9.9, "ym": "11506", "mkt": "listed"}},
                       dt.date(2026, 8, 3), str(p))
    m = json.load(open(p, encoding="utf-8"))["months"]["11506"]
    assert m["yoy"]["1101"] == 5.0, "第一次看到的值必須留著"
    assert m["revisions"] == 1 and m["revised_at"] == "2026-08-03"
    assert m["first_seen"] == "2026-07-25"


def test_snapshot_backfills_missing_market_without_touching_existing(tmp_path):
    """上櫃當月抓失敗、隔天補到 → 補進同一個月，但已存在的公司值不動。"""
    p = tmp_path / "revenue_history.json"
    mr.record_snapshot({"1101": {"yoy": 5.0, "ym": "11506", "mkt": "listed"}},
                       dt.date(2026, 7, 25), str(p))
    mr.record_snapshot({"1101": {"yoy": 5.0, "ym": "11506", "mkt": "listed"},
                        "6488": {"yoy": -3.0, "ym": "11506", "mkt": "otc"}},
                       dt.date(2026, 7, 26), str(p))
    m = json.load(open(p, encoding="utf-8"))["months"]["11506"]
    assert m["yoy"] == {"1101": 5.0, "6488": -3.0}
    assert m["mkt_n"] == {"listed": 1, "otc": 1}
    assert m["backfilled_at"] == "2026-07-26"
    assert "revisions" not in m, "補齊不是修正，不該算成修正"


def test_snapshot_refuses_to_write_over_unreadable_history(tmp_path, capsys):
    """檔案壞掉時寧可不寫，也不能覆蓋——這份資料無法重建。"""
    p = tmp_path / "revenue_history.json"
    p.write_text("{壞掉的 json", encoding="utf-8")
    added, n = mr.record_snapshot({"1101": {"yoy": 5.0, "ym": "11506", "mkt": "listed"}},
                                  dt.date(2026, 7, 25), str(p))
    assert (added, n) == (None, 0)
    assert p.read_text(encoding="utf-8") == "{壞掉的 json", "壞檔要原封不動留著，等人來看"


def test_snapshot_is_written_even_on_cache_hit(tmp_path, monkeypatch):
    """命中快取也要記快照——否則「當期」這個月永遠不會被存下來（第一次上線就是這情況）。"""
    cache = tmp_path / "revenue_cache.json"
    hist = tmp_path / "revenue_history.json"
    _write_cache(cache, {"1101": {"yoy": 5.0, "ym": "11506", "mkt": "listed"},
                         "6488": {"yoy": 2.0, "ym": "11506", "mkt": "otc"}})
    monkeypatch.setattr(mr, "CACHE_PATH", str(cache))
    monkeypatch.setattr(mr, "HISTORY_PATH", str(hist))
    monkeypatch.setattr(mr, "fetch_revenue_yoy",
                        lambda status=None: (_ for _ in ()).throw(AssertionError("不該抓取")))
    mr.load_or_fetch(dt.date(2026, 7, 25))
    assert "11506" in json.load(open(hist, encoding="utf-8"))["months"]
