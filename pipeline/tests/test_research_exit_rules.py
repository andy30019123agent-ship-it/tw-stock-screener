"""出場研究（research_exit_rules.simulate_exit）的成交規則單測。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import backtest_signals as bt          # noqa: E402
import research_exit_rules as rx       # noqa: E402


def _flat(n=60, px=100.0):
    return [px] * n, [px] * n, [px] * n, [px] * n


def test_持有20日_出場是第20天收盤():
    o, h, l, c = _flat()
    c = [100.0 + j for j in range(60)]          # 收盤線性上漲，用來辨認是哪一天
    r = rx.simulate_exit(o, h, l, c, 30, "hold", None, 20)
    assert r["hold"] == 20 and not r["stopped"]
    assert r["gross"] == c[30 + 19] / o[30] - 1          # entry_i+19，不是 entry_i+20
    assert r["net"] == bt._net_return(o[30], c[49])


def test_停損觸發_隔日開盤成交():
    o, h, l, c = _flat()
    e = 30
    l[e + 3] = 91.0                              # 第 4 天盤中碰到 −8%（92）
    o[e + 4] = 95.0                              # 隔日開盤反彈到 95：保守口徑照樣用開盤價
    r = rx.simulate_exit(o, h, l, c, e, "fixed", 0.08, 20)
    assert r["stopped"] and r["trigger_day"] == 4 and r["hold"] == 5
    assert r["gross"] == 95.0 / 100.0 - 1


def test_停損觸發_隔日跳空更低就吃跳空價():
    o, h, l, c = _flat()
    e = 30
    l[e + 3] = 91.0
    o[e + 4] = 80.0                              # 隔日開盤跳空到 −20%
    r = rx.simulate_exit(o, h, l, c, e, "fixed", 0.08, 20)
    assert abs(r["gross"] - (-0.20)) < 1e-12     # 吃 −20%，不是停損價 −8%
    # 樂觀上限：停損價當日成交 → −8%
    r2 = rx.simulate_exit(o, h, l, c, e, "fixed", 0.08, 20, fill="same_day")
    assert abs(r2["gross"] - (-0.08)) < 1e-12 and r2["hold"] == 4


def test_樂觀口徑_當天開盤已跳空跌破_只能拿開盤():
    o, h, l, c = _flat()
    e = 30
    o[e + 2], l[e + 2] = 85.0, 84.0              # 第 3 天一開盤就 −15%
    r = rx.simulate_exit(o, h, l, c, e, "fixed", 0.08, 20, fill="same_day")
    assert abs(r["gross"] - (-0.15)) < 1e-12


def test_最後一天才觸發_用當天收盤():
    o, h, l, c = _flat()
    e = 30
    l[e + 19], c[e + 19] = 90.0, 97.0            # 第 20 天盤中碰停損，但當天收盤本來就要賣
    r = rx.simulate_exit(o, h, l, c, e, "fixed", 0.08, 20)
    assert r["stopped"] and r["hold"] == 20 and abs(r["gross"] - (-0.03)) < 1e-12


def test_移動停損_用昨天以前的最高收盤():
    o, h, l, c = _flat()
    e = 30
    c[e + 1] = 120.0                             # 第 2 天收盤創高 120 → 回落 10% 線 108
    l[e + 2] = 109.0                             # 第 3 天低 109 未觸發（若用固定停損也不觸發）
    l[e + 3] = 107.0                             # 第 4 天低 107 觸發
    o[e + 4] = 106.0
    r = rx.simulate_exit(o, h, l, c, e, "trail", 0.10, 20)
    assert r["trigger_day"] == 4 and abs(r["gross"] - 0.06) < 1e-12


def test_跌破月線_收盤判斷():
    n = 60
    c = [100.0 + j for j in range(n)]            # 一路上漲，收盤都在 MA20 之上
    o, h, l = list(c), list(c), list(c)
    e = 30
    c[e + 5] = 80.0                              # 第 6 天收盤跌破
    o[e + 6] = 82.0
    r = rx.simulate_exit(o, h, l, c, e, "ma20", None, 20)
    assert r["trigger_day"] == 6 and r["gross"] == 82.0 / o[e] - 1
    r2 = rx.simulate_exit(o, h, l, c, e, "ma20", None, 20, fill="same_day")
    assert r2["gross"] == 80.0 / o[e] - 1


def test_斷點窗判斷():
    assert rx.window_has_break([10, 50], 31, 50)
    assert not rx.window_has_break([10, 51], 31, 50)
    assert not rx.window_has_break([], 31, 50)
    assert rx.window_has_break([31], 31, 31)


def test_規則清單事先固定():
    keys = [k for k, *_ in rx.RULES]
    assert keys == ["hold", "stop5", "stop8", "stop10", "stop12", "stop15", "stop20",
                    "trail8", "trail10", "trail15", "ma20"]
    assert rx.CAPS == (20, 40)
