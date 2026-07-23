"""填息天數（B 段第二段）。

重點在「用原始成交價比對，不能用還原權息後的序列」——還原序列已經把除權息的價差抹平，
拿它比會讓每一檔都在除權息當天瞬間「填息」，數字看起來漂亮但完全沒有意義。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from build_data import dividend_fill  # noqa: E402


def rows(*pairs):
    return [{"date": d, "open": c, "max": c, "min": c, "close": c,
             "Trading_Volume": 1000, "Trading_money": 1000} for d, c in pairs]


def test_填息_當日就漲回門檻算第1天():
    # 除權息當日開低走高、收盤 100.5 已站回前一日的 100 → 當天就填息完畢
    r = dividend_fill(
        rows(("2026-07-01", 100.0), ("2026-07-02", 100.5), ("2026-07-03", 101.0)),
        [{"date": "2026-07-02", "ratio": 0.97}],
    )
    assert r["ex_date"] == "2026-07-02"
    assert r["pre_close"] == 100.0
    assert r["fill_days"] == 1
    assert r["pending_days"] is None


def test_填息_第3天才漲回():
    r = dividend_fill(
        rows(("2026-07-01", 100.0), ("2026-07-02", 97.0), ("2026-07-03", 98.0), ("2026-07-04", 100.5)),
        [{"date": "2026-07-02", "ratio": 0.97}],
    )
    assert r["fill_days"] == 3


def test_剛好等於門檻算填息完成():
    r = dividend_fill(
        rows(("2026-07-01", 100.0), ("2026-07-02", 97.0), ("2026-07-03", 100.0)),
        [{"date": "2026-07-02", "ratio": 0.97}],
    )
    assert r["fill_days"] == 2


def test_尚未填息_回報已過天數與差距():
    r = dividend_fill(
        rows(("2026-07-01", 100.0), ("2026-07-02", 97.0), ("2026-07-03", 95.0)),
        [{"date": "2026-07-02", "ratio": 0.97}],
    )
    assert r["fill_days"] is None
    assert r["pending_days"] == 2
    assert r["discount_pct"] == -5.0  # 95 相對門檻 100


def test_多次除權息只看最近一次():
    r = dividend_fill(
        rows(("2026-01-01", 50.0), ("2026-01-02", 48.0), ("2026-07-01", 100.0),
             ("2026-07-02", 97.0), ("2026-07-03", 101.0)),
        [{"date": "2026-01-02", "ratio": 0.96}, {"date": "2026-07-02", "ratio": 0.97}],
    )
    assert r["ex_date"] == "2026-07-02"
    assert r["pre_close"] == 100.0


def test_沒有除權息事件回_None():
    assert dividend_fill(rows(("2026-07-01", 100.0)), []) is None
    assert dividend_fill(rows(("2026-07-01", 100.0)), None) is None


def test_除權息日落在歷史之外回_None_不硬猜():
    # 事件日早於歷史起點：抓不到「前一日收盤」就沒有門檻可比
    assert dividend_fill(rows(("2026-07-01", 100.0), ("2026-07-02", 99.0)),
                         [{"date": "2026-01-05", "ratio": 0.97}]) is None
    # 事件日晚於歷史終點：還沒發生
    assert dividend_fill(rows(("2026-07-01", 100.0), ("2026-07-02", 99.0)),
                         [{"date": "2026-12-31", "ratio": 0.97}]) is None
