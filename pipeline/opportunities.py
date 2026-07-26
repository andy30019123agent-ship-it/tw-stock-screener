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

# 🔄 2026-07-26：拿掉「每天固定推 N 檔」的購買組合語意（Andy 拍板：不用幫我配好組合、我自己會
# 挑買哪幾檔）。原本這裡有 40 行「TOP_N 該取多少」的量測紀錄（5→10→8 的實測表），連同 TOP_N
# 常數一起刪除——那整段是舊需求（固定榜單）的產物，新需求是「輸出全部合格候選＋分類，交給
# Andy 自己選」。舊量測數字仍留在 git 歷史（本檔 2026-07-25 之前的版本）可查。
PREVIEW_N = 10   # 前端預設展開顯示幾筆，純粹是畫面初始狀態，不是「建議買幾檔」；候選有幾檔就出幾檔。
MIN_VOL_LOTS = 500        # 20 日均量門檻（張）
BIAS_FLAG_PCT = 15        # 20 日乖離 > 此值加「乖離大」風險旗標
FORWARD = bt.FORWARD      # 成績單評估的前瞻交易日數（跟回測一致）

# 台股來回交易成本：手續費 0.1425%×2（買賣各一次）＋證交稅 0.3%（賣出）＋滑價 0.1%×2 ＝ 0.785%。
# 跟 backtest_signals.py 的 exit_analysis／_net_return（EXIT_FEE/EXIT_TAX/EXIT_SLIP，約 1052-1061 行）
# 同一把尺——改一邊要改兩邊，不要在這裡另外定義獨立的成本數字。
COST_PCT = bt.EXIT_FEE * 2 + bt.EXIT_TAX + bt.EXIT_SLIP * 2

# 候選情報三分類的百分位門檻（Phase 1：只用單一已驗證特徵分類，不做合成分數，見計畫 Task 5）。
TIER_HIGH_PCT = 0.67   # win_flag／ret_flag 門檻
TIER_MID_PCT = 0.33    # return 分類另外要求 turnover 百分位不在後段
# 🔴 2026-07-26 Codex 複查：候選少於這個數就不分類。n=1 時「跟自己比是第一名」、n=2 時只要
# 數值不同較高者就自動 1.0——那不是「排前段」，是只有一兩個人。百分位要有意義，池子得夠大。
# 10 是保守取值：三分位切點在 n=10 時每層約 3~4 檔，勉強能講「相對前段」。
MIN_TIER_POOL = 10
# picks 留檔天數。⚠️ 2026-07-25 從 90 改成 3650（約 10 年）：這份 picks_history.json 是
# **系統實際推薦紀錄的唯一來源**，也是未來唯一能回答「這套選股真的有用嗎」的真實績效證據
# （回測是模擬、這個是實績）。90 天上限會讓超過三個月的紀錄被永久刪掉、**之後補不回來**。
# 一天一筆、每筆 5 檔，10 年也只有約 2500 筆，檔案大小不是問題。
HISTORY_MAX = 3650


GATE_SIGNAL = "rs_confirmed_60_120"   # 入場門檻訊號（強勢雙確認）
GATE_MIN_POOL = 20                   # 過門檻又有引擎訊號的候選 < 此數 → 退回不設門檻（保命）


def _percentile_ranks(values):
    """把一組數值換算成組內百分位（0~1，同名次取平均、缺值視為最低墊底）。

    用於 feat_pct：算的是「當日候選池內」的相對位置，不是全市場排名。
    回傳與輸入等長、對齊原始順序的 list。

    🔴 2026-07-26 Codex 複查修正兩個會「無中生有」的行為：
    ① **只有一筆候選時原本回 1.0**——「跟自己比是第一名」是套套邏輯，不是資訊。那會讓當天
       唯一那檔股票的四個特徵全部拿到滿分、直接被標成「雙優」（實測重現過）。改回 None。
    ② **缺值（None）原本會被當成最低值參與排名、拿到 0.0**——0.0 是「墊底」這個合法的判斷，
       但我們其實不知道它的位置。缺值就該是缺值，改回 None，讓分類端明確地「永不達標」。
    """
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [None]                      # ①：沒有比較對象＝算不出相對位置，不是滿分
    safe = [v if v is not None else float("-inf") for v in values]
    order = sorted(range(n), key=lambda i: safe[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and safe[order[j + 1]] == safe[order[i]]:
            j += 1
        pct = (i + j) / 2 / (n - 1)          # 並列取平均名次
        for k in range(i, j + 1):
            ranks[order[k]] = pct
        i = j + 1
    # ②：缺值不給百分位（上面用 -inf 只是為了排序時有個確定位置，不代表它真的最低）
    return [None if v is None else r for v, r in zip(values, ranks)]


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
    feat_raw = []   # 跟 picks 對齊的原始特徵值；要看到候選池全體才能算百分位，迴圈結束後統一算
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
        recent_high20 = r.get("recent_high20")
        picks.append({
            "id": r["id"],
            "name": r["name"],
            "score": score,
            "reasons": reasons,
            "close": close,
            "support_ma20": ma20,
            "recent_high20": recent_high20,
            "rs20": r.get("rs20"),
            "rs_pct_60": r.get("rs_pct_60"),      # 排序依據（全市場 60 日報酬百分位）
            "revenue_yoy": yoy,
            "earnings_date": r.get("earnings_date"),
            "risk_flags": risk,
        })
        # turnover 不可用 avg_money_e：bt_to_price_hist 把回測母體的成交金額補 0（history_store.py:214），
        # avg_money_e 在這個資料源裡恆為 0，只能用均量×收盤價自己算。
        feat_raw.append({
            "turnover": (r.get("avg_vol_lots") or 0) * (close or 0),
            "bias20_pct": r.get("bias20_pct"),
            "high20_gap": ((recent_high20 - close) / close * 100
                           if recent_high20 and close else None),
            "rs_pct_60": r.get("rs_pct_60"),
        })

    # 候選情報三分類（Phase 1：只用單一已驗證特徵，不做合成分數，見計畫 Task 5）。
    # feat_pct 是「當日候選池內」的百分位，不是全市場排名——候選池每天大小不同，同一檔股票
    # 今天跟明天的 feat_pct 不能直接比較，只能比「跟今天其他候選比起來如何」。
    for key in ("turnover", "bias20_pct", "high20_gap", "rs_pct_60"):
        ranks = _percentile_ranks([f[key] for f in feat_raw])
        for p, pct in zip(picks, ranks):
            p.setdefault("feat_pct", {})[key] = pct
    # 🔴 2026-07-26 Codex 複查：候選池太小時，「百分位」這個概念本身就沒有意義——n=2 時只要
    # 兩檔數值不同，較高的那檔就自動拿到 1.0 被包裝成「排前段」。這不是排前段，是只有兩個人。
    # 候選不足 MIN_TIER_POOL 時一律不分類，並在輸出標明原因，讓前端能講「今天候選太少不分類」
    # 而不是硬給一個看起來有依據的標籤。
    tier_on = len(picks) >= MIN_TIER_POOL

    def _ge(v, thresh):
        """缺值永不達標——None 代表「不知道它在哪個位置」，不是「位置很高」。"""
        return v is not None and v >= thresh

    for p in picks:
        fp = p["feat_pct"]
        if not tier_on:
            p["tier"] = None
            continue
        win_flag = _ge(fp["turnover"], TIER_HIGH_PCT)
        ret_flag = _ge(fp["bias20_pct"], TIER_HIGH_PCT)
        if win_flag and ret_flag:
            p["tier"] = "both"
        elif win_flag:
            p["tier"] = "win"
        elif ret_flag and _ge(fp["turnover"], TIER_MID_PCT):
            p["tier"] = "return"
        else:
            p["tier"] = None

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
        "picks": picks,             # 2026-07-26 起不截斷：全部合格候選都輸出，買哪幾檔由 Andy 自己決定
        "pool_n": len(picks),        # 當日候選池大小（給前端顯示「共 N 檔」）
        "preview_n": PREVIEW_N,      # 前端預設展開幾筆，不是建議買幾檔
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


def adjusted_open_map(price_hist, div_hist, sid):
    """某股 {交易日: 還原權息開盤}，成績單算「隔日開盤進場」用（跟 adjusted_close_map／
    回測 collect_events 同一把尺）。"""
    import build_data as bd
    rows = hs.to_price_rows(price_hist.get(sid, {}))
    if not rows:
        return {}
    ev = hs.to_div_events(div_hist.get(sid))
    adj = bd.back_adjust_rows(sorted(rows, key=lambda r: r["date"]), ev)
    return {r["date"]: r["open"] for r in adj}


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
        # 2026-07-26 起 opp["picks"] 本身已是「全部合格候選」（不再截斷），這裡照樣全存，
        # 並多存 feat_pct／tier——這份歷史是未來唯一能回答「這套選股真的有用嗎」的實績證據，
        # 分類結果當天不存，日後補不回來。
        entries.append({
            "date": opp["date"],
            "gate": opp.get("gate"),                       # 門檻是否套用、候選池多大
            "picks": [{"id": p["id"], "name": p["name"],
                       "close": p["close"], "score": p["score"],
                       "reasons": p.get("reasons"),        # 當時的加權訊號（權重會隨重算改變）
                       "rs20": p.get("rs20"),
                       "rs_pct_60": p.get("rs_pct_60"),
                       "risk_flags": p.get("risk_flags"),
                       "revenue_yoy": p.get("revenue_yoy"),
                       "feat_pct": p.get("feat_pct"),
                       "tier": p.get("tier")} for p in opp["picks"]],
        })
    entries.sort(key=lambda e: e["date"])
    entries = entries[-HISTORY_MAX:]
    with open(PICKS_HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump({"entries": entries}, f, ensure_ascii=False, separators=(",", ":"))
    return entries


def compute_scoreboard(entries, cal, adj_close_by_sid, adj_open_by_sid, forward=FORWARD, cost=None):
    """純函式：對「已滿 forward 交易日」的舊 picks 算實績。回 {win_rate, avg_ret, samples, cost_pct, ...}。

    口徑（2026-07-26 起，跟 backtest_signals.collect_events／exit_analysis 同一把尺）：
    - 進場價＝pick 日**隔一個交易日**的還原開盤——管線 18:17（收盤後）才發榜，Andy 最快隔天
      開盤才買得到，用 pick 當日收盤當進場價等於偷看未來。
    - 出場價＝pick 日 + forward 個交易日的還原收盤（跟原本一致，持有期仍是 forward 天）。
    - 淨報酬＝毛報酬 − 來回成本（COST_PCT，預設 0.785%）；勝率＝淨報酬 > 0 的比例。
      全站「勝率」統一這把尺，不能有的地方看毛報酬、有的地方看淨報酬（會變成兩個不同定義的
      「勝率」互相打架，誤導 Andy）。
    找不到隔日開盤（例如當天停牌、資料缺）的樣本直接跳過，**不可用收盤價頂替**。
    """
    cost = COST_PCT if cost is None else cost
    pos = {d: i for i, d in enumerate(cal)}
    wins = cnt = 0
    ret_sum = 0.0
    for e in entries:
        d = e["date"]
        di = pos.get(d)
        if di is None or di + forward >= len(cal) or di + 1 >= len(cal):
            continue                                  # 尚未滿 forward 交易日，或連隔一日都排不出來
        d_entry = cal[di + 1]
        d_exit = cal[di + forward]
        for p in e["picks"]:
            base = (adj_open_by_sid.get(p["id"]) or {}).get(d_entry)
            fut = (adj_close_by_sid.get(p["id"]) or {}).get(d_exit)
            if not base or fut is None:
                continue                              # 隔日開盤／出場收盤缺值 → 跳過，不拿收盤頂替
            ret = fut / base - 1 - cost
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
        "cost_pct": round(cost * 100, 3),
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
    print("🎯 機會股引擎（輸出全部合格候選，不截斷成固定檔數）…")
    weights = bt.ensure_weights(price_hist, chip_hist, div_hist, universe, today=today, force=force_recompute)
    revenue = mr.load_or_fetch(today)
    print(f"   月營收 YoY 覆蓋 {len(revenue)} 檔")

    opp = build_opportunities(results, weights, revenue, data_date)

    entries = update_picks_history(opp)
    cal = trading_calendar(price_hist)
    ids = {p["id"] for e in entries for p in e["picks"]}
    adj_close_by_sid = {sid: adjusted_close_map(price_hist, div_hist, sid) for sid in ids}
    adj_open_by_sid = {sid: adjusted_open_map(price_hist, div_hist, sid) for sid in ids}
    scoreboard = compute_scoreboard(entries, cal, adj_close_by_sid, adj_open_by_sid)

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
    tiers = bt._load(bt.TIER_STATS_PATH)      # 條件層級歷史分佈（候選情報用，不給個股精確勝率）
    if tiers:
        _write_json(os.path.join(OUT_DIR, "tier_stats.json"), tiers)

    names = "、".join(f"{p['name']}({p['id']}) {p['score']}分" for p in opp["picks"][:PREVIEW_N]) or "（今日無符合標的）"
    more = f"…等共 {opp['pool_n']} 檔" if opp["pool_n"] > PREVIEW_N else ""
    print(f"   候選 {opp['pool_n']} 檔：{names}{more}")
    print(f"   成績單：樣本 {scoreboard['samples']}"
          + (f"、勝率 {scoreboard['win_rate']}、平均 {scoreboard['avg_ret']}%"
             if scoreboard["samples"] else "（尚未有滿 20 交易日的舊 picks）"))
    return opp
