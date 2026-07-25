#!/usr/bin/env python3
"""盤後選股快報 → Telegram。

由 GitHub Actions 在 build_data.py 之後呼叫：
- 只在「出現新的交易日資料」時推一次（用 notify_state.json 記錄上次推播的資料日期）。
  → 週末/假日沒有新資料 = 不推；排程跨午夜延遲也只推一次、不誤殺。
- 名單**直接讀 opportunities.json**（網站「今日機會股」那份，檔數 = opportunities.TOP_N），
  把中了哪些訊號 / 價位 / 風險寫成人看得懂的訊息。這支檔案不做任何排名判斷——
  快報與網站必須說同一套話（2026-07-25 移除了自有的退路排序）。
  名單產不出來就照實說「沒產出」，不可講成「今天沒機會」。
- token 由環境變數 TG_BOT_TOKEN 帶入（GitHub Secret），群組 id 預設叔叔名牌TG。

本機測試：
  python pipeline/notify_tg.py --dry-run          # 只印訊息不發、不動 state
  python pipeline/notify_tg.py --force            # 忽略 state 直接發（驗證用）
"""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
import opportunities as opp  # noqa: E402  # TOP_N：快報檔數必須與網站一致

CHAT_ID = os.environ.get("TG_CHAT_ID", "-5127072553")  # 群組「叔叔名牌TG」
SITE = "https://andy30019123agent-ship-it.github.io/tw-stock-screener/"
# 網站首頁「今日機會股 Top5」的產出，由 build_data → opportunities.run() 寫出。
OPP_PATH = os.path.join(os.path.dirname(__file__), "..", "public", "data", "opportunities.json")


def load_opportunity_picks(dd):
    """讀網站的「今日機會股 Top5」代號清單（依網站順序）。

    為什麼要讀它：快報原本自己有一套手寫 3/2/1 分的排名，網站 Top5 卻是用回測權重排的，
    同一天兩邊可能推薦完全不同的股票——使用者看到的是兩套互相矛盾的建議。以網站那份為準，
    快報就只負責「把同一份結論寫成人看得懂的訊息」。

    回 (ids, reason)：
      (["2395", ...], "ok")   正常
      ([], "empty")           檔案正常但今天零檔 → **這是真實結論**，照實說「今天沒有通過門檻的」
      (None, "missing")       檔案讀不到／日期對不上 → **這是管線故障**，不可講成市場結論

    ⚠️ 2026-07-25 改（Andy 裁示「候選不足就不用硬要呈現」）：原本回不到就退回自有排序湊數，
    結果是①快報與網站說不同的話②score>=4 在權重改版後幾乎不可能達到，於是實際行為變成
    發出「今日沒有明顯符合標的，先觀望」——**把管線故障講成了市場結論**。
    當天網站也是空的（引擎掛了），而快報卻讓人以為「今天大盤沒機會」，這比不推更糟。
    """
    try:
        with open(OPP_PATH, encoding="utf-8") as f:
            opp = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None, "missing"
    if dd and opp.get("date") and opp["date"] != dd:
        return None, "missing"
    return [p["id"] for p in (opp.get("picks") or [])], "ok"


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


# 圈號 ①~⑳（Unicode 有到 ⑳）；超出就退回「N.」純數字，不讓檔數變動炸掉整個推播。
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def _num(i):
    return CIRCLED[i] if 0 <= i < len(CIRCLED) else f"{i + 1}."


def build_message(d):
    stocks = d["stocks"]
    # 交易日優先讀頂層 data_date；舊資料沒有才退回掃 ohlc（全市場版 ohlc 已拆出，掃不到）
    dd = d.get("data_date") or data_date(stocks)
    mmdd = "/".join(dd.split("-")[1:]) if dd else "—"
    # 排名一律以網站的「今日機會股 Top5」為準（同一套回測權重），讓網站與 TG 說同一套話。
    by_id = {s["id"]: s for s in stocks}
    opp_ids, opp_reason = load_opportunity_picks(dd)
    # 🔴 2026-07-25（Andy 裁示「候選不足就不用硬要呈現」）：這裡原本有一條「湊數退路」，
    # 檔案缺席時改用自有排序硬選 10 檔。已移除——快報與網站必須說同一套話，
    # 名單產不出來就照實說「產不出來」，不要生一份來源不同的清單假裝正常。
    ranked = [by_id[i] for i in (opp_ids or []) if i in by_id]
    # 檔案有、但裡面的代號在 screener 裡都找不到 → 也是資料異常，不是零檔
    if opp_ids and not ranked:
        opp_reason = "missing"

    cnt = d.get("count", len(stocks))
    sep = "━━━━━━━━━━"  # 卡片分隔線

    if not ranked:
        # 分清楚兩件完全不同的事——講錯會讓人做錯決定：
        #   管線故障 → 「今天沒資料」，不可暗示「市場沒機會」（那是憑空的市場判斷）
        #   真的零檔 → 「今天沒有通過門檻的」，這是有效結論，可以放心觀望
        if opp_reason == "missing":
            lines = [
                f"📊 台股選股快報 {mmdd}",
                sep,
                "⚠️ 今天的精華名單沒有產出（資料管線問題，不是「今天沒機會」）。",
                "網站上的名單可能也是空的。這不是市場結論，請不要當成看空訊號。",
                "隔天自動更新後會恢復；若連兩天這樣請找我看。",
            ]
        else:
            lines = [
                f"📊 台股選股快報 {mmdd}",
                f"掃描 {cnt} 檔有量個股",
                sep,
                "今天沒有個股通過門檻（名單正常產出、就是零檔）——這是有效結論，可以觀望。",
            ]
    else:
        lines = [
            f"📊 台股選股快報 {mmdd}",
            f"精選 {len(ranked)} 檔（掃描 {cnt} 檔）",
        ]
        # 🔴 2026-07-25：這裡原本是寫死的 5 個圈號 ["①".."⑤"]，TOP_N 從 5 改成 10 之後
        # `nums[i]` 直接 IndexError → **整個推播步驟失敗，連帶擋掉後面的存檔回 main 與部署**
        # （workflow 是循序的，前一步 fail 後面全 skip）。
        # 改用 CIRCLED[i] 並在超出範圍時退回純數字，讓檔數再變也不會炸。
        for i, s in enumerate(ranked):
            chg = s.get("change_pct", 0)
            sign = "+" if chg >= 0 else ""
            lines.append(sep)
            lines.append(f"{_num(i)} {s['name']} {s['id']}　{sign}{chg:g}%")
            lines.append(" · ".join(reasons(s)))
            pn = price_note(s)
            if pn:
                lines.append(pn)
            warn = risk_warning(s, len(reasons(s)))
            if warn:
                lines.append(f"⚠️ {warn}")

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
