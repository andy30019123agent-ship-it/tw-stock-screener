"""回測權重與訊號旗標的單元測試（含勝率手算對照）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import backtest_signals as bt


def test_stats_to_weights_hand_calc():
    # 手算對照：糾結轉強成立 40 次，其中 30 次上漲（勝率 0.75）
    #   → weight = max(0, round((0.75 − 0.5) × 20)) = round(5.0) = 5
    stats = {"signal_ma": {"wins": 30, "count": 40, "ret_sum": 40 * 0.04}}
    w = bt.stats_to_weights(stats)
    assert w["signal_ma"]["samples"] == 40
    assert w["signal_ma"]["win_rate"] == 0.75
    assert w["signal_ma"]["weight"] == 5
    assert w["signal_ma"]["avg_ret"] == 4.0   # 平均報酬 4%


def test_weight_floor_at_zero():
    # 勝率 0.3 → (0.3−0.5)×20 = −4 → max(0, −4) = 0（差訊號權重歸零）
    stats = {"signal_breakout": {"wins": 12, "count": 40, "ret_sum": 0.0}}
    w = bt.stats_to_weights(stats)
    assert w["signal_breakout"]["weight"] == 0


def test_small_sample_uses_default_weight():
    # 樣本 < 30 一律用預設權重 1，不論勝率高低（統計不可靠）
    stats = {"trust_buy": {"wins": 10, "count": 10, "ret_sum": 10 * 0.1}}
    w = bt.stats_to_weights(stats)
    assert w["trust_buy"]["samples"] == 10
    assert w["trust_buy"]["weight"] == 1
    assert w["trust_buy"]["win_rate"] == 1.0    # 勝率仍照實呈現


def test_zero_sample_signal_present_with_default():
    # 完全沒出現的訊號也要在輸出裡（權重 1、勝率 None），供選股/展示不 KeyError
    w = bt.stats_to_weights({})
    for k in bt.SIGNALS:
        assert w[k]["weight"] == 1
        assert w[k]["win_rate"] is None
        assert w[k]["samples"] == 0


def test_signal_flags_reads_streaks():
    ind = {"signal_ma": True, "foreign_streak": 3, "trust_streak": 2,
           "undervalued": True}
    f = bt.signal_flags(ind)
    assert f["signal_ma"] is True
    assert f["foreign_buy"] is True     # streak 3 >= 3
    assert f["trust_buy"] is False      # streak 2 < 3
    assert f["undervalued"] is True
    assert f["sn_break_low_recover"] is False
