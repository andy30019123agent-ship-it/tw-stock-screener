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

FORWARD = 20        # 下 N 交易日報酬
MIN_SAMPLE = 30     # 低於此樣本數用預設權重
DEFAULT_WEIGHT = 1
MIN_BARS = 65       # compute_indicators 至少要 65 根 K 線
RECOMPUTE_DAYS = 6  # 距上次重算 ≥ 此天數才重算（約每週）
BACKTEST_MIN_VOL = 300  # 只回測有一定量能的股票，避免殭屍股雜訊

# 回測涵蓋的訊號（與 notify_tg.score()/reasons() 那批對齊）
SIGNALS = [
    "signal_ma", "signal_breakout",
    "sn_squeeze_breakout", "sn_lower_reversal", "sn_break_low_recover",
    "sn_immortal_guide", "sn_volume_support",
    "foreign_buy", "trust_buy", "holder_rising", "undervalued",
]

# 中文標籤（給 opportunities 的 reasons 與網頁展示共用）
SIGNAL_LABELS = {
    "signal_ma": "糾結轉強", "signal_breakout": "爆量突破",
    "sn_squeeze_breakout": "縮口帶量突破", "sn_lower_reversal": "破下軌翻紅",
    "sn_break_low_recover": "破底翻", "sn_immortal_guide": "仙人指路",
    "sn_volume_support": "大量撐",
    "foreign_buy": "外資連買", "trust_buy": "投信連買",
    "holder_rising": "千張大戶↑", "undervalued": "同業低估",
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
    }


def stats_to_weights(stats, min_sample=MIN_SAMPLE, default=DEFAULT_WEIGHT):
    """把每訊號的 {wins, count, ret_sum} 統計換成勝率/平均報酬/權重。純函式（好手算對照）。"""
    out = {}
    for k in SIGNALS:
        st = stats.get(k, {"wins": 0, "count": 0, "ret_sum": 0.0})
        c = st["count"]
        wr = (st["wins"] / c) if c else None
        if c >= min_sample:
            weight = max(0, round((wr - 0.5) * 20))
        else:
            weight = default
        out[k] = {
            "label": SIGNAL_LABELS.get(k, k),
            "win_rate": round(wr, 4) if wr is not None else None,
            "avg_ret": round(st["ret_sum"] / c * 100, 2) if c else None,  # 平均報酬（%）
            "samples": c,
            "weight": weight,
        }
    return out


def run_backtest(price_hist, chip_hist, div_hist, universe,
                 forward=FORWARD, min_bars=MIN_BARS):
    """對全市場逐檔、逐歷史交易日評估訊號並記錄下 forward 交易日的報酬（還原價）。
    回傳 stats_to_weights 的輸出。"""
    import build_data as bd  # 延遲載入避免與 build_data 的循環匯入
    stats = {k: {"wins": 0, "count": 0, "ret_sum": 0.0} for k in SIGNALS}
    for stock in universe:
        sid = stock["id"]
        pr = hs.to_price_rows(price_hist.get(sid, {}))
        if len(pr) < min_bars + forward + 1:
            continue
        pr = sorted(pr, key=lambda r: r["date"])
        cr = hs.to_chip_rows(chip_hist.get(sid, {}))
        ev = hs.to_div_events(div_hist.get(sid))

        # 先算「最新一根」的完整指標，順便當量能過濾（殭屍股跳過）
        full = bd.compute_indicators(pr, cr, ev, None)
        if full is None or full.get("avg_vol_lots", 0) < BACKTEST_MIN_VOL:
            continue

        # 還原權息後的收盤序列（跟 pr 同順序），用來算前瞻報酬
        adj_close = [r["close"] for r in bd.back_adjust_rows(pr, ev)]

        for i in range(min_bars - 1, len(pr) - forward):
            di = pr[i]["date"]
            slice_cr = [c for c in cr if c["date"] <= di]
            ind = bd.compute_indicators(pr[:i + 1], slice_cr, ev, None)
            if ind is None:
                continue
            flags = signal_flags(ind)
            if not any(flags.values()):
                continue
            base = adj_close[i]
            if not base:
                continue
            ret = adj_close[i + forward] / base - 1
            for k, fired in flags.items():
                if fired:
                    s = stats[k]
                    s["count"] += 1
                    s["ret_sum"] += ret
                    if ret > 0:
                        s["wins"] += 1
    return stats_to_weights(stats)


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
    weights = run_backtest(price_hist, chip_hist, div_hist, universe)
    out = {
        "date": today.isoformat(),
        "computed": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "forward_days": FORWARD,
        "min_sample": MIN_SAMPLE,
        "signals": weights,
    }
    with open(WEIGHTS_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
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
