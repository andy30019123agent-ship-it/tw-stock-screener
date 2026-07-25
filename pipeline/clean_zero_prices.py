"""清掉 price.json 裡「假 0 元」的歷史列（Andy 2026-07-25 授權）。

背景：TWSE 對零股／極低量成交會回傳字串 "0.00"（而不是 "--"），`market_sources._f()` 把它
當成合法浮點數 0.0，`_ohlc()` 的 None 檢查攔不到 → 整列 open=high=low=close=0.0 寫進歷史。
實測 36 筆、15 檔低量股（例：1213 於 2026-07-16 量 1 張、成交金額 7 元，卻記成收盤 0）。

`market_sources._ohlc()` 已加 `close <= 0` 防呆（擋新的），這支負責清既有的。

處理方式＝**整列刪除**，不是補值：那天確實沒有形成有效成交價，「沒有資料」才是事實。
下游 `to_price_rows` 本來就要處理有缺口的序列（停牌、新上市），少一天不會壞。

安全設計：
- 預設 dry-run，只報告不動檔；要真的寫入必須加 `--apply`。
- `--apply` 前自動備份成 price.json.bak-<時間戳>（時間戳由 --stamp 傳入，避免腳本內取時間）。
- 只刪「四個價格全部 <= 0」的列。只要有任一價格是正常值就保留（那種是別的問題，不在此處理）。

跑法：
    python3 pipeline/clean_zero_prices.py                      # 先看要刪什麼
    python3 pipeline/clean_zero_prices.py --apply --stamp 20260725_1400
"""
import argparse
import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
PRICE_PATH = os.path.join(HERE, "history", "price.json")


def find_zero_rows(price):
    """回 [(sid, date, row)]：四個價格全部 <= 0（或 None）的列。"""
    bad = []
    for sid, by in price.items():
        for date, row in by.items():
            prices = row[:4]
            if all((v is None or v <= 0) for v in prices):
                bad.append((sid, date, row))
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真的寫入（預設只做 dry-run 報告）")
    ap.add_argument("--stamp", default="manual", help="備份檔名用的時間戳（呼叫端傳入）")
    ap.add_argument("--path", default=PRICE_PATH)
    args = ap.parse_args()

    with open(args.path, encoding="utf-8") as f:
        price = json.load(f)

    bad = find_zero_rows(price)
    sids = sorted({b[0] for b in bad})
    print(f"發現假 0 元列 {len(bad)} 筆，涉及 {len(sids)} 檔：{', '.join(sids)}")
    for sid, date, row in sorted(bad)[:10]:
        print(f"   {sid} {date} → o/h/l/c={row[:4]} vol={row[4] if len(row) > 4 else '?'}")
    if len(bad) > 10:
        print(f"   …其餘 {len(bad) - 10} 筆")

    # 刪完之後每檔剩幾天——不能把某檔清成空的或短到算不出指標而沒人發現
    left = {}
    for sid in sids:
        left[sid] = len(price[sid]) - sum(1 for b in bad if b[0] == sid)
    thin = {s: n for s, n in left.items() if n < 65}
    print(f"\n刪除後天數 <65（算不出 MA60，會從選股清單消失）的檔：{thin or '無'}")

    if not args.apply:
        print("\n（dry-run，未寫入。要真的清請加 --apply）")
        return

    backup = f"{args.path}.bak-{args.stamp}"
    shutil.copy2(args.path, backup)
    print(f"\n已備份 → {os.path.relpath(backup)}")

    for sid, date, _ in bad:
        del price[sid][date]
    empty = [s for s in sids if not price[s]]
    for s in empty:
        del price[s]
    with open(args.path, "w", encoding="utf-8") as f:
        json.dump(price, f, ensure_ascii=False, separators=(",", ":"))

    after = find_zero_rows(price)
    print(f"✅ 已刪 {len(bad)} 筆；重掃剩餘假 0 元列：{len(after)} 筆"
          f"{'（清空的股票代號：' + ', '.join(empty) + '）' if empty else ''}")


if __name__ == "__main__":
    main()
