"""條件層級歷史分佈（tier_stats）單元測試。

見 pipeline/tier_stats.py 的 docstring：這個模組把 backtest_signals.collect_events()
產出的事件，按四個特徵（turnover / bias20_pct / high20_gap / rs_pct_60）在「同一天」內
切三分位，算出每個層級的成本後勝率分佈與 moving-block bootstrap 信賴區間。

事件格式（照 backtest_signals.collect_events 的實際輸出）：
    {"date": "2025-03-14", "sid": "2330", "i": 123, "ret": 0.083,
     "fired": [...], "raw_fired": [...],
     "feat": {"turnover": 67500.0, "bias20_pct": 4.2, "high20_gap": 1.8, "rs_pct_60": 0.91}}
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import tier_stats as ts  # noqa: E402


def _ev(date, sid, ret, turnover=None, bias20_pct=None, high20_gap=None, rs_pct_60=None):
    return {
        "date": date, "sid": sid, "i": 0, "ret": ret,
        "fired": [], "raw_fired": [],
        "feat": {
            "turnover": turnover, "bias20_pct": bias20_pct,
            "high20_gap": high20_gap, "rs_pct_60": rs_pct_60,
        },
    }


def _day_events(date, values, rets, sid_prefix="s"):
    """給一天造 9 筆事件：values 是這天 9 檔的 turnover（決定切層），rets 是各自報酬。"""
    assert len(values) == len(rets) == 9
    return [_ev(date, f"{sid_prefix}{i}", rets[i], turnover=values[i])
            for i in range(9)]


def test_同日切三分位不跨日比較():
    """day A 的 turnover 是 100~108（高），day B 是 1~9（低）——兩天的『高三分位』
    絕對值差 100 倍。若切三分位時不小心把兩天的樣本混在一起比（全域分位），day B 的
    9 檔會整批被歸進『低』層，day A 的『高』層會獨吃所有正報酬，win_rate 會被做高。
    正確做法（同日切）：day A 的高三分位（106~108）＝正報酬，day B 的高三分位（7~9）
    ＝負報酬，混在一起 win_rate 應該是 0.5——這樣才證明真的是逐日各切各的。
    """
    day_a = _day_events("2025-01-01", list(range(100, 109)),
                         [-0.05] * 3 + [0.0] * 3 + [0.05] * 3)
    day_b = _day_events("2025-01-02", list(range(1, 10)),
                         [0.05] * 3 + [0.0] * 3 + [-0.05] * 3)
    out = ts.compute_tier_stats(day_a + day_b, cost=0.0)
    high = out["features"]["turnover"]["high"]
    assert high["samples"] == 6, f"應該是兩天各 3 筆的『高』層合計，實際 {high['samples']}"
    assert high["win_rate"] == 0.5, f"高層混了兩天相反方向的報酬，勝率應為 0.5，實際 {high['win_rate']}"


def test_成本已扣():
    """9 筆事件毛報酬都是 0.5%，成本 0.785% > 0.5%，扣完淨報酬全部是負的，
    不論哪個層級 win_rate 都必須是 0——證明真的有扣成本，不是直接看毛報酬。"""
    day = _day_events("2025-02-01", list(range(1, 10)), [0.005] * 9)
    out = ts.compute_tier_stats(day, cost=0.00785)
    for tier in ("high", "mid", "low"):
        assert out["features"]["turnover"][tier]["win_rate"] == 0.0, \
            f"{tier} 層扣成本後應全輸，實際 {out['features']['turnover'][tier]['win_rate']}"


def test_blocks_等於不同日數除以20():
    """45 個交易日、每天都切得出『高』層 3 筆 → 高層 days=45、blocks=45//20=2。
    這是前端唯一看得到『樣本其實沒那麼獨立』的欄位，算錯等於整個模組的意義都沒了。"""
    events = []
    for d in range(45):
        date = f"2025-03-{d + 1:02d}" if d < 31 else f"2025-04-{d - 30:02d}"
        events += _day_events(date, list(range(1, 10)), [0.02] * 9)
    out = ts.compute_tier_stats(events, cost=0.0)
    high = out["features"]["turnover"]["high"]
    assert high["days"] == 45, f"實際 days={high['days']}"
    assert high["blocks"] == 2, f"45 // 20 應為 2，實際 {high['blocks']}"


def test_bootstrap同seed兩次呼叫結果相同():
    """演算法要求 3：固定 seed 的 moving-block bootstrap 必須可重現，不可依賴全域
    random 狀態。用 45 天、有漲有跌的資料跑兩次 compute_tier_stats，ci90 必須逐位元相同。"""
    events = []
    for d in range(45):
        date = f"2025-05-{d + 1:02d}" if d < 31 else f"2025-06-{d - 30:02d}"
        # 用 d 讓每天的漲跌方向與幅度不同，確保 bootstrap 真的有東西可抽、不會退化成單點。
        base_ret = 0.03 if d % 3 == 0 else (-0.02 if d % 3 == 1 else 0.0)
        rets = [base_ret + 0.001 * i for i in range(9)]
        events += _day_events(date, list(range(1, 10)), rets)
    out1 = ts.compute_tier_stats(events, cost=0.0, seed=20260726)
    out2 = ts.compute_tier_stats(events, cost=0.0, seed=20260726)
    assert out1["features"]["turnover"]["high"]["ci90"] == out2["features"]["turnover"]["high"]["ci90"]
    assert out1["features"]["turnover"]["mid"]["ci90"] == out2["features"]["turnover"]["mid"]["ci90"]
    assert out1["features"]["turnover"]["low"]["ci90"] == out2["features"]["turnover"]["low"]["ci90"]


def test_特徵值為None時只影響該特徵不影響其他特徵():
    """演算法要求 4：某天 9 筆事件的 bias20_pct 全是 None，turnover 都有值——
    bias20_pct 這天應該整天被跳過（該特徵樣本數為 0），但 turnover 的分層完全不受影響。"""
    events = [_ev("2025-07-01", f"s{i}", 0.02, turnover=100 + i, bias20_pct=None)
              for i in range(9)]
    out = ts.compute_tier_stats(events, cost=0.0)
    assert out["features"]["turnover"]["high"]["samples"] == 3, \
        "turnover 有值，不該被 bias20_pct 的 None 拖累"
    total_bias = sum(out["features"]["bias20_pct"][t]["samples"] for t in ("high", "mid", "low"))
    assert total_bias == 0, f"bias20_pct 全是 None，樣本數應為 0，實際 {total_bias}"
