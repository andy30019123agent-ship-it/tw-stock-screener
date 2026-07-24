#!/usr/bin/env python3
"""訊號回測 → 動態權重（機會股 Top 5 引擎的權重來源）。

對每個既有訊號（signal_ma / signal_breakout / 小詩系列 / 外資投信連買 / 千張大戶 / 同業低估），
用既有歷史（還原權息後的收盤價）回測「訊號成立日的下 20 交易日報酬 > 0」的勝率與平均報酬，
權重公式：weight = max(0, round((win_rate − 0.5) × 20))；樣本 < 30 的訊號用預設權重 1。

輸出 pipeline/signal_weights.json（含每訊號勝率 / 樣本數 / 平均報酬 / 權重，供網頁透明化展示）。

⚠️ 歷史深度限制：price 歷史約 110 交易日 → 技術訊號（signal_ma/breakout/小詩）樣本充足可回測；
   chip 歷史僅 20 交易日、估值/千張大戶是「當下快照」無逐日歷史 → 這些訊號回測樣本會不足 30，
   自動落到預設權重 1（誠實反映，不假裝有統計依據）。

重算頻率：由 ensure_weights() 控制——檔案不存在、或距上次重算 ≥ 6 天才重算（約每週一次），
平日沿用既有權重（省掉每天上萬次 compute_indicators）。
"""
import os
import sys
import json
import datetime as dt
from math import log, exp, floor, sqrt
from collections import Counter
from itertools import combinations

sys.path.insert(0, os.path.dirname(__file__))
import history_store as hs  # noqa: E402

HERE = os.path.dirname(__file__)
WEIGHTS_PATH = os.path.join(HERE, "signal_weights.json")
WINDOWS_PATH = os.path.join(HERE, "signal_windows.json")
COMBOS_PATH = os.path.join(HERE, "signal_combos.json")
EXITS_PATH = os.path.join(HERE, "signal_exits.json")
REGIME_PATH = os.path.join(HERE, "signal_regime.json")
BT_PRICE_PATH = os.path.join(HERE, "history", "bt_price.json")

# 勝率榜的時間窗（曆日數，從最新資料日往回；歷史=全部）。
# ⚠️ 沒有「近1月」：勝率是「進場後 20 交易日報酬」，最近 ~20 個交易日的訊號還沒有結果可算，
#    近1月窗幾乎必然是空的（答案尚未揭曉，不是 bug），列了只會誤導。最短從近3月起。
WINDOWS = [("3m", "近3月", 90), ("6m", "近半年", 180), ("1y", "近一年", 365), ("all", "歷史", None)]

FORWARD = 20        # 下 N 交易日報酬
MIN_SAMPLE = 30     # 低於此樣本數用預設權重
DEFAULT_WEIGHT = 1
MIN_BARS = 65       # compute_indicators 至少要 65 根 K 線
RECOMPUTE_DAYS = 6  # 距上次重算 ≥ 此天數才重算（約每週）
BACKTEST_MIN_VOL = 300  # 只回測有一定量能的股票，避免殭屍股雜訊

# 進 Top5 選股引擎計分的訊號（opportunities.build_opportunities 只加這些的權重）。
# 這是「引擎基準」——不要為了展示戰績就亂加，會改動 Top5 排名（見 ENGINE_SIGNALS 用途）。
ENGINE_SIGNALS = [
    "signal_ma", "signal_breakout",
    "sn_squeeze_breakout", "sn_lower_reversal", "sn_break_low_recover",
    "sn_immortal_guide", "sn_volume_support",
    "foreign_buy", "trust_buy", "holder_rising", "undervalued",
]
# 回測＋勝率榜「展示」涵蓋的訊號＝引擎訊號 ＋ 只做戰績展示、不進引擎的（多頭排列/填息快）。
# 多頭排列太常見，若進引擎會亂洗 Top5；填息快是狀態型訊號。兩者只給使用者看戰績，不改選股。
DISPLAY_ONLY_SIGNALS = ["bull_aligned", "fill_fast"]
# Phase B 的橫斷面訊號（相對強弱 RS ＋ 產業輪動）：也只先做展示＋OOS 驗證，不進引擎。
# 這些是「跨股票比較」出來的（個股 N 日報酬在全市場的百分位），不能在單股 pr[:i+1] 內算，
# 要先建 PIT 橫斷面 cache（build_xsect_cache）再由 collect_events 查詢，見下方 XSECT_SIGNALS。
XSECT_SIGNALS = ["rs_strong_60", "rs_confirmed_60_120", "industry_hot"]
SIGNALS = ENGINE_SIGNALS + DISPLAY_ONLY_SIGNALS + XSECT_SIGNALS

# 中文標籤（給 opportunities 的 reasons 與網頁展示共用）
SIGNAL_LABELS = {
    "signal_ma": "糾結轉強", "signal_breakout": "爆量突破",
    "sn_squeeze_breakout": "縮口帶量突破", "sn_lower_reversal": "破下軌翻紅",
    "sn_break_low_recover": "破底翻", "sn_immortal_guide": "仙人指路",
    "sn_volume_support": "大量撐",
    "foreign_buy": "外資連買", "trust_buy": "投信連買",
    "holder_rising": "千張大戶↑", "undervalued": "同業低估",
    "bull_aligned": "多頭排列", "fill_fast": "填息快",
    "rs_strong_60": "強勢股60日", "rs_confirmed_60_120": "強勢雙確認", "industry_hot": "熱門產業",
}

# Phase B 橫斷面訊號的 frozen 參數（同 Phase A：首次看結果前鎖定，改動＝升 spec_version）
RS_WINDOWS = (20, 60, 120)     # 相對強弱回看的交易日數
RS_MIN_UNIVERSE = 300          # 當日橫斷面母體 <300 檔則該日 RS/產業不可評估（避免薄母體排名失真）
RS_STRONG_PCT = 0.80           # 「強勢」門檻：N 日報酬在全市場的百分位
RS_CONFIRM_120_PCT = 0.70      # 雙確認：60 日強且 120 日也不弱
IND_MIN_MEMBERS = 10           # 產業當日最少幾檔可評估才納入
IND_MIN_COVERAGE = 0.30        # 且需達該產業母體的三成
IND_TOP_K = 7                  # 熱門產業取分數前 K（34 產業約前 20%）
IND_MIN_ELIGIBLE = 20          # 當日合格產業 <20 則不產生 industry_hot（市況太亂不判）
IND_WINSOR = 0.05              # 產業報酬前先對橫斷面報酬做 5%/95% winsorize（壓極端飆股）


def signal_flags(ind):
    """從 compute_indicators 的輸出（或加值後的 results 元素）抽出各訊號是否成立。
    純函式、不碰 I/O，回測與選股共用同一套判準避免漂移。"""
    return {
        "signal_ma": bool(ind.get("signal_ma")),
        "signal_breakout": bool(ind.get("signal_breakout")),
        "sn_squeeze_breakout": bool(ind.get("sn_squeeze_breakout")),
        "sn_lower_reversal": bool(ind.get("sn_lower_reversal")),
        "sn_break_low_recover": bool(ind.get("sn_break_low_recover")),
        "sn_immortal_guide": bool(ind.get("sn_immortal_guide")),
        "sn_volume_support": bool(ind.get("sn_volume_support")),
        "foreign_buy": (ind.get("foreign_streak", 0) or 0) >= 3,
        "trust_buy": (ind.get("trust_streak", 0) or 0) >= 3,
        "holder_rising": bool(ind.get("holder_rising")),
        "undervalued": bool(ind.get("undervalued")),
        # 展示型（不進引擎）：多頭排列＝MA5>10>20>60；填息快＝已填息且天數 ≤10
        "bull_aligned": bool(ind.get("bull_aligned")),
        "fill_fast": _fill_fast(ind.get("div_fill")),
    }


def _fill_fast(df):
    """填息快：最近一次除權息已填息、且填息天數 ≤10。div_fill 用未來除權息日時會回未填息，
    不會製造前視偏誤（保守）。與『填息快』快速套用（divFill=filled, maxFillDays=10）同義。"""
    return bool(df) and df.get("fill_days") is not None and df["fill_days"] <= 10


def stats_to_weights(stats, min_sample=MIN_SAMPLE, default=DEFAULT_WEIGHT):
    """把每訊號的統計換成勝率/超額報酬/權重。純函式（好手算對照）。

    **權重一律看「超額勝率」而非「絕對勝率」**：絕對勝率是「20 日後有沒有漲」，多頭市場裡
    隨便亂選也會超過 50%，拿它當證據等於把大盤的漲幅記在訊號頭上。超額＝該股報酬減掉
    「同一天全市場的平均報酬」，衡量的是「這個訊號有沒有比隨便買強」，才是真的邊際價值。

    **樣本不足一律 weight=0，不再給預設 1**：舊做法把「沒有證據」當成「中等證據」——
    投信連買 0 筆樣本、外資連買 1 筆樣本，權重卻和 3,691 筆樣本的縮口帶量突破一樣大，
    等於讓沒驗證過的條件左右機會股排名。沒證據就不該加分，但保留統計數字供觀察。
    """
    out = {}
    for k in SIGNALS:
        st = stats.get(k) or {}
        c = st.get("count", 0)
        wr = (st.get("wins", 0) / c) if c else None
        exc_wr = (st.get("exc_wins", 0) / c) if c else None
        validated = c >= min_sample
        # 權重看「平均超額報酬」而不是「超額勝率」：訊號報酬是右偏的——多數事件小輸、
        # 少數事件大贏。實測「大量撐」超額勝率只有 40%，平均超額卻是 +1.28pp，用勝率會
        # 把它判成廢訊號。交易看的是期望值，不是贏的次數。
        avg_exc_pp = (st.get("exc_sum", 0.0) / c * 100) if c else 0.0
        if not validated or avg_exc_pp <= 0:
            weight = 0
        else:
            weight = min(5, max(1, round(avg_exc_pp * 2)))
        out[k] = {
            "label": SIGNAL_LABELS.get(k, k),
            "win_rate": round(wr, 4) if wr is not None else None,          # 絕對勝率（僅供對照）
            "excess_win_rate": round(exc_wr, 4) if exc_wr is not None else None,  # 超額勝率（權重依據）
            "avg_ret": round(st.get("ret_sum", 0.0) / c * 100, 2) if c else None,   # 平均報酬（%）
            "avg_excess": round(st.get("exc_sum", 0.0) / c * 100, 2) if c else None,  # 平均超額報酬（百分點）
            "samples": c,
            "validated": validated,
            "weight": weight,
        }
    return out


# ── Phase B：橫斷面訊號（相對強弱 RS ＋ 產業輪動）的 PIT cache ─────────────────────

def _pct_rank_avg(values):
    """{key: value} → {key: 百分位 [0,1]}，最弱 0、最強 1，同分用平均排名。"""
    items = sorted(values.items(), key=lambda kv: kv[1])
    n = len(items)
    if n <= 1:
        return {k: 0.5 for k in values}
    ranks, i = {}, 0
    while i < n:
        j = i
        while j + 1 < n and items[j + 1][1] == items[i][1]:
            j += 1
        avg_rank = (i + j) / 2 + 1                # 1-based 平均排名
        for t in range(i, j + 1):
            ranks[items[t][0]] = avg_rank
        i = j + 1
    return {k: (r - 1) / (n - 1) for k, r in ranks.items()}


def _quantile_sorted(sorted_vals, q):
    """已排序序列的分位數（線性內插）。"""
    if not sorted_vals:
        return None
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    pos = q * (n - 1)
    lo = int(pos)
    frac = pos - lo
    if lo + 1 < n:
        return sorted_vals[lo] * (1 - frac) + sorted_vals[lo + 1] * frac
    return sorted_vals[-1]


def _winsorize(values, p=IND_WINSOR):
    """對一批數值做 p/(1-p) winsorize（把極端值夾到分位數），回同鍵 dict。"""
    if not values:
        return values
    s = sorted(values.values())
    lo, hi = _quantile_sorted(s, p), _quantile_sorted(s, 1 - p)
    return {k: min(max(v, lo), hi) for k, v in values.items()}


def build_xsect_cache(price_hist, div_hist, universe):
    """建立橫斷面 PIT cache：對每個交易日，算各股「近 N 日還原報酬」在全市場的百分位（RS），
    以及所屬產業當日是否「熱門」（產業輪動）。回 {date: {sid: {rs_pct_60, rs_pct_120, industry_hot}}}。

    刻意設計（避免前視）：交易日 t 只用 t 與 t−N 的還原收盤算報酬，母體＝當日有價的全部個股；
    母體 <300 檔則該日不評估。產業報酬先對橫斷面報酬 winsorize（壓少數飆股），產業內等權平均
    （沒有長期市值、且成交額加權會把當日爆量混進來與爆量突破重疊，故用等權）。"""
    industry = {s["id"]: s.get("industry") for s in universe}
    universe_ind_count = {}
    for s in universe:
        g = s.get("industry")
        universe_ind_count[g] = universe_ind_count.get(g, 0) + 1

    # 每檔還原收盤序列 {sid: {date: adj_close}}（跟回測同一把尺）
    import build_data as bd
    adj = {}
    all_dates = set()
    for sid, by in price_hist.items():
        pr = hs.to_price_rows(by)
        if not pr:
            continue
        ev = hs.to_div_events(div_hist.get(sid))
        ac = {r["date"]: r["close"] for r in bd.back_adjust_rows(sorted(pr, key=lambda r: r["date"]), ev)
              if r.get("close") and r["close"] > 0}
        if ac:
            adj[sid] = ac
            all_dates.update(ac)

    dates = sorted(all_dates)
    didx = {d: i for i, d in enumerate(dates)}
    cache = {}

    for ti, t in enumerate(dates):
        # 各 N 的個股報酬與百分位
        rs_pct = {N: {} for N in RS_WINDOWS}
        ret_by_N = {N: {} for N in RS_WINDOWS}
        for N in RS_WINDOWS:
            if ti < N:
                continue
            t_n = dates[ti - N]
            rets = {}
            for sid, ac in adj.items():
                p, pn = ac.get(t), ac.get(t_n)
                if p and pn:
                    rets[sid] = p / pn - 1
            if len(rets) < RS_MIN_UNIVERSE:
                continue
            ret_by_N[N] = rets
            rs_pct[N] = _pct_rank_avg(rets)

        # 產業輪動：需要 20/60 日報酬母體都在
        hot_set = None
        if ret_by_N[20] and ret_by_N[60]:
            hot_set = _hot_industries(ret_by_N[20], ret_by_N[60], industry, universe_ind_count)

        # 寫入 cache（只存有 60 日 RS 的個股，其餘查不到＝視為未成立）
        day = {}
        for sid in rs_pct[60]:
            g = industry.get(sid)
            day[sid] = {
                "rs_pct_60": round(rs_pct[60].get(sid), 4),
                "rs_pct_120": round(rs_pct[120][sid], 4) if sid in rs_pct[120] else None,
                "industry_hot": bool(hot_set and g in hot_set),
            }
        if day:
            cache[t] = day
    return cache


def _hot_industries(ret20, ret60, industry, universe_ind_count):
    """當日熱門產業集合。ret20/ret60＝{sid: N日報酬}。回 set(產業名) 或 None（市況太亂不判）。"""
    w20 = _winsorize(ret20)
    w60 = _winsorize(ret60)
    market_median_20 = _quantile_sorted(sorted(w20.values()), 0.5)

    def ind_mean(w):
        by_g = {}
        for sid, v in w.items():
            g = industry.get(sid)
            by_g.setdefault(g, []).append(v)
        out = {}
        for g, vals in by_g.items():
            tot = universe_ind_count.get(g, 0)
            if len(vals) >= IND_MIN_MEMBERS and tot and len(vals) / tot >= IND_MIN_COVERAGE:
                out[g] = sum(vals) / len(vals)
        return out

    ind20, ind60 = ind_mean(w20), ind_mean(w60)
    eligible = [g for g in ind20 if g in ind60]
    if len(eligible) < IND_MIN_ELIGIBLE:
        return None
    pct20 = _pct_rank_avg({g: ind20[g] for g in eligible})
    pct60 = _pct_rank_avg({g: ind60[g] for g in eligible})
    score = {g: 0.70 * pct20[g] + 0.30 * pct60[g] for g in eligible}
    # 分數前 K（同分用產業名固定排序，確保可重現）
    top = sorted(eligible, key=lambda g: (-score[g], str(g)))[:IND_TOP_K]
    hot = {g for g in top
           if ind20[g] > market_median_20 and pct60[g] >= 0.50}
    return hot


def _xsect_flags(x):
    """把 cache 裡某 (date,sid) 的橫斷面數值翻成三個訊號旗標；查不到一律 False（未成立、非缺值）。"""
    if not x:
        return {"rs_strong_60": False, "rs_confirmed_60_120": False, "industry_hot": False}
    p60, p120 = x.get("rs_pct_60"), x.get("rs_pct_120")
    strong60 = p60 is not None and p60 >= RS_STRONG_PCT
    return {
        "rs_strong_60": bool(strong60),
        "rs_confirmed_60_120": bool(strong60 and p120 is not None and p120 >= RS_CONFIRM_120_PCT),
        "industry_hot": bool(x.get("industry_hot")),
    }


def collect_events(price_hist, chip_hist, div_hist, universe,
                   forward=FORWARD, min_bars=MIN_BARS, cooldown=None, xsect=None):
    """逐檔、逐歷史交易日評估訊號，回傳 (events, by_date)。

    events：[{date, sid, ret, fired:[訊號…]}]，只收「有訊號成立」的事件。
    by_date：{date: [該日所有可評估個股的 forward 報酬…]}，當「同日全市場平均」基準用——
             這是唯一能從現有資料算出的乾淨對照組（指數歷史只有 39 天，蓋不住 110 天回測窗）。

    三個刻意的設計，都是為了讓數字可信：
    1. **流動性用當時的量**：舊版拿「完整序列（含今天）」的 20 日均量決定整檔要不要回測，
       等於用未來資訊篩過去樣本——當年沒量、現在爆量的會被算進來，當年活躍、現在變殭屍的
       整檔被丟掉。改成每個歷史時點各自用「那天當下」的 20 日均量判斷。
    2. **同一檔同一訊號設冷卻期**：形態會在最近 3 日內重複成立，20 日持有期又高度重疊，
       舊版把它們當成獨立樣本，樣本數嚴重虛胖（宣稱 3,496 筆其實遠少於此）。
    3. **只用 pr[:i+1] 算指標**：這點舊版就做對了，保留。
    """
    import build_data as bd  # 延遲載入避免與 build_data 的循環匯入
    cooldown = forward if cooldown is None else cooldown
    events, by_date = [], {}

    for stock in universe:
        sid = stock["id"]
        pr = hs.to_price_rows(price_hist.get(sid, {}))
        if len(pr) < min_bars + forward + 1:
            continue
        pr = sorted(pr, key=lambda r: r["date"])
        cr = hs.to_chip_rows(chip_hist.get(sid, {}))
        ev = hs.to_div_events(div_hist.get(sid))

        # 還原權息後的收盤序列（跟 pr 同順序），用來算前瞻報酬
        adj_close = [r["close"] for r in bd.back_adjust_rows(pr, ev)]
        last_fire = {}   # 訊號 → 最後一次採計的 i，做冷卻期

        for i in range(min_bars - 1, len(pr) - forward):
            di = pr[i]["date"]
            base = adj_close[i]
            if not base:
                continue
            ind = bd.compute_indicators(pr[:i + 1], [c for c in cr if c["date"] <= di], ev, None)
            if ind is None:
                continue
            # 流動性用「當下」的 20 日均量，不是最新的（point-in-time，避免前視偏誤）
            if (ind.get("avg_vol_lots", 0) or 0) < BACKTEST_MIN_VOL:
                continue

            ret = adj_close[i + forward] / base - 1
            by_date.setdefault(di, []).append(ret)   # 基準母體：所有「可評估」個股，不論有無訊號

            # raw_fired＝當天所有「原始成立」的訊號（不管冷卻）；eligible＝過了單訊號冷卻期的。
            # 單訊號統計吃 eligible（維持原結果不變）；組合統計吃 raw_fired（才是「當天真的同時
            # 成立 A+B」，否則 A 在冷卻期時 A+B 會被漏算——Codex 2026-07-24 指出）。
            flags = signal_flags(ind)
            if xsect is not None:                 # Phase B 橫斷面訊號（RS/產業）從 PIT cache 併入
                flags.update(_xsect_flags(xsect.get(di, {}).get(sid)))
            raw_fired, eligible_fired = [], []
            for k, hit in flags.items():
                if not hit:
                    continue
                raw_fired.append(k)
                if k in last_fire and i - last_fire[k] < cooldown:
                    continue                          # 冷卻期內，同一波訊號不重複採計（僅影響單訊號統計）
                last_fire[k] = i
                eligible_fired.append(k)
            if raw_fired:
                events.append({"date": di, "sid": sid, "i": i, "ret": ret,
                               "fired": eligible_fired, "raw_fired": raw_fired})
    return events, by_date


def events_to_stats(events, by_date):
    """把事件與同日基準換算成每訊號統計。純函式，方便單測與手算對照。"""
    bench = {d: (sum(v) / len(v)) for d, v in by_date.items() if v}
    stats = {k: {"wins": 0, "count": 0, "ret_sum": 0.0, "exc_wins": 0, "exc_sum": 0.0} for k in SIGNALS}
    for e in events:
        b = bench.get(e["date"], 0.0)
        exc = e["ret"] - b
        for k in e["fired"]:
            st = stats[k]
            st["count"] += 1
            st["ret_sum"] += e["ret"]
            st["exc_sum"] += exc
            if e["ret"] > 0:
                st["wins"] += 1
            if exc > 0:
                st["exc_wins"] += 1
    return stats


def run_backtest(price_hist, chip_hist, div_hist, universe,
                 forward=FORWARD, min_bars=MIN_BARS):
    """對全市場回測訊號，回傳 stats_to_weights 的輸出。"""
    events, by_date = collect_events(price_hist, chip_hist, div_hist, universe, forward, min_bars)
    return stats_to_weights(events_to_stats(events, by_date))


# ── Phase A 地基：walk-forward 樣本外(OOS)驗證 ＋ EWMA 時間自適應權重 ──────────
# 🔒 frozen config：首次看 OOS 結果前就鎖定，事後不准回頭調參數去迎合結果（那叫過擬合 harness）。
#    要改任何一個數字＝升 spec_version，且舊 OOS 已淪為「開發資料」不能再當乾淨樣本外。
#    新東西全部「並行輸出」到 signal_weights.json 的 oos/adaptive 欄位，現行 weight（Top5 引擎）一律不動。
OOS_TRAIN_DAYS = 252    # 訓練窗（交易日）：約一年
OOS_EMBARGO_DAYS = 20   # 隔離帶：train 最後事件的 20 日報酬要在 test 開始前成熟，否則假 OOS 會洩漏未來價
OOS_TEST_DAYS = 20      # 測試窗
OOS_STEP_DAYS = 20      # 每次前滾 20（＝test 寬，故各 fold 的 test 不重疊、事件不重複計）
OOS_MIN_TRAIN = 30      # 訓練期該訊號最少事件數，否則此 fold 不評該訊號
EWMA_HALF_LIFE = 63     # 近期加權半衰期（交易日）：約一季、約 3 個持有期；比 20 穩、比 126 更反映近況
EWMA_MAX_RECENT_SHARE = 0.30  # 近期最多佔混合權重的比例（樣本足才給到滿）
SHRINK_K = 30.0         # 樣本感知收縮：effective = blended × ESS/(ESS+K)，K=30 與最低樣本門檻一致
PHASE_A_SPEC = "phase-a-v1"

# ── 組合戰績（A＋B、A＋B＋C 同時成立的勝率）──────────────────────────
COMBO_MIN_SAMPLE = 5    # 至少幾筆才收（1~2 筆純巧合、會誤導）；Andy 要「樣本少沒關係、找最高勝率」
COMBO_MAX_SIZE = 3      # 最多幾個訊號同時成立（兩兩＋三個一組）
COMBO_TOP = 120         # 依平均超額取前 N（控制檔案大小）


def combo_stats(events, by_date, min_sample=COMBO_MIN_SAMPLE, max_size=COMBO_MAX_SIZE,
                top=COMBO_TOP, cooldown=FORWARD):
    """算「多個訊號同時成立」的組合戰績。用 raw_fired（當天原始同時成立、不受單訊號冷卻影響，
    才是真正的「A+B 當天同時出現」），並對每個 (個股, 組合) 自己做冷卻期（用交易日 index i，
    避免同一波 A+B 連續多天被當獨立樣本灌水）。另算 excess_lb＝平均超額的樣本數感知下界
    （mean − 1 個標準誤），小樣本/高波動會被壓低，幫使用者分辨「又高又穩」與「小樣本巧合」。

    回 (combos, pairs)：combos＝pairs+triples 依平均超額排序取前 top（排行榜用）；
    pairs＝所有合格兩兩組合（給熱力圖完整矩陣，不會因被高排名 triple 擠掉而出現假空格）。"""
    bench = {d: (sum(v) / len(v)) for d, v in by_date.items() if v}
    acc = {}
    last_fire = {}   # (sid, combo) → 最後採計的 i，做組合級冷卻
    for e in events:
        raw = sorted(set(e.get("raw_fired") or e.get("fired") or []))
        if len(raw) < 2:
            continue
        sid, i = e["sid"], e.get("i", 0)
        exc = e["ret"] - bench.get(e["date"], 0.0)
        win, exc_win = e["ret"] > 0, exc > 0
        for size in range(2, min(max_size, len(raw)) + 1):
            for combo in combinations(raw, size):
                key = (sid, combo)
                if key in last_fire and i - last_fire[key] < cooldown:
                    continue                          # 同一波組合冷卻期內不重複採計
                last_fire[key] = i
                st = acc.setdefault(combo, {"count": 0, "exc_sum": 0.0, "exc_sq": 0.0,
                                            "exc_wins": 0, "wins": 0, "ret_sum": 0.0})
                st["count"] += 1
                st["exc_sum"] += exc
                st["exc_sq"] += exc * exc
                st["ret_sum"] += e["ret"]
                st["exc_wins"] += exc_win
                st["wins"] += win

    def to_row(combo, st):
        c = st["count"]
        mean = st["exc_sum"] / c
        var = max(0.0, st["exc_sq"] / c - mean * mean)
        se = (var ** 0.5) / (c ** 0.5)              # 標準誤
        return {
            "sigs": list(combo),
            "labels": [SIGNAL_LABELS.get(s, s) for s in combo],
            "avg_excess": round(mean * 100, 2),
            "excess_lb": round((mean - se) * 100, 2),   # 穩健度：~1SE 下界，樣本越少/越波動壓越低
            "excess_win_rate": round(st["exc_wins"] / c, 4),
            "win_rate": round(st["wins"] / c, 4),
            "avg_ret": round(st["ret_sum"] / c * 100, 2),
            "samples": c,
        }

    rows = [to_row(combo, st) for combo, st in acc.items() if st["count"] >= min_sample]
    combos = sorted(rows, key=lambda x: -x["avg_excess"])[:top]
    pairs = sorted([r for r in rows if len(r["sigs"]) == 2], key=lambda x: -x["avg_excess"])
    return combos, pairs


# ── Phase A：樣本外驗證 ＋ 自適應權重（純函式、吃已收集好的 events/by_date，可單測）─────────

def _signal_event_excess(events, by_date):
    """每訊號 → [(date, excess_pp)]。excess＝該事件報酬 − 同日全市場平均，單位百分點(pp)。
    用 e["fired"]（過單訊號冷卻的），與單訊號統計/勝率榜同一把尺，OOS 與現況才可直接對照。"""
    bench = {d: (sum(v) / len(v)) for d, v in by_date.items() if v}
    per = {k: [] for k in SIGNALS}
    for e in events:
        exc = (e["ret"] - bench.get(e["date"], 0.0)) * 100.0
        for k in e["fired"]:
            per[k].append((e["date"], exc))
    return per


def walk_forward_oos(events, by_date):
    """滾動樣本外驗證。回 (per_signal_oos, total_folds)。

    fold＝train(252 交易日) → embargo(20) → test(20)，每次前滾 20（test 不重疊）。
    embargo 是關鍵：train 最後一天訊號的 20 日報酬會延伸進 test，不留空窗就會用到未來價、
    假 OOS 真洩漏。每個 fold 內用 train 期算該訊號平均超額，>0 且樣本 ≥30 才「合格」，
    合格才把該訊號在 test 期的實際事件收進 OOS 池——這才是「事前只用得到的資訊選、事後才驗」。"""
    dates = sorted(by_date.keys())          # 可評分交易日曆（皆已有 forward 報酬）
    N = len(dates)
    per = _signal_event_excess(events, by_date)

    folds = []                              # [(train_dates:set, test_dates:set)]
    s = 0
    span = OOS_TRAIN_DAYS + OOS_EMBARGO_DAYS + OOS_TEST_DAYS
    while s + span <= N:
        train_dates = set(dates[s:s + OOS_TRAIN_DAYS])
        t0 = s + OOS_TRAIN_DAYS + OOS_EMBARGO_DAYS
        test_dates = set(dates[t0:t0 + OOS_TEST_DAYS])
        folds.append((train_dates, test_dates))
        s += OOS_STEP_DAYS
    F = len(folds)

    out = {}
    for k in SIGNALS:
        evx = per[k]                        # [(date, excess_pp)]
        selected_x, selected_dates = [], []
        selected_folds = 0
        is_num, is_den = 0.0, 0             # is_selected＝Σ len(T_f)*train_avg / Σ len(T_f)
        for train_dates, test_dates in folds:
            train_x = [x for (d, x) in evx if d in train_dates]
            if len(train_x) < OOS_MIN_TRAIN:
                continue
            train_avg = sum(train_x) / len(train_x)
            if train_avg <= 0.0:            # 訓練期就沒有正超額 → 此 fold 不選這個訊號
                continue
            selected_folds += 1
            test_ev = [(d, x) for (d, x) in evx if d in test_dates]
            for d, x in test_ev:
                selected_x.append(x)
                selected_dates.append(d)
            if test_ev:
                is_num += len(test_ev) * train_avg
                is_den += len(test_ev)
        out[k] = _oos_row(k, len(evx), selected_folds, F, selected_x, selected_dates, is_num, is_den)
    return out, F


def _oos_row(k, total_hist, selected_folds, F, sel_x, sel_dates, is_num, is_den):
    """把某訊號跨 fold 的 OOS 結果整理成一列，含穩健度分類（誠實標示樣本不足）。"""
    n = len(sel_x)
    active_dates = len(set(sel_dates))
    row = {
        "label": SIGNAL_LABELS.get(k, k),
        "excess_pp": None, "win_rate": None, "samples": n, "active_dates": active_dates,
        "selected_folds": selected_folds, "total_folds": F,
        "selected_fraction": round(selected_folds / F, 4) if F else None,
        "is_selected_excess_pp": None, "shrinkage_pp": None, "retention_ratio": None,
    }
    # 狀態優先序：先排除「根本不夠資格評」的，最後才做穩健度分類
    if total_hist == 0:
        row["status"] = "no_events"; return row
    if total_hist < OOS_MIN_TRAIN:
        row["status"] = "insufficient_history"; return row
    if selected_folds == 0:
        row["status"] = "never_qualified"; return row
    if n == 0:
        row["status"] = "no_selected_oos_events"; return row

    oos = sum(sel_x) / n
    row["excess_pp"] = round(oos, 2)
    row["win_rate"] = round(sum(1 for x in sel_x if x > 0.0) / n, 4)   # x==0 算非勝
    is_sel = (is_num / is_den) if is_den else None
    if is_sel is not None:
        row["is_selected_excess_pp"] = round(is_sel, 2)
        row["shrinkage_pp"] = round(is_sel - oos, 2)
        row["retention_ratio"] = round(oos / is_sel, 3) if abs(is_sel) > 1e-9 else None

    rr, sf = row["retention_ratio"], row["selected_fraction"]
    if selected_folds < 3 or n < 30 or active_dates < 10 or rr is None:
        row["status"] = "insufficient_oos"
    elif oos <= 0:
        row["status"] = "overfit"           # 訓練看好、樣本外變負 → 過擬合
    elif rr < 0.25:
        row["status"] = "severe_shrinkage"
    elif rr < 0.50:
        row["status"] = "fragile"
    elif sf < 0.30:
        row["status"] = "regime_specific"   # 只有少數市況合格 → 挑市況
    else:
        row["status"] = "robust"            # 又高又穩、跨市況、樣本外站得住
    return row


def adaptive_weights(events, by_date):
    """EWMA 時間自適應候選權重。回 {sigkey: {...adaptive 欄位...}}。**並行輸出、不改現行 weight。**

    近期表現用「交易日 index 指數衰減」加權（半衰期 63 日）；近期占比隨近期有效樣本動態放大
    （最多 30%）；再乘樣本感知收縮（ESS 少就往 0 拉）得 effective，映射成 candidate_weight。
    有效樣本數(ESS)用同日群聚保守化——同一天幾十檔同時觸發不是幾十個獨立證據。"""
    dates = sorted(by_date.keys())
    idx = {d: i for i, d in enumerate(dates)}
    as_of_i = len(dates) - 1
    as_of = dates[-1] if dates else None
    per = _signal_event_excess(events, by_date)
    decay = exp(-log(2) / EWMA_HALF_LIFE)
    return {k: _adaptive_row(k, per[k], idx, as_of, as_of_i, decay) for k in SIGNALS}


def _ess_by_date(dates_list, weights=None):
    """同日群聚的有效樣本數 ESS＝1/Σ(每日權重佔比)²。weights=None 時每筆等權。"""
    if not dates_list:
        return 0.0
    if weights is None:
        cnt = Counter(dates_list)
        tot = len(dates_list)
        return 1.0 / sum((c / tot) ** 2 for c in cnt.values())
    W = sum(weights)
    if W <= 0:
        return 0.0
    by_d = {}
    for d, w in zip(dates_list, weights):
        by_d[d] = by_d.get(d, 0.0) + w
    return 1.0 / sum((q / W) ** 2 for q in by_d.values())


def _adaptive_row(k, evx, idx, as_of, as_of_i, decay):
    """單一訊號的自適應候選權重明細。evx＝[(date, excess_pp)]。"""
    label = SIGNAL_LABELS.get(k, k)
    hist_n = len(evx)
    row = {
        "label": label, "as_of": as_of, "matured_through": None,
        "half_life_days": EWMA_HALF_LIFE, "decay_lambda": round(decay, 5),
        "hist_samples": hist_n, "hist_n_eff": None, "hist_excess_pp": None,
        "recent_excess_pp": None, "recent_n_eff": None, "recent_se_pp": None,
        "recent_lcb90_pp": None, "recent_share": None, "blended_excess_pp": None,
        "blend_n_eff": None, "shrink_factor": None, "effective_excess_pp": None,
        "candidate_weight": 0, "status": "no_events",
    }
    if hist_n == 0:
        return row

    hdates = [d for d, _ in evx]
    row["matured_through"] = max(hdates)
    hist_excess = sum(x for _, x in evx) / hist_n
    row["hist_excess_pp"] = round(hist_excess, 2)
    hist_n_eff = _ess_by_date(hdates)          # 全歷史等權、同日群聚 ESS
    row["hist_n_eff"] = round(hist_n_eff, 1)

    if hist_n < MIN_SAMPLE:                     # 全歷史 <30 不夠評，仍回明細但候選權重 0
        row["status"] = "insufficient_history"
        return row

    # EWMA 近期加權平均（用交易日 index 的年齡指數衰減）
    ws = [decay ** (as_of_i - idx[d]) for d, _ in evx if d in idx]
    xs = [x for d, x in evx if d in idx]
    ds = [d for d, _ in evx if d in idx]
    W = sum(ws)
    recent_excess = recent_n_eff = None
    if W > 1e-12:
        recent_excess = sum(w * x for w, x in zip(ws, xs)) / W
        ps = [w / W for w in ws]
        event_n_eff = 1.0 / sum(p * p for p in ps)
        date_n_eff = _ess_by_date(ds, ws)
        recent_n_eff = min(event_n_eff, date_n_eff)
        row["recent_excess_pp"] = round(recent_excess, 2)
        row["recent_n_eff"] = round(recent_n_eff, 1)
        # 近期有效樣本 >1 才算加權變異數 → SE / 90% 單側下界（診斷用，不直接控權重）
        denom = 1.0 - sum(p * p for p in ps)
        if denom > 1e-12 and recent_n_eff and recent_n_eff > 1:
            wvar = sum(p * (x - recent_excess) ** 2 for p, x in zip(ps, xs)) / denom
            se = sqrt(wvar / recent_n_eff) if wvar >= 0 else None
            if se is not None:
                row["recent_se_pp"] = round(se, 2)
                row["recent_lcb90_pp"] = round(recent_excess - 1.2816 * se, 2)

    # 近期占比動態化：近期有效樣本越足、給越多（上限 30%）
    if recent_excess is None:
        recent_share = 0.0
        blended = hist_excess
    else:
        recent_share = EWMA_MAX_RECENT_SHARE * min(1.0, recent_n_eff / 30.0)
        blended = (1.0 - recent_share) * hist_excess + recent_share * recent_excess
    history_share = 1.0 - recent_share
    row["recent_share"] = round(recent_share, 3)
    row["blended_excess_pp"] = round(blended, 2)

    # 樣本感知收縮：混合有效樣本少就把估計往 0 拉
    blend_n_eff = history_share * hist_n_eff + (recent_share * recent_n_eff if recent_n_eff else 0.0)
    shrink = blend_n_eff / (blend_n_eff + SHRINK_K) if blend_n_eff > 0 else 0.0
    effective = blended * shrink
    row["blend_n_eff"] = round(blend_n_eff, 1)
    row["shrink_factor"] = round(shrink, 3)
    row["effective_excess_pp"] = round(effective, 2)

    if effective <= 0:
        row["candidate_weight"] = 0
    else:
        row["candidate_weight"] = min(5, max(1, floor(effective * 2.0 + 0.5)))  # half-up，非 bankers
    row["status"] = "eligible"
    return row


# ── 市況分層回測（Andy 選：同一訊號在多頭 vs 空頭效果差多少）─────────────────────
# 市況用「市場廣度」代理（全市場收在 ma20 之上比例＋20 日報酬中位），跟前端 market_breadth 橫幅同門檻。
# 🔑 point-in-time：交易日 t 的市況只用 ≤t 的資料（close_t、ma20_t、t−20→t 報酬），
#    絕不用 t→t+20 的前瞻報酬判市況（那是結果標籤、拿來判市況＝前視）。
REGIME_MIN_UNIVERSE = 100      # 當日可評估個股 <100 檔 → 市況 unknown（不硬判）


def _breadth_status(breadth, med_ret):
    """由廣度（收在 ma20 之上比例）＋20 日報酬中位判市況。與 build_data.market_breadth 同門檻。
    回 green/yellow/red（severe_red 併進 red，讓分層樣本夠）。"""
    if breadth >= 0.55 and med_ret >= 0.0:
        return "green"
    if breadth < 0.40 and med_ret < 0.0:
        return "red"
    return "yellow"


def build_regime_series(price_hist, div_hist):
    """每個歷史交易日的市況（green/yellow/red/unknown），point-in-time、無前視。
    回 {date: status}。breadth＝當日收在 ma20 之上的比例；med＝20 日還原報酬中位數。"""
    import build_data as bd
    above = {}    # date -> [n_above, n_total]
    rets = {}     # date -> [20 日報酬…]
    for sid, by in price_hist.items():
        pr = sorted(hs.to_price_rows(by), key=lambda r: r["date"])
        ev = hs.to_div_events(div_hist.get(sid))
        ac = [r["close"] for r in bd.back_adjust_rows(pr, ev)]
        ds = [r["date"] for r in pr]
        run = 0.0                                  # ma20 滾動和
        for i in range(len(ac)):
            c = ac[i]
            run += c or 0.0
            if i >= 20:
                run -= ac[i - 20] or 0.0
            if i >= 19 and c:                       # 有 20 根才算 ma20
                ma20 = run / 20
                a = above.setdefault(ds[i], [0, 0])
                a[1] += 1
                if c > ma20:
                    a[0] += 1
            if i >= 20 and ac[i - 20] and c:
                rets.setdefault(ds[i], []).append(c / ac[i - 20] - 1)
    series = {}
    for d, (n_ab, n_tot) in above.items():
        if n_tot < REGIME_MIN_UNIVERSE:
            series[d] = "unknown"
            continue
        rr = sorted(rets.get(d, []))
        med = rr[len(rr) // 2] if len(rr) % 2 else (rr[len(rr) // 2 - 1] + rr[len(rr) // 2]) / 2 if rr else 0.0
        series[d] = _breadth_status(n_ab / n_tot, med)
    return series


def regime_stratified_stats(events, by_date, regime):
    """把回測事件依「當時市況」分層，算每訊號在 green/yellow/red 的超額與勝率。
    回 {sigkey: {label, green:{...}, yellow:{...}, red:{...}}}，讓使用者看「只在多頭有效」vs「全天候」。"""
    buckets = ("green", "yellow", "red")
    ev_by = {b: [] for b in buckets}
    bd_all = by_date
    for e in events:
        st = regime.get(e["date"])
        if st in ev_by:
            ev_by[st].append(e)
    per_bucket = {b: stats_to_weights(events_to_stats(ev_by[b], bd_all)) for b in buckets}
    out = {}
    for k in SIGNALS:
        row = {"label": SIGNAL_LABELS.get(k, k)}
        for b in buckets:
            s = per_bucket[b][k]
            row[b] = {"avg_excess": s["avg_excess"], "excess_win_rate": s["excess_win_rate"],
                      "win_rate": s["win_rate"], "samples": s["samples"]}
        out[k] = row
    return out


def _apply_cost(gross):
    """把毛報酬換成成本後淨報酬（來回手續費＋證交稅＋滑價，乘除式，與出場分析同一把尺）。"""
    return (1 + gross) * (1 - EXIT_FEE - EXIT_TAX - EXIT_SLIP) / (1 + EXIT_FEE + EXIT_SLIP) - 1


def signal_quality(events):
    """每訊號的「防騙指標」：成本後期望值、賺賠比、獲利因子——讓「高勝率但期望值爛」現形。
    回 {sigkey: {...}}。用 e['fired']（過冷卻、與單訊號統計同母體）。成本後（forward=20 毛報酬扣來回成本）。"""
    acc = {k: {"n": 0, "nw": 0, "nl": 0, "sw": 0.0, "sl": 0.0, "s": 0.0} for k in SIGNALS}
    for e in events:
        net = _apply_cost(e["ret"])
        for k in e["fired"]:
            a = acc[k]
            a["n"] += 1
            a["s"] += net
            if net > 0:
                a["nw"] += 1
                a["sw"] += net
            elif net < 0:
                a["nl"] += 1
                a["sl"] += -net                       # 累積虧損絕對值
    out = {}
    for k in SIGNALS:
        a = acc[k]
        n = a["n"]
        if n == 0:
            out[k] = {"samples": 0, "net_expectancy": None, "payoff_ratio": None,
                      "profit_factor": None, "net_win_rate": None, "high_win_trap": False}
            continue
        avg_win = a["sw"] / a["nw"] if a["nw"] else 0.0
        avg_loss = a["sl"] / a["nl"] if a["nl"] else 0.0   # 已是絕對值
        net_wr = a["nw"] / n
        expct = a["s"] / n
        out[k] = {
            "samples": n,
            "net_expectancy": round(expct * 100, 2),        # 成本後期望值（百分點）＝最重要的單一指標
            "avg_win": round(avg_win * 100, 2),
            "avg_loss": round(avg_loss * 100, 2),
            "payoff_ratio": round(avg_win / avg_loss, 2) if avg_loss > 0 else None,
            "profit_factor": round(a["sw"] / a["sl"], 2) if a["sl"] > 0 else None,
            "net_win_rate": round(net_wr, 4),
            # 高勝率陷阱：勝率高但成本後期望值 ≤0（樣本夠才判）
            "high_win_trap": bool(n >= 20 and net_wr >= 0.60 and expct <= 0),
        }
    return out


def attach_phase_a(weights, events, by_date):
    """把 OOS 與自適應候選權重併進 weights['signals'][k]（新增 oos/adaptive/spec_version 巢狀欄位）。
    現行 weight 完全不動——Top5 引擎這階段照舊，新指標只供驗證與展示。回 (oos_by_sig, total_folds)。"""
    oos, F = walk_forward_oos(events, by_date)
    adaptive = adaptive_weights(events, by_date)
    sigs = weights.get("signals", {})
    for k in SIGNALS:
        if k in sigs:
            sigs[k]["oos"] = oos.get(k)
            sigs[k]["adaptive"] = adaptive.get(k)
            sigs[k]["spec_version"] = PHASE_A_SPEC
    return oos, F


# ── Phase B-5：出場優化（並行成本後報表，不動 forward=20 基準）──────────────────
EXIT_HOLDINGS = [5, 10, 20, 40]     # 固定持有交易日；20＝現行 control
EXIT_TRAIL_CAP = 40                 # 收盤回落停利的最長持有
EXIT_TRAIL_DROP = 0.10             # 收盤自波段高點回落 ≥10% 出場（close-based，非 ATR）
# 台股來回成本（保守用全額未打折）＋每邊滑價；ATR/盤中停損因只有還原收盤、暫緩（見 note）
EXIT_FEE = 0.001425                 # 手續費（買賣各一次）
EXIT_TAX = 0.003                    # 證交稅（賣出）
EXIT_SLIP = 0.001                   # 每邊滑價 0.1%（另有 0.2% 壓力測試，只在說明標示）
EXIT_SPEC = "phase-b-exit-v1"


def _net_return(entry, exit_price):
    """成本後淨報酬：買進含手續費+滑價、賣出再扣手續費+證交稅+滑價（乘除、非直接減）。"""
    return exit_price * (1 - EXIT_FEE - EXIT_TAX - EXIT_SLIP) / (entry * (1 + EXIT_FEE + EXIT_SLIP)) - 1


def exit_analysis(events, price_hist, div_hist, holdings=EXIT_HOLDINGS):
    """比較不同出場方式的「成本後」淨報酬（並行報表、不改 forward=20，Top5 引擎不動）。

    進場價＝訊號次日還原收盤（保守、不前視）；比較固定持有 5/10/20/40 日 ＋「收盤自波段高點
    回落 10%」停利。淨超額＝該股成本後淨報酬 − 同一進場日、同持有期的全市場毛報酬平均（基準不扣
    成本，因為它只是評估基準、不是實際買進）。所有出場用同一批「進場後 40 日路徑完整」的事件，
    確保各持有期公平可比。回 dict（給 signal_exits.json）。"""
    import build_data as bd
    # 每檔還原收盤序列（list 與 price_rows 排序對齊）＋日期→序列 index
    adj_by_sid = {}
    for sid, by in price_hist.items():
        pr = sorted(hs.to_price_rows(by), key=lambda r: r["date"])
        if not pr:
            continue
        ev = hs.to_div_events(div_hist.get(sid))
        ac = [r["close"] for r in bd.back_adjust_rows(pr, ev)]
        adj_by_sid[sid] = ([r["date"] for r in pr], ac)

    max_h = max(holdings + [EXIT_TRAIL_CAP])
    # 全市場基準：每個「進場日 → 持有 H 日」的毛報酬平均（母體＝所有有完整路徑的個股，非只有事件股）
    bench = {h: {} for h in holdings}
    for sid, (ds, ac) in adj_by_sid.items():
        n = len(ac)
        for j in range(n):
            base = ac[j]
            if not base or base <= 0:
                continue
            for h in holdings:
                k = j + h
                if k < n and ac[k]:
                    bench[h].setdefault(ds[j], []).append(ac[k] / base - 1)
    bench_mean = {h: {d: sum(v) / len(v) for d, v in m.items() if v} for h, m in bench.items()}

    # 各出場策略累積器
    strat_keys = [f"h{h}" for h in holdings] + ["trail10"]
    acc = {k: {"net": [], "exc": [], "hold": [], "mae": []} for k in strat_keys}
    n_events = 0
    entry_dates = set()

    for e in events:
        sid, i = e["sid"], e.get("i")
        rec = adj_by_sid.get(sid)
        if rec is None or i is None:
            continue
        ds, ac = rec
        entry_i = i + 1                              # 次日進場
        if entry_i + max_h >= len(ac):               # 需 40 日完整路徑，各持有期才公平可比
            continue
        entry = ac[entry_i]
        if not entry or entry <= 0:
            continue
        entry_date = ds[entry_i]
        n_events += 1
        entry_dates.add(entry_date)

        for h in holdings:
            exit_price = ac[entry_i + h]
            net = _net_return(entry, exit_price)
            b = bench_mean[h].get(entry_date)
            path = [ac[entry_i + d] for d in range(0, h + 1) if ac[entry_i + d]]
            mae = min(p / entry - 1 for p in path) if path else 0.0
            a = acc[f"h{h}"]
            a["net"].append(net)
            if b is not None:
                a["exc"].append(net - b)
            a["hold"].append(h)
            a["mae"].append(mae)

        # 收盤回落停利：從進場走到高點回落 10%，或到 40 日上限
        run_max = entry
        exit_i = entry_i + EXIT_TRAIL_CAP
        for d in range(1, EXIT_TRAIL_CAP + 1):
            c = ac[entry_i + d]
            if not c:
                continue
            if c > run_max:
                run_max = c
            if c <= run_max * (1 - EXIT_TRAIL_DROP):
                exit_i = entry_i + d
                break
        hold = exit_i - entry_i
        net = _net_return(entry, ac[exit_i])
        # trail 的基準用最接近的固定持有期（就近取 20 日毛報酬平均，僅供粗略對照）
        b = bench_mean.get(20, {}).get(entry_date)
        path = [ac[entry_i + d] for d in range(0, hold + 1) if ac[entry_i + d]]
        mae = min(p / entry - 1 for p in path) if path else 0.0
        t = acc["trail10"]
        t["net"].append(net)
        if b is not None:
            t["exc"].append(net - b)
        t["hold"].append(hold)
        t["mae"].append(mae)

    labels = {**{f"h{h}": f"持有{h}日" for h in holdings}, "trail10": "回落10%停利"}
    strategies = [_exit_row(k, labels[k], acc[k]) for k in strat_keys]
    return {
        "spec_version": EXIT_SPEC, "control": "h20", "n_events": n_events,
        "n_entry_dates": len(entry_dates),
        "cost": {"fee": EXIT_FEE, "tax": EXIT_TAX, "slippage_per_side": EXIT_SLIP,
                 "round_trip_pct": round((EXIT_FEE * 2 + EXIT_TAX + EXIT_SLIP * 2) * 100, 3)},
        "strategies": strategies,
    }


def _exit_row(key, label, a):
    """單一出場策略的成本後統計。"""
    net = a["net"]
    n = len(net)
    if n == 0:
        return {"key": key, "label": label, "samples": 0}
    exc = a["exc"]
    wins = [r for r in net if r > 0]
    losses = [-r for r in net if r < 0]
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    wr = len(wins) / n
    return {
        "key": key, "label": label, "samples": n,
        "avg_net_return": round(sum(net) / n * 100, 2),
        "avg_net_excess": round(sum(exc) / len(exc) * 100, 2) if exc else None,
        "net_win_rate": round(wr, 4),
        "avg_win": round(avg_win * 100, 2),
        "avg_loss": round(avg_loss * 100, 2),
        "payoff_ratio": round(avg_win / avg_loss, 2) if avg_loss > 0 else None,
        "expectancy": round((wr * avg_win - (1 - wr) * avg_loss) * 100, 2),
        "avg_mae": round(sum(a["mae"]) / len(a["mae"]) * 100, 2),
        "avg_holding_days": round(sum(a["hold"]) / len(a["hold"]), 1),
    }


def _latest_date(price_hist):
    """歷史裡最新的交易日（時間窗的錨點；ISO 字串大小比較即日期先後）。"""
    latest = ""
    for by in price_hist.values():
        if by:
            m = max(by)
            if m > latest:
                latest = m
    return latest


def windowed_stats(events, by_date, as_of_iso):
    """把「一次收集好的事件」切成多個時間窗各算一次統計 → 勝率榜的多視窗資料。

    刻意設計：collect_events（逐檔重算指標，很重）只跑一次，這裡各窗只是「按日期篩事件」
    再套 events_to_stats/stats_to_weights，幾乎零額外成本。每個窗的基準（同日全市場平均）
    也只用「該窗內」的日期，確保近3月的超額是跟近3月的大盤比，不被歷史平均污染。

    回 signals-major：{sigkey: {label, "3m":{...}, "6m":{...}, "1y":{...}, "all":{...}}}，
    方便前端「一列一訊號、橫向多窗」直接畫表。
    """
    if not as_of_iso:
        return {}
    as_of = dt.date.fromisoformat(as_of_iso)
    per_window = {}
    for key, _label, days in WINDOWS:
        if days is None:
            evs, bd = events, by_date
        else:
            cutoff = (as_of - dt.timedelta(days=days)).isoformat()
            evs = [e for e in events if e["date"] >= cutoff]
            bd = {d: v for d, v in by_date.items() if d >= cutoff}
        per_window[key] = stats_to_weights(events_to_stats(evs, bd))

    signals = {}
    for k in SIGNALS:
        row = {"label": SIGNAL_LABELS.get(k, k)}
        for key, _label, _days in WINDOWS:
            s = per_window[key][k]
            row[key] = {"avg_excess": s["avg_excess"], "excess_win_rate": s["excess_win_rate"],
                        "samples": s["samples"], "validated": s["validated"], "weight": s["weight"]}
        signals[k] = row
    return signals


def _load(path):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def ensure_weights(price_hist, chip_hist, div_hist, universe, today=None, force=False):
    """回傳最新的權重表。檔案不存在、或距上次重算 ≥ RECOMPUTE_DAYS 天（約每週）才重跑回測，
    否則沿用既有 signal_weights.json（省成本）。回傳 dict 並確保 signal_weights.json 已寫入。"""
    today = today or dt.date.today()
    existing = _load(WEIGHTS_PATH)
    need = force or not existing
    if not need and existing.get("date"):
        try:
            age = (today - dt.date.fromisoformat(existing["date"])).days
            need = age >= RECOMPUTE_DAYS
        except ValueError:
            need = True
    if not need:
        return existing

    print("🧮 回測訊號權重（約每週重算一次）…")
    # 回測改吃「長歷史」：price.json 只有 110 天，扣掉指標暖身 65 天與 20 天持有期後
    # 只剩約 25 個可回測交易日，而且全落在同一段市況——樣本不足以判斷訊號好壞。
    # 長歷史每週在這裡從 price.json 補上新日期（price 視窗 110 天 ≫ 一週，不會漏接）。
    bt_hist = hs.load(BT_PRICE_PATH) or hs.bt_empty()
    added = hs.bt_merge_from_price(bt_hist, price_hist)
    if added:
        hs.save(BT_PRICE_PATH, bt_hist)
        print(f"   長歷史併入 {added} 個新交易日 → 共 {len(bt_hist['dates'])} 天、{len(bt_hist['stocks'])} 檔")
    long_price = hs.bt_to_price_hist(bt_hist)
    if len(bt_hist.get("dates") or []) > len(next(iter(price_hist.values()), {})):
        print(f"   使用長歷史回測（{len(bt_hist['dates'])} 個交易日）")
        price_for_bt = long_price
    else:
        print("   長歷史尚未建立，暫用 110 天滾動歷史回測（樣本偏少）")
        price_for_bt = price_hist
    # Phase B：先建橫斷面 PIT cache（相對強弱 RS ＋ 產業輪動），collect_events 逐日查詢併入訊號。
    print("   建立橫斷面快取（相對強弱＋產業輪動）…")
    xsect = build_xsect_cache(price_for_bt, div_hist, universe)
    print(f"   橫斷面快取：{len(xsect)} 個交易日有 RS/產業資料")
    # 事件只收集一次（逐檔重算指標的重活），再分別算「全歷史權重」與「多時間窗勝率榜」。
    events, by_date = collect_events(price_for_bt, chip_hist, div_hist, universe, xsect=xsect)
    weights = stats_to_weights(events_to_stats(events, by_date))
    out = {
        "date": today.isoformat(),
        "computed": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "forward_days": FORWARD,
        "min_sample": MIN_SAMPLE,
        "signals": weights,
    }
    # Phase A：樣本外驗證＋自適應候選權重（並行欄位，不動現行 weight/Top5）。純切片、幾乎零成本。
    oos, total_folds = attach_phase_a(out, events, by_date)
    # Phase C：防騙指標（成本後期望值/賺賠比/獲利因子/高勝率陷阱），併進每訊號 quality 欄位。
    quality = signal_quality(events)
    for k, q in quality.items():
        if k in out["signals"]:
            out["signals"][k]["quality"] = q
    out["phase_a"] = {
        "spec_version": PHASE_A_SPEC, "total_folds": total_folds,
        "config": {"train_days": OOS_TRAIN_DAYS, "embargo_days": OOS_EMBARGO_DAYS,
                   "test_days": OOS_TEST_DAYS, "step_days": OOS_STEP_DAYS,
                   "min_train_samples": OOS_MIN_TRAIN, "ewma_half_life_days": EWMA_HALF_LIFE,
                   "ewma_max_recent_share": EWMA_MAX_RECENT_SHARE, "shrink_k": SHRINK_K},
    }
    with open(WEIGHTS_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    robust = [v["label"] for v in weights.values() if (v.get("oos") or {}).get("status") == "robust"]
    print(f"   樣本外驗證：{total_folds} folds，穩健訊號 {len(robust)} 個"
          + (f"（{'、'.join(robust)}）" if robust else "（尚無訊號通過 OOS 穩健門檻）"))

    # 多時間窗勝率榜（近3月/近半年/近一年/歷史）——給網頁勝率榜切窗與看趨勢用
    as_of = _latest_date(price_for_bt)
    windows_signals = windowed_stats(events, by_date, as_of)
    if windows_signals:
        windows_out = {
            "date": today.isoformat(),
            "computed": out["computed"],
            "forward_days": FORWARD,
            "min_sample": MIN_SAMPLE,
            "as_of": as_of,
            "windows": [{"key": k, "label": lb} for k, lb, _ in WINDOWS],
            "signals": windows_signals,
        }
        with open(WINDOWS_PATH, "w", encoding="utf-8") as f:
            json.dump(windows_out, f, ensure_ascii=False, separators=(",", ":"))

    # 組合戰績（A＋B、A＋B＋C 同時成立）——給網頁「組合排行榜」＋熱力圖用
    combos, pairs = combo_stats(events, by_date)
    combos_out = {
        "date": today.isoformat(),
        "computed": out["computed"],
        "forward_days": FORWARD,
        "min_sample": COMBO_MIN_SAMPLE,
        "combos": combos,   # pairs+triples 依平均超額排序（排行榜）
        "pairs": pairs,     # 所有合格兩兩配對（熱力圖完整矩陣）
    }
    with open(COMBOS_PATH, "w", encoding="utf-8") as f:
        json.dump(combos_out, f, ensure_ascii=False, separators=(",", ":"))
    if combos:
        print(f"   組合戰績：{len(combos)} 組排行 + {len(pairs)} 個兩兩配對（最強 "
              f"{'＋'.join(combos[0]['labels'])} 超額 {combos[0]['avg_excess']}pp、"
              f"下界 {combos[0]['excess_lb']}pp、樣本 {combos[0]['samples']}）")

    # 市況分層回測（Andy 選：同一訊號在多頭/盤整/空頭效果差多少；point-in-time 判市況）
    regime = build_regime_series(price_for_bt, div_hist)
    regime_stats = regime_stratified_stats(events, by_date, regime)
    from collections import Counter as _C
    rc = _C(regime.values())
    regime_out = {"date": today.isoformat(), "computed": out["computed"], "forward_days": FORWARD,
                  "regime_days": {b: rc.get(b, 0) for b in ("green", "yellow", "red", "unknown")},
                  "signals": regime_stats}
    with open(REGIME_PATH, "w", encoding="utf-8") as f:
        json.dump(regime_out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"   市況分層：紅{rc.get('red',0)}/黃{rc.get('yellow',0)}/綠{rc.get('green',0)} 交易日")

    # 出場優化（並行成本後報表；不改 forward=20 基準）
    exits = exit_analysis(events, price_for_bt, div_hist)
    exits.update({"date": today.isoformat(), "computed": out["computed"], "forward_days": FORWARD})
    with open(EXITS_PATH, "w", encoding="utf-8") as f:
        json.dump(exits, f, ensure_ascii=False, separators=(",", ":"))
    best = max((s for s in exits["strategies"] if s.get("samples")),
               key=lambda s: (s.get("avg_net_excess") if s.get("avg_net_excess") is not None else -99), default=None)
    if best:
        print(f"   出場分析：{exits['n_events']} 筆事件、來回成本 {exits['cost']['round_trip_pct']}%，"
              f"淨超額最高＝{best['label']}（{best['avg_net_excess']}pp、勝率 {round(best['net_win_rate']*100)}%）")

    strong = max(weights.items(), key=lambda kv: (kv[1]["weight"], kv[1]["samples"]))
    print(f"   權重已更新，最強訊號：{strong[1]['label']}（權重 {strong[1]['weight']}、樣本 {strong[1]['samples']}）")
    return out


if __name__ == "__main__":
    # 手動重算（本機驗證用）：python pipeline/backtest_signals.py
    price = hs.load(os.path.join(HERE, "history", "price.json"))
    chip = hs.load(os.path.join(HERE, "history", "chip.json"))
    divs = hs.load(os.path.join(HERE, "history", "dividends.json"))
    with open(os.path.join(HERE, "universe.json"), encoding="utf-8") as f:
        uni = json.load(f)["stocks"]
    w = ensure_weights(price, chip, divs, uni, force=True)
    for k, v in w["signals"].items():
        print(f"  {v['label']:8s} 勝率 {v['win_rate']}  平均 {v['avg_ret']}%  樣本 {v['samples']}  權重 {v['weight']}")
