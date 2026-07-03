"""機會股選股 / 成績單的單元測試（契約欄位、過濾規則、成績單手算對照）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import opportunities as opp

CONTRACT_KEYS = {"id", "name", "score", "reasons", "close", "support_ma20",
                 "recent_high20", "rs20", "revenue_yoy", "earnings_date", "risk_flags"}

# 簡化權重表：糾結轉強 3 分、爆量突破 2 分、其餘預設 1
WEIGHTS = {"signals": {
    "signal_ma": {"weight": 3}, "signal_breakout": {"weight": 2},
}}


def _stock(sid, **kw):
    base = {"id": sid, "name": f"股{sid}", "close": 100.0, "ma20": 95.0,
            "recent_high20": 110.0, "rs20": 1.0, "avg_vol_lots": 800,
            "earnings_date": None}
    base.update(kw)
    return base


def test_contract_keys_and_score_sum():
    results = [_stock("1111", signal_ma=True, signal_breakout=True)]
    rev = {"1111": {"yoy": 10.0}}
    o = opp.build_opportunities(results, WEIGHTS, rev, "2026-07-02")
    assert o["date"] == "2026-07-02"
    p = o["picks"][0]
    assert set(p.keys()) == CONTRACT_KEYS
    assert p["score"] == 5                    # 3 + 2
    assert p["reasons"] == ["糾結轉強", "爆量突破"]
    assert p["revenue_yoy"] == 10.0
    assert p["support_ma20"] == 95.0


def test_revenue_yoy_negative_dropped():
    results = [_stock("2222", signal_ma=True)]
    rev = {"2222": {"yoy": -3.0}}
    o = opp.build_opportunities(results, WEIGHTS, rev, "2026-07-02")
    assert o["picks"] == []                   # 營收年減 → 剔除


def test_revenue_missing_flagged_not_dropped():
    results = [_stock("3333", signal_ma=True)]
    o = opp.build_opportunities(results, WEIGHTS, {}, "2026-07-02")
    assert len(o["picks"]) == 1
    assert "營收資料缺" in o["picks"][0]["risk_flags"]
    assert o["picks"][0]["revenue_yoy"] is None


def test_low_liquidity_dropped():
    results = [_stock("4444", signal_ma=True, avg_vol_lots=300)]
    rev = {"4444": {"yoy": 5.0}}
    o = opp.build_opportunities(results, WEIGHTS, rev, "2026-07-02")
    assert o["picks"] == []                   # 均量 < 500 → 剔除


def test_high_bias_flagged_not_dropped():
    # close 130 vs ma20 100 → 乖離 30% > 15% → 加旗標但保留
    results = [_stock("5555", signal_ma=True, close=130.0, ma20=100.0)]
    rev = {"5555": {"yoy": 5.0}}
    o = opp.build_opportunities(results, WEIGHTS, rev, "2026-07-02")
    assert len(o["picks"]) == 1
    assert "乖離大" in o["picks"][0]["risk_flags"]


def test_no_signal_excluded_and_top5_sorted():
    results = [_stock("6001", signal_ma=True, signal_breakout=True),   # 5 分
              _stock("6002", signal_ma=True),                           # 3 分
              _stock("6003"),                                           # 無訊號 → 排除
              _stock("6004", signal_breakout=True),                     # 2 分
              _stock("6005", signal_ma=True, signal_breakout=True, rs20=9.0),  # 5 分、rs 高
              _stock("6006", signal_ma=True),                           # 3 分
              _stock("6007", signal_ma=True)]                           # 3 分
    rev = {s["id"]: {"yoy": 5.0} for s in results}
    o = opp.build_opportunities(results, WEIGHTS, rev, "2026-07-02")
    ids = [p["id"] for p in o["picks"]]
    assert len(ids) == 5                       # Top 5
    assert "6003" not in ids                   # 無訊號被排除
    assert ids[0] == "6005"                    # 同 5 分、rs20 高者在前
    assert ids[1] == "6001"
    scores = [p["score"] for p in o["picks"]]
    assert scores == sorted(scores, reverse=True)


def test_compute_scoreboard_hand_calc():
    # 交易日曆 25 天，pick 在 day0，滿 20 交易日後看 day20 報酬
    cal = [f"2026-06-{d:02d}" for d in range(1, 26)]   # 25 天
    d0, d20 = cal[0], cal[20]
    entries = [{"date": d0, "picks": [
        {"id": "A"}, {"id": "B"}, {"id": "C"}]}]
    adj = {
        "A": {d0: 100.0, d20: 110.0},   # +10% → 勝
        "B": {d0: 100.0, d20: 95.0},    # −5%  → 敗
        "C": {d0: 100.0, d20: 100.0},   # 0%   → 不算勝（>0 才算）
    }
    sb = opp.compute_scoreboard(entries, cal, adj, forward=20)
    assert sb["samples"] == 3
    assert sb["win_rate"] == round(1 / 3, 4)          # 只有 A 勝
    assert sb["avg_ret"] == round((0.10 - 0.05 + 0.0) / 3 * 100, 2)


def test_scoreboard_ignores_immature_picks():
    # pick 距今不足 20 交易日 → 不計入樣本
    cal = [f"2026-06-{d:02d}" for d in range(1, 11)]   # 只有 10 天
    entries = [{"date": cal[0], "picks": [{"id": "A"}]}]
    adj = {"A": {cal[0]: 100.0}}
    sb = opp.compute_scoreboard(entries, cal, adj, forward=20)
    assert sb["samples"] == 0
    assert sb["win_rate"] is None
