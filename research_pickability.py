"""研究：單檔層面到底有沒有「勝率」與「報酬」的可預測性？（Andy 2026-07-25 深夜需求）

Andy 要的是兩份榜：①相對勝率高 ②相對報酬可能較高，他自己挑。
但今晚已實測「名單內名次沒有區辨力」（前3 vs 後5 配對差 −0.26%、t −0.22），
所以**先別做榜，先回答「有沒有東西可以排」**。這支腳本只做研究、不改產品。

方法上刻意保守（因為很容易挑到雜訊）：
- 有效獨立批次只有 339/20≈17 → 任何比率的標準誤約 ±12pp。
- 所以：①只測**事先指定**的特徵清單 ②一律用**同日橫斷面分位數**（不用絕對門檻，避免市況漂移）
  ③把區間切成**前半／後半**，要求同號才算「可能有效」④報 bootstrap 信賴區間，不只點估計。

跑法：python3 research_pickability.py --stage collect   # 重抓特徵（約 6 分鐘，寫新快取）
      python3 research_pickability.py --stage analyze   # 分析
"""
import argparse
import bisect
import math
import os
import pickle
import random
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.join(HERE, "pipeline")
sys.path.insert(0, PIPE)

import backtest_signals as bt          # noqa: E402
import build_data as bd                # noqa: E402
import history_store as hs             # noqa: E402
import price_breaks as pb              # noqa: E402
import json                            # noqa: E402

FORWARD = bt.FORWARD
MIN_BARS = bt.MIN_BARS
MIN_VOL = 500
CACHE = os.path.join(os.environ.get("TWS_CACHE_DIR", "/tmp"), "pickability_cache.pkl")
SPLIT = "2025-10-01"          # 前後半切點（前半 164 天／後半 175 天）

# ── 事先指定的候選特徵（不亂搜；每個都有先驗理由）────────────────────────────
# 名稱: (從 indicators 取值的 lambda, 方向假設, 為什麼)
FEATURES = {
    "rs_pct_60":   ("近 60 日報酬的全市場百分位", "高好", "動能延續：現行排序依據"),
    "rs_pct_120":  ("近 120 日報酬百分位", "高好", "較長期動能，較不易是短線噪音"),
    "rv20_pct":    ("20 日已實現波動（年化%）", "低好", "低波動股的勝率通常較高（波動本身是虧損機率）"),
    "bias20_pct":  ("離 20 日均線幅度%", "高好", "今日實測：成本後超額隨乖離單調遞增"),
    "dispersion":  ("均線離散度", "低好", "糾結＝盤整末端，發散＝已走一段"),
    "avg_vol_lots": ("20 日均量（張）", "高好", "流動性：不容易被套、成交成本低"),
    "turnover_pct": ("成交金額/市值 代理（均量×收盤）", "高好", "熱度"),
    "foreign_streak": ("外資連買天數", "高好", "籌碼面（回測顯示 samples 少）"),
    "trust_streak": ("投信連買天數", "高好", "同上"),
    "pe":          ("本益比", "低好", "估值：便宜的下跌空間小"),
    "pb":          ("股價淨值比", "低好", "同上"),
    "high20_gap":  ("距近 20 日高點的距離%", "低好", "接近前高＝強勢；離很遠＝弱"),
}


def collect():
    import time
    t0 = time.time()
    bth = hs.load(os.path.join(PIPE, "history", "bt_price.json")) or hs.bt_empty()
    price_hist = hs.bt_to_price_hist(bth)
    div_hist = hs.load(os.path.join(PIPE, "history", "dividends.json")) or {}
    chip_hist = hs.load(os.path.join(PIPE, "history", "chip.json")) or {}
    universe = json.load(open(os.path.join(PIPE, "universe.json"), encoding="utf-8"))["stocks"]
    breaks = pb.load_breaks() or set()
    xsect = bt.build_xsect_cache(price_hist, div_hist, universe)
    print(f"[1] 載入＋橫斷面 {time.time()-t0:.0f}s：{len(price_hist)} 檔、{len(xsect)} 日有 RS", flush=True)

    t0 = time.time()
    recs = {}
    done = 0
    for stock in universe:
        sid = stock["id"]
        pr = hs.to_price_rows(price_hist.get(sid, {}))
        if len(pr) < MIN_BARS + FORWARD + 1:
            continue
        pr = sorted(pr, key=lambda r: r["date"])
        cr = sorted(hs.to_chip_rows(chip_hist.get(sid, {})), key=lambda r: r["date"])
        cr_dates = [c["date"] for c in cr]
        ev = hs.to_div_events(div_hist.get(sid))
        adj = [r["close"] for r in bd.back_adjust_rows(pr, ev)]
        brk = sorted(j for j, r in enumerate(pr) if (sid, r["date"]) in breaks) if breaks else []
        for i in range(MIN_BARS - 1, len(pr) - FORWARD):
            di = pr[i]["date"]
            base = adj[i]
            if not base:
                continue
            if brk:
                lo = bisect.bisect_right(brk, i)
                if lo < len(brk) and brk[lo] <= i + FORWARD:
                    continue
            cut = bisect.bisect_right(cr_dates, di)
            ind = bd.compute_indicators(pr[:i + 1], cr[:cut], ev, None)
            if ind is None:
                continue
            vol = int(ind.get("avg_vol_lots", 0) or 0)
            if vol < MIN_VOL:
                continue
            x = xsect.get(di, {}).get(sid) or {}
            close = ind.get("close") or 0
            hi20 = ind.get("recent_high20")
            feat = {
                "rs_pct_60": x.get("rs_pct_60"),
                "rs_pct_120": x.get("rs_pct_120"),
                "rv20_pct": ind.get("rv20_pct"),
                "bias20_pct": ind.get("bias20_pct"),
                "dispersion": ind.get("dispersion"),
                "avg_vol_lots": vol,
                "turnover_pct": (vol * close) if close else None,
                "foreign_streak": ind.get("foreign_streak"),
                "trust_streak": ind.get("trust_streak"),
                "pe": ind.get("pe"),
                "pb": ind.get("pb"),
                "high20_gap": ((close / hi20 - 1) * 100 if (hi20 and close) else None),
            }
            flags = bt.signal_flags(ind)
            flags.update(bt._xsect_flags(x))
            recs.setdefault(di, []).append({
                "sid": sid, "fwd": adj[i + FORWARD] / base - 1,
                "gate": bool(flags.get("rs_confirmed_60_120")),
                "has_engine": any(flags.get(k) for k in bt.ENGINE_SIGNALS),
                "f": feat,
            })
        done += 1
        if done % 300 == 0:
            print(f"    …{done}/{len(universe)} ({time.time()-t0:.0f}s)", flush=True)
    print(f"[2] 收集 {time.time()-t0:.0f}s：{len(recs)} 日、{sum(len(v) for v in recs.values())} 筆", flush=True)
    with open(CACHE, "wb") as f:
        pickle.dump({"recs": recs}, f, protocol=4)
    print(f"[3] 寫入 {CACHE}")


def boot_ci(vals, fn, n=400, seed=42):
    """bootstrap 信賴區間（重抽整批日，保留同日相關性）。"""
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        s = [vals[rng.randrange(len(vals))] for _ in range(len(vals))]
        out.append(fn(s))
    out.sort()
    return out[int(n * 0.025)], out[int(n * 0.975)]


def analyze():
    with open(CACHE, "rb") as f:
        recs = pickle.load(f)["recs"]
    dates = sorted(d for d in recs if d >= "2025-02-05")
    print(f"分析區間 {dates[0]} ~ {dates[-1]}，{len(dates)} 個交易日")
    print(f"候選池定義＝有引擎訊號＋過門檻＋均量≥{MIN_VOL}（與線上一致）\n")

    # 每天的候選池 + 同日基準（全市場平均毛報酬）
    days = []
    for d in dates:
        rows = recs[d]
        bench = statistics.mean([r["fwd"] for r in rows]) if rows else 0.0
        pool = [r for r in rows if r["has_engine"] and r["gate"]]
        if len(pool) < 20:
            pool = [r for r in rows if r["has_engine"]]
        if len(pool) >= 8:
            days.append((d, pool, bench))
    print(f"可用日數 {len(days)}（候選池 ≥8 檔）\n")

    hdr = f"{'特徵':<16}{'方向':<5}{'高分組賺錢%':>11}{'低分組賺錢%':>11}{'差(pp)':>8}{'95%CI':>18}{'前半':>7}{'後半':>7}"
    print("=" * 96)
    print("① 勝率：把每天候選池按特徵切成上下三分之一，比較「實際賺錢（扣成本後 >0）」的比率")
    print("=" * 96)
    print(hdr)
    print("-" * 96)
    for key, (label, direction, why) in FEATURES.items():
        pairs = []            # (日期, 高分組賺錢率, 低分組賺錢率)
        for d, pool, bench in days:
            vs = [r for r in pool if r["f"].get(key) is not None]
            if len(vs) < 6:
                continue
            vs.sort(key=lambda r: r["f"][key], reverse=(direction == "高好"))
            k = max(2, len(vs) // 3)
            top, bot = vs[:k], vs[-k:]
            wt = statistics.mean([1.0 if bt._apply_cost(r["fwd"]) > 0 else 0.0 for r in top])
            wb = statistics.mean([1.0 if bt._apply_cost(r["fwd"]) > 0 else 0.0 for r in bot])
            pairs.append((d, wt, wb))
        if len(pairs) < 50:
            print(f"{label[:14]:<16}{direction:<5}{'資料不足':>11}")
            continue
        wt = statistics.mean([p[1] for p in pairs]) * 100
        wb = statistics.mean([p[2] for p in pairs]) * 100
        diff = [(p[1] - p[2]) * 100 for p in pairs]
        lo, hi = boot_ci(diff, lambda s: statistics.mean(s))
        h1 = statistics.mean([(p[1] - p[2]) * 100 for p in pairs if p[0] < SPLIT] or [0])
        h2 = statistics.mean([(p[1] - p[2]) * 100 for p in pairs if p[0] >= SPLIT] or [0])
        same = "✔" if (h1 > 0) == (h2 > 0) and abs(h1) > 0.5 and abs(h2) > 0.5 else " "
        print(f"{label[:14]:<16}{direction:<5}{wt:>10.1f}%{wb:>10.1f}%{statistics.mean(diff):>8.2f}"
              f"{f'[{lo:+.1f},{hi:+.1f}]':>18}{h1:>7.1f}{h2:>7.1f} {same}")

    print("\n" + "=" * 96)
    print("② 報酬：同樣分組，比較「平均絕對報酬（扣成本後 %）」")
    print("=" * 96)
    print(f"{'特徵':<16}{'方向':<5}{'高分組':>9}{'低分組':>9}{'差(pp)':>8}{'95%CI':>18}{'前半':>7}{'後半':>7}")
    print("-" * 96)
    for key, (label, direction, why) in FEATURES.items():
        pairs = []
        for d, pool, bench in days:
            vs = [r for r in pool if r["f"].get(key) is not None]
            if len(vs) < 6:
                continue
            vs.sort(key=lambda r: r["f"][key], reverse=(direction == "高好"))
            k = max(2, len(vs) // 3)
            rt = statistics.mean([bt._apply_cost(r["fwd"]) * 100 for r in vs[:k]])
            rb = statistics.mean([bt._apply_cost(r["fwd"]) * 100 for r in vs[-k:]])
            pairs.append((d, rt, rb))
        if len(pairs) < 50:
            continue
        diff = [p[1] - p[2] for p in pairs]
        lo, hi = boot_ci(diff, lambda s: statistics.mean(s))
        h1 = statistics.mean([p[1] - p[2] for p in pairs if p[0] < SPLIT] or [0])
        h2 = statistics.mean([p[1] - p[2] for p in pairs if p[0] >= SPLIT] or [0])
        same = "✔" if (h1 > 0) == (h2 > 0) and abs(h1) > 0.3 and abs(h2) > 0.3 else " "
        print(f"{label[:14]:<16}{direction:<5}{statistics.mean([p[1] for p in pairs]):>9.2f}"
              f"{statistics.mean([p[2] for p in pairs]):>9.2f}{statistics.mean(diff):>8.2f}"
              f"{f'[{lo:+.1f},{hi:+.1f}]':>18}{h1:>7.2f}{h2:>7.2f} {same}")

    print("\n【判讀】✔ ＝前後半同號且都有一定幅度（最低門檻）。CI 跨 0 ＝這個特徵沒有證據。")
    print("⚠️ 有效獨立批次僅約 17 → 比率的誤差約 ±12pp，只有 CI 明顯不跨 0 且前後半同號才值得考慮。")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="analyze", choices=["collect", "analyze", "all"])
    a = ap.parse_args()
    if a.stage in ("collect", "all") or not os.path.exists(CACHE):
        collect()
    if a.stage in ("analyze", "all"):
        analyze()
