"""機會股選股 / 成績單的單元測試（契約欄位、過濾規則、成績單手算對照）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import opportunities as opp

# 跨 repo 契約欄位。rs_pct_60 於 2026-07-25 加入（排序依據從 rs20 換成它）。
CONTRACT_KEYS = {"id", "name", "score", "reasons", "close", "support_ma20",
                 "recent_high20", "rs20", "rs_pct_60", "revenue_yoy", "earnings_date", "risk_flags"}

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


def test_no_signal_excluded_and_sorted_by_rs_pct_60():
    """2026-07-25 規格變更：檔數 5→10（TOP_N）、同分時的排序依據 rs20 → rs_pct_60。
    rs20 實測與隨機排序無異（t=0.28）；rs_pct_60 是全市場 60 日報酬百分位，每項指標都更好。"""
    results = [_stock("6001", signal_ma=True, signal_breakout=True),   # 5 分
              _stock("6002", signal_ma=True),                           # 3 分
              # ⚠️ _stock 預設就帶 sn_squeeze_breakout（見 helper），所以這檔**不是無訊號**，
              # 只是簡化 WEIGHTS 沒給它分數 → score 0。舊測試註解寫「無訊號→排除」是錯的，
              # 它一直都在名單裡，只是以前 TOP_N=5 剛好把它截掉，所以沒被發現。
              _stock("6003"),                                           # 0 分（權重表沒列的訊號）
              _stock("6004", signal_breakout=True),                     # 2 分
              # 5 分、rs_pct_60 高 → 同分中應排最前；rs20 故意設低，證明排序不再看它
              _stock("6005", signal_ma=True, signal_breakout=True, rs20=-99.0, rs_pct_60=0.95),
              _stock("6006", signal_ma=True),                           # 3 分
              _stock("6007", signal_ma=True)]                           # 3 分
    rev = {s["id"]: {"yoy": 5.0} for s in results}
    o = opp.build_opportunities(results, WEIGHTS, rev, "2026-07-02")
    ids = [p["id"] for p in o["picks"]]
    assert len(ids) == 7                       # 7 檔都有訊號、未達 TOP_N=10 → 全數保留
    assert ids[-1] == "6003"                   # 0 分的排最後（權重表沒列到的訊號不加分）
    assert ids[0] == "6005"                    # 同 5 分：rs_pct_60 高者在前（即使 rs20 是 −99）
    assert ids[1] == "6001"
    scores = [p["score"] for p in o["picks"]]
    assert scores == sorted(scores, reverse=True)


def test_top_n_是_10_且會截斷():
    """TOP_N=10：候選超過 10 檔時只留前 10。"""
    results = [_stock(str(7000 + i), signal_ma=True, rs_pct_60=(i / 100)) for i in range(15)]
    rev = {s["id"]: {"yoy": 5.0} for s in results}
    o = opp.build_opportunities(results, WEIGHTS, rev, "2026-07-02")
    assert opp.TOP_N == 10
    assert len(o["picks"]) == 10
    # 同分（都 3 分）→ 依 rs_pct_60 由高到低，所以第一名是 i=14
    assert o["picks"][0]["id"] == "7014"


def test_缺rs_pct_60用最低值墊底_不可用0():
    """0 是「全市場最弱」的合法百分位，不能拿來代表缺值——否則缺資料的會排在最弱者前面。"""
    results = [_stock("8001", signal_ma=True, rs_pct_60=None),
               _stock("8002", signal_ma=True, rs_pct_60=0.0)]
    rev = {s["id"]: {"yoy": 5.0} for s in results}
    o = opp.build_opportunities(results, WEIGHTS, rev, "2026-07-02")
    assert [p["id"] for p in o["picks"]] == ["8002", "8001"], "有資料且為 0 的要排在缺資料的前面"


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


def test_run_passes_force_recompute_to_ensure_weights(monkeypatch):
    """daily.yml 的 workflow_dispatch.force_recompute → build_data.py --force-recompute →
    opp.run(force_recompute=...) → bt.ensure_weights(force=...)。這裡驗證最後一段接線：
    run() 沒有自己實作快取判斷（那是 backtest_signals.ensure_weights 的事），只負責把
    force_recompute 原封不動傳下去。stub 掉所有 I/O，只斷言 ensure_weights 收到的 force 值。"""
    captured = {}

    def fake_ensure_weights(price_hist, chip_hist, div_hist, universe, today=None, force=False):
        captured["force"] = force
        return {"signals": {}}

    monkeypatch.setattr(opp.bt, "ensure_weights", fake_ensure_weights)
    monkeypatch.setattr(opp.bt, "_load", lambda path: None)
    monkeypatch.setattr(opp.mr, "load_or_fetch", lambda today: {})
    monkeypatch.setattr(opp, "update_picks_history", lambda o: [])
    monkeypatch.setattr(opp, "trading_calendar", lambda price_hist: [])
    monkeypatch.setattr(
        opp, "compute_scoreboard",
        lambda entries, cal, adj, forward=opp.FORWARD: {
            "updated": "x", "forward_days": forward, "samples": 0,
            "win_rate": None, "avg_ret": None,
        },
    )
    monkeypatch.setattr(opp, "_write_json", lambda path, obj: None)

    opp.run([], {}, {}, {}, [], "2026-07-25", force_recompute=True)
    assert captured["force"] is True

    opp.run([], {}, {}, {}, [], "2026-07-25", force_recompute=False)
    assert captured["force"] is False

    opp.run([], {}, {}, {}, [], "2026-07-25")   # 預設不強制
    assert captured["force"] is False


# ── 入場門檻的降級可見性（2026-07-25 Codex 複查後補）──────────────────────
def _stock(sid, **kw):
    base = {"id": sid, "name": f"N{sid}", "avg_vol_lots": 5000, "close": 100, "ma20": 95,
            "sn_squeeze_breakout": True, "rs_confirmed_60_120": True, "rs_pct_60": 0.9}
    base.update(kw)
    return base


def _weights():
    return {"signals": {"sn_squeeze_breakout": {"weight": 1, "label": "縮口帶量突破"}}}


def test_gate_min_pool_要算營收過濾之後的候選數():
    """原本只看「有訊號＋流動性」就判 GATE_MIN_POOL，但之後還會剔除營收年減 →
    20 檔可能被砍到不足 5 檔，保命門檻沒真的保住輸出（2026-07-25 Codex 指出）。"""
    stocks = [_stock(str(1000 + i)) for i in range(25)]
    # 25 檔都過門檻，但其中 20 檔營收年減 → 實際可用只有 5 檔 < GATE_MIN_POOL(20)
    revenue = {s["id"]: {"yoy": (-1 if i < 20 else 1)} for i, s in enumerate(stocks)}
    out = opp.build_opportunities(stocks, _weights(), revenue, "2026-07-24")
    assert out["gate"]["pool"] == 5, "pool 應該只算營收也過關的"
    assert out["gate"]["applied"] is False
    assert out["gate"]["reason"] == "pool_too_small"


def test_gate_足夠時正常套用():
    stocks = [_stock(str(2000 + i)) for i in range(25)]
    revenue = {s["id"]: {"yoy": 5} for s in stocks}
    out = opp.build_opportunities(stocks, _weights(), revenue, "2026-07-24")
    assert out["gate"]["applied"] is True and out["gate"]["reason"] == "applied"


def test_RS_資料不可用時門檻退回全市場但要說明原因():
    """RS 掛掉 → 旗標全 False → 門檻靜默失效卻看起來正常。必須用 reason 分辨故障與候選不足。"""
    stocks = [_stock(str(3000 + i), rs_confirmed_60_120=False, rs_pct_60=None) for i in range(25)]
    revenue = {s["id"]: {"yoy": 5} for s in stocks}
    out = opp.build_opportunities(stocks, _weights(), revenue, "2026-07-24")
    assert out["gate"]["applied"] is False
    assert out["gate"]["reason"] == "rs_unavailable"
    assert len(out["picks"]) > 0, "退回全市場後仍要推得出東西"
