#!/usr/bin/env python3
"""盤後選股快報 → Telegram。

由 GitHub Actions 在 build_data.py 之後呼叫：
- 只在「出現新的交易日資料」時推一次（用 notify_state.json 記錄上次推播的資料日期）。
  → 週末/假日沒有新資料 = 不推；排程跨午夜延遲也只推一次、不誤殺。
- 名單**直接讀 opportunities.json**（網站「今日候選」那份，2026-07-26 起不截斷成固定檔數），
  把中了哪些訊號 / 價位 / 風險寫成人看得懂的訊息。這支檔案不做任何排名判斷——
  快報與網站必須說同一套話（2026-07-25 移除了自有的退路排序）。
  名單產不出來就照實說「沒產出」，不可講成「今天沒機會」。
- token 由環境變數 TG_BOT_TOKEN 帶入（GitHub Secret），群組 id 預設叔叔名牌TG。

2026-07-26（Andy 裁示「不用幫我配好購買組合，我自己會挑」）：快報從「①②③…固定檔數編號清單」
改成分類摘要，不再有任何暗示購買順序或組合的字樣——候選現在有上百檔，全列不可能、硬選幾檔
又會被讀成「這幾檔就是建議買的」，改成分類摘要＋「共 N 檔，列前 M 檔」的措辭。
2026-11-13 分類簡化：原本三分類只有「成交金額高」站得住，改成只有一個分類「相對優勢」
（成交金額在當日候選池前 1/3）＋「乖離排前段」純描述標籤；主訊息改講「同一天互相比」的差距
（tier_stats.json 的 paired.cat_edge_vs_rest），單檔賺錢機率照實放旁邊。

本機測試：
  python pipeline/notify_tg.py --dry-run          # 只印訊息不發、不動 state
  python pipeline/notify_tg.py --force            # 忽略 state 直接發（驗證用）
"""
import argparse
import json
import math
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
from opportunities import normalize_tier, TIER_EDGE   # noqa: E402  分類相容與線上同一支

CHAT_ID = os.environ.get("TG_CHAT_ID", "-5127072553")  # 群組「叔叔名牌TG」
SITE = "https://andy30019123agent-ship-it.github.io/tw-stock-screener/"
# 網站首頁「今日候選」的產出，由 build_data → opportunities.run() 寫出。
OPP_PATH = os.path.join(os.path.dirname(__file__), "..", "public", "data", "opportunities.json")


def load_opportunity_picks(dd):
    """讀網站的「今日候選」清單（依網站順序，含 tier 分類）。

    為什麼要讀它：快報原本自己有一套手寫 3/2/1 分的排名，網站候選卻是用回測權重排的，
    同一天兩邊可能推薦完全不同的股票——使用者看到的是兩套互相矛盾的建議。以網站那份為準，
    快報就只負責「把同一份結論寫成人看得懂的訊息」。

    回 (picks, reason, gate)：
      ([{"id": "2395", "tier": "edge", "bias_high": False}, ...], "ok", gate)   正常
      ([], "ok", gate)                               檔案正常但今天零檔 → **這是真實結論**
      (None, "missing", None)                        檔案讀不到／日期對不上 → **這是管線故障**
    tier／bias_high 一律經 opportunities.normalize_tier：舊檔（2026-11-13 以前）的三分類舊值
    也能讀，不 crash。gate＝opportunities.json 的 gate（門檻有沒有套用）。

    ⚠️ 2026-07-25 改（Andy 裁示「候選不足就不用硬要呈現」）：原本回不到就退回自有排序湊數，
    結果是①快報與網站說不同的話②score>=4 在權重改版後幾乎不可能達到，於是實際行為變成
    發出「今日沒有明顯符合標的，先觀望」——**把管線故障講成了市場結論**。
    當天網站也是空的（引擎掛了），而快報卻讓人以為「今天大盤沒機會」，這比不推更糟。
    """
    try:
        with open(OPP_PATH, encoding="utf-8") as f:
            opp = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None, "missing", None
    if dd and opp.get("date") and opp["date"] != dd:
        return None, "missing", None
    out = []
    for p in (opp.get("picks") or []):
        tier, bias_high = normalize_tier(p)
        out.append({"id": p["id"], "tier": tier, "bias_high": bias_high})
    return out, "ok", opp.get("gate")


def data_date(stocks):
    """全市場最後一根 K 線的日期 = 這份資料的交易日。"""
    dates = [s["ohlc"][-1]["t"] for s in stocks if s.get("ohlc")]
    return max(dates) if dates else None


# ── 排名相關的實測結論（2026-07-25，勿再在這支檔案裡手寫分數）─────────────────────────
# 快報的排名**完全來自 opportunities.json**（網站 Top N 那份）。這裡曾經有一套自己的
# score() 退路排序，已刪除，原因有三：
#   ① 手寫分數曾與回測結論相反——「破底翻」回測平均超額 −0.91pp、weight=0，手寫卻給 +2；
#      「外資/投信連買」回測 samples=0（沒有證據），手寫也給 +2。
#   ② 改吃回測權重後，成本後權重讓唯一正權重的引擎訊號只值 1 分，score>=4 幾乎不可能達到，
#      這條退路實際上是死的——而它「死掉的方式」是發出「今日沒有明顯符合標的，先觀望」，
#      把管線故障講成市場結論（2026-07-25 真的發生了）。
#   ③ Andy 裁示：候選不足就不用硬要呈現。名單產不出來就說產不出來。
#
# 順帶記下另一個被推翻的設計（verify_bias_penalty.py，375,659 筆）：原本對乖離（離月線幅度）
# 大的股票扣分以「抑制追高」，方向是**反的**——
#   乖離%   成本後超額   中位數   贏大盤   每單位風險
#   <0       −1.59pp    −3.67    33.5%    −0.119
#   6~12     −0.53pp    −2.54    38.5%    −0.039
#   15~20    +0.85pp    −1.84    43.5%    +0.050
#   ≥25      +2.36pp    −1.98    45.0%    +0.100
# 成本後超額隨乖離單調遞增，且①風險調整後也遞增②紅黃綠三市況都不逆轉。扣分已移除。
# **但沒有反過來加分**：中位數每組都是負的、≥25 組標準差 23.5 全場最高，加分沒有證據。
# 追高風險改用 runaway_flags 在網站上「提示」，不在排名裡動手腳。


def reasons(s):
    """為何注意：緊湊標籤，控制每行長度避免手機折行破版。"""
    r = []
    if s.get("signal_breakout"):
        r.append("爆量突破")
    for t in (s.get("sn_tags") or [])[:2]:   # 小詩形態最多帶 2 個標籤
        r.append(t)
    if s.get("signal_ma"):
        r.append("糾結轉強")
    elif s.get("bull_aligned") and s.get("diverging"):
        r.append("多頭發散")
    elif s.get("bull_aligned"):
        r.append("多頭排列")
    elif s.get("golden_cross_recent"):
        r.append("黃金交叉")
    elif s.get("squeeze_recent"):
        r.append("糾結待變")
    fs = s.get("foreign_streak", 0)
    if fs >= 3:
        r.append(f"外資連{fs}買")
    ts = s.get("trust_streak", 0)
    if ts >= 3:
        r.append(f"投信連{ts}買")
    if s.get("holder_rising"):
        r.append("千張↑")
    if s.get("undervalued"):
        r.append("同業低估")
    ed = s.get("earnings_date")
    if ed:
        r.append(f"📅{'/'.join(ed.split('-')[1:])}法說會")
    return r


def price_note(s):
    """支撐/壓力 + 前高，緊湊一行。ma20/recent_high20 由 build_data.py 算好、跟網頁共用同一份
    （原本這裡自己掃 ohlc，但全市場版 ohlc 已拆到 charts/<id>.json、screener.json 裡沒有，會掃空）。"""
    close, ma20 = s["close"], s.get("ma20")
    parts = []
    if ma20:
        parts.append(f"ma20 {ma20:.1f}{'撐' if close >= ma20 else '壓'}")
    hi = s.get("recent_high20")
    if hi and hi > close:
        parts.append(f"高 {hi:g}")
    return "　".join(parts)


def risk_warning(s, n_reasons):
    """只回「值得警示」的風險（緊湊）；無特別警示則回空字串。"""
    disp = s.get("bias20_pct")
    if disp is not None and disp >= 12:
        return f"乖離 {disp:.0f}% 偏大"
    if n_reasons <= 1:
        return "訊號單一待確認"
    vol = s.get("avg_vol_lots")
    if vol is not None and vol < 700:
        return "均量偏低"
    return ""


# 大盤市況文案沿用網站 MarketAdvice.jsx 同一套（src/components/MarketAdvice.jsx:11-15），
# 快報跟網站不要各講一套市況判斷。
MARKET_STATUS_LABEL = {
    "green": "偏強（多頭）", "yellow": "中性（盤整）",
    "red": "偏弱（空頭）", "severe_red": "明顯走弱（空頭）",
}

# 候選情報分類（2026-11-13 起只剩一類）：tier 值來自 opportunities.py（"edge"／None）。
EDGE_LABEL = "相對優勢候選"
EDGE_ICON = "🎯"
BIAS_TAG = "乖離排前段"   # 純描述標籤（當天候選池乖離前 1/3），不可包裝成加分

# 每個分類段落最多列幾檔：手機閱讀考量，候選現在有上百檔、不可能全列。5 檔足夠給「大概
# 長什麼樣子」的感覺，完整名單導去網站看。這是「畫面顯示筆數」不是「建議買幾檔」——
# 標題一律會明講「共 N 檔，這裡列前 M 檔」，不能讓 M 看起來像應該買 M 檔。
TIER_PREVIEW_N = 5

# 條件層級歷史分佈（與網站同一份 JSON）。快報的提醒句數字一律從這裡讀，不再寫死。
TIER_STATS_PATH = os.path.join(os.path.dirname(__file__), "..", "public", "data", "tier_stats.json")

# 固定提醒（2026-07-26 規格；2026-11-13 改成讀 JSON、主訊息改成同日配對差）：
# 候選是「情報」不是「配好的組合」。數字一律讀 tier_stats.json（候選池重播母體），不寫死；
# 讀不到或 stale 就只講不含數字的版本（與網站 src/lib/tierVerdict.js 同一套判斷）。
DISCLAIMER_BASE = "⚠️ 這不是購買組合。"
EV_NEAR_ZERO_PP = 0.5   # 期望值差的 CI 下限 >0 但 < 這個值 → 「略高，但接近量不出」（與網站同值）


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf")


def _ci(c):
    return c if isinstance(c, (list, tuple)) and len(c) == 2 and _num(c[0]) and _num(c[1]) else None


def load_tier_stats(path=None):
    try:
        with open(path or TIER_STATS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _usable_pair(tiers, key):
    """與網站 tierVerdict.usablePair 同規則：stale／缺欄位 → None。"""
    if not isinstance(tiers, dict) or tiers.get("stale"):
        return None
    p = (tiers.get("paired") or {}).get(key)
    if not isinstance(p, dict) or not _num(p.get("win_pp")) or not _ci(p.get("win_ci90")):
        return None
    return p


def _verdict(ci):
    ci = _ci(ci)
    if not ci:
        return None
    return "better" if ci[0] > 0 else "worse" if ci[1] < 0 else "nodiff"


def _r1(v):
    """|v| 四捨五入到 0.1，算式與網站 tierVerdict.js 的 r1 相同（floor(|x|×10+0.5)），兩邊才逐字一致。"""
    return f"{math.floor(abs(v) * 10 + 0.5) / 10:.1f}"


def _f1(v):
    return _r1(v)


def _n1(v):
    r = _r1(v)
    return ("−" if v < 0 and r != "0.0" else "+" if v > 0 and r != "0.0" else "") + r


def _rng(c):
    return f"{_n1(c[0])}～{_n1(c[1])}"


def stale_note(tiers):
    if isinstance(tiers, dict) and tiers.get("stale"):
        return f"（⚠️ 統計已過期，上次成功重算 {tiers.get('date') or '—'}）"
    return ""


def tier_disclaimer(tiers):
    """主訊息：相對優勢 vs 當日其餘候選的同日配對差＋相對優勢的單檔賺錢機率＋平均每筆差。
    幅度宣稱規則（與網站同）：CI 下限 >0 才講「多」，且一律附誤差範圍；下限 <0.5pp 用保守說法。"""
    if isinstance(tiers, dict) and tiers.get("stale"):
        return (DISCLAIMER_BASE + "相對優勢跟其他候選的比較" + stale_note(tiers)
                + "，今天先不引用數字，有分類也可能虧錢。")
    p = _usable_pair(tiers, "cat_edge_vs_rest")
    if not p:
        return DISCLAIMER_BASE + "相對優勢跟其他候選的歷史比較今天讀不到，有分類也可能虧錢。"
    v = _verdict(p["win_ci90"])
    rng = _rng(p["win_ci90"])
    if v == "better":
        head = f"同一天的候選裡，相對優勢這群比其他候選的賺錢機率多約 {_f1(p['win_pp'])} 個百分點（誤差範圍 {rng}）"
    elif v == "worse":
        head = f"同一天的候選裡，相對優勢這群比其他候選的賺錢機率少約 {_f1(p['win_pp'])} 個百分點（誤差範圍 {rng}）"
    else:
        head = (f"同一天的候選裡，相對優勢這群跟其他候選的賺錢機率量不出差別"
                f"（差 {'+' if p['win_pp'] >= 0 else '−'}{_f1(p['win_pp'])} 個百分點，誤差範圍 {rng}）")
    eci = _ci(p.get("ev_ci90"))
    ev = p.get("ev_pp")
    if eci and _num(ev):
        if eci[0] >= EV_NEAR_ZERO_PP:
            head += f"，平均每筆也多約 {_f1(ev)} 個百分點（誤差範圍 {_rng(eci)}）"
        elif eci[0] > 0:
            head += f"，平均每筆略高約 {_f1(ev)} 個百分點，但接近量不出（誤差範圍 {_rng(eci)}）"
        elif eci[1] < 0:
            head += f"，平均每筆少約 {_f1(ev)} 個百分點（誤差範圍 {_rng(eci)}）"
        else:
            head += f"，平均每筆量不出差別（誤差範圍 {_rng(eci)}）"
    edge = ((tiers.get("categories") or {}).get("edge") or {})
    wr = edge.get("win_rate")
    if _num(wr):
        tail = (f"。但單檔賺錢機率只有 {wr * 100:.1f}%，不到一半" if wr < 0.5
                else f"。單檔賺錢機率 {wr * 100:.1f}%，過半也不代表穩賺")
    else:
        tail = "。單檔賺錢機率請以網站為準"
    when = f"（{tiers.get('date') or '—'} 用歷史候選池重算）"
    return f"{DISCLAIMER_BASE}{head}{tail}{when}。"


def gate_note(gate, tiers):
    """門檻退回日的一句提醒（不切換整組統計數字）；門檻有套用回空字串。數字讀 by_gate.fallback。"""
    if not isinstance(gate, dict) or gate.get("applied") is not False:
        return ""
    if gate.get("reason") != "pool_too_small":
        return "⚠️ 今天強弱資料算不出來、強勢門檻沒套用，分類請保守看。"
    base = "⚠️ 今天過強勢門檻的候選不足，門檻已放寬；"
    t = tiers if isinstance(tiers, dict) else {}
    cats = (((t.get("by_gate") or {}).get("fallback") or {}).get("categories") or {})
    e, r = (cats.get("edge") or {}).get("win_rate"), (cats.get("rest") or {}).get("win_rate")
    if t.get("stale") or not (_num(e) and _num(r)):
        return base + "這種日子的歷史數字讀不到，分類請保守看。"
    nums = f"（相對優勢賺錢機率 {e * 100:.1f}%、其他候選 {r * 100:.1f}%）"
    if e < r:
        return base + f"歷史上這種日子分類方向曾經相反{nums}。"
    return base + f"歷史上這種日子分類的差距跟平常不一樣{nums}，請保守看。"


def bias_note(tiers):
    """「乖離排前段」標籤說明：只是描述；同日比量不出差別時照實講。"""
    p = _usable_pair(tiers, "bias_high_vs_rest")
    if p and _verdict(p["win_ci90"]) == "nodiff" and _verdict(p.get("ev_ci90")) in ("nodiff", None):
        return f"「{BIAS_TAG}」只是描述（當天候選裡乖離前 1/3），量不出比較常賺或賺比較多。"
    return f"「{BIAS_TAG}」只是描述（當天候選裡乖離前 1/3），不代表比較好。"


def market_status_line(d):
    """大盤市況一行摘要，讀 screener.json 頂層 market_breadth（跟網站同一份資料）。
    沒有這個欄位（舊資料、或測試用的假資料）就不顯示，不硬湊一行。"""
    mb = d.get("market_breadth")
    if not mb or not mb.get("status"):
        return ""
    label = MARKET_STATUS_LABEL.get(mb["status"], mb["status"])
    breadth = mb.get("breadth20")
    detail = f"，全市場 {breadth * 100:.0f}% 站上月線" if breadth is not None else ""
    return f"市場狀態：{label}{detail}"


def _tier_section(group, bias_by_id=None):
    """組一個分類段落：標題「共 N 檔，這裡列前 M 檔」＋每檔一行摘要（無序號，避免暗示買序）。

    group：已經照 opportunities.json 原始順序、只含這個 tier 的候選（stock dict list）。
    只顯示 TIER_PREVIEW_N 筆——候選有上百檔時全列不可能，而且列出來也不代表「該買這幾檔」，
    純粹是「這個分類長什麼樣子」的舉例，所以標題必須同時講清楚「共 N 檔」跟「列前 M 檔」。

    ⚠️ **刻意不照該榜自己的特徵排序**（例如勝率榜不照 turnover 由高到低排）：實測支持的是
    「同日三分位的層級差異」（2026-11-13 候選池重播、同日配對：成交金額前 1/3 比後 1/3 賺錢比例高
    約 8 個百分點；舊註解的 51.9%/43.8% 是錯母體＋舊口徑的數字，已作廢），**沒有**測出「turnover
    越高越好」是單調的。照特徵排序等於用畫面宣稱一個沒量過的梯度——2026-07-25 已經踩過
    一模一樣的坑（「前 3 名標最高信心」實測被推翻，第 2 名反而是全場最差、賺錢機率 45.1%）。
    有證據的是「有沒有進這個層級」，不是「在層級裡排第幾」，所以標題下面必須明說順序不是排名。
    """
    bias_by_id = bias_by_id or {}
    shown = group[:TIER_PREVIEW_N]
    lines = [f"{EDGE_ICON} {EDGE_LABEL}（共 {len(group)} 檔，這裡列前 {len(shown)} 檔）",
             "（照候選清單原始順序，不是好壞排名）"]
    if not shown:
        lines.append("（目前沒有符合的候選）")
        return lines
    for s in shown:
        chg = s.get("change_pct", 0)
        sign = "+" if chg >= 0 else ""
        tag = f"　［{BIAS_TAG}］" if bias_by_id.get(s["id"]) else ""
        lines.append(f"・{s['name']} {s['id']}　{sign}{chg:g}%{tag}")
        rs = " · ".join(reasons(s))
        if rs:
            lines.append(rs)
        pn = price_note(s)
        if pn:
            lines.append(pn)
        warn = risk_warning(s, len(reasons(s)))
        if warn:
            lines.append(f"⚠️ {warn}")
    return lines


def build_message(d):
    stocks = d["stocks"]
    # 交易日優先讀頂層 data_date；舊資料沒有才退回掃 ohlc（全市場版 ohlc 已拆出，掃不到）
    dd = d.get("data_date") or data_date(stocks)
    mmdd = "/".join(dd.split("-")[1:]) if dd else "—"
    # 候選一律以網站的「今日候選」為準（同一套回測權重），讓網站與 TG 說同一套話。
    by_id = {s["id"]: s for s in stocks}
    opp_picks, opp_reason, gate = load_opportunity_picks(dd)
    # 🔴 2026-07-25（Andy 裁示「候選不足就不用硬要呈現」）：這裡原本有一條「湊數退路」，
    # 檔案缺席時改用自有排序硬選 10 檔。已移除——快報與網站必須說同一套話，
    # 名單產不出來就照實說「產不出來」，不要生一份來源不同的清單假裝正常。
    tier_by_id = {p["id"]: p.get("tier") for p in (opp_picks or [])}
    bias_by_id = {p["id"]: p.get("bias_high") for p in (opp_picks or [])}
    ranked = [by_id[p["id"]] for p in (opp_picks or []) if p["id"] in by_id]
    # 檔案有、但裡面的代號在 screener 裡都找不到 → 也是資料異常，不是零檔
    if opp_picks and not ranked:
        opp_reason = "missing"

    cnt = d.get("count", len(stocks))
    sep = "━━━━━━━━━━"  # 卡片分隔線
    mkt = market_status_line(d)

    if not ranked:
        # 分清楚兩件完全不同的事——講錯會讓人做錯決定：
        #   管線故障 → 「今天沒資料」，不可暗示「市場沒機會」（那是憑空的市場判斷）
        #   真的零檔 → 「今天沒有通過門檻的」，這是有效結論，可以放心觀望
        if opp_reason == "missing":
            lines = [
                f"📊 台股選股快報 {mmdd}",
                sep,
                "⚠️ 今天的候選名單沒有產出（資料管線問題，不是「今天沒機會」）。",
                "網站上的名單可能也是空的。這不是市場結論，請不要當成看空訊號。",
                "隔天自動更新後會恢復；若連兩天這樣請找我看。",
            ]
        else:
            lines = [
                f"📊 台股選股快報 {mmdd}",
                f"掃描 {cnt} 檔有量個股",
            ]
            if mkt:
                lines.append(mkt)
            lines.append(sep)
            lines.append("今天沒有個股通過門檻（名單正常產出、就是零檔）——這是有效結論，可以觀望。")
    else:
        # 候選情報（2026-11-13 起只剩「相對優勢」一類）：完整清單導去網站看。
        # 主訊息＝同日配對差（tier_disclaimer），門檻退回日加一句提醒（gate_note）。
        lines = [
            f"📊 台股選股快報 {mmdd}",
            f"資料正常｜掃描 {cnt} 檔有量個股，候選共 {len(ranked)} 檔",
        ]
        if mkt:
            lines.append(mkt)
        tiers = load_tier_stats()
        lines.append(sep)
        lines.append(tier_disclaimer(tiers))
        gn = gate_note(gate, tiers)
        if gn:
            lines.append(gn)
        edge = [s for s in ranked if tier_by_id.get(s["id"]) == TIER_EDGE]
        lines.append(sep)
        lines.extend(_tier_section(edge, bias_by_id))
        if any(bias_by_id.get(s["id"]) for s in edge[:TIER_PREVIEW_N]):
            lines.append(bias_note(tiers))
        rest_n = len(ranked) - len(edge)
        if rest_n > 0:
            lines.append(f"其他候選 {rest_n} 檔沒有分類稱號，完整清單請看網站。")

    lines.append(sep)
    lines.append(f"🔗 完整清單 {SITE}")
    lines.append("※ 僅供參考，非投資建議")
    return "\n".join(lines), dd


def send(text):
    token = os.environ.get("TG_BOT_TOKEN")
    if not token:
        raise SystemExit("缺少環境變數 TG_BOT_TOKEN")
    data = urllib.parse.urlencode(
        {"chat_id": CHAT_ID, "text": text, "disable_web_page_preview": "true"}
    ).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", data=data
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        resp = json.load(r)
    if not resp.get("ok"):
        raise SystemExit(f"Telegram 發送失敗：{resp}")
    return resp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="public/data/screener.json")
    ap.add_argument("--state", default="pipeline/notify_state.json")
    ap.add_argument("--dry-run", action="store_true", help="只印訊息，不發、不動 state")
    ap.add_argument("--force", action="store_true", help="忽略 state 直接發")
    args = ap.parse_args()

    with open(args.data, encoding="utf-8") as f:
        d = json.load(f)

    text, dd = build_message(d)

    # 閘門：只有出現新的交易日資料才推
    last = None
    if os.path.exists(args.state):
        try:
            last = json.load(open(args.state, encoding="utf-8")).get("last_notified")
        except Exception:
            last = None

    if args.dry_run:
        print(f"[dry-run] 資料日期={dd} 上次推播={last}\n{'-'*40}\n{text}")
        return

    # 防禦：資料日期讀不到（dd=None，代表資料異常）就別推，免得每晚重複發「—」日期快報
    if not args.force and not dd:
        print("資料日期讀不到（dd=None），資料可能異常，略過推播。")
        return

    if not args.force and dd and last and dd <= last:
        print(f"資料日期 {dd} 未更新（上次已推 {last}），不重複推播。")
        return

    send(text)
    print(f"已推播選股快報（資料日期 {dd}）。")

    if not args.force:
        with open(args.state, "w", encoding="utf-8") as f:
            json.dump({"last_notified": dd}, f, ensure_ascii=False)
        print(f"已更新 state：last_notified={dd}")


if __name__ == "__main__":
    main()
