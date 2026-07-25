"""評估 TG 快報備援排序的候選門檻該設多少（Andy 2026-07-25 要求：不要隨便都出現、也不要太極端）。

背景：`notify_tg.score()` 從「手寫 +2/+3」改成「加總回測權重」後，分數量級從最高 15 變成最高 6，
原本的門檻 `>= 4` 是照舊量級訂的，必須重新校準。今天實測 ≥4 剛好 5 檔，但那可能是巧合。

做法：跑一次 collect_events（與正式回測同一支），對每個歷史交易日算「有幾檔的權重加總 ≥ N」，
看每個門檻在 479 個交易日裡有多少天湊不滿 5 檔。這才是「會不會很難出現」的真答案。

⚠️ 一個已知的近似：真正的 score() 還會對乖離過大者扣 1~3 分（抑制追高），這裡算的是扣分前的
權重加總，所以是樂觀估計（實際候選數會比這裡少一些）。今天的實測值（含扣分）可當校準錨點。

跑法：python3 eval_notify_threshold.py
"""
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipeline"))
import backtest_signals as bt          # noqa: E402
import history_store as hs             # noqa: E402

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipeline")


def main():
    price = hs.load(os.path.join(HERE, "history", "price.json"))
    chip = hs.load(os.path.join(HERE, "history", "chip.json"))
    divs = hs.load(os.path.join(HERE, "history", "dividends.json"))
    with open(os.path.join(HERE, "universe.json"), encoding="utf-8") as f:
        uni = json.load(f)["stocks"]
    weights = (bt._load(bt.WEIGHTS_PATH) or {}).get("signals", {})

    engine_w = {k: (weights.get(k) or {}).get("weight", 0) or 0 for k in bt.ENGINE_SIGNALS}
    engine_w = {k: v for k, v in engine_w.items() if v}
    print(f"引擎訊號權重：{engine_w}")
    print(f"理論最高分（全部同時成立）：{sum(engine_w.values())}\n")

    bt_hist = hs.load(os.path.join(HERE, "history", "bt_price.json")) or hs.bt_empty()
    long_price = hs.bt_to_price_hist(bt_hist)
    print(f"回測歷史 {len(bt_hist['dates'])} 交易日，開始收集事件（數分鐘）…", flush=True)
    events, _ = bt.collect_events(long_price, chip, divs, uni)
    print(f"事件 {len(events)} 筆\n", flush=True)

    # 每個交易日、每檔的權重加總（用 raw_fired＝當天真的成立的訊號，不受冷卻影響，
    # 因為 notify 是「今天」的快照，沒有冷卻概念）
    per_day = {}
    for e in events:
        sc = sum(engine_w.get(k, 0) for k in (e.get("raw_fired") or e.get("fired") or []))
        if sc > 0:
            per_day.setdefault(e["date"], []).append(sc)

    days = sorted(per_day)
    print(f"有候選的交易日：{len(days)} / {len(bt_hist['dates'])}\n")
    print(f"{'門檻':<6}{'平均候選數':>10}{'中位':>8}{'湊不滿5檔的天數':>16}{'完全0檔的天數':>15}")
    print("-" * 58)
    total_days = len(bt_hist["dates"])
    for th in (1, 2, 3, 4, 5, 6):
        counts = []
        for d in bt_hist["dates"]:
            counts.append(sum(1 for sc in per_day.get(d, []) if sc >= th))
        counts_sorted = sorted(counts)
        avg = sum(counts) / len(counts)
        med = counts_sorted[len(counts_sorted) // 2]
        under5 = sum(1 for c in counts if c < 5)
        zero = sum(1 for c in counts if c == 0)
        print(f"≥{th:<5}{avg:>10.1f}{med:>8}{under5:>10} ({under5 / total_days * 100:.0f}%)"
              f"{zero:>9} ({zero / total_days * 100:.0f}%)")

    print("\n各分數出現次數（所有日 × 所有檔）：")
    allsc = Counter(sc for v in per_day.values() for sc in v)
    print("  " + "  ".join(f"{k}分:{v}" for k, v in sorted(allsc.items(), reverse=True)))


if __name__ == "__main__":
    main()
