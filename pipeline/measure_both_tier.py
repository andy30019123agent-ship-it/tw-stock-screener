#!/usr/bin/env python3
"""重算條件層級統計＋雙優驗證（正確母體），並輸出「舊母體 vs 新母體」對照。

📌 分類已於 2026-11-13 簡化（只剩「相對優勢」一類＋「乖離高」描述標籤，見 opportunities.TIER_SCHEME）。
本檔仍是「手動重算 tier_stats.json」的驅動腳本；其中雙優四格（both_tier_check.json、
event_both_check）僅供歷史對照，網站已不再有「雙優」這個分類。

🔴 2026-11-13 重寫：舊版（2026-07-26）把 collect_events 的**所有訊號事件**當母體分層——
任一 raw signal 成立就收（含多頭排列等展示型訊號、均量 300 張起）。網站上被分類的卻是
「最終候選池」（引擎訊號＋500 張＋強勢雙確認門檻＋營收濾網，百分位在池內排）。兩者不是
同一群股票，所以 7/26 告訴 Andy 的「成交金額高層 48.6%／低層 41.4%／雙優 50.0%」描述的
不是網站上的分類。

新做法（與每週 ensure_weights 同一套程式）：
  collect_events(pool_rows=...) 收每日候選列 → tier_stats.compute_pool_tier_stats 逐日呼叫
  opportunities.build_opportunities 重播候選池 → opportunities.feature_level 切層。

輸出：
  pipeline/tier_stats.json＋public/data/tier_stats.json   新母體（前端／快報讀這份）
  pipeline/both_tier_check.json                          雙優四格：新母體＋舊母體對照
  $TWS_OUT（預設 /tmp/tier_compare.json）                 完整對照（報告用）

跑法：python3 pipeline/measure_both_tier.py   （約 20~30 分鐘，逐檔逐日重算指標）
"""
import datetime as dt
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import backtest_signals as bt   # noqa: E402
import history_store as hs      # noqa: E402
import tier_stats as ts         # noqa: E402

# 2026-07-26 舊母體、舊成本（直接減 0.785%）時對 Andy 公布過的數字，原樣留存供對照
PUBLISHED_2026_07_26 = {
    "turnover_high_win_rate": 0.486, "turnover_low_win_rate": 0.414,
    "both_win_rate": 0.500, "both_avg_win_pct": 18.4, "both_avg_loss_pct": -10.5,
    "turnover_high_avg_win_pct": 16.3, "turnover_high_avg_loss_pct": -9.9,
    "turnover_high_ev_pct": 2.85, "bias_only_win_rate": 0.425,
}


def event_both_check(events, net_fn=bt._apply_cost, block=ts.DEFAULT_BLOCK,
                     n_boot=ts.DEFAULT_N_BOOT, seed=ts.DEFAULT_SEED):
    """舊母體（所有訊號事件、同日三分位）的雙優四格，只供對照。切法與 2026-07-26 版相同。"""
    import random
    by_day = {}
    for e in events:
        f = e.get("feat") or {}
        if f.get("turnover") is None or f.get("bias20_pct") is None:
            continue
        by_day.setdefault(e["date"], []).append((f["turnover"], f["bias20_pct"], e["ret"]))
    groups = {"both": [], "turn_only": [], "bias_only": [], "neither": []}
    for d, rows in by_day.items():
        if len(rows) < ts.MIN_DAY_SAMPLES:
            continue
        t_hi = ts._percentile(sorted(r[0] for r in rows), 200 / 3)
        b_hi = ts._percentile(sorted(r[1] for r in rows), 200 / 3)
        for t, b, ret in rows:
            th, bh = t >= t_hi, b >= b_hi
            k = "both" if (th and bh) else "turn_only" if th else "bias_only" if bh else "neither"
            groups[k].append((d, net_fn(ret)))
    rng = random.Random(seed)
    return {k: ts._tier_summary(v, block, n_boot, rng) for k, v in groups.items()}


def main():
    t0 = time.time()
    bt_hist = hs.load(bt.BT_PRICE_PATH)
    price = hs.bt_to_price_hist(bt_hist)
    chip = hs.load(os.path.join(HERE, "history", "chip.json")) or {}
    divs = hs.load(os.path.join(HERE, "history", "dividends.json")) or {}
    with open(os.path.join(HERE, "universe.json"), encoding="utf-8") as f:
        uni = json.load(f)["stocks"]
    weights = bt._load(bt.WEIGHTS_PATH) or {}
    print(f"長歷史 {len(bt_hist['dates'])} 日（{bt_hist['dates'][0]}~{bt_hist['dates'][-1]}）、"
          f"{len(bt_hist['stocks'])} 檔", flush=True)

    xsect = bt.build_xsect_cache(price, divs, uni)
    print(f"橫斷面快取 {len(xsect)} 天（{time.time() - t0:.0f}s）", flush=True)
    pool_rows = {}
    events, _ = bt.collect_events(price, chip, divs, uni, xsect=xsect, pool_rows=pool_rows)
    print(f"事件 {len(events)} 筆、候選列 {sum(len(v) for v in pool_rows.values())} 筆／"
          f"{len(pool_rows)} 天（{time.time() - t0:.0f}s）", flush=True)

    now = dt.datetime.now()
    new = ts.compute_pool_tier_stats(pool_rows, weights=weights)
    new.update({"date": now.date().isoformat(), "computed": now.strftime("%Y-%m-%d %H:%M"),
                "forward_days": bt.FORWARD, "stale": False})
    old = ts.compute_tier_stats(events)
    old_both = event_both_check(events)
    print(f"統計完成（{time.time() - t0:.0f}s）", flush=True)

    bt._atomic_write_json(bt.TIER_STATS_PATH, new)
    pub = os.path.join(HERE, "..", "public", "data", "tier_stats.json")
    bt._atomic_write_json(pub, new)
    both_out = {
        "computed": new["computed"], "population": new["meta"]["population_label"],
        "candidate_pool": new["both_check"],
        "old_population_all_signal_events": old_both,
        "note": "分類已於 2026-11-13 簡化（網站只剩「相對優勢」），此檔僅供歷史對照。"
                "candidate_pool＝正確母體；old_population 只供對照（2026-07-26 誤用的母體，成本已改 _apply_cost）",
    }
    with open(os.path.join(HERE, "both_tier_check.json"), "w", encoding="utf-8") as f:
        json.dump(both_out, f, ensure_ascii=False, indent=1)
    cmp_path = os.environ.get("TWS_OUT", "/tmp/tier_compare.json")
    with open(cmp_path, "w", encoding="utf-8") as f:
        json.dump({"new": new, "old": old, "old_both": old_both,
                   "published_2026_07_26": PUBLISHED_2026_07_26,
                   "n_events": len(events)}, f, ensure_ascii=False, indent=1)

    def line(tag, d):
        if not d or d.get("win_rate") is None:
            return f"{tag:14} 樣本不足"
        return (f"{tag:14} n={d['samples']:>7} 天={d['days']:>4} 批={d['blocks']:>3} "
                f"賺錢 {d['win_rate'] * 100:5.1f}% CI{d['ci90']} 期望 {d['ev_pct']:+.2f}% "
                f"CI{d['ci90_ev']} 中位 {d['median_pct']:+.2f}%")
    for feat in ("turnover", "bias20_pct"):
        for t in ts.TIERS:
            print(line(f"舊 {feat[:4]} {t}", old["features"][feat][t]))
            print(line(f"新 {feat[:4]} {t}", new["features"][feat][t]))
    for k in ("both", "turn_only", "bias_only", "neither"):
        print(line(f"舊 {k}", old_both[k]))
        print(line(f"新 {k}", new["both_check"][k]))
    for g in ("applied", "fallback"):
        sub = new["by_gate"][g]
        print(f"--- 門檻{g}：{sub['meta']['days_total']} 天、候選 {sub['meta']['candidates_total']} 筆")
        for t in ts.TIERS:
            print(line(f"  turn {t}", sub["features"]["turnover"][t]))
        for k in ("edge", "rest", "bias_high", "not_bias_high"):
            print(line(f"  {k}", sub["categories"].get(k)))
    print("同日配對差（pp）：")
    for k, v in new["paired"].items():
        print(f"  {k:24} 勝率 {v['win_pp']:+.2f} CI{v['win_ci90']}  每筆 {v['ev_pp']:+.2f} CI{v['ev_ci90']}"
              f"  前半/後半勝率 {v['first_half_win_pp']:+.2f}/{v['second_half_win_pp']:+.2f}")
    print(json.dumps(new["meta"], ensure_ascii=False)[:1500])
    print(f"✅ 寫入 {bt.TIER_STATS_PATH}、{pub}、both_tier_check.json、{cmp_path}")


if __name__ == "__main__":
    main()
