"""回測權重與訊號旗標的單元測試（含勝率手算對照）。

2026-07-23 改版重點（Codex 交叉審計後 Andy 拍板全修）：
- 權重改看「超額勝率」（該股報酬 － 同日全市場平均），不再看絕對勝率。絕對勝率在多頭市場
  裡亂選也會 >50%，等於把大盤漲幅記在訊號頭上。
- 樣本不足一律 weight=0，不再給預設 1。「沒有證據」不該等於「中等證據」。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import backtest_signals as bt


def test_stats_to_weights_hand_calc():
    # 手算對照：糾結轉強成立 40 次，平均報酬 4%、平均超額 +1.5 個百分點
    #   → weight = min(5, max(1, round(1.5 × 2))) = 3
    stats = {"signal_ma": {"wins": 32, "count": 40, "ret_sum": 40 * 0.04,
                           "exc_wins": 30, "exc_sum": 40 * 0.015}}
    w = bt.stats_to_weights(stats)
    assert w["signal_ma"]["samples"] == 40
    assert w["signal_ma"]["win_rate"] == 0.8            # 絕對勝率照實呈現（僅供對照）
    assert w["signal_ma"]["excess_win_rate"] == 0.75    # 超額勝率也照實呈現
    assert w["signal_ma"]["avg_ret"] == 4.0             # 平均報酬 4%
    assert w["signal_ma"]["avg_excess"] == 1.5          # 平均超額 1.5 個百分點 → 權重依據
    assert w["signal_ma"]["weight"] == 3
    assert w["signal_ma"]["validated"] is True


def test_勝率高但期望值為負_權重歸零():
    # 實測「破底翻」的形狀：絕對勝率 60%，平均超額卻是 −2pp（純粹跟著大盤反彈）。
    # 舊公式看勝率會給它最高權重 3，新公式看期望值直接歸零。
    stats = {"sn_break_low_recover": {"wins": 60, "count": 100, "ret_sum": 100 * 0.023,
                                      "exc_wins": 35, "exc_sum": -100 * 0.02}}
    w = bt.stats_to_weights(stats)
    assert w["sn_break_low_recover"]["win_rate"] == 0.6
    assert w["sn_break_low_recover"]["avg_excess"] == -2.0
    assert w["sn_break_low_recover"]["weight"] == 0


def test_期望值微正也至少給1分_但上限5():
    low = bt.stats_to_weights({"signal_ma": {"count": 40, "wins": 20, "ret_sum": 0.0,
                                             "exc_wins": 20, "exc_sum": 40 * 0.001}})
    assert low["signal_ma"]["weight"] == 1      # +0.1pp → round(0.2)=0，但正期望值保底 1
    high = bt.stats_to_weights({"signal_ma": {"count": 40, "wins": 40, "ret_sum": 0.0,
                                              "exc_wins": 40, "exc_sum": 40 * 0.10}})
    assert high["signal_ma"]["weight"] == 5     # +10pp → 20，封頂 5


def test_絕對勝率高但沒贏過大盤_權重應為零():
    # 40 次全部上漲（絕對勝率 1.0），但只有 12 次贏過同日平均 → 超額勝率 0.3
    #   → (0.3−0.5)×20 = −4 → max(0, −4) = 0。這正是「牛市亂選也會贏」要擋掉的情況。
    stats = {"signal_breakout": {"wins": 40, "count": 40, "ret_sum": 40 * 0.05,
                                 "exc_wins": 12, "exc_sum": -40 * 0.01}}
    w = bt.stats_to_weights(stats)
    assert w["signal_breakout"]["win_rate"] == 1.0
    assert w["signal_breakout"]["weight"] == 0


def test_樣本不足一律權重零_但統計照實呈現():
    # 樣本 < 30 → weight 0（不再是預設 1）；勝率與樣本數仍照實輸出供觀察
    stats = {"trust_buy": {"wins": 10, "count": 10, "ret_sum": 10 * 0.1,
                           "exc_wins": 10, "exc_sum": 10 * 0.05}}
    w = bt.stats_to_weights(stats)
    assert w["trust_buy"]["samples"] == 10
    assert w["trust_buy"]["weight"] == 0
    assert w["trust_buy"]["validated"] is False
    assert w["trust_buy"]["win_rate"] == 1.0


def test_零樣本訊號仍在輸出裡_權重零():
    # 完全沒出現的訊號也要在輸出裡（供選股/展示不 KeyError），但權重必須是 0
    w = bt.stats_to_weights({})
    for k in bt.SIGNALS:
        assert w[k]["weight"] == 0
        assert w[k]["win_rate"] is None
        assert w[k]["samples"] == 0
        assert w[k]["validated"] is False


def test_signal_flags_reads_streaks():
    ind = {"signal_ma": True, "foreign_streak": 3, "trust_streak": 2,
           "undervalued": True}
    f = bt.signal_flags(ind)
    assert f["signal_ma"] is True
    assert f["foreign_buy"] is True     # streak 3 >= 3
    assert f["trust_buy"] is False      # streak 2 < 3
    assert f["undervalued"] is True
    assert f["sn_break_low_recover"] is False


def test_超額基準用同日全市場平均():
    # 同一天三檔可評估：報酬 10%、0%、-4% → 平均 2%。訊號只在第一檔成立。
    events = [{"date": "2026-07-01", "sid": "A", "ret": 0.10, "fired": ["signal_ma"]}]
    by_date = {"2026-07-01": [0.10, 0.0, -0.04]}
    st = bt.events_to_stats(events, by_date)
    assert st["signal_ma"]["count"] == 1
    assert st["signal_ma"]["wins"] == 1                       # 絕對：+10% > 0
    assert st["signal_ma"]["exc_wins"] == 1                   # 超額：10% − 2% = +8%
    assert round(st["signal_ma"]["exc_sum"], 6) == round(0.10 - 0.02, 6)


def test_大盤更強時_上漲也算輸():
    # 個股 +3%，但同日全市場平均 +8% → 絕對算贏、超額算輸。這是新舊做法的關鍵差異。
    events = [{"date": "2026-07-01", "sid": "A", "ret": 0.03, "fired": ["signal_ma"]}]
    by_date = {"2026-07-01": [0.08, 0.08, 0.08]}
    st = bt.events_to_stats(events, by_date)
    assert st["signal_ma"]["wins"] == 1
    assert st["signal_ma"]["exc_wins"] == 0
