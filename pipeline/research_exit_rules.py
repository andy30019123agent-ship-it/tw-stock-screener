#!/usr/bin/env python3
"""出場研究（2026-11-13）：候選股買了之後，看錯時大概跌多少該賣？

研究腳本，不進每日管線；唯一例外：跑完會寫 pipeline/exit_rules_summary.json 給網站「停損代價表」讀（手動重跑才更新）。報告：_reports/研究_出場規則_2026-11-13.md

母體：逐日重播線上 opportunities.build_opportunities 後的候選池（與 tier_stats.compute_pool_tier_stats
同一套：collect_events(pool_rows=...) → tier_stats.replay_pool_days）。不是「所有訊號事件」。
進場：訊號日隔日開盤（還原價）。對照組：固定持有 20 個交易日、第 20 日收盤出場
（進場日算第 1 天 → 出場 index＝entry_i+19，與 collect_events 的 _ret 同口徑，程式會逐筆核對）。
成本：backtest_signals._net_return（＝_apply_cost 同一把尺，乘除式）。

出場規則在跑之前就全部列好（RULES），跑完不增刪：
  固定停損 −5/−8/−10/−12/−15/−20%（以進場價計）、移動停損（自進場後最高收盤回落 −8/−10/−15%）、
  跌破月線（還原收盤 < 還原 MA20），各自都有時間上限（20 日主結果、40 日看結論會不會翻轉）。
  驗收後追加一條（2026-11-13 驗收 🟢9，唯一的增補）：網站預設防守價
  「−15% 與月線取較高者」（src/lib/position.js defendPrice：訊號日收盤 ×0.85，若 0.85×收盤 < MA20 < 收盤
  則改用 MA20；訊號日定好的固定價位，盤中最低碰到即觸發）。

成交假設（FILLS）：
  next_open（保守，主結果）：當天盤中最低價碰到停損價（月線規則是收盤跌破）→ **隔日開盤**賣，
             隔日開盤跳空多低就吃多低（也可能比停損價高）。若觸發日剛好是時間上限最後一天，
             那天收盤本來就要賣 → 用當天收盤。
  same_day（樂觀上限）：停損價當天成交；當天開盤就已跳空跌破停損價則只能拿開盤價。
             月線規則用當天收盤。現實做不到這麼好（跌停鎖死賣不掉、盯盤延遲），只當上限看。

跑法（一行，約 8 分鐘：2026-11-13 本機實測 479 秒，幾乎全花在逐檔逐日重算指標＋重播候選池；
有 --cache 時約 17 秒）：
    python3 pipeline/research_exit_rules.py
加 --cache PATH 可把重播後的候選清單存起來，第二次起直接讀（只省時間，不改結果）；
加 --out PATH 把數字表（Markdown）另存一份。
"""
import argparse
import bisect
import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import backtest_signals as bt   # noqa: E402
import history_store as hs      # noqa: E402
import tier_stats as ts         # noqa: E402

CONTROL_DAYS = 20
CAPS = (20, 40)
FILLS = ("next_open", "same_day")
# (key, kind, param, label)——先寫死再跑，不可依結果增刪
RULES = (
    [("hold", "hold", None, "固定持有（對照組）")]
    + [(f"stop{int(x * 100)}", "fixed", x, f"固定停損 −{int(x * 100)}%")
       for x in (0.05, 0.08, 0.10, 0.12, 0.15, 0.20)]
    + [(f"trail{int(x * 100)}", "trail", x, f"移動停損 高點回落 −{int(x * 100)}%")
       for x in (0.08, 0.10, 0.15)]
    + [("ma20", "ma20", None, "收盤跌破月線")]
    # ↓ 驗收後追加（2026-11-13 驗收報告 🟢9）：網站現行預設防守價 src/lib/position.js defendPrice。
    #   除這一條外規則清單不增刪。
    + [("site15ma", "site", 0.15, "網站預設 −15%／月線取較高者（驗收後追加）")]
)
BLOCK = 20
N_BOOT = 1000
SEED = 20261113
MAE_LEVELS = (0.05, 0.08, 0.10, 0.15)


# ── 純函式（有單測）──────────────────────────────────────────────────────────
def site_stop_level(c, sig_i, pct=0.15):
    """照 src/lib/position.js defendPrice 算「網站預設防守價」（一個固定價位，訊號日當天算好）：
    stop＝訊號日收盤 ×(1−pct)；ma20＝訊號日（含）前 20 根收盤平均；
    只有 stop < ma20 < 收盤 時用月線，否則用 stop（月線在現價之上不算防守位）。
    用還原價：還原是乘法係數，同一天的 ma20／收盤比值與 point-in-time 相同。"""
    close = c[sig_i]
    stop = close * (1 - pct)
    ma20 = sum(c[sig_i - 19:sig_i + 1]) / 20 if sig_i >= 19 else None
    if ma20 is not None and stop < ma20 < close:
        return ma20
    return stop


def simulate_exit(o, h, l, c, entry_i, kind, param, cap, fill="next_open"):
    """單筆交易模擬。o/h/l/c 為同一檔的還原 OHLC（list，同 index）。
    進場＝o[entry_i]；進場日算第 1 天，時間上限出場＝c[entry_i+cap-1]。
    回 dict：gross（毛報酬）、net（成本後）、hold（持有交易日數，賣出那天也算）、
            stopped（是否被規則觸發）、trigger_day（第幾天觸發，None＝沒觸發）。"""
    entry = o[entry_i]
    last = entry_i + cap - 1
    peak = entry
    site_level = site_stop_level(c, entry_i - 1, param) if kind == "site" else None

    def done(px, hold, stopped, trig):
        return {"gross": px / entry - 1, "net": bt._net_return(entry, px), "hold": hold,
                "stopped": stopped, "trigger_day": trig}

    for k in range(cap):
        t = entry_i + k
        level = None
        if kind == "hold":
            hit = False
        elif kind == "fixed":
            level = entry * (1 - param)
            hit = l[t] <= level
        elif kind == "trail":
            level = peak * (1 - param)          # peak＝進場價與「昨天以前」收盤的最高者（盤中只知道這些）
            hit = l[t] <= level
        elif kind == "ma20":
            ma = sum(c[t - 19:t + 1]) / 20
            hit = c[t] < ma
        elif kind == "site":
            level = site_level                  # 訊號日就定好的固定價位（盤中最低碰到即觸發）
            hit = l[t] <= level
        else:
            raise ValueError(kind)
        if hit:
            if fill == "same_day":
                px = c[t] if level is None else min(level, o[t])
                return done(px, k + 1, True, k + 1)
            if t == last:                        # 時間上限當天：收盤本來就要賣
                return done(c[t], cap, True, k + 1)
            return done(o[t + 1], k + 2, True, k + 1)   # 保守：隔日開盤，跳空多低吃多低
        if kind == "trail":
            peak = max(peak, c[t])
    return done(c[last], cap, False, None)


def window_has_break(brk_idx, lo, hi):
    """brk_idx（已排序的斷點 index）裡有沒有落在 [lo, hi] 的。"""
    j = bisect.bisect_left(brk_idx, lo)
    return j < len(brk_idx) and brk_idx[j] <= hi


def percentile(vals, pct):
    s = sorted(vals)
    return ts._percentile(s, pct) if s else None


# ── 母體：候選池重播 ─────────────────────────────────────────────────────────
def build_candidates():
    """與 measure_both_tier.main 同一套載入流程，回候選清單 [{date, sid, tier, gate, ret}]。"""
    t0 = time.time()
    bt_hist = hs.load(bt.BT_PRICE_PATH)
    price = hs.bt_to_price_hist(bt_hist)
    chip = hs.load(os.path.join(HERE, "history", "chip.json")) or {}
    divs = hs.load(os.path.join(HERE, "history", "dividends.json")) or {}
    with open(os.path.join(HERE, "universe.json"), encoding="utf-8") as f:
        uni = json.load(f)["stocks"]
    weights = bt._load(bt.WEIGHTS_PATH) or {}
    xsect = bt.build_xsect_cache(price, divs, uni)
    print(f"橫斷面快取 {len(xsect)} 天（{time.time() - t0:.0f}s）", flush=True)
    pool_rows = {}
    bt.collect_events(price, chip, divs, uni, xsect=xsect, pool_rows=pool_rows)
    print(f"候選列 {sum(len(v) for v in pool_rows.values())} 筆（{time.time() - t0:.0f}s）", flush=True)
    out = []
    for date, opp, ret_by_id in ts.replay_pool_days(pool_rows, weights):
        gate = bool((opp.get("gate") or {}).get("applied"))
        for p in opp["picks"]:
            out.append({"date": date, "sid": p["id"], "tier": p.get("tier") or "unclassified",
                        "bias_high": bool(p.get("bias_high")),
                        "gate": gate, "ret": ret_by_id.get(p["id"])})
    print(f"重播完成：{len(out)} 筆候選（{time.time() - t0:.0f}s）", flush=True)
    return out


def load_ohlc():
    """每檔還原 OHLC 序列（與 collect_events 同：bt_to_price_hist → to_price_rows → back_adjust_rows）。"""
    import build_data as bd
    import price_breaks as pb
    price = hs.bt_to_price_hist(hs.load(bt.BT_PRICE_PATH))
    divs = hs.load(os.path.join(HERE, "history", "dividends.json")) or {}
    breaks = pb.load_breaks()
    out = {}
    for sid, by in price.items():
        pr = sorted(hs.to_price_rows(by), key=lambda r: r["date"])
        adj = bd.back_adjust_rows(pr, hs.to_div_events(divs.get(sid)))
        out[sid] = {
            "idx": {r["date"]: j for j, r in enumerate(pr)},
            "o": [r["open"] for r in adj], "h": [r["max"] for r in adj],
            "l": [r["min"] for r in adj], "c": [r["close"] for r in adj],
            "brk": sorted(j for j, r in enumerate(pr) if (sid, r["date"]) in breaks),
        }
    return out


# ── 統計 ────────────────────────────────────────────────────────────────────
def summarize(trades):
    """trades：[{net, hold, stopped, recovered}]（recovered 只對 stopped 有意義）。"""
    n = len(trades)
    if not n:
        return {"n": 0}
    nets = sorted(t["net"] for t in trades)
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x <= 0]
    stopped = [t for t in trades if t["stopped"]]
    return {
        "n": n,
        "win": len(wins) / n,
        "mean": sum(nets) / n,
        "median": ts._percentile(nets, 50),
        "avg_win": sum(wins) / len(wins) if wins else None,
        "avg_loss": sum(losses) / len(losses) if losses else None,
        "p5": ts._percentile(nets, 5),
        "worst": nets[0],
        "stop_rate": len(stopped) / n,
        "recover_win": (sum(1 for t in stopped if t["recovered"]) / len(stopped)) if stopped else None,
        "recover_better": (sum(1 for t in stopped if t["better"]) / len(stopped)) if stopped else None,
        "hold": sum(t["hold"] for t in trades) / n,
    }


def paired(rule_tr, ctrl_tr, dates, rng_seed=SEED, block=BLOCK):
    """同一批進場的配對差：每筆 d＝規則淨報酬 − 對照淨報酬；先算每天平均，再對日序列
    circular block bootstrap（預設 block=20，持有期重疊 → 相鄰日高度相關）。單位 pp。"""
    by_d, by_w = {}, {}
    for r, c_, d in zip(rule_tr, ctrl_tr, dates):
        by_d.setdefault(d, []).append((r["net"] - c_["net"]) * 100)
        by_w.setdefault(d, []).append(((r["net"] > 0) - (c_["net"] > 0)) * 100)
    days = sorted(by_d)
    ev = [sum(by_d[d]) / len(by_d[d]) for d in days]
    wn = [sum(by_w[d]) / len(by_w[d]) for d in days]
    if not days:
        return {"days": 0}
    half = len(days) // 2
    return {
        "days": len(days), "blocks": len(days) // block,
        "ev_pp": sum(ev) / len(ev), "ev_ci": ts._circular_mean_ci(ev, block, N_BOOT, random.Random(rng_seed)),
        "win_pp": sum(wn) / len(wn), "win_ci": ts._circular_mean_ci(wn, block, N_BOOT, random.Random(rng_seed)),
        "ev_first": sum(ev[:half]) / max(half, 1), "ev_second": sum(ev[half:]) / max(len(ev) - half, 1),
        "split": days[half] if half < len(days) else None,
    }


def circular_ratio_ci(sums, counts, block, n_boot=N_BOOT, rng=None):
    """「按筆平均」的 90% CI：按日的 (總和, 筆數) 序列做 circular block bootstrap（與 _circular_mean_ci
    同一種抽法，截成恰好 n 天），每次算 Σ總和／Σ筆數——同一天的筆數一起抽，保留同日相關。"""
    n = len(sums)
    if n == 0:
        return None
    rng = rng or random.Random(SEED)
    b = min(block, n)
    vals = []
    for _ in range(n_boot):
        picked = []
        while len(picked) < n:
            s = rng.randrange(n)
            picked.extend((s + k) % n for k in range(b))
        picked = picked[:n]
        cnt = sum(counts[j] for j in picked)
        vals.append(sum(sums[j] for j in picked) / cnt)
    vals.sort()
    return [round(ts._percentile(vals, 5), 2), round(ts._percentile(vals, 95), 2)]


def hold_vs_sell(stop_tr, hold_tr, dates, max_day=5, blocks=(20, 40)):
    """驗收 🔴1 的「可操作版本」：停損規則在前 max_day 天內（含進場日）觸發的那批，
    「續抱到時間上限」vs「觸發後隔日開盤賣」（＝停損規則本身的成交）誰好。
    stop_tr／hold_tr／dates 同 index 對齊。差＝續抱淨報酬 − 賣出淨報酬（正＝續抱較好）。
    回：n、按筆平均差 pp、續抱較好比例、每日一票的平均與各 block 長度的 90% CI。"""
    idx = [j for j, t in enumerate(stop_tr)
           if t["stopped"] and t["trigger_day"] is not None and t["trigger_day"] <= max_day]
    if not idx:
        return {"n": 0}
    diffs = [(hold_tr[j]["net"] - stop_tr[j]["net"]) * 100 for j in idx]
    out = {"n": len(idx), "per_trade_pp": sum(diffs) / len(diffs),
           "hold_better": sum(1 for d in diffs if d > 0) / len(diffs),
           "hold_win": sum(1 for j in idx if hold_tr[j]["net"] > 0) / len(idx),
           "sell_win": sum(1 for j in idx if stop_tr[j]["net"] > 0) / len(idx)}
    sub_h = [hold_tr[j] for j in idx]
    sub_s = [stop_tr[j] for j in idx]
    sub_d = [dates[j] for j in idx]
    by_day = {}
    for d, x in zip(sub_d, diffs):
        by_day.setdefault(d, []).append(x)
    days = sorted(by_day)
    sums = [sum(by_day[d]) for d in days]
    cnts = [len(by_day[d]) for d in days]
    for b in blocks:
        p = paired(sub_h, sub_s, sub_d, block=b)
        out["days"] = p["days"]
        out["per_day_pp"] = p["ev_pp"]
        out[f"per_day_ci_b{b}"] = p["ev_ci"]
        out[f"per_trade_ci_b{b}"] = circular_ratio_ci(sums, cnts, b, rng=random.Random(SEED))
    return out


def verdict(ci):
    if not ci:
        return "—"
    if ci[0] > 0:
        return "較好"
    if ci[1] < 0:
        return "較差"
    return "量不出差別"


def run(cands, ohlc):
    """回 (results dict, markdown 字串)。"""
    res = {"n_candidates": len(cands)}
    md = []
    # ---- 對應到價格 index，套斷點排除 ----
    base = []
    mismatch = n_unmeas = n_nomap = 0
    for cd in cands:
        if cd["ret"] is None:
            n_unmeas += 1
            continue
        s = ohlc.get(cd["sid"])
        i = s["idx"].get(cd["date"]) if s else None
        if i is None:
            n_nomap += 1
            continue
        e = i + 1
        # 斷點排除：窗 [entry_i, entry_i+cap-1]（＝collect_events 的 (i, i+20]）
        ok = {cap: (e + cap - 1 < len(s["c"]) and not window_has_break(s["brk"], e, e + cap - 1))
              for cap in CAPS}
        if not ok[CONTROL_DAYS]:
            n_unmeas += 1
            continue
        g = s["c"][e + CONTROL_DAYS - 1] / s["o"][e] - 1
        if abs(g - cd["ret"]) > 1e-9:
            mismatch += 1
        base.append((cd, s, e, ok))
    res.update({"n_measurable": len(base), "n_unmeasurable": n_unmeas, "n_unmapped": n_nomap,
                "ret_mismatch": mismatch})
    md.append(f"- 候選總筆數 {len(cands):,}；可量測 {len(base):,}；報酬量不出來（跨斷點／缺價）{n_unmeas}；"
              f"對不到價格 {n_nomap}；持有 20 日報酬與 collect_events 不一致 {mismatch} 筆（應為 0）")

    # ---- 模擬所有規則 ----
    sims = {}   # (cap, fill, key) -> list of trades（與 subset 的 base 對齊）
    for cap in CAPS:
        sub = [b for b in base if b[3][cap]]
        for fill in FILLS:
            for key, kind, param, _ in RULES:
                trs = []
                for cd, s, e, _ok in sub:
                    trs.append(simulate_exit(s["o"], s["h"], s["l"], s["c"], e, kind, param, cap, fill))
                sims[(cap, fill, key)] = trs
        res[f"n_cap{cap}"] = len(sub)
    sub_of = {cap: [b for b in base if b[3][cap]] for cap in CAPS}
    # 對照組（固定持有 20 日）在各 cap 子集上的結果
    ctrl = {}
    for cap in CAPS:
        ctrl[cap] = [simulate_exit(s["o"], s["h"], s["l"], s["c"], e, "hold", None, CONTROL_DAYS)
                     for _cd, s, e, _ok in sub_of[cap]]
    # 加上 recovered／better：被停損的那筆，若照樣抱到時間上限，會不會賺／會不會比較好
    for (cap, fill, key), trs in sims.items():
        hold_cap = sims[(cap, "next_open", "hold")]
        for t, hc in zip(trs, hold_cap):
            t["recovered"] = hc["net"] > 0
            t["better"] = hc["net"] > t["net"]

    def pct(x, d=1):
        return "—" if x is None else f"{x * 100:+.{d}f}%"

    def rate(x):
        return "—" if x is None else f"{x * 100:.1f}%"

    def ci_s(ci):
        return "—" if not ci else f"{ci[0]:+.2f}～{ci[1]:+.2f}"

    label = {k: lab for k, _, _, lab in RULES}
    _d20 = sorted(b[0]["date"] for b in sub_of[CONTROL_DAYS])
    res["meta20"] = {"n": len(_d20), "signal_days": len(set(_d20)),
                     "first": _d20[0] if _d20 else None, "last": _d20[-1] if _d20 else None}
    res["summary"], res["paired"] = {}, {}
    n_cmp = {"main": 0, "robust": 0, "hold_vs_sell": 0}   # 有算 CI、拿來下判定的配對比較列數（多重比較用）
    for cap in CAPS:
        dates = [b[0]["date"] for b in sub_of[cap]]
        for fill in FILLS:
            fill_lab = "隔日開盤成交（保守，主結果）" if fill == "next_open" else "停損價當日成交（樂觀上限）"
            md.append(f"\n### 時間上限 {cap} 日｜{fill_lab}\n")
            md.append(f"樣本 {len(sub_of[cap]):,} 筆、{len(set(dates))} 個進場訊號日（約 {len(set(dates)) // BLOCK} 批獨立樣本）。"
                      "「被停損後會回來」＝那筆若照樣抱到時間上限，最後是賺的比例；「續抱較好」＝抱到上限比停損出場報酬高的比例。\n")
            md.append("| 規則 | 樣本 | 賺錢機率 | 平均 | 中位 | 賺時平均 | 賠時平均 | 最差 5% | 最差單筆 | 被停損比例 | 被停損後會回來 | 續抱較好 | 平均持有天數 |")
            md.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
            for key, *_ in RULES:
                sm = summarize(sims[(cap, fill, key)])
                res["summary"][f"cap{cap}_{fill}_{key}"] = sm
                lab = label[key] if not (key == "hold" and cap != CONTROL_DAYS) else f"固定持有 {cap} 日"
                md.append(f"| {lab} | {sm['n']:,} | {rate(sm['win'])} | {pct(sm['mean'], 2)} | {pct(sm['median'], 2)} | "
                          f"{pct(sm['avg_win'])} | {pct(sm['avg_loss'])} | {pct(sm['p5'])} | {pct(sm['worst'])} | "
                          f"{rate(sm['stop_rate'])} | {rate(sm['recover_win'])} | {rate(sm['recover_better'])} | {sm['hold']:.1f} |")
            refs = [("對照組（持有 20 日）", ctrl[cap])]
            if cap != CONTROL_DAYS:
                refs.append((f"固定持有 {cap} 日", sims[(cap, "next_open", "hold")]))
            for ref_lab, ref in refs:
                md.append(f"\n配對差：規則 − {ref_lab}（同一批進場；先算每日平均再 block bootstrap，90% CI；單位：百分點 pp）\n")
                md.append("| 規則 | 平均每筆差 | 90% CI | 判定 | 賺錢機率差 | 90% CI | 前半段／後半段（每筆差） |")
                md.append("|---|---|---|---|---|---|---|")
                for key, *_ in RULES:
                    if key == "hold" and (cap == CONTROL_DAYS or ref is not ctrl[cap]):
                        continue
                    p = paired(sims[(cap, fill, key)], ref, dates)
                    res["paired"][f"cap{cap}_{fill}_{key}_vs_{'h20' if ref is ctrl[cap] else 'hcap'}"] = p
                    n_cmp["main"] += 1
                    lab = label[key] if key != "hold" else f"固定持有 {cap} 日"
                    md.append(f"| {lab} | {p['ev_pp']:+.2f} | {ci_s(p['ev_ci'])} | {verdict(p['ev_ci'])} | "
                              f"{p['win_pp']:+.2f} | {ci_s(p['win_ci'])} | {p['ev_first']:+.2f}／{p['ev_second']:+.2f}（切點 {p['split']}） |")

    # ---- 穩健性：主設定（cap20、保守成交）按子群拆開看配對差 ----
    cap, fill = CONTROL_DAYS, "next_open"
    rows = sub_of[cap]
    dates_all = sorted(set(b[0]["date"] for b in rows))
    split = dates_all[len(dates_all) // 2]
    groups = [
        ("前半段", lambda cd: cd["date"] < split), ("後半段", lambda cd: cd["date"] >= split),
        ("門檻有套用", lambda cd: cd["gate"]), ("門檻退回", lambda cd: not cd["gate"]),
        ("相對優勢", lambda cd: cd["tier"] == "edge"), ("其他候選", lambda cd: cd["tier"] != "edge"),
        ("乖離排前段（bias_high）", lambda cd: cd["bias_high"]),
        ("非乖離排前段", lambda cd: not cd["bias_high"]),
    ]
    md.append(f"\n### 穩健性：時間上限 20 日、隔日開盤成交，規則 − 對照組，按子群拆開（前後半切點 {split}）\n")
    n_gate_off = len(set(b[0]["date"] for b in rows if not b[0]["gate"]))
    md.append(f"每格＝平均每筆差 pp［90% CI］；★＝CI 不跨 0。子群天數少時 CI 很寬"
              f"（門檻退回只有 {n_gate_off} 天÷{BLOCK}≈{n_gate_off / BLOCK:.1f} 批獨立樣本）。\n")
    head = "| 規則 | " + " | ".join(g for g, _ in groups) + " |"
    md.append(head)
    md.append("|---" * (len(groups) + 1) + "|")
    sizes = []
    res["robust"] = {}
    for gname, fn in groups:
        idx = [j for j, b in enumerate(rows) if fn(b[0])]
        sizes.append(f"{gname} {len(idx):,} 筆／{len(set(rows[j][0]['date'] for j in idx))} 天")
    for key, *_ in RULES:
        if key == "hold":
            continue
        cells = []
        for gname, fn in groups:
            idx = [j for j, b in enumerate(rows) if fn(b[0])]
            p = paired([sims[(cap, fill, key)][j] for j in idx], [ctrl[cap][j] for j in idx],
                       [rows[j][0]["date"] for j in idx])
            res["robust"][f"{key}_{gname}"] = p
            n_cmp["robust"] += 1
            star = "★" if p.get("ev_ci") and (p["ev_ci"][0] > 0 or p["ev_ci"][1] < 0) else ""
            cells.append(f"{p['ev_pp']:+.2f}［{ci_s(p['ev_ci'])}］{star}" if p["days"] else "—")
        md.append(f"| {label[key]} | " + " | ".join(cells) + " |")
    md.append("\n子群大小：" + "；".join(sizes))
    # 子群的對照組本身長怎樣（讓讀者知道各群的底子）
    md.append("\n各子群對照組（持有 20 日）本身：\n")
    md.append("| 子群 | 樣本 | 賺錢機率 | 平均 | 中位 |")
    md.append("|---|---|---|---|---|")
    for gname, fn in groups:
        sm = summarize([ctrl[cap][j] | {"recovered": False, "better": False}
                        for j, b in enumerate(rows) if fn(b[0])])
        md.append(f"| {gname} | {sm['n']:,} | {rate(sm['win'])} | {pct(sm['mean'], 2)} | {pct(sm['median'], 2)} |")

    # ---- 描述性：最後賺錢的候選，途中最深跌多少；最後賠錢的，前 5 日跌破多少 ----
    md.append("\n### 描述性：抱滿 20 日的「途中最深跌幅」（MAE，以進場價計、盤中最低價）\n")
    mae, mae_c, first5, final = [], [], [], []
    for cd, s, e, _ok in rows:
        ent = s["o"][e]
        mae.append(min(s["l"][e:e + CONTROL_DAYS]) / ent - 1)
        mae_c.append(min(s["c"][e:e + CONTROL_DAYS]) / ent - 1)
        # 判定口徑與 simulate_exit 相同（低點 <= 進場價×(1−x)）：整數價位剛好 −10% 時，
        # 舊寫法 low/ent−1 <= −0.1 會因浮點誤差漏算（上一版 7,737 筆 vs 停損觸發 7,781 筆的差異來源）
        first5.append((min(s["l"][e:e + 5]), ent))
    final = [t["net"] for t in ctrl[cap]]
    win_i = [j for j, x in enumerate(final) if x > 0]
    los_i = [j for j, x in enumerate(final) if x <= 0]
    res["mae"] = {}
    md.append("| 群 | 樣本 | 中位 | 75 分位（4 筆有 1 筆跌更深） | 90 分位（10 筆有 1 筆跌更深） | 收盤口徑中位 | 收盤口徑 90 分位 |")
    md.append("|---|---|---|---|---|---|---|")
    for gname, ids in (("最後賺錢的", win_i), ("最後賠錢的", los_i), ("全部", list(range(len(final))))):
        v = [mae[j] for j in ids]
        vc = [mae_c[j] for j in ids]
        r = {"n": len(v), "p50": percentile(v, 50), "p75": percentile(v, 25), "p90": percentile(v, 10),
             "c50": percentile(vc, 50), "c90": percentile(vc, 10)}
        res["mae"][gname] = r
        md.append(f"| {gname} | {r['n']:,} | {pct(r['p50'])} | {pct(r['p75'])} | {pct(r['p90'])} | {pct(r['c50'])} | {pct(r['c90'])} |")
    md.append("\n（「75 分位」＝依跌幅深淺排，比 75% 的同群更深的那個值。）\n")
    md.append("前 5 個交易日內（含進場日）盤中最低曾跌破 X% 的比例，與「跌破後最後還賺錢」的機率：\n")
    md.append("| 前 5 日曾跌破 | 最後賠錢的群中有幾成 | 最後賺錢的群中有幾成 | 跌破的筆數 | 跌破後抱滿 20 日仍賺錢的機率 | 沒跌破的賺錢機率 |")
    md.append("|---|---|---|---|---|---|")
    res["first5"] = {}
    for x in MAE_LEVELS:
        hit_set = {j for j in range(len(final)) if first5[j][0] <= first5[j][1] * (1 - x)}
        hit = sorted(hit_set)
        miss = [j for j in range(len(final)) if j not in hit_set]
        r = {
            "losers_share": sum(1 for j in los_i if j in hit_set) / len(los_i),
            "winners_share": sum(1 for j in win_i if j in hit_set) / len(win_i),
            "n_hit": len(hit),
            "win_given_hit": (sum(1 for j in hit if final[j] > 0) / len(hit)) if hit else None,
            "win_given_miss": (sum(1 for j in miss if final[j] > 0) / len(miss)) if miss else None,
        }
        res["first5"][f"{int(x * 100)}"] = r
        md.append(f"| −{int(x * 100)}% | {rate(r['losers_share'])} | {rate(r['winners_share'])} | {r['n_hit']:,} | "
                  f"{rate(r['win_given_hit'])} | {rate(r['win_given_miss'])} |")

    # ---- 誤砍率：抱滿 20 日最後會賺的，有幾成會先被這條規則洗出場（驗收 🟡2）----
    md.append("\n### 誤砍率：時間上限 20 日、隔日開盤成交，各規則「被停損出場」的比例，按最後結果拆開\n")
    md.append("「最後會賺的」＝同一筆抱滿 20 日成本後 > 0。誤砍率＝這群裡被規則觸發的比例。\n")
    md.append("| 規則 | 全部候選被停損 | 最後會賺的被誤砍 | 最後會賠的被停損 |")
    md.append("|---|---|---|---|")
    res["miscut"] = {}
    sim_main = {key: sims[(cap, fill, key)] for key, *_ in RULES}
    for key, *_ in RULES:
        if key == "hold":
            continue
        trs = sim_main[key]
        r = {"all": sum(1 for t in trs if t["stopped"]) / len(trs),
             "winners": sum(1 for j in win_i if trs[j]["stopped"]) / len(win_i),
             "losers": sum(1 for j in los_i if trs[j]["stopped"]) / len(los_i)}
        res["miscut"][key] = r
        md.append(f"| {label[key]} | {rate(r['all'])} | {rate(r['winners'])} | {rate(r['losers'])} |")

    # ---- 可操作版本：前 5 天就觸發 −10% 的那批，續抱 vs 隔日開盤賣（驗收 🔴1）----
    md.append("\n### 前 5 個交易日內（含進場日）就觸發 −10% 停損的那批：續抱到第 20 日 vs 觸發後隔日開盤賣\n")
    md.append("差＝續抱淨報酬 − 隔日賣淨報酬（正＝續抱較好）。按筆＝每筆一票；按日＝先算每天平均再每天一票。"
              "CI＝circular block bootstrap 90%（按筆的 CI 是整天一起抽、算 Σ差／Σ筆數）。\n")
    md.append("| 群 | 筆數 | 天數 | 按筆平均差 | 按筆 90% CI（block 20） | 按筆 90% CI（block 40） | 按日平均差 | 按日 90% CI（block 20） | 按日 90% CI（block 40） | 續抱較好的比例 | 續抱最後賺錢 | 隔日賣仍賺錢 |")
    md.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    res["hold_vs_sell"] = {}
    dates_main = [b[0]["date"] for b in rows]
    hv_groups = [("全部", lambda cd: True)] + [g for g in groups if g[0] not in ("前半段", "後半段")]
    for gname, fn in hv_groups:
        idx = [j for j, b in enumerate(rows) if fn(b[0])]
        r = hold_vs_sell([sim_main["stop10"][j] for j in idx], [ctrl[cap][j] for j in idx],
                         [dates_main[j] for j in idx], max_day=5)
        res["hold_vs_sell"][gname] = r
        if not r["n"]:
            md.append(f"| {gname} | 0 | — | — | — | — | — | — | — | — | — | — |")
            continue
        n_cmp["hold_vs_sell"] += 1
        md.append(f"| {gname} | {r['n']:,} | {r['days']} | {r['per_trade_pp']:+.2f} | {ci_s(r['per_trade_ci_b20'])} | "
                  f"{ci_s(r['per_trade_ci_b40'])} | {r['per_day_pp']:+.2f} | {ci_s(r['per_day_ci_b20'])} | "
                  f"{ci_s(r['per_day_ci_b40'])} | {rate(r['hold_better'])} | {rate(r['hold_win'])} | {rate(r['sell_win'])} |")

    res["n_comparisons"] = n_cmp
    md.append(f"\n### 這份報告一共做了幾組有 CI 的配對比較\n")
    md.append(f"主表（各時間上限×成交口徑×對照組）{n_cmp['main']} 列＋子群穩健性表 {n_cmp['robust']} 格＋"
              f"「續抱 vs 隔日賣」{n_cmp['hold_vs_sell']} 列＝**{sum(n_cmp.values())} 組**；"
              "主表每列另有「賺錢機率差」一個 CI。全部沒做多重比較校正。")
    return res, "\n".join(md)


# 網站「各條停損線的代價」表要讀的精簡 JSON（前端 ExitCostTable）。數字直接取自 run() 的結果，
# 與報告「時間上限 20 日｜隔日開盤成交」主表、「誤砍率」表同一份，不另算。
SUMMARY_ROWS = (  # (summary key, 顯示名)
    ("hold", "抱滿 20 天"), ("stop8", "−8%"), ("stop10", "−10%"), ("stop12", "−12%"),
    ("stop15", "−15%"), ("stop20", "−20%"), ("site15ma", "網站預設（−15% 與月線取較高者）"),
)


def build_summary(res, as_of):
    """從 run() 的 res 組出 exit_rules_summary.json 的內容（純函式，有單測）。
    欄位皆為小數比例（0.502＝50.2%）；hold（對照組）沒有停損線，觸發／誤砍給 None（畫面顯示「—」，不是 0%）。"""
    m = res["meta20"]
    rows = []
    for key, lab in SUMMARY_ROWS:
        sm = res["summary"][f"cap{CONTROL_DAYS}_next_open_{key}"]
        mc = res["miscut"].get(key)
        rows.append({
            "key": key, "label": lab,
            "stop_rate": None if key == "hold" else sm["stop_rate"],
            "miscut_winners": None if key == "hold" else mc["winners"],
            "win_rate": sm["win"],
            "p5": sm["p5"],
            "worst": sm["worst"],
        })
    return {
        "as_of": as_of, "source": "pipeline/research_exit_rules.py（報告 _reports/研究_出場規則_2026-11-13.md）",
        "hold_days": CONTROL_DAYS, "fill": "next_open",
        "n": m["n"], "signal_days": m["signal_days"], "batches": m["signal_days"] // BLOCK,
        "first_date": m["first"], "last_date": m["last"],
        "rows": rows,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cache", help="候選清單快取（存在就讀、不存在就建完存檔）")
    ap.add_argument("--out", help="把數字表 Markdown 另存到此路徑")
    ap.add_argument("--json", help="把完整結果 JSON 另存到此路徑")
    ap.add_argument("--summary", default=os.path.join(HERE, "exit_rules_summary.json"),
                    help="網站表格用的精簡 JSON 輸出路徑（預設 pipeline/exit_rules_summary.json）")
    a = ap.parse_args()
    t0 = time.time()
    if a.cache and os.path.exists(a.cache):
        with open(a.cache, encoding="utf-8") as f:
            cands = json.load(f)
        print(f"讀快取 {a.cache}：{len(cands)} 筆候選", flush=True)
    else:
        cands = build_candidates()
        if a.cache:
            with open(a.cache, "w", encoding="utf-8") as f:
                json.dump(cands, f, ensure_ascii=False)
    ohlc = load_ohlc()
    res, md = run(cands, ohlc)
    print(md)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(md + "\n")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
    if a.summary:
        as_of = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 8 * 3600))   # 台北日期
        with open(a.summary, "w", encoding="utf-8") as f:
            json.dump(build_summary(res, as_of), f, ensure_ascii=False, indent=1)
            f.write("\n")
        print(f"精簡 JSON → {a.summary}", flush=True)
    print(f"\n完成（{time.time() - t0:.0f}s）", flush=True)


if __name__ == "__main__":
    main()
