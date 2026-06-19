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
import html
import json
import os
import sys
import urllib.parse
import urllib.request

CHAT_ID = os.environ.get("TG_CHAT_ID", "-5127072553")  # 群組「叔叔名牌TG」
SITE = "https://andy30019123agent-ship-it.github.io/tw-stock-screener/"


def esc(t):
    return html.escape(str(t))


def data_date(stocks):
    """全市場最後一根 K 線的日期 = 這份資料的交易日。"""
    dates = [s["ohlc"][-1]["t"] for s in stocks if s.get("ohlc")]
    return max(dates) if dates else None


def score(s):
    sc = 0
    if s.get("signal_ma"):
        sc += 3
    if s.get("bull_aligned") and s.get("diverging"):
        sc += 2
    if s.get("foreign_streak", 0) >= 3:
        sc += 2
    if s.get("trust_streak", 0) >= 3:
        sc += 2
    if s.get("holder_rising"):
        sc += 1
    return sc


def reasons(s):
    """為何注意：緊湊標籤，控制每行長度避免手機折行破版。"""
    r = []
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
    return r


def price_note(s):
    """支撐/壓力 + 前高，緊湊一行。"""
    close, ma20 = s["close"], s.get("ma20")
    parts = []
    if ma20:
        parts.append(f"ma20 {ma20:.1f}{'撐' if close >= ma20 else '壓'}")
    oh = s.get("ohlc", [])[-20:]
    if oh:
        hi = max(b["h"] for b in oh)
        if hi > close:
            parts.append(f"高 {hi:g}")
    return "　".join(parts)


def risk_warning(s, n_reasons):
    """只回「值得警示」的風險（緊湊）；無特別警示則回空字串。"""
    disp = s.get("dispersion_pct")
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
    dd = data_date(stocks)
    mmdd = "/".join(dd.split("-")[1:]) if dd else "—"
    ranked = sorted(
        [s for s in stocks if score(s) >= 2],
        key=lambda s: (-score(s), -s.get("foreign_streak", 0)),
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
