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
2. **成本後**：淨報酬 = bt._apply_cost(ret)（來回手續費＋證交稅＋滑價，乘除式，約 0.785%，
   常數定義見 backtest_signals.py，這裡不重複定義）。win_rate 一律用
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

🔴 2026-11-13 母體更正（Codex 2026-07-26 複查必修第 3 點）：上面的 compute_tier_stats 是對
「collect_events 的所有訊號事件」分層——任一 raw signal 成立就收（含多頭排列等展示型訊號、
均量 300 張以上）。但網站上被分類的是「最終候選池」：引擎訊號＋500 張＋強勢雙確認門檻＋
營收過濾後才排百分位。「所有事件的前 1/3」≠「候選池前 1/3」，所以舊數字不能拿來描述網站
上的分類。**線上用的是 compute_pool_tier_stats**：逐日把 collect_events(pool_rows=...) 收到的
候選列丟進 opportunities.build_opportunities（同一支函式）重播，再用 opportunities.feature_level
（線上分類同一支）切層。compute_tier_stats 保留只做「舊母體 vs 新母體」對照。

成本一律用 backtest_signals._apply_cost（乘除式，與出場分析同一把尺），不再直接減 0.785%。
bootstrap 改成 circular moving-block、拼接後截成恰好 n_days 天（Codex 建議 1）。
"""
import random
from math import floor, ceil

import backtest_signals as bt

FEATURES = ("turnover", "bias20_pct", "high20_gap", "rs_pct_60")
TIERS = ("high", "mid", "low")

# 一天內某特徵非 None 的事件數低於這個門檻就整天跳過（切不出有意義的三分位）。
MIN_DAY_SAMPLES = 9

DEFAULT_COST = 0.00785   # 僅供輸出 cost_pct 顯示（約略值）；實際扣成本用 bt._apply_cost（乘除式）
DEFAULT_BLOCK = 20       # moving-block 長度＝持有窗天數；也用來把 days 換算成約當獨立批次數
DEFAULT_N_BOOT = 400
DEFAULT_SEED = 20260726


def compute_tier_stats(events, net_fn=None, block=DEFAULT_BLOCK,
                        n_boot=DEFAULT_N_BOOT, seed=DEFAULT_SEED):
    """【舊母體，只供對照】把事件按四個特徵各自切三層，回傳每層的成本後分佈。

    net_fn：毛報酬 → 淨報酬，預設 bt._apply_cost（測試可傳 lambda r: r 表示不扣成本）。

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
    net_fn = net_fn or bt._apply_cost
    rng = random.Random(seed)   # 規則 3：獨立的 Random 實例，不吃全域 random 狀態，結果可重現
    features_out = {
        feat: _feature_tiers(events, feat, net_fn, block, n_boot, rng)
        for feat in FEATURES
    }
    return {
        "cost_pct": round(DEFAULT_COST * 100, 3),
        "updated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "features": features_out,
    }


def _feature_tiers(events, feat, net_fn, block, n_boot, rng):
    """單一特徵的三層統計。逐日蒐集『這天、這個特徵非 None』的 (值, 淨報酬)，
    在該天內切三分位分進 high/mid/low，最後把所有天的同層樣本合併算統計量。"""
    by_date = {}
    for e in events:
        v = (e.get("feat") or {}).get(feat)
        if v is None:
            continue   # 規則 4：只在這個特徵的分層裡跳過，不動其他特徵
        by_date.setdefault(e["date"], []).append((v, e["ret"]))

    tier_entries = {"high": [], "mid": [], "low": []}   # 每層： [(date, net_ret), ...]
    skipped_ties = 0                                    # 因為並列太多而無法分層的天數
    for date in sorted(by_date):
        day = by_date[date]
        if len(day) < MIN_DAY_SAMPLES:
            continue   # 規則 1：樣本太少切不出有意義的三分位，整天跳過
        values = sorted(v for v, _ in day)
        lo_thresh = _percentile(values, 100 / 3)
        hi_thresh = _percentile(values, 200 / 3)
        # 🔴 2026-07-26 Codex 複查抓到：兩個切點相等時（例如某日的 high20_gap 有一半以上都是 0，
        # 因為那些股票剛好都在創新高），下面的 `v <= lo_thresh` 會**優先命中**，於是那天的樣本
        # 會被整批塞進 low、high 與 mid 都是 0 筆——而外面看到的只是「low 的樣本數比較多」，
        # 完全看不出那天根本沒有被分層過。這會讓 low 層混入大量「其實不低」的樣本，統計失真。
        # 決定：切不開就**整天跳過這個特徵**（跟樣本太少同一個處理），並把跳過天數輸出讓人看得到。
        # 不用「按排名硬切」是因為值相同就是相同，硬排名等於發明一個資料裡沒有的順序。
        if lo_thresh == hi_thresh:
            skipped_ties += 1
            continue
        for v, ret in day:
            if v <= lo_thresh:
                tier = "low"
            elif v >= hi_thresh:
                tier = "high"
            else:
                tier = "mid"
            tier_entries[tier].append((date, net_fn(ret)))   # 規則 2：成本後淨報酬

    out = {tier: _tier_summary(tier_entries[tier], block, n_boot, rng) for tier in TIERS}
    out["skipped_tie_days"] = skipped_ties   # 前端/報告要能看到「這個特徵有幾天切不開」
    return out


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
            "avg_win_pct": None, "avg_loss_pct": None, "ev_pct": None,
            "ci90": None, "ci90_ev": None,
        }

    net_rets = sorted(r for _, r in entries)
    wins = [r for r in net_rets if r > 0]
    losses = [r for r in net_rets if r <= 0]
    # 只留 3 位（0.1%）：前端 toFixed(1)、報告、TG 讀同一個數就不會差 0.1（驗收 2026-11-13）
    win_rate = round(len(wins) / n, 3)
    ci_win, ci_ev = _moving_block_ci(entries, block, n_boot, rng)
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
        "ev_pct": round(sum(net_rets) / n * 100, 2),   # 期望值＝平均淨報酬
        "ci90": ci_win,
        "ci90_ev": ci_ev,
    }


def _moving_block_ci(entries, block, n_boot, rng):
    """規則 3：以「交易日」為重抽單位的 circular moving-block bootstrap，回傳
    (win_rate 的 90% CI, 平均淨報酬的 90% CI)，單位皆為 %。

    做法：把這個層級的資料按日期分組（同一天可能有多筆事件），排成日序列。每次重抽從
    這個日序列裡隨機挑「連續 block 天」的區塊——**環狀**（尾端接回開頭，頭尾日被抽中的
    機率與中間日相同），挑到湊滿原本的天數後**截成恰好 n_days 天**（2026-11-13 改，Codex
    建議 1：舊版非環狀、且整塊湊滿會多抽，頭尾 regime 被低估），把被挑中的天的事件全部
    攤平算一次；重複 n_boot 次，取第 5 與第 95 百分位。block=20 對齊持有窗長度。
    """
    by_date = {}
    for d, r in entries:
        by_date.setdefault(d, []).append(r)
    day_returns = [by_date[d] for d in sorted(by_date)]
    n_days = len(day_returns)
    if n_days == 0:
        return None, None

    eff_block = min(block, n_days)
    n_blocks_needed = ceil(n_days / eff_block)

    boot_win, boot_ev = [], []
    for _ in range(n_boot):
        picked = []
        for _ in range(n_blocks_needed):
            s = rng.randrange(n_days)
            picked.extend(day_returns[(s + k) % n_days] for k in range(eff_block))
        picked = picked[:n_days]
        rets = [r for day in picked for r in day]
        if rets:
            boot_win.append(sum(1 for r in rets if r > 0) / len(rets))
            boot_ev.append(sum(rets) / len(rets))

    if not boot_win:
        return None, None
    boot_win.sort()
    boot_ev.sort()
    ci_win = [round(_percentile(boot_win, 5) * 100, 2), round(_percentile(boot_win, 95) * 100, 2)]
    ci_ev = [round(_percentile(boot_ev, 5) * 100, 2), round(_percentile(boot_ev, 95) * 100, 2)]
    return ci_win, ci_ev


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


# ── 2026-11-13：正確母體＝逐日重播完整候選流程後的候選池 ─────────────────────────
# 一天的候選池中，某特徵「同一個百分位」的股票數超過池子的這個比例 → 該特徵當天不分層。
# _percentile_ranks 對並列取平均名次，大量並列時整群會落在同一個百分位（例如一半候選
# high20_gap 都是 0 → 全部拿到同一個低百分位、整群掉進 low），那等於把「切不開」包裝成
# 「都在後段」。1/3＝一層的名額；並列群比一層還大，就代表這天這個特徵切不出三層。
MAX_TIE_SHARE = 1 / 3

# 歷史上無法重播的濾網／訊號（寫進輸出 metadata 與報告，不可默默略過）。
NOT_REPLAYED = [
    {"item": "營收年減剔除（近月營收 YoY < 0）",
     "why": "官方月營收端點只給最新一期，沒有逐月歷史；重播時視同『營收資料缺』＝不剔除",
     "effect": "歷史候選池比線上略大（線上會再刷掉營收年減的股票）"},
    {"item": "同業低估（undervalued）訊號",
     "why": "需要當時的本益比／同業中位數，回測母體沒有歷史估值；與 collect_events 同口徑恆不成立",
     "effect": "只靠這個訊號入選的股票不會出現在歷史候選池"},
    {"item": "千張大戶↑（holder_rising）訊號",
     "why": "集保大戶歷史只有近期幾週，回測時幾乎恆不成立（與 collect_events 同口徑）",
     "effect": "同上"},
    {"item": "外資連買／投信連買訊號",
     "why": "籌碼歷史最早只到 2026-05-29，重播期間（2025-01～2026-10）只靠籌碼訊號入選的候選是 0 列",
     "effect": "歷史候選池少了線上約一成的候選（線上快照中只靠這兩個訊號入選的約占 11%）"},
    {"item": "倖存者偏差（只重播今天的股票清單）",
     "why": "重播用現存股票清單，已下市的股票不在歷史資料裡",
     "effect": "三層的絕對賺錢機率可能偏高；同日配對差受影響應較小"},
    {"item": "訊號權重用「今天」算的",
     "why": "重播時 weights 是用全歷史算出來的現行權重，不是當時的版本",
     "effect": "只影響分數排序與推薦理由，不影響候選資格、門檻與分層（驗收實測樣本數逐筆相同）"},
    {"item": "上市未滿約 85 個交易日的新股",
     "why": "collect_events 要求至少 MIN_BARS+FORWARD+1 根 K 線才回測",
     "effect": "線上可能是候選、歷史重播看不到"},
]


def replay_pool_days(pool_rows, weights=None):
    """逐日呼叫 opportunities.build_opportunities（線上同一支函式）重播候選池。

    pool_rows：{date: [row...]}，由 collect_events(pool_rows=...) 產生（見 bt._pool_row）。
    營收傳空 dict（歷史無法重播，見 NOT_REPLAYED）。回 [(date, opp, ret_by_id)]，日期遞增。"""
    import opportunities as op   # 延遲載入：opportunities 也 import backtest_signals
    out = []
    for date in sorted(pool_rows):
        rows = pool_rows[date]
        opp = op.build_opportunities(rows, weights or {}, {}, date)
        out.append((date, opp, {r["id"]: r.get("_ret") for r in rows}))
    return out


def _max_tie_count(values):
    cnt = {}
    for v in values:
        if v is not None:
            cnt[v] = cnt.get(v, 0) + 1
    return max(cnt.values()) if cnt else 0


def compute_pool_tier_stats(pool_rows, weights=None, net_fn=None, block=DEFAULT_BLOCK,
                            n_boot=DEFAULT_N_BOOT, seed=DEFAULT_SEED, replayed=None, _subsets=True):
    """條件層級統計（正確母體版）。輸出 schema 與 compute_tier_stats 相容（features.*.high/mid/low），
    另加：
      both_check：成交金額高 × 乖離高 的四格互斥（both／turn_only／bias_only／neither）
      categories：線上分類本身的歷史表現（2026-11-13 起 edge＝相對優勢／rest＝其餘候選；
                  bias_high／not_bias_high＝「乖離高」描述標籤有／沒有）
      all：當天有分類的候選池全體（基準）
      meta：母體定義、各種跳過的天數／筆數、沒重播的濾網
    規則：
      - 候選數 < opportunities.MIN_TIER_POOL 的日子整天不分層（與線上 tier_on 同一門檻），計數。
      - 某特徵最大並列群 > 候選數 × MAX_TIE_SHARE → 該特徵當天不分層，計數。
      - 缺值（feat_pct=None）永不達標：不進任何一層、在 both_check 視為「不是高」，計數。
      - 報酬量不出來的候選（_ret=None）參與排名但不進統計，計數。
    replayed：可直接傳 replay_pool_days 的結果（測試或重複利用時省一次重播）。

    另外兩塊（_subsets=True 時）：
      paired：同日配對差（高層 − 低層、各格 − 都不是），先算每天的差、再對「日序列」做
              circular block bootstrap。合併統計（上面那些）是「按筆數加權」，候選池大的日子
              權重大；配對差是「每天一票」，而且同一天比較、大盤漲跌自動抵銷——要宣稱
              「A 層比 B 層好」看的是這個，不是兩層各自的 CI 有沒有重疊。
      by_gate：按當天強勢雙確認門檻「有套用／退回」分開算。2026-11-13 實測門檻退回的日子
              只佔 14% 的天數，卻因為池子大（中位 338 檔 vs 65 檔）佔了近一半的筆數，
              而且那些日子的層級方向是反的——合併數字會被它們拉平，必須分開看。"""
    import datetime as dt
    import opportunities as op
    net_fn = net_fn or bt._apply_cost
    rng = random.Random(seed)
    days = replayed if replayed is not None else replay_pool_days(pool_rows, weights)

    feat_entries = {f: {t: [] for t in TIERS} for f in FEATURES}
    tie_days = {f: 0 for f in FEATURES}
    missing = {f: 0 for f in FEATURES}
    both_entries = {k: [] for k in ("both", "turn_only", "bias_only", "neither")}
    # 2026-11-13 分類簡化：線上只剩 tier="edge"（相對優勢）一類；分類直接讀 build_opportunities
    # 給的 tier／bias_high（線上同一支函式），不在這裡另判一次。
    cat_entries = {k: [] for k in ("edge", "rest", "bias_high", "not_bias_high")}
    all_entries = []
    meta = {"days_total": len(days), "days_small_pool": 0, "days_classified": 0,
            "days_gate_applied": 0, "days_both_check_skipped_tie": 0,
            "candidates_total": 0, "candidates_unmeasurable": 0, "pool_sizes": []}

    for date, opp, ret_by_id in days:
        picks = opp["picks"]
        n = len(picks)
        meta["candidates_total"] += n
        meta["pool_sizes"].append(n)
        if (opp.get("gate") or {}).get("applied"):
            meta["days_gate_applied"] += 1
        if n < op.MIN_TIER_POOL:
            meta["days_small_pool"] += 1          # 與線上同：候選太少不分類
            continue
        meta["days_classified"] += 1
        skip_feat = set()
        for f in FEATURES:
            if _max_tie_count([p["feat_pct"][f] for p in picks]) > n * MAX_TIE_SHARE:
                tie_days[f] += 1
                skip_feat.add(f)
        for p in picks:
            ret = ret_by_id.get(p["id"])
            if ret is None:
                meta["candidates_unmeasurable"] += 1
                continue
            entry = (date, net_fn(ret))
            all_entries.append(entry)
            cat_entries["edge" if p.get("tier") == op.TIER_EDGE else "rest"].append(entry)
            cat_entries["bias_high" if p.get("bias_high") else "not_bias_high"].append(entry)
            lv = {f: op.feature_level(p["feat_pct"][f]) for f in FEATURES}
            for f in FEATURES:
                if f in skip_feat:
                    continue
                if lv[f] is None:
                    missing[f] += 1
                    continue
                feat_entries[f][lv[f]].append(entry)
            if "turnover" in skip_feat or "bias20_pct" in skip_feat:
                continue
            th, bh = lv["turnover"] == "high", lv["bias20_pct"] == "high"
            key = "both" if (th and bh) else "turn_only" if th else "bias_only" if bh else "neither"
            both_entries[key].append(entry)
        if "turnover" in skip_feat or "bias20_pct" in skip_feat:
            meta["days_both_check_skipped_tie"] += 1

    def summ(entries):
        return _tier_summary(entries, block, n_boot, rng)

    features_out = {}
    for f in FEATURES:
        features_out[f] = {t: summ(feat_entries[f][t]) for t in TIERS}
        features_out[f]["skipped_tie_days"] = tie_days[f]
        features_out[f]["missing_values"] = missing[f]
    sizes = sorted(meta.pop("pool_sizes"))
    meta["pool_size_median"] = sizes[len(sizes) // 2] if sizes else None
    meta.update({
        "date_from": days[0][0] if days else None,
        "date_to": days[-1][0] if days else None,
        "population": "candidate_pool_replay",
        "population_label": "逐日重播 opportunities.build_opportunities 後的最終候選池"
                            "（引擎訊號＋均量≥500 張＋強勢雙確認門檻（候選不足 20 檔時退回）；營收濾網未重播）",
        "entry": "訊號隔日開盤", "exit": f"第 {bt.FORWARD} 交易日收盤",
        "cost": "backtest_signals._apply_cost（乘除式）",
        "bootstrap": f"circular moving-block，block={block}，n_boot={n_boot}，截成恰好 n_days",
        "min_tier_pool": op.MIN_TIER_POOL, "max_tie_share": round(MAX_TIE_SHARE, 4),
        "tier_scheme": op.TIER_SCHEME,
        "tier_rule": {"edge": f"相對優勢＝成交金額在當日候選池內百分位 ≥ {op.TIER_HIGH_PCT}（前 1/3）",
                      "bias_high": f"乖離高（純描述標籤）＝20 日乖離在當日候選池內百分位 ≥ {op.TIER_HIGH_PCT}",
                      "rest": "其餘候選（不給分類稱號）"},
        "tier_cut": {"high": f"候選池內百分位 ≥ {op.TIER_HIGH_PCT}",
                     "mid": f"{op.TIER_MID_PCT} ≤ 百分位 < {op.TIER_HIGH_PCT}",
                     "low": f"百分位 < {op.TIER_MID_PCT}"},
        "not_replayed": NOT_REPLAYED,
    })
    out = {
        "cost_pct": round(DEFAULT_COST * 100, 3),
        "updated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "features": features_out,
        "both_check": {k: summ(v) for k, v in both_entries.items()},
        "categories": {k: summ(v) for k, v in cat_entries.items()},
        "all": summ(all_entries),
        "meta": meta,
    }
    if _subsets:
        out["paired"] = _paired_block(feat_entries, both_entries, cat_entries, block, n_boot, seed)
        by_gate = {}
        for key, want in (("applied", True), ("fallback", False)):
            sub = [d for d in days if bool((d[1].get("gate") or {}).get("applied")) == want]
            by_gate[key] = compute_pool_tier_stats(None, net_fn=net_fn, block=block, n_boot=n_boot,
                                                   seed=seed, replayed=sub, _subsets=False)
            by_gate[key].pop("updated", None)
            by_gate[key]["meta"] = {k: by_gate[key]["meta"][k] for k in
                                    ("days_total", "days_classified", "candidates_total",
                                     "pool_size_median", "date_from", "date_to")}
        out["by_gate"] = by_gate
    return out


def _paired_block(feat_entries, both_entries, cat_entries, block, n_boot, seed):
    """同日配對差：對每一天算 (A 層指標 − B 層指標)，兩層當天都有樣本才算；
    回 {名稱: {days, win_pp, win_ci90, ev_pp, ev_ci90, first_half_*, second_half_*}}（單位 pp）。"""
    pairs = {
        "turnover_high_vs_low": (feat_entries["turnover"]["high"], feat_entries["turnover"]["low"]),
        "bias20_pct_high_vs_low": (feat_entries["bias20_pct"]["high"], feat_entries["bias20_pct"]["low"]),
        "both_vs_neither": (both_entries["both"], both_entries["neither"]),
        "turn_only_vs_neither": (both_entries["turn_only"], both_entries["neither"]),
        "bias_only_vs_neither": (both_entries["bias_only"], both_entries["neither"]),
        # 線上分類本身（2026-11-13 起網站上的主訊息）：相對優勢 vs 當日其餘全部候選
        "cat_edge_vs_rest": (cat_entries["edge"], cat_entries["rest"]),
        # 「乖離高」描述標籤 vs 當日其餘候選（說明處要照實講量不量得出差別）
        "bias_high_vs_rest": (cat_entries["bias_high"], cat_entries["not_bias_high"]),
    }
    out = {}
    for name, (a, b) in pairs.items():
        da, db = {}, {}
        for d, r in a:
            da.setdefault(d, []).append(r)
        for d, r in b:
            db.setdefault(d, []).append(r)
        dates = sorted(set(da) & set(db))
        if not dates:
            out[name] = {"days": 0, "win_pp": None, "win_ci90": None, "ev_pp": None, "ev_ci90": None}
            continue
        win = [(sum(x > 0 for x in da[d]) / len(da[d]) - sum(x > 0 for x in db[d]) / len(db[d])) * 100
               for d in dates]
        ev = [(sum(da[d]) / len(da[d]) - sum(db[d]) / len(db[d])) * 100 for d in dates]
        half = len(dates) // 2
        rng = random.Random(seed)
        out[name] = {
            "days": len(dates),
            "win_pp": round(sum(win) / len(win), 2), "win_ci90": _circular_mean_ci(win, block, n_boot, rng),
            "ev_pp": round(sum(ev) / len(ev), 2), "ev_ci90": _circular_mean_ci(ev, block, n_boot, rng),
            "first_half_win_pp": round(sum(win[:half]) / max(half, 1), 2),
            "second_half_win_pp": round(sum(win[half:]) / max(len(win) - half, 1), 2),
            "first_half_ev_pp": round(sum(ev[:half]) / max(half, 1), 2),
            "second_half_ev_pp": round(sum(ev[half:]) / max(len(ev) - half, 1), 2),
            "split_date": dates[half] if half < len(dates) else None,
        }
    return out


def _circular_mean_ci(series, block, n_boot, rng):
    """日序列平均值的 90% CI（circular moving-block、截成恰好 n 天）。"""
    n = len(series)
    if n == 0:
        return None
    b = min(block, n)
    means = []
    for _ in range(n_boot):
        picked = []
        while len(picked) < n:
            s = rng.randrange(n)
            picked.extend(series[(s + k) % n] for k in range(b))
        picked = picked[:n]
        means.append(sum(picked) / n)
    means.sort()
    return [round(_percentile(means, 5), 2), round(_percentile(means, 95), 2)]
