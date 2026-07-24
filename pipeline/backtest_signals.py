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
SIGNALS = ENGINE_SIGNALS + DISPLAY_ONLY_SIGNALS

# 中文標籤（給 opportunities 的 reasons 與網頁展示共用）
SIGNAL_LABELS = {
    "signal_ma": "糾結轉強", "signal_breakout": "爆量突破",
    "sn_squeeze_breakout": "縮口帶量突破", "sn_lower_reversal": "破下軌翻紅",
    "sn_break_low_recover": "破底翻", "sn_immortal_guide": "仙人指路",
    "sn_volume_support": "大量撐",
    "foreign_buy": "外資連買", "trust_buy": "投信連買",
    "holder_rising": "千張大戶↑", "undervalued": "同業低估",
    "bull_aligned": "多頭排列", "fill_fast": "填息快",
}


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


def collect_events(price_hist, chip_hist, div_hist, universe,
                   forward=FORWARD, min_bars=MIN_BARS, cooldown=None):
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
            raw_fired, eligible_fired = [], []
            for k, hit in signal_flags(ind).items():
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
    # 事件只收集一次（逐檔重算指標的重活），再分別算「全歷史權重」與「多時間窗勝率榜」。
    events, by_date = collect_events(price_for_bt, chip_hist, div_hist, universe)
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
