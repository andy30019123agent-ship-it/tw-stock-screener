#!/usr/bin/env python3
"""量測「雙優」到底有沒有比較好——這個分類上線了但從沒被單獨量過。

問題：tier_stats.py 是「每個特徵各自切三分位」，回答的是「成交金額高的那層如何」與
「乖離高的那層如何」。但產品把「兩個都高」標成雙優，卻從來沒量過交集本身。
交集有可能比單一條件好，也可能更差（兩個條件都極端＝更少見、更極端的股票）。

做法：用與 tier_stats 相同的事件母體與同日三分位切法，分成四組互斥：
  both  ＝ 成交金額高層 且 乖離高層
  turn  ＝ 只有成交金額高層
  bias  ＝ 只有乖離高層
  none  ＝ 兩者都不是高層
每組算成本後（0.785%）的賺錢機率、期望值、賺賠幅度、約當獨立批次。
"""
import json, os, sys
sys.path.insert(0, "/Users/andyc/Desktop/agent/tw-stock-screener/pipeline")
os.chdir("/Users/andyc/Desktop/agent/tw-stock-screener/pipeline")

import history_store as hs
import backtest_signals as bt
import tier_stats as ts

COST = ts.DEFAULT_COST

price = hs.load("history/price.json")
chip = hs.load("history/chip.json")
divs = hs.load("history/dividends.json")
uni = json.load(open("universe.json"))["stocks"]

bt_hist = hs.load(bt.BT_PRICE_PATH)
long_price = hs.bt_to_price_hist(bt_hist)
print(f"長歷史 {len(bt_hist['dates'])} 個交易日、{len(bt_hist['stocks'])} 檔", flush=True)

print("建立橫斷面快取…", flush=True)
xsect = bt.build_xsect_cache(long_price, divs, uni)
print(f"橫斷面快取 {len(xsect)} 天", flush=True)

print("收集事件…", flush=True)
events, by_date = bt.collect_events(long_price, chip, divs, uni, xsect=xsect)
print(f"事件 {len(events)} 筆", flush=True)

# 同日三分位切點（與 tier_stats 同一套邏輯）
by_day = {}
for e in events:
    f = e.get("feat") or {}
    if f.get("turnover") is None or f.get("bias20_pct") is None:
        continue
    by_day.setdefault(e["date"], []).append((f["turnover"], f["bias20_pct"], e["ret"]))

groups = {"both": [], "turn": [], "bias": [], "none": []}
for d, rows in by_day.items():
    if len(rows) < ts.MIN_DAY_SAMPLES:
        continue
    t_hi = ts._percentile(sorted(r[0] for r in rows), 200 / 3)
    b_hi = ts._percentile(sorted(r[1] for r in rows), 200 / 3)
    for t, b, ret in rows:
        th, bh = t >= t_hi, b >= b_hi
        key = "both" if (th and bh) else "turn" if th else "bias" if bh else "none"
        groups[key].append((d, ret - COST))

print("\n=== 結果（成本後 0.785%、持有 20 日、隔日開盤進場）===", flush=True)
print(f"{'組別':6} {'n':>7} {'天':>5} {'批次':>4} {'賺錢機率':>8} {'賺時':>8} {'賠時':>8} {'期望值':>8} {'中位':>8}")
label = {"both": "雙優", "turn": "只金額", "bias": "只乖離", "none": "都不是"}
out = {}
for k in ("both", "turn", "bias", "none"):
    rows = groups[k]
    if not rows:
        continue
    rets = sorted(r for _, r in rows)
    days = len(set(d for d, _ in rows))
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    wr = len(wins) / len(rets)
    aw = sum(wins) / len(wins) * 100 if wins else 0
    al = sum(losses) / len(losses) * 100 if losses else 0
    ev = wr * aw + (1 - wr) * al
    med = ts._percentile(rets, 50) * 100
    out[k] = {"n": len(rets), "days": days, "blocks": days // 20, "win_rate": round(wr, 4),
              "avg_win_pct": round(aw, 2), "avg_loss_pct": round(al, 2),
              "ev_pct": round(ev, 2), "median_pct": round(med, 2)}
    print(f"{label[k]:6} {len(rets):>7} {days:>5} {days//20:>4} {wr*100:>7.1f}% "
          f"{aw:>7.2f}% {al:>7.2f}% {ev:>+7.2f}% {med:>+7.2f}%")

with open("/Users/andyc/Desktop/agent/tw-stock-screener/pipeline/both_tier_check.json", "w",
          encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print("\n✅ 已寫入 pipeline/both_tier_check.json", flush=True)
