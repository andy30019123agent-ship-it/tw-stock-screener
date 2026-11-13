"""條件層級統計「正確母體」版（tier_stats.compute_pool_tier_stats）與 collect_events(pool_rows=...)。

2026-11-13：舊版母體是「所有訊號事件」，網站上被分類的卻是「最終候選池」。這裡驗證：
重播真的走 build_opportunities、切層真的走 feature_level、小池/並列/缺值/量不出報酬
都有計數而不是默默塞進某一層，以及最重要的對照組——同一批資料，母體不同數字就不同。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import backtest_signals as bt          # noqa: E402
import opportunities as op             # noqa: E402
import tier_stats as ts                # noqa: E402

ID = lambda r: r   # noqa: E731  不扣成本，方便手算


def _row(sid, turnover_rank, ret, *, vol=800, bias=1.0, gate=True, engine=True,
         high20=None, rs=0.9):
    close = 100.0
    return {"id": sid, "name": sid, "signal_ma": engine, "avg_vol_lots": vol * turnover_rank,
            "close": close, "ma20": 95.0, "recent_high20": high20 if high20 is not None else 110.0 + turnover_rank,
            "bias20_pct": bias, "rs20": None, "rs_pct_60": rs,
            "rs_confirmed_60_120": gate, "_ret": ret}


def _day(n=12, rets=None, **kw):
    rets = rets or [0.05 if i >= n * 2 // 3 else -0.05 for i in range(n)]
    return [_row(f"S{i:02d}", i + 1, rets[i], bias=float(i), **kw) for i in range(n)]


def test_feature_level切點與線上分類一致():
    assert op.feature_level(None) is None
    assert op.feature_level(op.TIER_HIGH_PCT) == "high"
    assert op.feature_level(op.TIER_HIGH_PCT - 1e-9) == "mid"
    assert op.feature_level(op.TIER_MID_PCT) == "mid"
    assert op.feature_level(0.0) == "low"


def test_重播走build_opportunities且分類與線上相同():
    pool = {"2025-03-03": _day()}
    rep = ts.replay_pool_days(pool)
    date, opp, ret_by_id = rep[0]
    direct = op.build_opportunities(pool["2025-03-03"], {}, {}, "2025-03-03")
    assert [p["tier"] for p in opp["picks"]] == [p["tier"] for p in direct["picks"]]
    out = ts.compute_pool_tier_stats(pool, net_fn=ID, n_boot=20, replayed=rep)
    # 12 檔、turnover 與報酬同序：前 1/3（百分位 ≥0.67 → 後 4 檔）全贏
    assert out["features"]["turnover"]["high"]["samples"] == 4
    assert out["features"]["turnover"]["high"]["win_rate"] == 1.0
    assert out["categories"]["both"]["samples"] == 4      # turnover 與 bias 同序 → 前段都雙優
    assert out["meta"]["population"] == "candidate_pool_replay"
    assert out["meta"]["not_replayed"], "沒重播的濾網必須寫進 metadata"


def test_對照組_母體不同數字就不同():
    """同一天：12 檔真候選（引擎訊號＋量夠）＋12 檔『有訊號事件但不是候選』（只有展示型訊號、
    成交金額更大、全部賠）。舊母體（所有事件）的成交金額前 1/3 會被非候選佔滿 → 勝率 0；
    新母體（候選池）的前 1/3 是真候選的前段 → 勝率 1。數字不同＝母體改變確實會改變結論。"""
    cand = _day()
    non = [_row(f"N{i:02d}", 100 + i, -0.05, engine=False) for i in range(12)]
    events = [{"date": "2025-03-03", "sid": r["id"], "ret": r["_ret"],
               "feat": {"turnover": r["avg_vol_lots"] * r["close"], "bias20_pct": r["bias20_pct"],
                        "high20_gap": None, "rs_pct_60": None}} for r in cand + non]
    old = ts.compute_tier_stats(events, net_fn=ID, n_boot=20)
    new = ts.compute_pool_tier_stats({"2025-03-03": cand + non}, net_fn=ID, n_boot=20)
    assert old["features"]["turnover"]["high"]["win_rate"] == 0.0
    assert new["features"]["turnover"]["high"]["win_rate"] == 1.0
    assert new["meta"]["candidates_total"] == 12, "非候選（無引擎訊號）不得進候選池"


def test_小候選池日不分層且計數():
    pool = {"2025-03-03": _day(n=op.MIN_TIER_POOL - 1), "2025-03-04": _day()}
    out = ts.compute_pool_tier_stats(pool, net_fn=ID, n_boot=20)
    assert out["meta"]["days_small_pool"] == 1
    assert out["meta"]["days_classified"] == 1
    total = sum(out["features"]["turnover"][t]["samples"] for t in ts.TIERS)
    assert total == 12, "小池那天的 9 檔不得出現在任何一層"


def test_大量並列整天不分層而不是全塞某層():
    """12 檔裡 8 檔 high20_gap 都是 0（都在前高）→ 並列群 8 > 12/3 → 該特徵當天不分層。
    對照：同一天 turnover 照常分層。"""
    rows = _day()
    for r in rows[:8]:
        r["recent_high20"] = r["close"]           # high20_gap = 0
    out = ts.compute_pool_tier_stats({"2025-03-03": rows}, net_fn=ID, n_boot=20)
    g = out["features"]["high20_gap"]
    assert g["skipped_tie_days"] == 1
    assert sum(g[t]["samples"] for t in ts.TIERS) == 0
    assert sum(out["features"]["turnover"][t]["samples"] for t in ts.TIERS) == 12


def test_缺值永不達標且計數():
    rows = _day()
    for r in rows:
        r["rs_pct_60"] = None
    rows[-1]["rs_pct_60"] = 0.5                    # 只有一檔有值
    out = ts.compute_pool_tier_stats({"2025-03-03": rows}, net_fn=ID, n_boot=20)
    rs = out["features"]["rs_pct_60"]
    assert rs["missing_values"] == 11
    assert sum(rs[t]["samples"] for t in ts.TIERS) == 1, "缺值不可被當成任何層級（只剩有值那檔）"


def test_量不出報酬的候選仍佔名次但不進統計():
    rows = _day()
    rows[0]["_ret"] = None
    out = ts.compute_pool_tier_stats({"2025-03-03": rows}, net_fn=ID, n_boot=20)
    assert out["meta"]["candidates_unmeasurable"] == 1
    assert sum(out["features"]["turnover"][t]["samples"] for t in ts.TIERS) == 11
    # 名次沒被改：最高 4 檔仍是 high（若把 None 那檔整個丟掉，百分位切點會位移）
    assert out["features"]["turnover"]["high"]["samples"] == 4


def test_both_check四格互斥且加總等於全體():
    rows = _day()
    rows.reverse()
    for i, r in enumerate(rows):
        r["bias20_pct"] = float(i)                # bias 與 turnover 反序 → 不會同時高
    out = ts.compute_pool_tier_stats({"2025-03-03": rows}, net_fn=ID, n_boot=20)
    bc = out["both_check"]
    assert bc["both"]["samples"] == 0
    assert sum(bc[k]["samples"] for k in bc) == out["all"]["samples"] == 12


def test_成本預設用_apply_cost():
    rows = _day(rets=[0.005] * 12)
    out = ts.compute_pool_tier_stats({"2025-03-03": rows}, n_boot=20)
    expect = round(bt._apply_cost(0.005) * 100, 2)
    assert out["all"]["ev_pct"] == expect
    assert out["all"]["win_rate"] == 0.0


def test_circular_bootstrap_同seed可重現且區間合理():
    pool = {}
    for d in range(45):
        date = f"2025-05-{d + 1:02d}" if d < 31 else f"2025-06-{d - 30:02d}"
        base = 0.03 if d % 3 == 0 else -0.02
        pool[date] = _day(rets=[base + 0.001 * i for i in range(12)])
    a = ts.compute_pool_tier_stats(pool, net_fn=ID, n_boot=50, seed=1)
    b = ts.compute_pool_tier_stats(pool, net_fn=ID, n_boot=50, seed=1)
    assert a["all"]["ci90"] == b["all"]["ci90"] and a["all"]["ci90_ev"] == b["all"]["ci90_ev"]
    lo, hi = a["all"]["ci90"]
    assert 0 <= lo <= a["all"]["win_rate"] * 100 <= hi <= 100


def test_moving_block_每次重抽恰好n_days天():
    """環狀＋截斷：每一次重抽攤平後的事件數必須等於原始事件數（每天 1 筆時）。"""
    import random

    class Spy(random.Random):
        pass
    entries = [(f"d{i:03d}", 0.01 if i % 2 else -0.01) for i in range(45)]   # 45 天、block 20
    lo_hi = ts._moving_block_ci(entries, 20, 200, Spy(3))
    # 每天 1 筆、贏輸交錯：截成 45 天後勝率只能是 k/45；若沒截（60 天）會出現 k/60 的值
    for v in lo_hi[0]:
        assert abs(v / 100 * 45 - round(v / 100 * 45)) < 0.06, v


def test_collect_events_pool_rows_不改變events且收進跨斷點候選(monkeypatch):
    rows = []
    for i in range(100):
        c = 100.0 + i * 0.5
        rows.append([c, c, c, c, 600000, 0])
    dates = [f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(100)]
    price_hist = {"9999": dict(zip(dates, rows))}
    universe = [{"id": "9999", "name": "測試", "market": "上市", "industry": "IND00"}]
    real = bt.signal_flags

    def fake(ind):
        f = real(ind)
        f["signal_ma"] = True                    # 強制引擎訊號成立，讓候選列出現
        return f
    monkeypatch.setattr(bt, "signal_flags", fake)
    brk = {("9999", dates[85])}                   # 讓 i=66..84 一帶的報酬窗跨斷點
    ev0, bd0 = bt.collect_events(price_hist, {}, {}, universe, breaks=brk)
    pool = {}
    ev1, bd1 = bt.collect_events(price_hist, {}, {}, universe, breaks=brk, pool_rows=pool)
    assert [(e["date"], e["ret"]) for e in ev0] == [(e["date"], e["ret"]) for e in ev1]
    assert bd0 == bd1
    all_rows = [r for v in pool.values() for r in v]
    assert any(r["_ret"] is None for r in all_rows), "跨斷點的日子仍應是候選（_ret=None）"
    measured = {r["_ret"] for r in all_rows if r["_ret"] is not None}
    assert measured == {e["ret"] for e in ev1}
    # 重播列餵回 signal_flags 要得到同樣的引擎旗標
    assert fake(all_rows[0])["signal_ma"] is True


def test_paired_同日配對差手算():
    """一天高層全贏、低層全輸 → 勝率差 +100pp；另一天反過來 → −100pp；平均 0。"""
    d1 = _day()                                              # 高 4 檔 +5%、其他 −5%
    d2 = _day(rets=[0.05 if i < 4 else -0.05 for i in range(12)])   # 低 4 檔贏
    out = ts.compute_pool_tier_stats({"2025-03-03": d1, "2025-03-04": d2}, net_fn=ID, n_boot=20)
    p = out["paired"]["turnover_high_vs_low"]
    assert p["days"] == 2
    assert p["win_pp"] == 0.0
    assert p["first_half_win_pp"] == 100.0 and p["second_half_win_pp"] == -100.0
    assert abs(p["ev_pp"]) < 1e-9


def test_by_gate_門檻套用與退回分開算():
    """門檻退回（過門檻候選 < 20）的日子池子大、權重大，必須能分開看。"""
    applied = [_row(f"A{i:02d}", i + 1, 0.05, gate=True) for i in range(op.GATE_MIN_POOL)]
    fallback = [_row(f"F{i:02d}", i + 1, -0.05, gate=False) for i in range(30)]
    out = ts.compute_pool_tier_stats({"2025-03-03": applied, "2025-03-04": fallback},
                                     net_fn=ID, n_boot=20)
    assert out["meta"]["days_gate_applied"] == 1
    assert out["by_gate"]["applied"]["all"]["win_rate"] == 1.0
    assert out["by_gate"]["fallback"]["all"]["win_rate"] == 0.0
    assert out["by_gate"]["applied"]["all"]["samples"] + out["by_gate"]["fallback"]["all"]["samples"] \
        == out["all"]["samples"]
