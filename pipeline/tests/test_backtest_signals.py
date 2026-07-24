"""回測權重與訊號旗標的單元測試（含勝率手算對照）。

2026-07-23 改版重點（Codex 交叉審計後 Andy 拍板全修）：
- 權重改看「超額勝率」（該股報酬 － 同日全市場平均），不再看絕對勝率。絕對勝率在多頭市場
  裡亂選也會 >50%，等於把大盤漲幅記在訊號頭上。
- 樣本不足一律 weight=0，不再給預設 1。「沒有證據」不該等於「中等證據」。
"""
import os
import sys
import datetime as _dt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import backtest_signals as bt


def _seq_dates(n, start="2024-01-01"):
    """n 個遞增且可排序的日期字串（單測把 by_date 的鍵當交易日曆用，週末與否無所謂）。"""
    d0 = _dt.date.fromisoformat(start)
    return [(d0 + _dt.timedelta(days=i)).isoformat() for i in range(n)]


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


# ── 多時間窗勝率榜（windowed_stats）────────────────────────────────────
def test_windowed_stats_依日期切窗與per窗基準():
    # 三個事件分佈在不同時間；as_of=2026-07-23
    #   3m 界=2026-04-24、6m 界=2026-01-24、1y 界=2025-07-23
    events = [
        {"date": "2026-07-01", "sid": "A", "ret": 0.05, "fired": ["signal_ma"]},  # 落在所有窗
        {"date": "2026-01-01", "sid": "B", "ret": 0.03, "fired": ["signal_ma"]},  # 只在 1y、all
        {"date": "2024-09-01", "sid": "C", "ret": 0.02, "fired": ["signal_ma"]},  # 只在 all
    ]
    by_date = {  # 每日基準均值為 0（[x,-x]），讓超額＝該股報酬，方便手算
        "2026-07-01": [0.05, -0.05],
        "2026-01-01": [0.03, -0.03],
        "2024-09-01": [0.02, -0.02],
    }
    w = bt.windowed_stats(events, by_date, "2026-07-23")
    s = w["signal_ma"]
    # 窗內樣本數：3m 只 7/1（1）；6m 同（1/1 早於 1/24 被排除）；1y 加上 1/1（2）；all 全部（3）
    assert s["3m"]["samples"] == 1
    assert s["6m"]["samples"] == 1
    assert s["1y"]["samples"] == 2
    assert s["all"]["samples"] == 3
    # per-窗基準：3m 只用窗內那天 → 超額＝5pp；all 平均 (5+3+2)/3 = 3.33pp
    assert s["3m"]["avg_excess"] == 5.0
    assert s["all"]["avg_excess"] == 3.33
    # 結構：每訊號有 label 與四個窗
    assert s["label"] == "糾結轉強"
    assert set(k for k in s if k != "label") == {"3m", "6m", "1y", "all"}


def test_windowed_stats_沒事件的訊號各窗樣本為零():
    w = bt.windowed_stats([], {}, "2026-07-23")
    assert w["signal_breakout"]["all"]["samples"] == 0
    assert w["signal_breakout"]["3m"]["avg_excess"] is None


def test_windowed_stats_無as_of回空():
    assert bt.windowed_stats([{"date": "2026-07-01", "sid": "A", "ret": 0.05,
                               "fired": ["signal_ma"]}], {"2026-07-01": [0.05]}, "") == {}


# ── 組合戰績（combo_stats）────────────────────────────────────────────
def _cev(date, sid, i, ret, sigs):
    return {"date": date, "sid": sid, "i": i, "ret": ret, "raw_fired": sigs, "fired": sigs}


def test_combo_stats_兩兩組合超額樣本與回傳結構():
    # A、B 常一起出現且贏；C 單獨出現。基準均值 0（[x,-x]）→ 超額＝報酬。不同 sid 不觸發組合冷卻。
    events = [
        _cev("d1", "1", 0, 0.05, ["signal_ma", "signal_breakout"]),
        _cev("d2", "2", 0, 0.03, ["signal_ma", "signal_breakout"]),
        _cev("d3", "3", 0, -0.01, ["signal_ma", "signal_breakout"]),
        _cev("d4", "4", 0, 0.02, ["sn_squeeze_breakout"]),  # 單一，不成組合
    ]
    by_date = {"d1": [0.05, -0.05], "d2": [0.03, -0.03], "d3": [-0.01, 0.01], "d4": [0.02, -0.02]}
    combos, pairs = bt.combo_stats(events, by_date, min_sample=1)
    ma_bo = [c for c in combos if set(c["sigs"]) == {"signal_ma", "signal_breakout"}]
    assert len(ma_bo) == 1
    c = ma_bo[0]
    assert c["samples"] == 3
    assert c["avg_excess"] == round((0.05 + 0.03 - 0.01) / 3 * 100, 2)  # 2.33pp
    assert c["excess_win_rate"] == round(2 / 3, 4)
    assert "糾結轉強" in c["labels"] and "爆量突破" in c["labels"]
    assert not any(len(x["sigs"]) < 2 for x in combos)
    # pairs 應含這個兩兩配對（給熱力圖）
    assert any(set(p["sigs"]) == {"signal_ma", "signal_breakout"} for p in pairs)


def test_combo_stats_樣本門檻():
    events = [_cev("d1", "1", 0, 0.10, ["signal_ma", "signal_breakout"])]
    by_date = {"d1": [0.0]}
    combos, pairs = bt.combo_stats(events, by_date, min_sample=5)
    assert combos == [] and pairs == []            # 1 筆 <5 被濾掉
    combos2, _ = bt.combo_stats(events, by_date, min_sample=1)
    assert combos2 and combos2[0]["samples"] == 1


def test_combo_stats_組合級冷卻去重():
    # 同一檔、同一組合，冷卻期(預設20)內連續成立 → 只算一筆，不灌水
    events = [
        _cev("d1", "1", 0, 0.05, ["signal_ma", "signal_breakout"]),
        _cev("d2", "1", 3, 0.05, ["signal_ma", "signal_breakout"]),   # i 差 3 < 20 → 不採計
        _cev("d3", "1", 25, 0.05, ["signal_ma", "signal_breakout"]),  # i 差 25 ≥ 20 → 再採計
    ]
    by_date = {"d1": [0.0], "d2": [0.0], "d3": [0.0]}
    combos, _ = bt.combo_stats(events, by_date, min_sample=1, cooldown=20)
    assert combos[0]["samples"] == 2               # 中間那筆被冷卻濾掉


def test_combo_stats_穩健度下界壓低小樣本波動():
    # 高波動小樣本：平均超額不低，但 excess_lb（下界）應明顯低於平均
    events = [
        _cev("d1", "1", 0, 0.20, ["signal_ma", "signal_breakout"]),
        _cev("d2", "2", 0, -0.10, ["signal_ma", "signal_breakout"]),
    ]
    by_date = {"d1": [0.0], "d2": [0.0]}
    combos, _ = bt.combo_stats(events, by_date, min_sample=1)
    c = combos[0]
    assert c["avg_excess"] == 5.0                   # (20-10)/2 = 5pp
    assert c["excess_lb"] < c["avg_excess"]         # 波動大 → 下界被壓低


# ── Phase A：walk-forward 樣本外驗證（walk_forward_oos）────────────────────
def test_oos_fold_count_math():
    # N=312 → (312-292)//20+1 = 2 folds；N=291 → 不足一個 fold（0）
    o2, f2 = bt.walk_forward_oos([], {d: [0.0] for d in _seq_dates(312)})
    assert f2 == 2
    o0, f0 = bt.walk_forward_oos([], {d: [0.0] for d in _seq_dates(291)})
    assert f0 == 0
    assert o0["signal_ma"]["status"] == "no_events"


def test_oos_穩健訊號_一致正超額():
    # 每天都有正 +5pp 超額的訊號 → 每個 fold 訓練都合格、樣本外也 +5 → robust、retention 1.0
    dates = _seq_dates(440)                          # F = (440-292)//20+1 = 8 folds
    by_date = {d: [0.0] for d in dates}              # 基準 0 → 超額＝報酬
    events = [{"date": d, "sid": s, "ret": 0.05, "fired": ["signal_ma"]}
              for d in dates for s in ("A", "B")]
    oos, F = bt.walk_forward_oos(events, by_date)
    r = oos["signal_ma"]
    assert F == 8
    assert r["status"] == "robust"
    assert r["excess_pp"] == 5.0
    assert r["selected_fraction"] == 1.0
    assert r["retention_ratio"] == 1.0
    assert r["selected_folds"] == 8 and r["active_dates"] >= 10


def test_oos_過擬合訊號_訓練正樣本外負():
    # 前 252 天 +8pp、之後 −8pp：早期 fold 訓練期看好（合格），但其樣本外落在負區 → overfit
    dates = _seq_dates(440)
    by_date = {d: [0.0] for d in dates}
    events = []
    for i, d in enumerate(dates):
        ret = 0.08 if i < 252 else -0.08
        for s in ("A", "B"):
            events.append({"date": d, "sid": s, "ret": ret, "fired": ["signal_ma"]})
    oos, _ = bt.walk_forward_oos(events, by_date)
    r = oos["signal_ma"]
    assert r["selected_folds"] >= 3                  # 早期 fold 訓練期為正、確實被選
    assert r["excess_pp"] < 0                         # 但樣本外是負的
    assert r["status"] == "overfit"


def test_oos_樣本不足誠實標示():
    # 只有 5 筆歷史事件 → 連訓練門檻都不到，標 insufficient_history、不硬算
    dates = _seq_dates(400)
    by_date = {d: [0.0] for d in dates}
    events = [{"date": dates[i], "sid": "A", "ret": 0.05, "fired": ["signal_ma"]}
              for i in range(5)]
    oos, _ = bt.walk_forward_oos(events, by_date)
    assert oos["signal_ma"]["status"] == "insufficient_history"


# ── Phase A：EWMA 時間自適應權重（adaptive_weights）──────────────────────
def test_ess_by_date_群聚():
    assert bt._ess_by_date([]) == 0.0
    assert bt._ess_by_date(["d1", "d1", "d1"]) == 1.0        # 全同一天 → 相當於 1 個獨立樣本
    assert round(bt._ess_by_date(["d1", "d2", "d3", "d4"]), 6) == 4.0   # 全不同天 → 4


def test_adaptive_近期加權高於歷史():
    # 前 50 天 +2pp、最後 10 天 +10pp → EWMA 近期均值應被拉高，且介於歷史與最新之間
    dates = _seq_dates(60)
    by_date = {d: [0.0] for d in dates}
    events = [{"date": dates[i], "sid": "A", "ret": (0.10 if i >= 50 else 0.02),
               "fired": ["signal_ma"]} for i in range(60)]
    adp = bt.adaptive_weights(events, by_date)["signal_ma"]
    assert adp["status"] == "eligible"
    assert adp["hist_excess_pp"] == round((50 * 2 + 10 * 10) / 60, 2)   # 3.33pp
    assert adp["recent_excess_pp"] > adp["hist_excess_pp"]              # 近期被拉高
    assert adp["effective_excess_pp"] < adp["blended_excess_pp"]        # 收縮後變小
    assert 1 <= adp["candidate_weight"] <= 5


def test_adaptive_樣本不足與零樣本():
    dates = _seq_dates(60)
    by_date = {d: [0.0] for d in dates}
    few = [{"date": dates[i], "sid": "A", "ret": 0.05, "fired": ["signal_ma"]} for i in range(10)]
    adp = bt.adaptive_weights(few, by_date)
    assert adp["signal_ma"]["status"] == "insufficient_history"
    assert adp["signal_ma"]["candidate_weight"] == 0
    assert adp["signal_breakout"]["status"] == "no_events"              # 完全沒出現
    assert adp["signal_breakout"]["candidate_weight"] == 0


def test_attach_phase_a_併入欄位不動原weight():
    dates = _seq_dates(440)
    by_date = {d: [0.0] for d in dates}
    events = [{"date": d, "sid": s, "ret": 0.05, "fired": ["signal_ma"]}
              for d in dates for s in ("A", "B")]
    weights = {"signals": bt.stats_to_weights(bt.events_to_stats(events, by_date))}
    before = weights["signals"]["signal_ma"]["weight"]
    oos, F = bt.attach_phase_a(weights, events, by_date)
    sig = weights["signals"]["signal_ma"]
    assert sig["weight"] == before                    # 現行 weight 一律不動
    assert sig["spec_version"] == bt.PHASE_A_SPEC
    assert sig["oos"]["status"] == "robust"
    assert sig["adaptive"]["candidate_weight"] >= 1
