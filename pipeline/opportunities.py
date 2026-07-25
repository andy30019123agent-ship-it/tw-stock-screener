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


GATE_SIGNAL = "rs_confirmed_60_120"   # 入場門檻訊號（強勢雙確認）
GATE_MIN_POOL = 20                   # 過門檻又有引擎訊號的候選 < 此數 → 退回不設門檻（保命）


def build_opportunities(results, weights, revenue, data_date):
    """純函式：從已加值的 results 產出 opportunities dict（不碰 I/O，好單測）。

    **強勢雙確認當「入場門檻」而非加分項（Andy 2026-07-25 選）**：
    全樣本實測顯示這兩類訊號性質不同——強勢雙確認範圍廣（21% 的股票）、邊際穩（去掉最極端
    2% 事件後平均超額仍為正、樣本外 6/6 折都合格）；縮口帶量突破那類範圍窄（4%）、有區辨力
    但邊際弱（去掉最高 1% 就轉負）。把「廣而穩」的當篩子、「窄而準」的當排序依據，比把兩者
    的權重硬加在一起合理：後者會讓 21% 的股票先白拿 4 分（最高權重），廣泛訊號淹掉區辨力。
    這也維持了「多頭排列因太常見而不進引擎」的既有邏輯一致性——強勢雙確認比它更常見。

    保命機制：若過門檻的候選太少（GATE_MIN_POOL），退回不設門檻並在輸出標記。橫斷面資料
    要長歷史才算得出來，抓取失敗時旗標會全 False——不能因此讓 Top5 整個空掉。
    """
    sig = (weights or {}).get("signals", {})

    def eligible(r):
        """有引擎訊號、且流動性達標。回 (fired, ok)。"""
        flags = bt.signal_flags(r)
        # 只用「引擎訊號」計分／當理由——多頭排列、填息快只做戰績展示，不進 Top5（否則
        # 多頭排列太常見會亂洗排名）。展示型訊號的戰績在勝率榜/策略戰績表另外呈現。
        fired = [k for k, v in flags.items() if v and k in bt.ENGINE_SIGNALS]
        return fired, bool(fired) and (r.get("avg_vol_lots", 0) or 0) >= MIN_VOL_LOTS

    # ⚠️ GATE_MIN_POOL 必須用「通過所有硬過濾之後」的候選數來判（2026-07-25 Codex 指出）：
    # 原本只看「有訊號＋流動性」，但下面還會剔除營收年減，20 檔可能被砍到不足 5 檔 → 保命門檻
    # 沒真的保住輸出。這裡先把營收條件也算進去再判。
    def passes_revenue(r):
        rev = revenue.get(r["id"])
        return rev is None or rev.get("yoy") is None or rev["yoy"] >= 0

    gated = [r for r in results if r.get(GATE_SIGNAL) and eligible(r)[1] and passes_revenue(r)]
    gate_on = len(gated) >= GATE_MIN_POOL
    pool = gated if gate_on else results
    # 說清楚「為什麼沒套門檻」——RS 資料掛掉時門檻會靜默失效，必須能分辨故障與候選不足
    gate_reason = ("applied" if gate_on
                   else "rs_unavailable" if not any(r.get("rs_pct_60") is not None for r in results)
                   else "pool_too_small")

    picks = []
    for r in pool:
        fired, ok = eligible(r)
        if not ok:
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

        # 權重缺 key（舊版/部分損壞/新增訊號但快取未重算）時回退 0，不是 1——沒有回測證據
        # 就不該給分（否則未驗證訊號會偷偷加分改變 Top5）。（Codex 2026-07-24 指出）
        score = sum(int(sig.get(k, {}).get("weight", 0) or 0) for k in fired)
        # 「推薦理由」只列**有權重**的訊號。權重改看成本後超額後（2026-07-25），破底翻／糾結轉強／
        # 大量撐／仙人指路／爆量突破的權重都是 0（扣掉成本後贏不過大盤）——把它們列成理由會讓
        # 使用者以為那是加分項，跟「權重依據」的語意衝突（Codex 2026-07-24 第 10 項）。
        # 一個都沒有時給明確說明，不要留空讓人猜。
        scored = [k for k in fired if (sig.get(k, {}).get("weight", 0) or 0) > 0]
        reasons = [bt.SIGNAL_LABELS[k] for k in scored if k in bt.SIGNAL_LABELS]
        if not reasons:
            reasons = [f"僅符合門檻（{bt.SIGNAL_LABELS.get(GATE_SIGNAL, GATE_SIGNAL)}），"
                       "無加權訊號、按相對強弱排序"]
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
    return {
        "date": data_date,
        "picks": picks[:TOP_N],
        # 前端/快報要能講清楚這批是「強勢股裡的技術面最佳」還是「全市場技術面最佳」
        "gate": {"signal": GATE_SIGNAL, "applied": gate_on, "pool": len(gated),
                 "reason": gate_reason, "min_pool": GATE_MIN_POOL,
                 "label": bt.SIGNAL_LABELS.get(GATE_SIGNAL, GATE_SIGNAL)},
    }


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


def run(results, price_hist, chip_hist, div_hist, universe, data_date, today=None, force_recompute=False):
    """機會股引擎主流程（build_data.main 尾段呼叫）。

    force_recompute：略過 ensure_weights 的「距上次重算 < RECOMPUTE_DAYS 天就沿用舊權重」快取閘門，
    強制重跑回測。改過回測計算邏輯、部署後線上數字卻還沒更新（要等最多一週）時，由
    workflow_dispatch 的 force_recompute 輸入一路傳到這裡（見 daily.yml）。
    """
    today = today or dt.date.today()
    print("🎯 機會股 Top 5 引擎…")
    weights = bt.ensure_weights(price_hist, chip_hist, div_hist, universe, today=today, force=force_recompute)
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
    combos = bt._load(bt.COMBOS_PATH)          # 組合戰績排行榜
    if combos:
        _write_json(os.path.join(OUT_DIR, "signal_combos.json"), combos)
    exits = bt._load(bt.EXITS_PATH)            # 出場優化分析
    if exits:
        _write_json(os.path.join(OUT_DIR, "signal_exits.json"), exits)
    regime = bt._load(bt.REGIME_PATH)         # 市況分層回測
    if regime:
        _write_json(os.path.join(OUT_DIR, "signal_regime.json"), regime)

    names = "、".join(f"{p['name']}({p['id']}) {p['score']}分" for p in opp["picks"]) or "（今日無符合標的）"
    print(f"   Top {len(opp['picks'])}：{names}")
    print(f"   成績單：樣本 {scoreboard['samples']}"
          + (f"、勝率 {scoreboard['win_rate']}、平均 {scoreboard['avg_ret']}%"
             if scoreboard["samples"] else "（尚未有滿 20 交易日的舊 picks）"))
    return opp
