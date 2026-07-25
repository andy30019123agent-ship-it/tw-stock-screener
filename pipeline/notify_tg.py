#!/usr/bin/env python3
"""盤後選股快報 → Telegram。

由 GitHub Actions 在 build_data.py 之後呼叫：
- 只在「出現新的交易日資料」時推一次（用 notify_state.json 記錄上次推播的資料日期）。
  → 週末/假日沒有新資料 = 不推；排程跨午夜延遲也只推一次、不誤殺。
- 依分數挑 3-5 檔值得注意的電子股，把中了哪些訊號 / 價位 / 風險寫成訊息。
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
import backtest_signals as bt  # noqa: E402  # ENGINE_SIGNALS/signal_flags：跟網站 Top5 同一套判準

CHAT_ID = os.environ.get("TG_CHAT_ID", "-5127072553")  # 群組「叔叔名牌TG」
SITE = "https://andy30019123agent-ship-it.github.io/tw-stock-screener/"
# 網站首頁「今日機會股 Top5」的產出，由 build_data → opportunities.run() 寫出。
OPP_PATH = os.path.join(os.path.dirname(__file__), "..", "public", "data", "opportunities.json")
# 回測權重表（跟 opportunities.py 用同一份），score() 的退路排序改吃這份，不再手寫分數。
WEIGHTS_PATH = os.path.join(os.path.dirname(__file__), "signal_weights.json")


def load_opportunity_picks(dd):
    """讀網站的「今日機會股 Top5」代號清單（依網站順序）。

    為什麼要讀它：快報原本自己有一套手寫 3/2/1 分的排名，網站 Top5 卻是用回測權重排的，
    同一天兩邊可能推薦完全不同的股票——使用者看到的是兩套互相矛盾的建議。以網站那份為準，
    快報就只負責「把同一份結論寫成人看得懂的訊息」。

    日期對不上或檔案讀不到就回 None，讓呼叫端退回自有排序——寧可推一份略舊邏輯的清單，
    也不要因為缺一個檔案就整天不推。
    """
    try:
        with open(OPP_PATH, encoding="utf-8") as f:
            opp = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if dd and opp.get("date") and opp["date"] != dd:
        return None
    ids = [p["id"] for p in (opp.get("picks") or [])]
    return ids or None


def data_date(stocks):
    """全市場最後一根 K 線的日期 = 這份資料的交易日。"""
    dates = [s["ohlc"][-1]["t"] for s in stocks if s.get("ohlc")]
    return max(dates) if dates else None


def load_weights():
    """讀回測權重表（跟 opportunities.py 用同一份 pipeline/signal_weights.json）。

    讀不到／格式壞掉就回空 dict——score() 會讓所有訊號落回 0 分，退化成只剩乖離扣分
    （保守但安全，不會因為缺一個檔案就整條退路排序掛掉）。"""
    try:
        with open(WEIGHTS_PATH, encoding="utf-8") as f:
            return (json.load(f) or {}).get("signals", {})
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def score(s, weights):
    """opp_ids 讀不到時的退路排序分數。

    改成讀回測權重（跟網站 Top5 同一份 signal_weights.json、同一套 bt.ENGINE_SIGNALS 判準），
    不再手寫 +2/+3 這種分數——手寫分數曾經跟回測結論相反（例：「破底翻」回測平均超額
    −0.91pp、weight=0，手寫卻給 +2；「外資/投信連買」回測 samples=0 沒有證據，手寫也給 +2）。
    weight 為 0 或 signal_weights.json 缺這個 key，一律不加分（呼應 opportunities.py 的規則）。
    """
    flags = bt.signal_flags(s)
    sc = sum(
        int((weights.get(k) or {}).get("weight", 0) or 0)
        for k in bt.ENGINE_SIGNALS if flags.get(k)
    )
    # 抑制追高：乖離（現價離 20 日均線幾 %）過大者扣分，讓快報偏向「還沒噴太遠、
    # 相對安全的進場點」，而非已經漲一大段的追高點。
    # ⚠️ 這裡曾經誤用 dispersion_pct——那是「四條均線彼此的離散度」，不是股價乖離。
    # 兩者方向相關（噴過頭的股票均線也會攤開）所以沒露餡，但扣分依據和風險提示的數字都是錯的。
    disp = s.get("bias20_pct")
    if disp is not None:
        if disp >= 20:
            sc -= 3
        elif disp >= 15:
            sc -= 2
        elif disp >= 12:
            sc -= 1
    return sc


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


def build_message(d):
    stocks = d["stocks"]
    # 交易日優先讀頂層 data_date；舊資料沒有才退回掃 ohlc（全市場版 ohlc 已拆出，掃不到）
    dd = d.get("data_date") or data_date(stocks)
    mmdd = "/".join(dd.split("-")[1:]) if dd else "—"
    # 排名一律以網站的「今日機會股 Top5」為準（同一套回測權重），讓網站與 TG 說同一套話。
    by_id = {s["id"]: s for s in stocks}
    opp_ids = load_opportunity_picks(dd)
    ranked = [by_id[i] for i in opp_ids if i in by_id] if opp_ids else []
    if not ranked:
        # 退路：機會股檔案缺席/日期對不上時，用回測權重分數排序，至少還推得出東西。
        weights = load_weights()
        ranked = sorted(
            [s for s in stocks if score(s, weights) >= 4],   # 候選門檻 2→4：讓「精選」名副其實
            key=lambda s: (-score(s, weights), -s.get("foreign_streak", 0)),
        )[:5]

    cnt = d.get("count", len(stocks))
    sep = "━━━━━━━━━━"  # 卡片分隔線

    if not ranked:
        lines = [
            f"📊 台股電子選股快報 {mmdd}",
            f"掃描 {cnt} 檔有量電子股",
            sep,
            "今日沒有明顯符合『均線多頭＋法人連買』的標的，先觀望。",
        ]
    else:
        lines = [
            f"📊 台股電子選股快報 {mmdd}",
            f"精選 {len(ranked)} 檔（掃描 {cnt} 檔）",
        ]
        nums = ["①", "②", "③", "④", "⑤"]
        for i, s in enumerate(ranked):
            chg = s.get("change_pct", 0)
            sign = "+" if chg >= 0 else ""
            lines.append(sep)
            lines.append(f"{nums[i]} {s['name']} {s['id']}　{sign}{chg:g}%")
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
