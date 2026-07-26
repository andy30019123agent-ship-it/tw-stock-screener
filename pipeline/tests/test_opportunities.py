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


def test_top_n_會截斷且不寫死檔數():
    """候選超過 TOP_N 時只留前 TOP_N。

    ⚠️ 這個測試刻意**不寫死檔數**：2026-07-25 一天內從 5 改成 10 再改成 8，
    每次寫死都要改測試，而寫死的地方（例如 notify_tg 的 5 個圈號）曾直接讓部署整條掛掉。
    """
    n = opp.TOP_N
    results = [_stock(str(7000 + i), signal_ma=True, rs_pct_60=(i / 100)) for i in range(n + 5)]
    rev = {s["id"]: {"yoy": 5.0} for s in results}
    o = opp.build_opportunities(results, WEIGHTS, rev, "2026-07-02")
    assert len(o["picks"]) == n
    # 同分（都 3 分）→ 依 rs_pct_60 由高到低，第一名是 rs 最高的那檔
    assert o["picks"][0]["id"] == str(7000 + n + 4)


def test_缺rs_pct_60用最低值墊底_不可用0():
    """0 是「全市場最弱」的合法百分位，不能拿來代表缺值——否則缺資料的會排在最弱者前面。"""
    results = [_stock("8001", signal_ma=True, rs_pct_60=None),
               _stock("8002", signal_ma=True, rs_pct_60=0.0)]
    rev = {s["id"]: {"yoy": 5.0} for s in results}
    o = opp.build_opportunities(results, WEIGHTS, rev, "2026-07-02")
    assert [p["id"] for p in o["picks"]] == ["8002", "8001"], "有資料且為 0 的要排在缺資料的前面"


def test_compute_scoreboard_hand_calc():
    """2026-07-26 改口徑：進場價＝pick 日隔一交易日的還原開盤、出場價＝pick 日 +20 交易日還原收盤，
    報酬另扣來回成本 COST_PCT。取代舊版「進場價＝pick 當日收盤、不扣成本」的手算測試——
    舊口徑不是 Andy 真的買得到的價格，也跟全站其他勝率的口徑（扣成本）不一致。"""
    cal = [f"2026-06-{d:02d}" for d in range(1, 26)]   # 25 天
    d_entry, d_exit = cal[1], cal[20]
    entries = [{"date": cal[0], "picks": [
        {"id": "A"}, {"id": "B"}, {"id": "C"}]}]
    adj_open = {"A": {d_entry: 100.0}, "B": {d_entry: 100.0}, "C": {d_entry: 100.0}}
    adj_close = {
        "A": {d_exit: 110.0},   # 毛 +10%
        "B": {d_exit: 95.0},    # 毛 −5%
        "C": {d_exit: 100.0},   # 毛 0%
    }
    sb = opp.compute_scoreboard(entries, cal, adj_close, adj_open, forward=20)
    cost = opp.COST_PCT
    net = [110.0 / 100 - 1 - cost, 95.0 / 100 - 1 - cost, 100.0 / 100 - 1 - cost]
    assert sb["samples"] == 3
    assert sb["win_rate"] == round(sum(1 for r in net if r > 0) / 3, 4)   # 只有 A 扣成本後仍是正的
    assert sb["avg_ret"] == round(sum(net) / 3 * 100, 2)
    assert sb["cost_pct"] == round(cost * 100, 3)


def test_compute_scoreboard_扣成本後口徑():
    """毛報酬 +0.5% 扣掉來回成本 0.785% 後變負，勝率不該算贏——全站「勝率」是同一把尺
    （Andy 2026-07-26 指出：成績單用毛報酬、其他地方用成本後報酬，兩個「勝率」互相矛盾）。"""
    cal = [f"2026-06-{d:02d}" for d in range(1, 26)]
    d_entry, d_exit = cal[1], cal[20]
    entries = [{"date": cal[0], "picks": [{"id": "A"}]}]
    adj_open = {"A": {d_entry: 100.0}}
    adj_close = {"A": {d_exit: 100.5}}   # 毛報酬 +0.5%
    sb = opp.compute_scoreboard(entries, cal, adj_close, adj_open, forward=20)
    assert sb["samples"] == 1
    assert sb["win_rate"] == 0.0, "扣完成本淨報酬是負的（0.5% − 0.785%），不該算贏"
    assert sb["cost_pct"] == round(opp.COST_PCT * 100, 3)


def test_scoreboard_ignores_immature_picks():
    # pick 距今不足 20 交易日 → 不計入樣本
    cal = [f"2026-06-{d:02d}" for d in range(1, 11)]   # 只有 10 天
    entries = [{"date": cal[0], "picks": [{"id": "A"}]}]
    adj_open = {"A": {cal[1]: 100.0}}
    adj_close = {}
    sb = opp.compute_scoreboard(entries, cal, adj_close, adj_open, forward=20)
    assert sb["samples"] == 0
    assert sb["win_rate"] is None


def test_scoreboard_找不到隔日開盤時跳過不用收盤頂替():
    """隔日開盤缺值（例如當天停牌）時必須跳過該筆，不可退回用收盤價頂替——
    收盤價頂替等於偷看未來，違反「隔日開盤」口徑（計畫 Task 4）。"""
    cal = [f"2026-06-{d:02d}" for d in range(1, 26)]
    d_exit = cal[20]
    entries = [{"date": cal[0], "picks": [{"id": "A"}]}]
    adj_open = {}   # 沒有任何隔日開盤資料
    adj_close = {"A": {cal[0]: 100.0, d_exit: 110.0}}   # 就算收盤價有 pick 當日的值也不可拿來頂替
    sb = opp.compute_scoreboard(entries, cal, adj_close, adj_open, forward=20)
    assert sb["samples"] == 0
    assert sb["win_rate"] is None


def test_adjusted_open_map_回傳還原開盤():
    """新增 adjusted_open_map（跟既有 adjusted_close_map 對稱），供成績單算隔日開盤進場用。"""
    price_hist = {"9999": {
        "2026-06-01": [100.0, 105.0, 99.0, 102.0, 1000, 100000],
        "2026-06-02": [103.0, 108.0, 102.0, 106.0, 1000, 100000],
    }}
    m = opp.adjusted_open_map(price_hist, {}, "9999")
    assert m == {"2026-06-01": 100.0, "2026-06-02": 103.0}


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
        lambda entries, cal, adj_close, adj_open, forward=opp.FORWARD: {
            "updated": "x", "forward_days": forward, "samples": 0,
            "win_rate": None, "avg_ret": None, "cost_pct": round(opp.COST_PCT * 100, 3),
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


def test_gate_off_reason_does_not_claim_gate_passed():
    """門檻沒套用時，理由不可寫成「僅符合門檻（強勢雙確認）」。

    那等於把「沒檢查」說成「檢查過了」：門檻沒套用時（強弱資料算不出來、或過門檻的股票
    不足 GATE_MIN_POOL 檔）這些股票根本沒被強勢雙確認篩過，卻被標成通過門檻
    → 使用者會高估這份名單的品質。門檻是否套用會改變這句話的真假，必須分開寫。
    """
    # 沒有任何 rs_pct_60（強弱資料算不出來）→ gated 為空 → 門檻退回不套用
    # 訊號用 sn_squeeze_breakout 但權重表裡沒有它 → 沒有加權理由 → 走 fallback 那句
    results = [_stock(str(2000 + i), sn_squeeze_breakout=True, rs_pct_60=None) for i in range(3)]
    rev = {r["id"]: {"yoy": 5.0} for r in results}
    o = opp.build_opportunities(results, WEIGHTS, rev, "2026-07-24")
    assert o["gate"]["applied"] is False and o["gate"]["reason"] == "rs_unavailable"
    assert o["picks"], "門檻退回不套用時仍要有名單（保命機制）"
    for p in o["picks"]:
        txt = " ".join(p["reasons"])
        assert "僅符合門檻" not in txt, f"門檻沒套用時不可宣稱符合門檻：{txt}"
        assert "未經強勢篩選" in txt, f"要明講沒篩過：{txt}"


def test_gate_on_reason_still_says_gate_passed():
    """對照組：門檻真的套用時，那句「僅符合門檻」是對的，不可被上面的修法改掉。"""
    results = [_stock(str(3000 + i), sn_squeeze_breakout=True,
                      rs_confirmed_60_120=True, rs_pct_60=0.9) for i in range(opp.GATE_MIN_POOL)]
    rev = {r["id"]: {"yoy": 5.0} for r in results}
    o = opp.build_opportunities(results, WEIGHTS, rev, "2026-07-24")
    assert o["gate"]["applied"] is True
    assert any("僅符合門檻" in " ".join(p["reasons"]) for p in o["picks"])
