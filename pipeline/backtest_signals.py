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

sys.path.insert(0, os.path.dirname(__file__))
import history_store as hs  # noqa: E402

HERE = os.path.dirname(__file__)
WEIGHTS_PATH = os.path.join(HERE, "signal_weights.json")
WINDOWS_PATH = os.path.join(HERE, "signal_windows.json")
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

            fired = []
            for k, hit in signal_flags(ind).items():
                if not hit:
                    continue
                if k in last_fire and i - last_fire[k] < cooldown:
                    continue                          # 冷卻期內，同一波訊號不重複採計
                last_fire[k] = i
                fired.append(k)
            if fired:
                events.append({"date": di, "sid": sid, "ret": ret, "fired": fired})
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
    with open(WEIGHTS_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

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
