"""複驗「抑制追高（乖離扣分）」是不是方向反了（Andy 2026-07-25 要求，投資面審查提出）。

背景：`notify_tg.py` 對乖離（現價離 20 日均線幾 %）大的股票扣分，設計假設是「已經漲一大段
再追進去風險高」。但審查 agent 用兩年資料實測後說**方向相反**：乖離 >25% 組平均超額 +4.27pp、
乖離 <0 組僅 +0.05pp。這會推翻我自己的設計，所以必須自己複驗一次才動。

⚠️ 這支腳本要回答的不只是「哪一組平均超額高」，還有三個會改變結論的問題：
1. **扣掉交易成本後**還成立嗎？（今天已證實毛值會騙人）
2. **中位數**也是同方向嗎？（右偏分佈下平均可能被少數飆股主宰）
3. **風險調整後**呢？高乖離組通常波動也高，賺得多可能只是承擔更多風險。
4. **跨市況**是否穩定？（可能只在多頭成立）

跑法：python3 verify_bias_penalty.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipeline"))

import backtest_signals as bt          # noqa: E402
import history_store as hs            # noqa: E402
import build_data as bd               # noqa: E402

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipeline")
# 乖離分組（%）：與 notify_tg 的扣分級距對齊（≥12 扣1、≥15 扣2、≥20 扣3）
BUCKETS = [(-1e9, 0), (0, 6), (6, 12), (12, 15), (15, 20), (20, 25), (25, 1e9)]


def label(lo, hi):
    if lo < -1e8:
        return "<0"
    if hi > 1e8:
        return "≥25"
    return f"{lo:g}~{hi:g}"


def stats(vals):
    if not vals:
        return None
    n = len(vals)
    v = sorted(vals)
    mean = sum(v) / n
    med = v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2
    var = sum((x - mean) ** 2 for x in v) / (n - 1) if n > 1 else 0.0
    sd = var ** 0.5
    return {"n": n, "mean": mean, "med": med, "sd": sd,
            "win": sum(1 for x in v if x > 0) / n,
            "per_risk": (mean / sd if sd > 0 else 0.0)}


def main():
    chip = hs.load(os.path.join(HERE, "history", "chip.json"))
    divs = hs.load(os.path.join(HERE, "history", "dividends.json"))
    with open(os.path.join(HERE, "universe.json"), encoding="utf-8") as f:
        uni = json.load(f)["stocks"]
    bt_hist = hs.load(os.path.join(HERE, "history", "bt_price.json")) or hs.bt_empty()
    long_price = hs.bt_to_price_hist(bt_hist)
    print(f"回測歷史 {len(bt_hist['dates'])} 交易日、{len(bt_hist['stocks'])} 檔", flush=True)

    regime = bt.build_regime_series(long_price, divs)
    breaks = __import__("price_breaks").load_breaks()
    print("逐檔逐日重算指標並依乖離分組（重活，數分鐘）…", flush=True)

    # 逐檔重跑一次 collect_events 的核心迴圈，但額外記下當時的 bias20_pct。
    # 不能直接用 collect_events 的輸出——它沒存 bias20。
    import bisect
    by_date_ret = {}
    rows = []          # (date, bias20, gross_ret)
    for stock in uni:
        sid = stock["id"]
        pr = hs.to_price_rows(long_price.get(sid, {}))
        if len(pr) < bt.MIN_BARS + bt.FORWARD + 1:
            continue
        pr = sorted(pr, key=lambda r: r["date"])
        cr = hs.to_chip_rows(chip.get(sid, {}))
        ev = hs.to_div_events(divs.get(sid))
        adj = [r["close"] for r in bd.back_adjust_rows(pr, ev)]
        brk = sorted(j for j, r in enumerate(pr) if (sid, r["date"]) in breaks) if breaks else []
        for i in range(bt.MIN_BARS - 1, len(pr) - bt.FORWARD):
            base = adj[i]
            if not base:
                continue
            if brk:
                lo = bisect.bisect_right(brk, i)
                if lo < len(brk) and brk[lo] <= i + bt.FORWARD:
                    continue
            di = pr[i]["date"]
            ind = bd.compute_indicators(pr[:i + 1], [c for c in cr if c["date"] <= di], ev, None)
            if ind is None or (ind.get("avg_vol_lots", 0) or 0) < bt.BACKTEST_MIN_VOL:
                continue
            ret = adj[i + bt.FORWARD] / base - 1
            by_date_ret.setdefault(di, []).append(ret)
            b = ind.get("bias20_pct")
            if b is not None:
                rows.append((di, b, ret))

    bench = {d: sum(v) / len(v) for d, v in by_date_ret.items() if v}
    print(f"樣本 {len(rows)} 筆、基準日 {len(bench)} 天\n", flush=True)

    def bucket_of(b):
        for lo, hi in BUCKETS:
            if lo <= b < hi:
                return label(lo, hi)
        return label(*BUCKETS[-1])

    # 全樣本
    groups, groups_net = {}, {}
    reg_groups = {}
    for d, b, ret in rows:
        bmk = bench.get(d, 0.0)
        key = bucket_of(b)
        groups.setdefault(key, []).append((ret - bmk) * 100)
        groups_net.setdefault(key, []).append((bt._apply_cost(ret) - bmk) * 100)
        reg_groups.setdefault((key, regime.get(d, "unknown")), []).append((bt._apply_cost(ret) - bmk) * 100)

    order = [label(lo, hi) for lo, hi in BUCKETS]
    print("=" * 96)
    print("乖離分組 × 超額報酬（pp）——毛 vs 成本後，含中位數與風險調整")
    print("=" * 96)
    print(f"{'乖離%':<8}{'樣本':>8}{'毛平均':>9}{'成本後':>9}{'成本後中位':>11}{'贏大盤':>8}{'標準差':>8}{'每單位風險':>11}")
    print("-" * 96)
    for k in order:
        g, gn = groups.get(k), groups_net.get(k)
        if not g:
            continue
        sg, sn = stats(g), stats(gn)
        print(f"{k:<8}{sn['n']:>8}{sg['mean']:>9.2f}{sn['mean']:>9.2f}{sn['med']:>11.2f}"
              f"{sn['win'] * 100:>7.1f}%{sn['sd']:>8.1f}{sn['per_risk']:>11.3f}")

    print("\n" + "=" * 96)
    print("跨市況檢查（成本後超額，pp）——只在多頭成立的話就不能拿掉扣分")
    print("=" * 96)
    print(f"{'乖離%':<8}" + "".join(f"{r:>14}" for r in ("green", "yellow", "red")))
    print("-" * 96)
    for k in order:
        if k not in groups_net:
            continue
        cells = []
        for r in ("green", "yellow", "red"):
            s = stats(reg_groups.get((k, r), []))
            cells.append(f"{s['mean']:>8.2f}({s['n']})" if s and s["n"] >= 30 else f"{'—':>14}")
        print(f"{k:<8}" + "".join(f"{c:>14}" for c in cells))

    print("\n【判讀指引】")
    print("  要「移除乖離扣分」成立，需同時滿足：①成本後平均隨乖離遞增 ②中位數同方向")
    print("  ③每單位風險不因高乖離而變差 ④三種市況都不逆轉。任一條不成立就不該全面移除。")


if __name__ == "__main__":
    main()
