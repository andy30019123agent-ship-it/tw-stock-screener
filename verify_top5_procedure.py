#!/usr/bin/env python3
"""回測「Top5 選股程序」本身（唯讀分析腳本）。

不改任何既有程式碼；只讀 pipeline/history/*.json 與 pipeline/*.py 的純函式，
逐日重播 opportunities.build_opportunities 的決策鏈，量測成本後超額。

用法：python3 verify_top5_procedure.py [--stage collect|analyze|all] [--limit N]
中間結果快取在 CACHE_PATH，analyze 階段可重跑而不必重算 10 分鐘。
"""
import os
import sys
import json
import math
import random
import argparse
import pickle
import bisect
import time

REPO = os.path.dirname(os.path.abspath(__file__))
# 允許腳本放在 scratchpad：用環境變數或預設 repo 路徑
PIPE = os.environ.get("TWS_PIPELINE") or os.path.join(REPO, "pipeline")
if not os.path.isdir(PIPE):
    PIPE = "/Users/andyc/Desktop/agent/tw-stock-screener/pipeline"
sys.path.insert(0, PIPE)

import history_store as hs          # noqa: E402
import build_data as bd             # noqa: E402
import backtest_signals as bt       # noqa: E402
import opportunities as opp         # noqa: E402
import price_breaks as pb           # noqa: E402

CACHE_PATH = os.path.join(os.environ.get("TWS_CACHE_DIR", "/tmp"), "top5_replay_cache.pkl")

FORWARD = bt.FORWARD
MIN_BARS = bt.MIN_BARS
BENCH_MIN_VOL = bt.BACKTEST_MIN_VOL      # 300：基準母體門檻（與既有回測同一把尺）
GATE_MIN_POOL = opp.GATE_MIN_POOL
TOP_N = opp.TOP_N
LIVE_MIN_VOL = opp.MIN_VOL_LOTS          # 500
ENGINE = list(bt.ENGINE_SIGNALS)
E_IDX = {k: i for i, k in enumerate(ENGINE)}
GATE_BIT = len(ENGINE)                   # rs_confirmed_60_120 放在最高位


# ────────────────────────────── 階段 1：重播收集 ──────────────────────────────
def collect(limit=None):
    t0 = time.time()
    bth = hs.load(os.path.join(PIPE, "history", "bt_price.json")) or hs.bt_empty()
    price_hist = hs.bt_to_price_hist(bth)
    div_hist = hs.load(os.path.join(PIPE, "history", "dividends.json")) or {}
    chip_hist = hs.load(os.path.join(PIPE, "history", "chip.json")) or {}
    universe = json.load(open(os.path.join(PIPE, "universe.json"), encoding="utf-8"))["stocks"]
    breaks = pb.load_breaks() or set()
    print(f"[1] 載入完成 {time.time()-t0:.1f}s：{len(price_hist)} 檔、{len(bth.get('dates') or [])} 交易日、"
          f"除權息 {len(div_hist)}、籌碼 {len(chip_hist)}、universe {len(universe)}、價格斷點 {len(breaks)}")

    t0 = time.time()
    xsect = bt.build_xsect_cache(price_hist, div_hist, universe)
    print(f"[2] 橫斷面 PIT cache {time.time()-t0:.1f}s：{len(xsect)} 個交易日有 RS")

    t0 = time.time()
    regime = bt.build_regime_series(price_hist, div_hist)
    print(f"[3] 市況序列 {time.time()-t0:.1f}s：{len(regime)} 日")

    t0 = time.time()
    # recs[date] = [(sid, vol, raw_mask, cool_mask, rs60, ret20, fwd_gross), ...]
    recs = {}
    ulist = universe[:limit] if limit else universe
    done = 0
    for stock in ulist:
        sid = stock["id"]
        pr = hs.to_price_rows(price_hist.get(sid, {}))
        if len(pr) < MIN_BARS + FORWARD + 1:
            continue
        pr = sorted(pr, key=lambda r: r["date"])
        cr = sorted(hs.to_chip_rows(chip_hist.get(sid, {})), key=lambda r: r["date"])
        cr_dates = [c["date"] for c in cr]
        ev = hs.to_div_events(div_hist.get(sid))
        adj = [r["close"] for r in bd.back_adjust_rows(pr, ev)]
        brk_idx = sorted(j for j, r in enumerate(pr) if (sid, r["date"]) in breaks) if breaks else []
        last_fire = {}
        for i in range(MIN_BARS - 1, len(pr) - FORWARD):
            di = pr[i]["date"]
            base = adj[i]
            if not base:
                continue
            if brk_idx:                                  # 與 collect_events 同：報酬窗跨斷點就整筆丟
                lo = bisect.bisect_right(brk_idx, i)
                if lo < len(brk_idx) and brk_idx[lo] <= i + FORWARD:
                    continue
            cut = bisect.bisect_right(cr_dates, di)
            ind = bd.compute_indicators(pr[:i + 1], cr[:cut], ev, None)
            if ind is None:
                continue
            vol = int(ind.get("avg_vol_lots", 0) or 0)
            fwd = adj[i + FORWARD] / base - 1
            ret20 = (adj[i] / adj[i - 20] - 1) if (i >= 20 and adj[i - 20]) else None
            flags = bt.signal_flags(ind)
            flags.update(bt._xsect_flags(xsect.get(di, {}).get(sid)))
            raw = 0
            cool = 0
            for k in ENGINE:
                if flags.get(k):
                    raw |= 1 << E_IDX[k]
                    if not (k in last_fire and i - last_fire[k] < FORWARD):
                        last_fire[k] = i
                        cool |= 1 << E_IDX[k]
            if flags.get("rs_confirmed_60_120"):
                raw |= 1 << GATE_BIT
            x = xsect.get(di, {}).get(sid) or {}
            recs.setdefault(di, []).append(
                (sid, vol, raw, cool, x.get("rs_pct_60"), ret20, fwd))
        done += 1
        if done % 200 == 0:
            print(f"    …{done}/{len(ulist)} 檔 ({time.time()-t0:.0f}s)")
    print(f"[4] 重播收集 {time.time()-t0:.1f}s：{len(recs)} 個交易日、"
          f"{sum(len(v) for v in recs.values())} 筆 (日,股) 觀測")

    payload = {"recs": recs, "regime": regime, "engine": ENGINE,
               "dates_all": sorted(bth.get("dates") or []),
               "z0050": _etf_series(price_hist, div_hist, breaks, "0050")}
    with open(CACHE_PATH, "wb") as f:
        pickle.dump(payload, f, protocol=4)
    print(f"[5] 快取寫入 {CACHE_PATH}")
    return payload


def _etf_series(price_hist, div_hist, breaks, sid):
    """0050 的「入場日 → 20 交易日後毛報酬」；跨越已知價格斷點（分割）的窗丟掉。"""
    pr = sorted(hs.to_price_rows(price_hist.get(sid, {})), key=lambda r: r["date"])
    if not pr:
        return {}
    ev = hs.to_div_events(div_hist.get(sid))
    adj = [r["close"] for r in bd.back_adjust_rows(pr, ev)]
    brk = sorted(j for j, r in enumerate(pr) if (sid, r["date"]) in breaks)
    out = {}
    for i in range(len(pr) - FORWARD):
        if not adj[i]:
            continue
        lo = bisect.bisect_right(brk, i)
        if lo < len(brk) and brk[lo] <= i + FORWARD:
            continue
        out[pr[i]["date"]] = adj[i + FORWARD] / adj[i] - 1
    return out


# ────────────────────────────── 統計工具 ──────────────────────────────
def mean(v):
    return sum(v) / len(v) if v else None


def median(v):
    s = sorted(v)
    n = len(s)
    if not n:
        return None
    m = n // 2
    return s[m] if n % 2 else (s[m - 1] + s[m]) / 2


def stdev(v):
    n = len(v)
    if n < 2:
        return None
    mu = mean(v)
    return math.sqrt(sum((x - mu) ** 2 for x in v) / (n - 1))


def newey_west_se(v, lags=FORWARD - 1):
    """Bartlett kernel HAC SE（校正 20 日重疊窗造成的序列相關）。輸入＝按日期排序的日序列。"""
    n = len(v)
    if n < lags + 2:
        return None
    mu = mean(v)
    e = [x - mu for x in v]
    g0 = sum(x * x for x in e) / n
    s = g0
    for L in range(1, lags + 1):
        gl = sum(e[t] * e[t - L] for t in range(L, n)) / n
        s += 2 * (1 - L / (lags + 1)) * gl
    if s <= 0:
        return None
    return math.sqrt(s / n)


def summarize(daily, label):
    """daily = [(date, portfolio_net_excess_pp, n_holdings), ...] 已按日期排序。"""
    vals = [x[1] for x in daily]
    if not vals:
        return {"label": label, "n_days": 0}
    se = (stdev(vals) / math.sqrt(len(vals))) if len(vals) > 1 else None
    nw = newey_west_se(vals)
    # 不重疊子樣本：每 FORWARD 天取一天，5 個 offset 各算一次
    nonov = []
    for off in range(0, FORWARD, 4):
        sub = vals[off::FORWARD]
        if len(sub) >= 5:
            nonov.append(mean(sub))
    return {
        "label": label,
        "n_days": len(vals),
        "avg_holdings": round(mean([x[2] for x in daily]), 1),
        "mean_pp": round(mean(vals), 3),
        "median_pp": round(median(vals), 3),
        "win_rate": round(sum(1 for x in vals if x > 0) / len(vals), 4),
        "sd_pp": round(stdev(vals), 3) if len(vals) > 1 else None,
        "se_naive_pp": round(se, 3) if se else None,
        "se_nw_pp": round(nw, 3) if nw else None,
        "t_nw": round(mean(vals) / nw, 2) if nw else None,
        "nonoverlap_means_pp": [round(x, 3) for x in nonov],
    }


# ────────────────────────────── 階段 2：分析 ──────────────────────────────
class Day:
    __slots__ = ("date", "recs", "bench", "regime")


def prepare(payload):
    recs, regime = payload["recs"], payload["regime"]
    days = []
    for d in sorted(recs):
        rows = recs[d]
        pool = [r[6] for r in rows if r[1] >= BENCH_MIN_VOL]
        if not pool:
            continue
        o = Day()
        o.date = d
        o.recs = rows
        o.bench = sum(pool) / len(pool)
        o.regime = regime.get(d, "unknown")
        days.append(o)
    return days


def net_excess_pp(fwd, bench):
    return (bt._apply_cost(fwd) - bench) * 100


def engine_mask_nonzero(weights_by_key):
    m = 0
    for k, w in weights_by_key.items():
        if w and k in E_IDX:
            m |= 1 << E_IDX[k]
    return m


def score_of(mask, wvec):
    s = 0
    for i, w in enumerate(wvec):
        if w and (mask >> i) & 1:
            s += w
    return s


def run_arm(days, wvec, *, gate=True, vol_min=LIVE_MIN_VOL, top_n=TOP_N,
            sort_key="ret20", use_score=True, rng=None, engine_required=True):
    """重播一組設定，回 (daily list, meta)。"""
    daily = []
    gate_off_days = []
    for D in days:
        cands = []
        for (sid, vol, raw, cool, rs60, ret20, fwd) in D.recs:
            if vol < vol_min:
                continue
            emask = raw & ((1 << len(ENGINE)) - 1)
            if engine_required and emask == 0:
                continue
            cands.append((sid, emask, bool((raw >> GATE_BIT) & 1), rs60, ret20, fwd))
        if not cands:
            continue
        if gate:
            gated = [c for c in cands if c[2]]
            gate_on = len(gated) >= GATE_MIN_POOL
            pool = gated if gate_on else cands
            if not gate_on:
                gate_off_days.append(D.date)
        else:
            pool = cands
        if not pool:
            continue
        if sort_key == "none":
            sel = pool
        else:
            if sort_key == "ret20":
                key = lambda c: (-(score_of(c[1], wvec) if use_score else 0),
                                 -(c[4] if c[4] is not None else -999))
            elif sort_key == "rs_pct_60":
                key = lambda c: (-(score_of(c[1], wvec) if use_score else 0),
                                 -(c[3] if c[3] is not None else -999))
            elif sort_key == "random":
                key = lambda c: (-(score_of(c[1], wvec) if use_score else 0), rng.random())
            elif sort_key == "ret20_asc":
                key = lambda c: (-(score_of(c[1], wvec) if use_score else 0),
                                 (c[4] if c[4] is not None else 999))
            else:
                raise ValueError(sort_key)
            sel = sorted(pool, key=key)[:top_n]
        ex = [net_excess_pp(c[5], D.bench) for c in sel]
        daily.append((D.date, mean(ex), len(sel), D.regime))
    return daily, {"gate_off_days": gate_off_days}


def by_regime(daily):
    out = {}
    for r in ("green", "yellow", "red", "unknown"):
        sub = [x for x in daily if x[3] == r]
        if sub:
            out[r] = {"n_days": len(sub), "mean_pp": round(mean([x[1] for x in sub]), 3),
                      "median_pp": round(median([x[1] for x in sub]), 3),
                      "win_rate": round(sum(1 for x in sub if x[1] > 0) / len(sub), 4)}
    return out


def quintiles(days, wvec, *, within_score=None):
    """候選池按 ret20 分五等分，看各分位成本後超額（日期群聚 SE）。"""
    per_day = {q: [] for q in range(5)}     # 每日各分位的平均超額
    counts = {q: 0 for q in range(5)}
    for D in days:
        cands = []
        for (sid, vol, raw, cool, rs60, ret20, fwd) in D.recs:
            if vol < LIVE_MIN_VOL:
                continue
            emask = raw & ((1 << len(ENGINE)) - 1)
            if emask == 0:
                continue
            if not ((raw >> GATE_BIT) & 1):
                continue
            if within_score is not None and score_of(emask, wvec) != within_score:
                continue
            if ret20 is None:
                continue
            cands.append((ret20, fwd))
        if len(cands) < 10:
            continue
        cands.sort(key=lambda c: c[0])
        n = len(cands)
        for q in range(5):
            lo, hi = q * n // 5, (q + 1) * n // 5
            grp = cands[lo:hi]
            if grp:
                per_day[q].append(mean([net_excess_pp(c[1], D.bench) for c in grp]))
                counts[q] += len(grp)
    out = {}
    for q in range(5):
        v = per_day[q]
        if not v:
            continue
        nw = newey_west_se(v)
        out[f"Q{q+1}"] = {"n_days": len(v), "n_obs": counts[q],
                          "mean_pp": round(mean(v), 3), "median_pp": round(median(v), 3),
                          "win_rate_days": round(sum(1 for x in v if x > 0) / len(v), 4),
                          "se_nw_pp": round(nw, 3) if nw else None}
    return out


def walkforward_weights(days):
    """每日重算 ENGINE 訊號權重，只用「該日之前已成熟（事件日 +20 交易日 ≤ 今日）」的事件。
    回 {date: wvec}。權重公式與 stats_to_weights 相同（成本後超額 pp × 2，clip 1~5，樣本 <30 → 0）。"""
    dates = [D.date for D in days]
    dpos = {d: i for i, d in enumerate(dates)}
    # 每個 (日,股) 事件在成熟日（i+FORWARD）才可用
    matured = {d: [] for d in dates}
    for D in days:
        i = dpos[D.date]
        mi = i + FORWARD
        if mi >= len(dates):
            continue
        md = dates[mi]
        for (sid, vol, raw, cool, rs60, ret20, fwd) in D.recs:
            if vol < BENCH_MIN_VOL or cool == 0:
                continue
            matured[md].append((cool, net_excess_pp(fwd, D.bench) / 100))
    acc_n = [0] * len(ENGINE)
    acc_x = [0.0] * len(ENGINE)
    out = {}
    for d in dates:
        for cool, nx in matured[d]:
            for i in range(len(ENGINE)):
                if (cool >> i) & 1:
                    acc_n[i] += 1
                    acc_x[i] += nx
        w = []
        for i in range(len(ENGINE)):
            if acc_n[i] < bt.MIN_SAMPLE:
                w.append(0)
                continue
            pp = acc_x[i] / acc_n[i] * 100
            w.append(0 if pp <= 0 else min(5, max(1, round(pp * 2))))
        out[d] = tuple(w)
    return out


def run_arm_dynamic(days, wmap, **kw):
    """權重逐日變動版本（走前權重）。"""
    daily = []
    for D in days:
        wvec = wmap.get(D.date, tuple([0] * len(ENGINE)))
        sub, _ = run_arm([D], list(wvec), **kw)
        daily.extend(sub)
    return daily


def bench_arms(days, payload):
    out = {}
    # 全市場等權（成本後）
    d1 = []
    for D in days:
        rows = [r for r in D.recs if r[1] >= BENCH_MIN_VOL]
        if not rows:
            continue
        d1.append((D.date, mean([net_excess_pp(r[6], D.bench) for r in rows]), len(rows), D.regime))
    out["market_ew"] = (d1, summarize(d1, "全市場等權（≥300 張，成本後超額）"))
    # rs_pct_60 前 5%
    d2 = []
    for D in days:
        rows = [r for r in D.recs if r[1] >= LIVE_MIN_VOL and r[4] is not None]
        if len(rows) < 20:
            continue
        rows.sort(key=lambda r: -r[4])
        k = max(1, len(rows) * 5 // 100)
        sel = rows[:k]
        d2.append((D.date, mean([net_excess_pp(r[6], D.bench) for r in sel]), len(sel), D.regime))
    out["rs60_top5pct"] = (d2, summarize(d2, "rs_pct_60 前 5%（≥500 張，等權）"))
    # 0050
    z = payload.get("z0050") or {}
    d3 = []
    for D in days:
        if D.date in z:
            d3.append((D.date, net_excess_pp(z[D.date], D.bench), 1, D.regime))
    out["etf0050"] = (d3, summarize(d3, "0050（成本後 − 同日全市場平均毛報酬）"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all", choices=["collect", "analyze", "all"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    if a.stage in ("collect", "all") or not os.path.exists(CACHE_PATH):
        payload = collect(a.limit)
    else:
        payload = None
    if a.stage == "collect":
        return
    if payload is None:
        with open(CACHE_PATH, "rb") as f:
            payload = pickle.load(f)

    days = prepare(payload)
    print(f"\n可分析交易日 {len(days)}：{days[0].date} ~ {days[-1].date}")

    wjson = bt._load(os.path.join(PIPE, "signal_weights.json")) or {}
    sig = wjson.get("signals", {})
    wvec = [int(sig.get(k, {}).get("weight", 0) or 0) for k in ENGINE]
    print("現行 ENGINE 權重：" + ", ".join(f"{k}={w}" for k, w in zip(ENGINE, wvec) if w) + "（其餘 0）")

    R = {"meta": {"dates": [days[0].date, days[-1].date], "n_days": len(days),
                  "engine_weights": dict(zip(ENGINE, wvec)),
                  "cost_roundtrip_pct": round((1 - (1 - bt.EXIT_FEE - bt.EXIT_TAX - bt.EXIT_SLIP) /
                                               (1 + bt.EXIT_FEE + bt.EXIT_SLIP)) * 100, 4)}}

    # Q1 基準線：現行程序
    base, meta = run_arm(days, wvec)
    R["baseline"] = summarize(base, "現行 Top5 程序")
    R["baseline"]["by_regime"] = by_regime(base)
    R["baseline"]["gate_off_days"] = meta["gate_off_days"]
    R["baseline"]["n_gate_off"] = len(meta["gate_off_days"])
    if meta["gate_off_days"]:
        off = set(meta["gate_off_days"])
        sub = [x for x in base if x[0] in off]
        R["baseline"]["gate_off_perf"] = summarize(sub, "門檻退回日")
        R["baseline"]["gate_on_perf"] = summarize([x for x in base if x[0] not in off], "門檻生效日")

    # 前後半期穩定性（回應「權重用全期算＝輕微前視」）
    half = len(base) // 2
    R["baseline"]["first_half"] = summarize(base[:half], "前半期")
    R["baseline"]["second_half"] = summarize(base[half:], "後半期")

    # Q2 ablation
    ab = {}
    ab["gate_off"] = summarize(run_arm(days, wvec, gate=False)[0], "無門檻（全市場計分排序）")
    ab["sort_rs_pct_60"] = summarize(run_arm(days, wvec, sort_key="rs_pct_60")[0], "改用 rs_pct_60 排序")
    ab["sort_ret20_asc"] = summarize(run_arm(days, wvec, sort_key="ret20_asc")[0], "反向排序（rs20 最弱 5 檔）")
    ab["sort_none_all"] = summarize(run_arm(days, wvec, sort_key="none")[0], "不排序（全部候選等權）")
    rand = []
    for s in range(20):
        rng = random.Random(1000 + s)
        rand.append(summarize(run_arm(days, wvec, sort_key="random", rng=rng)[0], f"隨機排序 seed{s}"))
    ab["sort_random"] = {"n_draws": len(rand),
                          "mean_of_means_pp": round(mean([r["mean_pp"] for r in rand]), 3),
                          "sd_of_means_pp": round(stdev([r["mean_pp"] for r in rand]), 3),
                          "min_pp": min(r["mean_pp"] for r in rand),
                          "max_pp": max(r["mean_pp"] for r in rand),
                          "mean_of_medians_pp": round(mean([r["median_pp"] for r in rand]), 3),
                          "mean_win_rate": round(mean([r["win_rate"] for r in rand]), 4),
                          "n_days": rand[0]["n_days"]}
    ab["no_score"] = summarize(run_arm(days, wvec, use_score=False)[0], "不計分（只按 rs20 取前 5）")
    for v in (200, 300, 0):
        ab[f"vol_{v}"] = summarize(run_arm(days, wvec, vol_min=v)[0], f"量能門檻 {v} 張")
    for n in (1, 3, 10, 20):
        ab[f"top_{n}"] = summarize(run_arm(days, wvec, top_n=n)[0], f"取 {n} 檔")
    ab["no_engine_required"] = summarize(
        run_arm(days, wvec, engine_required=False)[0], "不要求有引擎訊號（門檻+量能即可）")
    R["ablation"] = ab

    # Q3 rs20 五分位
    R["quintiles_all"] = quintiles(days, wvec)
    R["quintiles_score1"] = quintiles(days, wvec, within_score=1)
    R["quintiles_score0"] = quintiles(days, wvec, within_score=0)

    # 候選池結構：score 分佈、score=1 是否足 5 檔
    struct = {"days": 0, "score1_ge5": 0, "pool_sizes": [], "score1_sizes": []}
    for D in days:
        cands = [r for r in D.recs if r[1] >= LIVE_MIN_VOL
                 and (r[2] & ((1 << len(ENGINE)) - 1)) and ((r[2] >> GATE_BIT) & 1)]
        if not cands:
            continue
        struct["days"] += 1
        struct["pool_sizes"].append(len(cands))
        n1 = sum(1 for c in cands if score_of(c[2] & ((1 << len(ENGINE)) - 1), wvec) >= 1)
        struct["score1_sizes"].append(n1)
        if n1 >= TOP_N:
            struct["score1_ge5"] += 1
    R["pool_structure"] = {
        "days_with_gated_pool": struct["days"],
        "median_pool": median(struct["pool_sizes"]),
        "median_score1": median(struct["score1_sizes"]),
        "days_score1_ge_5": struct["score1_ge5"],
        "pct_days_score1_ge_5": round(struct["score1_ge5"] / struct["days"], 4) if struct["days"] else None,
    }

    # Q5 基準
    R["benchmarks"] = {k: v[1] for k, v in bench_arms(days, payload).items()}

    # 走前權重（無前視）版本
    wmap = walkforward_weights(days)
    dyn = run_arm_dynamic(days, wmap)
    R["walkforward_weights"] = summarize(dyn, "走前權重（無前視）")
    R["walkforward_weights"]["weight_paths"] = {
        k: sorted({wmap[d][i] for d in wmap}) for i, k in enumerate(ENGINE)}

    out = a.out or os.path.join(os.environ.get("TWS_CACHE_DIR", "/tmp"), "top5_results.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(R, f, ensure_ascii=False, indent=1)
    print(json.dumps(R, ensure_ascii=False, indent=1))
    print(f"\n結果 JSON：{out}")


if __name__ == "__main__":
    main()
