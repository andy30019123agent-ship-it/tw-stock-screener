#!/usr/bin/env python3
"""機會股引擎：把當日有訊號的股票依「訊號權重加總」排序，過濾後產出跨 repo 契約 JSON。

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

# 每天推薦幾檔。⚠️ 2026-07-25 從 5 改成 10（Andy 選 1️⃣，依 verify_top5_procedure.py 的實測）：
#   檔數  平均   中位   日勝率  sd    最大回撤  t(NW)
#    5   2.47  0.97  53.4% 11.80  −27.3  1.78   ← 舊設定
#   10   2.72  1.06  55.4%  9.00  −18.8  2.38   ← 現在
#   20   2.64  2.12  64.0%  6.35  −10.8  3.00
#
# 🔄 **2026-07-25 深夜改成 8（Andy 定案）**。他把目標講清楚了：不要每天下一堆單，要「最精簡、
# 勝率相對高、又賺得多」。照這個目標重量（現行 rs_pct_60 排序、339 天、扣成本、20 交易日）：
#   檔數  賺錢機率  贏大盤  平均絕對  中位絕對  超額 t
#    4     63.4%   56.9%   5.86    4.78    2.22
#    5     66.1%   58.1%   5.75    4.30    2.17
#    8     66.7%   62.5%   6.19    5.45    2.73   ← 現行
#   10     65.8%   62.8%   5.88    4.90    2.80
#   15     68.7%   61.7%   5.80    4.85    3.21
#   20     72.0%   63.4%   5.57    4.85    3.52
#
# ⚠️ **8 不是「量測得出來最好」的檔數，別把它當神奇數字**：持有期 20 天彼此重疊，
# 有效獨立批次只有 339/20 ≈ 17，勝率的標準誤約 **±12pp** → 4~20 檔的勝率差距全在誤差內。
# 唯一單調的訊號是「超額 t 值隨檔數上升」（2.17 → 3.52）＝檔數越多結論越可信。
# 所以選 8 的真正理由是：**在測不出差別的平原上，取 Andy 要的「精簡」那一端**，
# 而不是往下砍到 4~5 檔（那裡 t 值開始明顯掉，且單檔運氣成分變大：一次進場最慘 −44%）。
# 改檔數時要一起回來重算這張表，並更新 src/components/OutcomeShape.jsx 的 MEASURED。
# 可行性：score>0 的候選中位 26 檔、94.4% 的日子有 ≥5 檔，取 8 檔不會經常湊不滿。
TOP_N = 8
MIN_VOL_LOTS = 500        # 20 日均量門檻（張）
BIAS_FLAG_PCT = 15        # 20 日乖離 > 此值加「乖離大」風險旗標
FORWARD = bt.FORWARD      # 成績單評估的前瞻交易日數（跟回測一致）
# picks 留檔天數。⚠️ 2026-07-25 從 90 改成 3650（約 10 年）：這份 picks_history.json 是
# **系統實際推薦紀錄的唯一來源**，也是未來唯一能回答「這套選股真的有用嗎」的真實績效證據
# （回測是模擬、這個是實績）。90 天上限會讓超過三個月的紀錄被永久刪掉、**之後補不回來**。
# 一天一筆、每筆 5 檔，10 年也只有約 2500 筆，檔案大小不是問題。
HISTORY_MAX = 3650


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
            # 🔴 2026-07-25 修：這句原本不分情況都寫「僅符合門檻（強勢雙確認）」，但門檻沒套用時
            # （RS 資料掛掉、或過門檻的候選不足 20 檔）這檔股票**根本沒被強勢雙確認檢查過**——
            # 等於把「沒檢查」說成「檢查過了」。門檻是否套用會改變這句話的真假，必須分開寫。
            if gate_on:
                reasons = [f"僅符合門檻（{bt.SIGNAL_LABELS.get(GATE_SIGNAL, GATE_SIGNAL)}），"
                           "無加權訊號、按相對強弱排序"]
            else:
                why = {"rs_unavailable": "今天的強弱資料算不出來",
                       "pool_too_small": "過門檻的股票不足 20 檔"}.get(gate_reason, gate_reason)
                reasons = [f"⚠️ 今天沒套用強勢雙確認門檻（{why}）＝這檔未經強勢篩選，"
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
            "rs_pct_60": r.get("rs_pct_60"),      # 排序依據（全市場 60 日報酬百分位）
            "revenue_yoy": yoy,
            "earnings_date": r.get("earnings_date"),
            "risk_flags": risk,
        })

    # ⚠️ 2026-07-25 排序依據從 rs20 改成 rs_pct_60（Andy 選 4️⃣）。實測（verify_top5_procedure.py）：
    #   rs20 排序：+2.47pp／中位 0.97／t 1.78——但**跟隨機排序比 t 只有 0.28、0/20 seed 顯著**，
    #             故意選最弱 5 檔反而 t=2.29 更「顯著」→ 它沒有排序訊息，只是把 sd 從 3.7 放大到 11.8。
    #   rs_pct_60 排序：+3.09pp／中位 1.64／sd 11.45／t 2.09——每一項都更好。
    # 兩者的差別：rs20 是「個股 20 日報酬 − 加權指數」（受大盤短期波動影響），
    # rs_pct_60 是「個股 60 日報酬在全市場的百分位」（跨股票比較、不依賴指數，指數只有 40 天歷史）。
    # 缺 rs_pct_60 的用 -1 墊底（0 是「最弱」的合法百分位，不能拿來當缺值）。
    picks.sort(key=lambda p: (-p["score"], -(p["rs_pct_60"] if p["rs_pct_60"] is not None else -1)))
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
        # 留下「當時的完整脈絡」而不只有代號與收盤價：事後檢討時要能回答「那天為什麼推它、
        # 當時大盤如何、門檻有沒有套上」。這些欄位當天不存，日後永遠補不回來
        # （2026-07-25 加：原本只存 id/name/close/score）。
        entries.append({
            "date": opp["date"],
            "gate": opp.get("gate"),                       # 門檻是否套用、候選池多大
            "picks": [{"id": p["id"], "name": p["name"],
                       "close": p["close"], "score": p["score"],
                       "reasons": p.get("reasons"),        # 當時的加權訊號（權重會隨重算改變）
                       "rs20": p.get("rs20"),
                       "rs_pct_60": p.get("rs_pct_60"),
                       "risk_flags": p.get("risk_flags"),
                       "revenue_yoy": p.get("revenue_yoy")} for p in opp["picks"]],
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
    print(f"🎯 機會股引擎（取前 {TOP_N} 檔）…")
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
