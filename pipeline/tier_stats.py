#!/usr/bin/env python3
"""條件層級歷史分佈（供前端「候選情報」顯示——不是購買組合，不給個股精確勝率）。

輸入是 backtest_signals.collect_events() 回傳的 events（見該函式 docstring）：
    {"date": "2025-03-14", "sid": "2330", "i": 123, "ret": 0.083,
     "fired": [...], "raw_fired": [...],
     "feat": {"turnover": 67500.0, "bias20_pct": 4.2, "high20_gap": 1.8, "rs_pct_60": 0.91}}
`ret` 已經是「隔日開盤進場 → 第 forward 日收盤出場」的毛報酬（見 backtest_signals.collect_events）。

這個模組把事件按四個 point-in-time 特徵，各自切成「高／中／低」三層，算出每層的
成本後報酬分佈。存在的理由：Andy 自己選股時，不該被告知「這檔勝率 57%」（資料的解析度
根本沒有精細到單一個股），只能被告知「你挑的這檔落在哪個條件層級、那個層級歷史上
表現如何」。

四條演算法規則（都是為了不說謊，缺一條數字就會誤導）：

1. **同日切三分位，不跨日比較**：分層一律在同一個交易日之內比。若把不同交易日的事件
   混在一起排百分位，大盤當天的漲跌會混進特徵的解釋力裡——大盤大漲那天隨便一檔的
   turnover 可能都比大盤重跌那天的『高』turnover 還低，跨日比等於拿蘋果比橘子。
   某天（該特徵非 None 的）事件數 < MIN_DAY_SAMPLES（9）筆就整天跳過，因為 9 筆以下
   切不出有意義的三分位（三等分每層不到 3 筆，雜訊比訊號大）。
2. **成本後**：淨報酬 = ret - cost（cost 預設 0.785%，即來回手續費＋證交稅＋滑價，
   常數定義見 backtest_signals.py，這裡用外部傳入值不重複定義）。win_rate 一律用
   「淨報酬 > 0」的比例，不是毛報酬——毛報酬看起來會贏，但 Andy 真的按這個進出場，
   到手的是淨報酬。
3. **moving-block bootstrap 算 ci90**：20 日持有窗高度重疊，同一批訊號在相鄰交易日
   會重複觸發，`samples`（事件數）嚴重高估獨立性——26 萬筆事件其實可能只有約 20 個
   獨立批次。信賴區間必須以「交易日」為重抽單位（block=20，對齊持有窗長度），不能
   以「事件」為單位重抽，否則自助抽樣會把同一批相關事件當成獨立樣本，信賴區間會
   窄到失真。用 `random.Random(seed)`（不吃全域 random 狀態）固定重抽序列，保證同
   seed 兩次呼叫結果逐位元相同——這是給 Andy 的數字，不能今天跑一次、明天跑一次
   不一樣。
4. **None 值只影響該特徵**：某事件的某個特徵是 None（例如 rs_pct_60 需要橫斷面快取，
   早期資料可能沒有），只在計算「那個特徵」的分層時整筆略過，不影響其他三個特徵各自
   的分層——四個特徵各自獨立過濾、獨立分層。

純函式、不做任何 I/O（讀檔／寫檔留給呼叫端），方便單測。
"""
import random
from math import floor, ceil

FEATURES = ("turnover", "bias20_pct", "high20_gap", "rs_pct_60")
TIERS = ("high", "mid", "low")

# 一天內某特徵非 None 的事件數低於這個門檻就整天跳過（切不出有意義的三分位）。
MIN_DAY_SAMPLES = 9

DEFAULT_COST = 0.00785   # 來回成本（手續費×2＋證交稅＋滑價×2），與 backtest_signals 常數同口徑
DEFAULT_BLOCK = 20       # moving-block 長度＝持有窗天數；也用來把 days 換算成約當獨立批次數
DEFAULT_N_BOOT = 400
DEFAULT_SEED = 20260726


def compute_tier_stats(events, cost=DEFAULT_COST, block=DEFAULT_BLOCK,
                        n_boot=DEFAULT_N_BOOT, seed=DEFAULT_SEED):
    """把事件按四個特徵各自切三層，回傳每層的成本後分佈。見本檔 docstring 的四條規則。

    回傳：
        {
          "cost_pct": 0.785,
          "updated": "YYYY-MM-DD HH:MM",
          "features": {
            "turnover":   {"high": {...}, "mid": {...}, "low": {...}},
            "bias20_pct": {...}, "high20_gap": {...}, "rs_pct_60": {...}
          }
        }
    每層 {...} 含：samples／days／blocks／win_rate／median_pct／p20_pct／p80_pct／
    avg_win_pct／avg_loss_pct／ci90。
    """
    import datetime as dt
    rng = random.Random(seed)   # 規則 3：獨立的 Random 實例，不吃全域 random 狀態，結果可重現
    features_out = {
        feat: _feature_tiers(events, feat, cost, block, n_boot, rng)
        for feat in FEATURES
    }
    return {
        "cost_pct": round(cost * 100, 3),
        "updated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "features": features_out,
    }


def _feature_tiers(events, feat, cost, block, n_boot, rng):
    """單一特徵的三層統計。逐日蒐集『這天、這個特徵非 None』的 (值, 淨報酬)，
    在該天內切三分位分進 high/mid/low，最後把所有天的同層樣本合併算統計量。"""
    by_date = {}
    for e in events:
        v = (e.get("feat") or {}).get(feat)
        if v is None:
            continue   # 規則 4：只在這個特徵的分層裡跳過，不動其他特徵
        by_date.setdefault(e["date"], []).append((v, e["ret"]))

    tier_entries = {"high": [], "mid": [], "low": []}   # 每層： [(date, net_ret), ...]
    for date in sorted(by_date):
        day = by_date[date]
        if len(day) < MIN_DAY_SAMPLES:
            continue   # 規則 1：樣本太少切不出有意義的三分位，整天跳過
        values = sorted(v for v, _ in day)
        lo_thresh = _percentile(values, 100 / 3)
        hi_thresh = _percentile(values, 200 / 3)
        for v, ret in day:
            if v <= lo_thresh:
                tier = "low"
            elif v >= hi_thresh:
                tier = "high"
            else:
                tier = "mid"
            tier_entries[tier].append((date, ret - cost))   # 規則 2：成本後淨報酬

    return {tier: _tier_summary(tier_entries[tier], block, n_boot, rng) for tier in TIERS}


def _tier_summary(entries, block, n_boot, rng):
    """單一層級的統計量。entries 是 [(date, net_ret), ...]，可能橫跨很多天。"""
    n = len(entries)
    dates = sorted(set(d for d, _ in entries))
    days = len(dates)
    blocks = days // block   # 約當獨立批次數，前端必須跟 win_rate 並排顯示

    if n == 0:
        return {
            "samples": 0, "days": 0, "blocks": 0, "win_rate": None,
            "median_pct": None, "p20_pct": None, "p80_pct": None,
            "avg_win_pct": None, "avg_loss_pct": None, "ci90": None,
        }

    net_rets = sorted(r for _, r in entries)
    wins = [r for r in net_rets if r > 0]
    losses = [r for r in net_rets if r <= 0]
    win_rate = round(len(wins) / n, 4)
    avg_win_pct = round(sum(wins) / len(wins) * 100, 2) if wins else None
    avg_loss_pct = round(sum(losses) / len(losses) * 100, 2) if losses else None

    return {
        "samples": n,
        "days": days,
        "blocks": blocks,
        "win_rate": win_rate,
        "median_pct": round(_percentile(net_rets, 50) * 100, 2),
        "p20_pct": round(_percentile(net_rets, 20) * 100, 2),
        "p80_pct": round(_percentile(net_rets, 80) * 100, 2),
        "avg_win_pct": avg_win_pct,
        "avg_loss_pct": avg_loss_pct,
        "ci90": _moving_block_ci(entries, block, n_boot, rng),
    }


def _moving_block_ci(entries, block, n_boot, rng):
    """規則 3：以「交易日」為重抽單位的 moving-block bootstrap，算 win_rate 的 90% 信賴區間。

    做法：把這個層級的資料按日期分組（同一天可能有多筆事件），排成日序列。每次重抽從
    這個日序列裡隨機挑「連續 block 天」的區塊（可重疊、可重複挑到同一個區塊），挑到湊滿
    原本的天數為止，把被挑中的天的事件全部攤平算一次 win_rate；重複 n_boot 次，取第 5
    與第 95 百分位當信賴區間。block=20 對齊持有窗長度——相鄰交易日的事件因為持有期重疊
    而高度相關，用「日」而非「事件」當重抽單位才不會把相關樣本當成獨立樣本。
    """
    by_date = {}
    for d, r in entries:
        by_date.setdefault(d, []).append(r)
    day_returns = [by_date[d] for d in sorted(by_date)]
    n_days = len(day_returns)
    if n_days == 0:
        return None

    eff_block = min(block, n_days)
    starts = list(range(0, n_days - eff_block + 1)) or [0]
    n_blocks_needed = ceil(n_days / eff_block)

    boot_win_rates = []
    for _ in range(n_boot):
        picked = []
        for _ in range(n_blocks_needed):
            s = rng.choice(starts)
            picked.extend(day_returns[s:s + eff_block])
        rets = [r for day in picked for r in day]
        if rets:
            boot_win_rates.append(sum(1 for r in rets if r > 0) / len(rets))

    if not boot_win_rates:
        return None
    boot_win_rates.sort()
    lo = _percentile(boot_win_rates, 5)
    hi = _percentile(boot_win_rates, 95)
    return [round(lo * 100, 2), round(hi * 100, 2)]


def _percentile(sorted_vals, pct):
    """線性內插百分位數（pct 為 0~100）。sorted_vals 必須已排序、非空。"""
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    k = (n - 1) * pct / 100
    f, c = floor(k), ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    return sorted_vals[f] * (c - k) + sorted_vals[c] * (k - f)
