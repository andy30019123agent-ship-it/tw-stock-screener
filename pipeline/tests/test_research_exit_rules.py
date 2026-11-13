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
    # 原 11 條不變；驗收後只追加網站預設一條（放最後）
    assert keys == ["hold", "stop5", "stop8", "stop10", "stop12", "stop15", "stop20",
                    "trail8", "trail10", "trail15", "ma20", "site15ma"]
    assert rx.CAPS == (20, 40)


def test_網站預設_月線在現價下且高於85折_用月線():
    c = [100.0] * 19 + [110.0]                   # 訊號日 i=19 收盤 110，MA20＝100.5
    lvl = rx.site_stop_level(c, 19)
    assert abs(lvl - (100 * 19 + 110) / 20) < 1e-12   # 93.5 < 100.5 < 110 → 用月線


def test_網站預設_月線在現價之上_退回85折():
    c = [100.0] * 19 + [90.0]                    # 收盤 90 在月線 99.5 之下 → 月線不是防守位
    assert abs(rx.site_stop_level(c, 19) - 90 * 0.85) < 1e-12


def test_網站預設_月線低於85折_用85折():
    c = [50.0] * 19 + [200.0]                    # MA20＝57.5 < 170 → 用 170
    assert abs(rx.site_stop_level(c, 19) - 170.0) < 1e-12


def test_網站預設_以訊號日價位觸發_隔日開盤成交():
    n = 60
    c = [100.0] * n
    o, h, l = list(c), list(c), list(c)
    sig = 29
    c[sig] = 105.0                               # 訊號日收盤 105，MA20＝100.25 → 防守價 100.25
    e = sig + 1
    for j in range(e, n):                        # 進場後價位 101（在防守價之上）
        o[j] = h[j] = l[j] = c[j] = 101.0
    l[e + 2] = 100.2                             # 第 3 天低點跌破 100.25 → 觸發（固定 −15% 不會觸發）
    o[e + 3] = 99.0
    r = rx.simulate_exit(o, h, l, c, e, "site", 0.15, 20)
    assert r["stopped"] and r["trigger_day"] == 3 and abs(r["gross"] - (99.0 / 101.0 - 1)) < 1e-12
    r_fixed = rx.simulate_exit(o, h, l, c, e, "fixed", 0.15, 20)
    assert not r_fixed["stopped"]


def _t(net, stopped=False, day=None):
    return {"net": net, "stopped": stopped, "trigger_day": day}


def test_續抱vs隔日賣_只取前5天觸發且差為續抱減賣出():
    stop = [_t(-0.11, True, 2), _t(-0.12, True, 5), _t(-0.10, True, 6), _t(0.05)]
    hold = [_t(0.03), _t(-0.20), _t(0.50), _t(0.05)]
    dates = ["d1", "d1", "d2", "d3"]
    r = rx.hold_vs_sell(stop, hold, dates, max_day=5, blocks=(20,))
    assert r["n"] == 2 and r["days"] == 1          # 第 3 筆第 6 天才觸發、第 4 筆沒觸發 → 不算
    # 差：+14pp、−8pp → 按筆平均 +3pp；同一天 → 按日也是 +3pp
    assert abs(r["per_trade_pp"] - 3.0) < 1e-9 and abs(r["per_day_pp"] - 3.0) < 1e-9
    assert r["hold_better"] == 0.5 and r["hold_win"] == 0.5 and r["sell_win"] == 0.0


def test_續抱vs隔日賣_按筆與按日權重不同():
    stop = [_t(-0.1, True, 1)] * 3 + [_t(-0.1, True, 1)]
    hold = [_t(0.0)] * 3 + [_t(-0.3)]                # d1 三筆各 +10pp，d2 一筆 −20pp
    r = rx.hold_vs_sell(stop, hold, ["d1", "d1", "d1", "d2"], blocks=(20,))
    assert abs(r["per_trade_pp"] - 2.5) < 1e-9      # (30−20)/4
    assert abs(r["per_day_pp"] - (-5.0)) < 1e-9     # (10 + −20)/2


def test_按筆CI_常數序列就是該值():
    ci = rx.circular_ratio_ci([6.0, 4.0, 2.0], [3, 2, 1], 2, n_boot=50)
    assert ci == [2.0, 2.0]
