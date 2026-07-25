"""驗證「訊號戰績是否完全靠最極端 1% 事件撐起來」（2026-07-25 審查 🔴1，全樣本複驗）。

審查 agent 只跑了子樣本（n=230~778，實際全樣本 2273~8146）並自標「需全市場重跑」。
這支腳本用完整 479 交易日重算，對每個訊號輸出：平均超額、中位數、去頂 1%/2% 後的平均、
5% trimmed mean、單筆最大值、贏過大盤的比例。唯讀，不寫任何檔案。

跑法：python3 verify_outlier_dependence.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipeline"))

import backtest_signals as bt          # noqa: E402
import history_store as hs             # noqa: E402

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipeline")


def pct(sorted_vals, q):
    if not sorted_vals:
        return None
    i = min(len(sorted_vals) - 1, max(0, int(round(q * (len(sorted_vals) - 1)))))
    return sorted_vals[i]


def mean(v):
    return sum(v) / len(v) if v else None


def drop_top(sorted_vals, frac):
    """去掉最高的 frac 比例（至少去 1 筆，若樣本夠）。"""
    k = int(len(sorted_vals) * frac)
    if frac > 0 and k == 0 and len(sorted_vals) > 20:
        k = 1
    return sorted_vals[:len(sorted_vals) - k] if k else sorted_vals


def trimmed(sorted_vals, frac):
    """兩端各去 frac。"""
    k = int(len(sorted_vals) * frac)
    return sorted_vals[k:len(sorted_vals) - k] if k and len(sorted_vals) - 2 * k > 0 else sorted_vals


def main():
    price = hs.load(os.path.join(HERE, "history", "price.json"))
    chip = hs.load(os.path.join(HERE, "history", "chip.json"))
    divs = hs.load(os.path.join(HERE, "history", "dividends.json"))
    with open(os.path.join(HERE, "universe.json"), encoding="utf-8") as f:
        uni = json.load(f)["stocks"]

    bt_hist = hs.load(os.path.join(HERE, "history", "bt_price.json")) or hs.bt_empty()
    long_price = hs.bt_to_price_hist(bt_hist)
    print(f"全樣本回測歷史：{len(bt_hist['dates'])} 交易日、{len(bt_hist['stocks'])} 檔", flush=True)

    print("建立橫斷面 PIT 快取…", flush=True)
    xsect = bt.build_xsect_cache(long_price, divs, uni)
    print("收集事件（重活，數分鐘）…", flush=True)
    events, by_date = bt.collect_events(long_price, chip, divs, uni, xsect=xsect)
    print(f"事件數：{len(events)}、有基準的交易日：{len(by_date)}", flush=True)

    # 同日基準（跟 events_to_stats 一致：該日所有可評估個股的平均報酬）
    bench = {d: mean(v) for d, v in by_date.items()}

    # 每個訊號蒐集「超額」樣本。單訊號統計吃 eligible_fired（與正式權重同路徑）。
    per_sig = {}
    for e in events:
        b = bench.get(e["date"])
        if b is None:
            continue
        exc = (e["ret"] - b) * 100
        for s in e.get("eligible_fired") or e.get("fired") or []:
            per_sig.setdefault(s, []).append(exc)

    label = {}
    w = bt._load(bt.WEIGHTS_PATH).get("signals") or {}
    for k, v in w.items():
        label[k] = v.get("label", k)

    rows = []
    for sig, vals in per_sig.items():
        v = sorted(vals)
        n = len(v)
        rows.append({
            "sig": sig, "label": label.get(sig, sig), "n": n,
            "mean": mean(v), "median": pct(v, 0.5),
            "drop1": mean(drop_top(v, 0.01)), "drop2": mean(drop_top(v, 0.02)),
            "trim5": mean(trimmed(v, 0.05)),
            "max": v[-1], "min": v[0],
            "win": sum(1 for x in v if x > 0) / n,
        })
    rows.sort(key=lambda r: -(r["mean"] or 0))

    print("\n" + "=" * 108)
    print("全樣本：去極值後平均超額還剩多少（單位 pp）")
    print("=" * 108)
    hdr = f"{'訊號':<14}{'n':>6}{'平均':>8}{'中位':>8}{'去頂1%':>9}{'去頂2%':>9}{'兩端5%':>9}{'單筆max':>10}{'贏大盤%':>9}"
    print(hdr)
    print("-" * 108)
    for r in rows:
        print(f"{r['label']:<14}{r['n']:>6}{r['mean']:>8.2f}{r['median']:>8.2f}"
              f"{r['drop1']:>9.2f}{r['drop2']:>9.2f}{r['trim5']:>9.2f}"
              f"{r['max']:>10.1f}{r['win'] * 100:>9.1f}")

    flip = [r for r in rows if (r["mean"] or 0) > 0 and (r["drop1"] or 0) <= 0]
    flip2 = [r for r in rows if (r["mean"] or 0) > 0 and (r["drop2"] or 0) <= 0]
    print("-" * 108)
    print(f"平均為正、但去掉最高 1% 就 ≤0 的訊號：{len(flip)}/{len([r for r in rows if (r['mean'] or 0) > 0])}"
          f" → {[r['label'] for r in flip]}")
    print(f"平均為正、但去掉最高 2% 就 ≤0 的訊號：{len(flip2)}"
          f" → {[r['label'] for r in flip2]}")


if __name__ == "__main__":
    main()
