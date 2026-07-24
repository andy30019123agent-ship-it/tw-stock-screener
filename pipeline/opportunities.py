#!/usr/bin/env python3
"""機會股 Top 5 引擎：把當日有訊號的股票依「訊號權重加總」排序，過濾後產出跨 repo 契約 JSON。

產出（皆由 run() 寫出）：
- public/data/opportunities.json ── 跨 repo 契約（欄位固定，下游 dashboard 晚報會 fetch），走 Pages。
- public/data/signal_weights.json ── 回測權重表（供網頁透明化展示），從 pipeline 版複製一份給前端。
- public/data/scoreboard.json    ── 機會股成績單（滿 20 交易日的舊 picks 實績）。
- pipeline/picks_history.json     ── 逐日 picks 留檔（持久化、給成績單回算，commit 回 repo）。
- pipeline/scoreboard.json        ── 成績單持久化副本。

過濾規則（規格元件 B）：
- 當日至少 1 個訊號才入選；分數 = 各成立訊號的回測權重加總。
- 近月營收 YoY < 0 → 剔除；抓不到 → 不過濾、標 risk_flag「營收資料缺」。
- 20 日均量 < 500 張 → 剔除（流動性）。
- 20 日乖離 > +15% → 不剔除，但加 risk_flag「乖離大」。
"""
import os
import sys
import json
import datetime as dt

sys.path.insert(0, os.path.dirname(__file__))
import history_store as hs        # noqa: E402
import backtest_signals as bt     # noqa: E402
import monthly_revenue as mr      # noqa: E402

HERE = os.path.dirname(__file__)
OUT_DIR = os.path.join(HERE, "..", "public", "data")
PICKS_HISTORY_PATH = os.path.join(HERE, "picks_history.json")
SCOREBOARD_PATH = os.path.join(HERE, "scoreboard.json")

TOP_N = 5
MIN_VOL_LOTS = 500        # 20 日均量門檻（張）
BIAS_FLAG_PCT = 15        # 20 日乖離 > 此值加「乖離大」風險旗標
FORWARD = bt.FORWARD      # 成績單評估的前瞻交易日數（跟回測一致）
HISTORY_MAX = 90          # picks 留檔最多天數


def build_opportunities(results, weights, revenue, data_date):
    """純函式：從已加值的 results 產出 opportunities dict（不碰 I/O，好單測）。"""
    sig = (weights or {}).get("signals", {})
    picks = []
    for r in results:
        flags = bt.signal_flags(r)
        # 只用「引擎訊號」計分／當理由——多頭排列、填息快只做戰績展示，不進 Top5（否則
        # 多頭排列太常見會亂洗排名）。展示型訊號的戰績在勝率榜/策略戰績表另外呈現。
        fired = [k for k, v in flags.items() if v and k in bt.ENGINE_SIGNALS]
        if not fired:
            continue
        if (r.get("avg_vol_lots", 0) or 0) < MIN_VOL_LOTS:   # 流動性
            continue

        risk = []
        rev = revenue.get(r["id"])
        yoy = rev["yoy"] if rev else None
        if yoy is None:
            risk.append("營收資料缺")
        elif yoy < 0:
            continue                                          # 營收年減 → 剔除

        close, ma20 = r.get("close"), r.get("ma20")
        if ma20 and close and (close - ma20) / ma20 * 100 > BIAS_FLAG_PCT:
            risk.append("乖離大")

        score = sum(int(sig.get(k, {}).get("weight", bt.DEFAULT_WEIGHT)) for k in fired)
        reasons = [bt.SIGNAL_LABELS[k] for k in fired if k in bt.SIGNAL_LABELS]
        picks.append({
            "id": r["id"],
            "name": r["name"],
            "score": score,
            "reasons": reasons,
            "close": close,
            "support_ma20": ma20,
            "recent_high20": r.get("recent_high20"),
            "rs20": r.get("rs20"),
            "revenue_yoy": yoy,
            "earnings_date": r.get("earnings_date"),
            "risk_flags": risk,
        })

    picks.sort(key=lambda p: (-p["score"], -(p["rs20"] if p["rs20"] is not None else -999)))
    return {"date": data_date, "picks": picks[:TOP_N]}


def trading_calendar(price_hist):
    """全市場所有出現過的交易日（排序）= 交易日曆，供成績單算『下 20 交易日』。"""
    dates = set()
    for d in price_hist.values():
        dates.update(d.keys())
    return sorted(dates)


def adjusted_close_map(price_hist, div_hist, sid):
    """某股 {交易日: 還原權息收盤}，成績單算報酬用（跟回測同一把尺）。"""
    import build_data as bd
    rows = hs.to_price_rows(price_hist.get(sid, {}))
    if not rows:
        return {}
    ev = hs.to_div_events(div_hist.get(sid))
    adj = bd.back_adjust_rows(sorted(rows, key=lambda r: r["date"]), ev)
    return {r["date"]: r["close"] for r in adj}


def update_picks_history(opp):
    """把今天的 picks 併入 picks_history.json（同日覆蓋、留最近 HISTORY_MAX 天）。回 entries list。"""
    hist = {}
    if os.path.exists(PICKS_HISTORY_PATH):
        try:
            with open(PICKS_HISTORY_PATH, encoding="utf-8") as f:
                hist = json.load(f)
        except Exception:
            hist = {}
    entries = [e for e in hist.get("entries", []) if e.get("date") != opp["date"]]
    if opp["date"]:
        entries.append({
            "date": opp["date"],
            "picks": [{"id": p["id"], "name": p["name"],
                       "close": p["close"], "score": p["score"]} for p in opp["picks"]],
        })
    entries.sort(key=lambda e: e["date"])
    entries = entries[-HISTORY_MAX:]
    with open(PICKS_HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump({"entries": entries}, f, ensure_ascii=False, separators=(",", ":"))
    return entries


def compute_scoreboard(entries, cal, adj_by_sid, forward=FORWARD):
    """純函式：對「已滿 forward 交易日」的舊 picks 算實績。回 {win_rate, avg_ret, samples, ...}。"""
    pos = {d: i for i, d in enumerate(cal)}
    wins = cnt = 0
    ret_sum = 0.0
    for e in entries:
        d = e["date"]
        di = pos.get(d)
        if di is None or di + forward >= len(cal):
            continue                                  # 尚未滿 forward 交易日
        d_future = cal[di + forward]
        for p in e["picks"]:
            adj = adj_by_sid.get(p["id"]) or {}
            base, fut = adj.get(d), adj.get(d_future)
            if not base or fut is None:
                continue
            ret = fut / base - 1
            cnt += 1
            ret_sum += ret
            if ret > 0:
                wins += 1
    return {
        "updated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "forward_days": forward,
        "samples": cnt,
        "win_rate": round(wins / cnt, 4) if cnt else None,
        "avg_ret": round(ret_sum / cnt * 100, 2) if cnt else None,
    }


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def run(results, price_hist, chip_hist, div_hist, universe, data_date, today=None):
    """機會股引擎主流程（build_data.main 尾段呼叫）。"""
    today = today or dt.date.today()
    print("🎯 機會股 Top 5 引擎…")
    weights = bt.ensure_weights(price_hist, chip_hist, div_hist, universe, today=today)
    revenue = mr.load_or_fetch(today)
    print(f"   月營收 YoY 覆蓋 {len(revenue)} 檔")

    opp = build_opportunities(results, weights, revenue, data_date)

    entries = update_picks_history(opp)
    cal = trading_calendar(price_hist)
    ids = {p["id"] for e in entries for p in e["picks"]}
    adj_by_sid = {sid: adjusted_close_map(price_hist, div_hist, sid) for sid in ids}
    scoreboard = compute_scoreboard(entries, cal, adj_by_sid)

    _write_json(os.path.join(OUT_DIR, "opportunities.json"), opp)
    _write_json(os.path.join(OUT_DIR, "signal_weights.json"), weights)
    _write_json(os.path.join(OUT_DIR, "scoreboard.json"), scoreboard)
    _write_json(SCOREBOARD_PATH, scoreboard)
    # 多時間窗勝率榜：由 ensure_weights 每週重算時寫 pipeline/signal_windows.json，
    # 這裡每天把它複製到 public/data 給前端（沒有就略過，跟其他區塊一樣不硬性依賴）。
    windows = bt._load(bt.WINDOWS_PATH)
    if windows:
        _write_json(os.path.join(OUT_DIR, "signal_windows.json"), windows)

    names = "、".join(f"{p['name']}({p['id']}) {p['score']}分" for p in opp["picks"]) or "（今日無符合標的）"
    print(f"   Top {len(opp['picks'])}：{names}")
    print(f"   成績單：樣本 {scoreboard['samples']}"
          + (f"、勝率 {scoreboard['win_rate']}、平均 {scoreboard['avg_ret']}%"
             if scoreboard["samples"] else "（尚未有滿 20 交易日的舊 picks）"))
    return opp
