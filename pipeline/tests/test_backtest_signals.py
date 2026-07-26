"""回測權重與訊號旗標的單元測試（含勝率手算對照）。

2026-07-23 改版重點（Codex 交叉審計後 Andy 拍板全修）：
- 權重改看「超額勝率」（該股報酬 － 同日全市場平均），不再看絕對勝率。絕對勝率在多頭市場
  裡亂選也會 >50%，等於把大盤漲幅記在訊號頭上。
- 樣本不足一律 weight=0，不再給預設 1。「沒有證據」不該等於「中等證據」。
"""
import os
import sys
import datetime as _dt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import backtest_signals as bt


def _seq_dates(n, start="2024-01-01"):
    """n 個遞增且可排序的日期字串（單測把 by_date 的鍵當交易日曆用，週末與否無所謂）。"""
    d0 = _dt.date.fromisoformat(start)
    return [(d0 + _dt.timedelta(days=i)).isoformat() for i in range(n)]


def _make_rows(n, close=100.0, start="2024-01-01", rise=0.5, vol=500000):
    """造 n 天穩定上升的日線資料（open=high=low=close，量固定在 500 張／日）。
    2026-07-26（隔日開盤測試）：用單調上升序列是為了讓 warmup 後 ma5>ma10>ma20>ma60
    （多頭排列 bull_aligned）恆成立、保證每個可評估日都會有訊號觸發——這樣測試才能
    只觀察「進場價算對了沒」，不被「訊號到底有沒有成立」這個變數干擾。"""
    dates = _seq_dates(n, start=start)
    rows = []
    for i, d in enumerate(dates):
        c = round(close + i * rise, 4)
        rows.append({"date": d, "open": c, "max": c, "min": c, "close": c,
                     "Trading_Volume": vol, "Trading_money": 0})
    return rows


def _rows_to_hist(rows):
    """把 `_make_rows` 的 row list 轉成 collect_events 吃的 price_hist[sid] 格式
    {date: [open, max, min, close, Trading_Volume, Trading_money]}（對齊
    history_store.to_price_rows 的欄位順序，這樣改動 row 的 open/close 後轉回去仍生效）。"""
    return {r["date"]: [r["open"], r["max"], r["min"], r["close"],
                        r["Trading_Volume"], r["Trading_money"]] for r in rows}


def test_stats_to_weights_hand_calc():
    # 手算對照：糾結轉強成立 40 次，平均報酬 4%、平均超額 +1.5 個百分點
    #   → weight = min(5, max(1, round(1.5 × 2))) = 3
    stats = {"signal_ma": {"wins": 32, "count": 40, "ret_sum": 40 * 0.04,
                           "exc_wins": 30, "exc_sum": 40 * 0.015}}
    w = bt.stats_to_weights(stats)
    assert w["signal_ma"]["samples"] == 40
    assert w["signal_ma"]["win_rate"] == 0.8            # 絕對勝率照實呈現（僅供對照）
    assert w["signal_ma"]["excess_win_rate"] == 0.75    # 超額勝率也照實呈現
    assert w["signal_ma"]["avg_ret"] == 4.0             # 平均報酬 4%
    assert w["signal_ma"]["avg_excess"] == 1.5          # 平均超額 1.5 個百分點 → 權重依據
    assert w["signal_ma"]["weight"] == 3
    assert w["signal_ma"]["validated"] is True


def test_勝率高但期望值為負_權重歸零():
    # 實測「破底翻」的形狀：絕對勝率 60%，平均超額卻是 −2pp（純粹跟著大盤反彈）。
    # 舊公式看勝率會給它最高權重 3，新公式看期望值直接歸零。
    stats = {"sn_break_low_recover": {"wins": 60, "count": 100, "ret_sum": 100 * 0.023,
                                      "exc_wins": 35, "exc_sum": -100 * 0.02}}
    w = bt.stats_to_weights(stats)
    assert w["sn_break_low_recover"]["win_rate"] == 0.6
    assert w["sn_break_low_recover"]["avg_excess"] == -2.0
    assert w["sn_break_low_recover"]["weight"] == 0


def test_權重改看成本後超額_毛正淨負要歸零():
    """2026-07-25 Andy 拍板「乾淨」：權重基準從毛超額改成成本後超額。
    真實案例＝爆量突破（毛 +0.74pp、扣掉來回 0.785% 成本後 −0.06pp）——毛看起來有邊際，
    扣完成本其實贏不過大盤，這種不該再拿權重去影響 Top5 排名。"""
    stats = {"signal_breakout": {"count": 2765, "wins": 1255, "ret_sum": 0.0,
                                 "exc_wins": 1100, "exc_sum": 2765 * 0.0074,
                                 "net_exc_sum": -2765 * 0.0006, "net_exc_wins": 1000}}
    w = bt.stats_to_weights(stats)["signal_breakout"]
    assert w["avg_excess"] == 0.74      # 毛超額照實呈現（供對照）
    assert w["net_excess"] == -0.06     # 成本後為負
    assert w["weight"] == 0             # ← 關鍵：權重看淨值，歸零
    assert w["weight_basis"] == "net_excess"


def test_權重用淨值算級距_不是毛值():
    # 毛 +2.0pp、淨 +1.0pp → 權重應該是 round(1.0×2)=2，不是 round(2.0×2)=4
    stats = {"signal_ma": {"count": 100, "wins": 60, "ret_sum": 0.0,
                           "exc_wins": 60, "exc_sum": 100 * 0.02,
                           "net_exc_sum": 100 * 0.01, "net_exc_wins": 55}}
    w = bt.stats_to_weights(stats)["signal_ma"]
    assert w["avg_excess"] == 2.0 and w["net_excess"] == 1.0
    assert w["weight"] == 2


def test_舊資料沒有淨超額欄位時退回毛超額():
    """歷史 stats 檔沒有 net_exc_sum，不能因此整批歸零（那會讓舊檔一讀就把 Top5 清空）。"""
    stats = {"signal_ma": {"count": 100, "wins": 60, "ret_sum": 0.0,
                           "exc_wins": 60, "exc_sum": 100 * 0.015}}
    w = bt.stats_to_weights(stats)["signal_ma"]
    assert w["net_excess"] == 1.5 and w["weight"] == 3     # 退回用毛超額


def test_events_to_stats_算出成本後超額():
    """淨超額必須比毛超額低約一個來回成本（0.785%），且用同一個同日基準。"""
    events = [{"date": "d1", "sid": "A", "i": 0, "ret": 0.10, "fired": ["signal_ma"]}]
    by_date = {"d1": [0.10, 0.0, -0.04]}          # 同日平均 +2%
    st = bt.events_to_stats(events, by_date)["signal_ma"]
    assert round(st["exc_sum"], 6) == round(0.10 - 0.02, 6)          # 毛超額 8pp
    expected_net = bt._apply_cost(0.10) - 0.02
    assert round(st["net_exc_sum"], 6) == round(expected_net, 6)
    assert st["net_exc_sum"] < st["exc_sum"]                          # 淨一定低於毛
    assert st["net_exc_wins"] == 1                                    # 淨超額仍為正


def test_期望值微正也至少給1分_但上限5():
    low = bt.stats_to_weights({"signal_ma": {"count": 40, "wins": 20, "ret_sum": 0.0,
                                             "exc_wins": 20, "exc_sum": 40 * 0.001}})
    assert low["signal_ma"]["weight"] == 1      # +0.1pp → round(0.2)=0，但正期望值保底 1
    high = bt.stats_to_weights({"signal_ma": {"count": 40, "wins": 40, "ret_sum": 0.0,
                                              "exc_wins": 40, "exc_sum": 40 * 0.10}})
    assert high["signal_ma"]["weight"] == 5     # +10pp → 20，封頂 5


def test_絕對勝率高但沒贏過大盤_權重應為零():
    # 40 次全部上漲（絕對勝率 1.0），但只有 12 次贏過同日平均 → 超額勝率 0.3
    #   → (0.3−0.5)×20 = −4 → max(0, −4) = 0。這正是「牛市亂選也會贏」要擋掉的情況。
    stats = {"signal_breakout": {"wins": 40, "count": 40, "ret_sum": 40 * 0.05,
                                 "exc_wins": 12, "exc_sum": -40 * 0.01}}
    w = bt.stats_to_weights(stats)
    assert w["signal_breakout"]["win_rate"] == 1.0
    assert w["signal_breakout"]["weight"] == 0


def test_樣本不足一律權重零_但統計照實呈現():
    # 樣本 < 30 → weight 0（不再是預設 1）；勝率與樣本數仍照實輸出供觀察
    stats = {"trust_buy": {"wins": 10, "count": 10, "ret_sum": 10 * 0.1,
                           "exc_wins": 10, "exc_sum": 10 * 0.05}}
    w = bt.stats_to_weights(stats)
    assert w["trust_buy"]["samples"] == 10
    assert w["trust_buy"]["weight"] == 0
    assert w["trust_buy"]["validated"] is False
    assert w["trust_buy"]["win_rate"] == 1.0


def test_零樣本訊號仍在輸出裡_權重零():
    # 完全沒出現的訊號也要在輸出裡（供選股/展示不 KeyError），但權重必須是 0
    w = bt.stats_to_weights({})
    for k in bt.SIGNALS:
        assert w[k]["weight"] == 0
        assert w[k]["win_rate"] is None
        assert w[k]["samples"] == 0
        assert w[k]["validated"] is False


def test_signal_flags_reads_streaks():
    ind = {"signal_ma": True, "foreign_streak": 3, "trust_streak": 2,
           "undervalued": True}
    f = bt.signal_flags(ind)
    assert f["signal_ma"] is True
    assert f["foreign_buy"] is True     # streak 3 >= 3
    assert f["trust_buy"] is False      # streak 2 < 3
    assert f["undervalued"] is True
    assert f["sn_break_low_recover"] is False


def test_超額基準用同日全市場平均():
    # 同一天三檔可評估：報酬 10%、0%、-4% → 平均 2%。訊號只在第一檔成立。
    events = [{"date": "2026-07-01", "sid": "A", "ret": 0.10, "fired": ["signal_ma"]}]
    by_date = {"2026-07-01": [0.10, 0.0, -0.04]}
    st = bt.events_to_stats(events, by_date)
    assert st["signal_ma"]["count"] == 1
    assert st["signal_ma"]["wins"] == 1                       # 絕對：+10% > 0
    assert st["signal_ma"]["exc_wins"] == 1                   # 超額：10% − 2% = +8%
    assert round(st["signal_ma"]["exc_sum"], 6) == round(0.10 - 0.02, 6)


def test_大盤更強時_上漲也算輸():
    # 個股 +3%，但同日全市場平均 +8% → 絕對算贏、超額算輸。這是新舊做法的關鍵差異。
    events = [{"date": "2026-07-01", "sid": "A", "ret": 0.03, "fired": ["signal_ma"]}]
    by_date = {"2026-07-01": [0.08, 0.08, 0.08]}
    st = bt.events_to_stats(events, by_date)
    assert st["signal_ma"]["wins"] == 1
    assert st["signal_ma"]["exc_wins"] == 0


# ── 多時間窗勝率榜（windowed_stats）────────────────────────────────────
def test_windowed_stats_依日期切窗與per窗基準():
    # 三個事件分佈在不同時間；as_of=2026-07-23
    #   3m 界=2026-04-24、6m 界=2026-01-24、1y 界=2025-07-23
    events = [
        {"date": "2026-07-01", "sid": "A", "ret": 0.05, "fired": ["signal_ma"]},  # 落在所有窗
        {"date": "2026-01-01", "sid": "B", "ret": 0.03, "fired": ["signal_ma"]},  # 只在 1y、all
        {"date": "2024-09-01", "sid": "C", "ret": 0.02, "fired": ["signal_ma"]},  # 只在 all
    ]
    by_date = {  # 每日基準均值為 0（[x,-x]），讓超額＝該股報酬，方便手算
        "2026-07-01": [0.05, -0.05],
        "2026-01-01": [0.03, -0.03],
        "2024-09-01": [0.02, -0.02],
    }
    w = bt.windowed_stats(events, by_date, "2026-07-23")
    s = w["signal_ma"]
    # 窗內樣本數：3m 只 7/1（1）；6m 同（1/1 早於 1/24 被排除）；1y 加上 1/1（2）；all 全部（3）
    assert s["3m"]["samples"] == 1
    assert s["6m"]["samples"] == 1
    assert s["1y"]["samples"] == 2
    assert s["all"]["samples"] == 3
    # per-窗基準：3m 只用窗內那天 → 超額＝5pp；all 平均 (5+3+2)/3 = 3.33pp
    assert s["3m"]["avg_excess"] == 5.0
    assert s["all"]["avg_excess"] == 3.33
    # 結構：每訊號有 label 與四個窗
    assert s["label"] == "糾結轉強"
    assert set(k for k in s if k != "label") == {"3m", "6m", "1y", "all"}


def test_windowed_stats_沒事件的訊號各窗樣本為零():
    w = bt.windowed_stats([], {}, "2026-07-23")
    assert w["signal_breakout"]["all"]["samples"] == 0
    assert w["signal_breakout"]["3m"]["avg_excess"] is None


def test_windowed_stats_無as_of回空():
    assert bt.windowed_stats([{"date": "2026-07-01", "sid": "A", "ret": 0.05,
                               "fired": ["signal_ma"]}], {"2026-07-01": [0.05]}, "") == {}


# ── 組合戰績（combo_stats）────────────────────────────────────────────
def _cev(date, sid, i, ret, sigs):
    return {"date": date, "sid": sid, "i": i, "ret": ret, "raw_fired": sigs, "fired": sigs}


def test_combo_stats_兩兩組合超額樣本與回傳結構():
    # A、B 常一起出現且贏；C 單獨出現。基準均值 0（[x,-x]）→ 超額＝報酬。不同 sid 不觸發組合冷卻。
    events = [
        _cev("d1", "1", 0, 0.05, ["signal_ma", "signal_breakout"]),
        _cev("d2", "2", 0, 0.03, ["signal_ma", "signal_breakout"]),
        _cev("d3", "3", 0, -0.01, ["signal_ma", "signal_breakout"]),
        _cev("d4", "4", 0, 0.02, ["sn_squeeze_breakout"]),  # 單一，不成組合
    ]
    by_date = {"d1": [0.05, -0.05], "d2": [0.03, -0.03], "d3": [-0.01, 0.01], "d4": [0.02, -0.02]}
    combos, pairs = bt.combo_stats(events, by_date, min_sample=1)
    ma_bo = [c for c in combos if set(c["sigs"]) == {"signal_ma", "signal_breakout"}]
    assert len(ma_bo) == 1
    c = ma_bo[0]
    assert c["samples"] == 3
    # gross_excess＝毛超額（手算對照）；avg_excess 自 2026-07-25 起是**成本後**超額，
    # 與單訊號權重同一把尺（同一頁不能兩套尺，否則會拿組合的毛值去比單訊號的淨值）。
    assert c["gross_excess"] == round((0.05 + 0.03 - 0.01) / 3 * 100, 2)  # 2.33pp
    net_hand = sum(bt._apply_cost(r) for r in (0.05, 0.03, -0.01)) / 3 * 100
    assert c["avg_excess"] == round(net_hand, 2)
    assert c["avg_excess"] < c["gross_excess"]
    assert c["excess_win_rate"] == round(2 / 3, 4)
    assert "糾結轉強" in c["labels"] and "爆量突破" in c["labels"]
    assert not any(len(x["sigs"]) < 2 for x in combos)
    # pairs 應含這個兩兩配對（給熱力圖）
    assert any(set(p["sigs"]) == {"signal_ma", "signal_breakout"} for p in pairs)


def test_combo_stats_樣本門檻():
    events = [_cev("d1", "1", 0, 0.10, ["signal_ma", "signal_breakout"])]
    by_date = {"d1": [0.0]}
    combos, pairs = bt.combo_stats(events, by_date, min_sample=5)
    assert combos == [] and pairs == []            # 1 筆 <5 被濾掉
    combos2, _ = bt.combo_stats(events, by_date, min_sample=1)
    assert combos2 and combos2[0]["samples"] == 1


def test_combo_stats_組合級冷卻去重():
    # 同一檔、同一組合，冷卻期(預設20)內連續成立 → 只算一筆，不灌水
    events = [
        _cev("d1", "1", 0, 0.05, ["signal_ma", "signal_breakout"]),
        _cev("d2", "1", 3, 0.05, ["signal_ma", "signal_breakout"]),   # i 差 3 < 20 → 不採計
        _cev("d3", "1", 25, 0.05, ["signal_ma", "signal_breakout"]),  # i 差 25 ≥ 20 → 再採計
    ]
    by_date = {"d1": [0.0], "d2": [0.0], "d3": [0.0]}
    combos, _ = bt.combo_stats(events, by_date, min_sample=1, cooldown=20)
    assert combos[0]["samples"] == 2               # 中間那筆被冷卻濾掉


def test_combo_stats_穩健度下界壓低小樣本波動():
    # 高波動小樣本：平均超額不低，但 excess_lb（下界）應明顯低於平均
    events = [
        _cev("d1", "1", 0, 0.20, ["signal_ma", "signal_breakout"]),
        _cev("d2", "2", 0, -0.10, ["signal_ma", "signal_breakout"]),
    ]
    by_date = {"d1": [0.0], "d2": [0.0]}
    combos, _ = bt.combo_stats(events, by_date, min_sample=1)
    c = combos[0]
    assert c["gross_excess"] == 5.0                 # 毛：(20-10)/2 = 5pp
    assert c["avg_excess"] < c["gross_excess"]      # 成本後一定更低
    assert c["excess_lb"] < c["avg_excess"]         # 波動大 → 下界被壓低


def test_combo_stats_日期群聚校正標準誤():
    """同一天成立的事件高度相關（同一個大盤環境、同一波行情）。當成獨立樣本會低估標準誤、
    高估顯著性。改成先取每日平均、再對日平均算 SE（cluster-robust）。

    構造：兩天，每天 3 筆完全相同的超額 → 天內變異為 0、跨日變異才是真的不確定性。
    若把 6 筆當獨立樣本，SE 會被 sqrt(6) 除而虛小；群聚校正只被 sqrt(2 天) 除。"""
    ev = []
    for sid, r in (("1", 0.10), ("2", 0.10), ("3", 0.10)):
        ev.append(_cev("d1", sid, 0, r, ["signal_ma", "signal_breakout"]))
    for sid, r in (("4", -0.02), ("5", -0.02), ("6", -0.02)):
        ev.append(_cev("d2", sid, 0, r, ["signal_ma", "signal_breakout"]))
    by_date = {"d1": [0.0], "d2": [0.0]}
    c = bt.combo_stats(ev, by_date, min_sample=1)[0][0]
    assert c["samples"] == 6 and c["n_days"] == 2
    assert c["se_kind"] == "clustered"
    # 日平均 = +10pp 與 −2pp → 毛均值 4pp；跨日 SE = std([10,-2])/sqrt(2)
    assert c["gross_excess"] == 4.0
    assert c["avg_excess"] < 4.0            # 成本後（來回 0.785%）必然更低
    # 天內無變異 → 若當成獨立樣本 SE 會接近 0、下界幾乎等於平均；群聚校正後要明顯被壓低
    assert c["excess_lb"] < c["avg_excess"] - 1.0, "群聚校正後下界要被顯著壓低"
    assert abs(c["t_stat"]) < 2.0, f"只有 2 天的樣本 t 值不該很大，實際 {c['t_stat']}"


def test_combo_stats_單日樣本退回未校正並標記():
    """全部事件都在同一天 → 算不出跨日變異，退回 naive SE 並標記，不能假裝有校正。"""
    ev = [_cev("d1", str(i), 0, 0.05 + i * 0.01, ["signal_ma", "signal_breakout"]) for i in range(4)]
    c = bt.combo_stats(ev, {"d1": [0.0]}, min_sample=1)[0][0]
    assert c["n_days"] == 1 and c["se_kind"] == "naive"


def test_combo_stats_多重比較門檻隨組合數變嚴():
    """從 N 組裡挑最高，本來就會挑到運氣好的。Bonferroni 門檻要隨檢定數變嚴。"""
    assert round(bt._z_for_bonferroni(1), 2) == 1.96      # 單一檢定＝教科書值
    z36, z680 = bt._z_for_bonferroni(36), bt._z_for_bonferroni(680)
    assert 3.1 < z36 < 3.3 and 3.9 < z680 < 4.1
    assert z680 > z36 > bt._z_for_bonferroni(1)
    # 小樣本高波動的組合不該過門檻
    ev = [_cev("d1", "1", 0, 0.20, ["signal_ma", "signal_breakout"]),
          _cev("d2", "2", 0, -0.10, ["signal_ma", "signal_breakout"])]
    c = bt.combo_stats(ev, {"d1": [0.0], "d2": [0.0]}, min_sample=1)[0][0]
    assert c["survives_mc"] is False


# ── Phase A：walk-forward 樣本外驗證（walk_forward_oos）────────────────────
def test_oos_fold_count_math():
    # N=312 → (312-292)//20+1 = 2 folds；N=291 → 不足一個 fold（0）
    o2, f2 = bt.walk_forward_oos([], {d: [0.0] for d in _seq_dates(312)})
    assert f2 == 2
    o0, f0 = bt.walk_forward_oos([], {d: [0.0] for d in _seq_dates(291)})
    assert f0 == 0
    assert o0["signal_ma"]["status"] == "no_events"


def test_oos_穩健訊號_一致正超額():
    # 每天都有正 +5pp 超額的訊號 → 每個 fold 訓練都合格、樣本外也 +5 → robust、retention 1.0
    dates = _seq_dates(440)                          # F = (440-292)//20+1 = 8 folds
    by_date = {d: [0.0] for d in dates}              # 基準 0 → 超額＝報酬
    events = [{"date": d, "sid": s, "ret": 0.05, "fired": ["signal_ma"]}
              for d in dates for s in ("A", "B")]
    oos, F = bt.walk_forward_oos(events, by_date)
    r = oos["signal_ma"]
    assert F == 8
    assert r["status"] == "robust"
    assert r["excess_pp"] == 5.0
    assert r["selected_fraction"] == 1.0
    assert r["retention_ratio"] == 1.0
    assert r["selected_folds"] == 8 and r["active_dates"] >= 10


def test_oos_過擬合訊號_訓練正樣本外負():
    # 前 252 天 +8pp、之後 −8pp：早期 fold 訓練期看好（合格），但其樣本外落在負區 → overfit
    dates = _seq_dates(440)
    by_date = {d: [0.0] for d in dates}
    events = []
    for i, d in enumerate(dates):
        ret = 0.08 if i < 252 else -0.08
        for s in ("A", "B"):
            events.append({"date": d, "sid": s, "ret": ret, "fired": ["signal_ma"]})
    oos, _ = bt.walk_forward_oos(events, by_date)
    r = oos["signal_ma"]
    assert r["selected_folds"] >= 3                  # 早期 fold 訓練期為正、確實被選
    assert r["excess_pp"] < 0                         # 但樣本外是負的
    assert r["status"] == "overfit"


def test_oos_樣本不足誠實標示():
    # 只有 5 筆歷史事件 → 連訓練門檻都不到，標 insufficient_history、不硬算
    dates = _seq_dates(400)
    by_date = {d: [0.0] for d in dates}
    events = [{"date": dates[i], "sid": "A", "ret": 0.05, "fired": ["signal_ma"]}
              for i in range(5)]
    oos, _ = bt.walk_forward_oos(events, by_date)
    assert oos["signal_ma"]["status"] == "insufficient_history"


# ── Phase A：EWMA 時間自適應權重（adaptive_weights）──────────────────────
def test_ess_by_date_群聚():
    assert bt._ess_by_date([]) == 0.0
    assert bt._ess_by_date(["d1", "d1", "d1"]) == 1.0        # 全同一天 → 相當於 1 個獨立樣本
    assert round(bt._ess_by_date(["d1", "d2", "d3", "d4"]), 6) == 4.0   # 全不同天 → 4


def test_adaptive_近期加權高於歷史():
    # 前 50 天 +2pp、最後 10 天 +10pp → EWMA 近期均值應被拉高，且介於歷史與最新之間
    dates = _seq_dates(60)
    by_date = {d: [0.0] for d in dates}
    events = [{"date": dates[i], "sid": "A", "ret": (0.10 if i >= 50 else 0.02),
               "fired": ["signal_ma"]} for i in range(60)]
    adp = bt.adaptive_weights(events, by_date)["signal_ma"]
    assert adp["status"] == "eligible"
    assert adp["hist_excess_pp"] == round((50 * 2 + 10 * 10) / 60, 2)   # 3.33pp
    assert adp["recent_excess_pp"] > adp["hist_excess_pp"]              # 近期被拉高
    assert adp["effective_excess_pp"] < adp["blended_excess_pp"]        # 收縮後變小
    assert 1 <= adp["candidate_weight"] <= 5


def test_adaptive_樣本不足與零樣本():
    dates = _seq_dates(60)
    by_date = {d: [0.0] for d in dates}
    few = [{"date": dates[i], "sid": "A", "ret": 0.05, "fired": ["signal_ma"]} for i in range(10)]
    adp = bt.adaptive_weights(few, by_date)
    assert adp["signal_ma"]["status"] == "insufficient_history"
    assert adp["signal_ma"]["candidate_weight"] == 0
    assert adp["signal_breakout"]["status"] == "no_events"              # 完全沒出現
    assert adp["signal_breakout"]["candidate_weight"] == 0


def test_attach_phase_a_併入欄位不動原weight():
    dates = _seq_dates(440)
    by_date = {d: [0.0] for d in dates}
    events = [{"date": d, "sid": s, "ret": 0.05, "fired": ["signal_ma"]}
              for d in dates for s in ("A", "B")]
    weights = {"signals": bt.stats_to_weights(bt.events_to_stats(events, by_date))}
    before = weights["signals"]["signal_ma"]["weight"]
    oos, F = bt.attach_phase_a(weights, events, by_date)
    sig = weights["signals"]["signal_ma"]
    assert sig["weight"] == before                    # 現行 weight 一律不動
    assert sig["spec_version"] == bt.PHASE_A_SPEC
    assert sig["oos"]["status"] == "robust"
    assert sig["adaptive"]["candidate_weight"] >= 1


# ── Phase B：橫斷面訊號（相對強弱 RS ＋ 產業輪動）─────────────────────────
def test_pct_rank_avg():
    r = bt._pct_rank_avg({"a": 1, "b": 2, "c": 3, "d": 4, "e": 5})
    assert r["a"] == 0.0 and r["e"] == 1.0 and r["c"] == 0.5   # 最弱0、最強1、中位0.5
    r2 = bt._pct_rank_avg({"a": 1, "b": 1, "c": 3})            # 同分 → 平均排名
    assert r2["a"] == r2["b"] == 0.25 and r2["c"] == 1.0


def test_winsorize_夾極端值():
    w = bt._winsorize({"a": -100, "b": 1, "c": 2, "d": 3, "e": 100})
    assert w["a"] > -100 and w["e"] < 100                       # 極端值被夾
    assert w["c"] == 2                                          # 中間不動


def test_xsect_flags_門檻():
    assert bt._xsect_flags(None) == {"rs_strong_60": False, "rs_confirmed_60_120": False,
                                     "industry_hot": False}
    full = bt._xsect_flags({"rs_pct_60": 0.85, "rs_pct_120": 0.75, "industry_hot": True})
    assert full == {"rs_strong_60": True, "rs_confirmed_60_120": True, "industry_hot": True}
    # 60 強但 120 不足 → 只有 strong、沒有雙確認
    assert bt._xsect_flags({"rs_pct_60": 0.85, "rs_pct_120": 0.6, "industry_hot": False})["rs_confirmed_60_120"] is False
    # 60 不強 → 都不成立
    assert bt._xsect_flags({"rs_pct_60": 0.5, "rs_pct_120": 0.9, "industry_hot": False})["rs_strong_60"] is False


def test_build_xsect_cache_相對強弱與產業():
    dates = _seq_dates(65)
    n_stocks, n_ind = 300, 30
    # 產業編號越大漲越多（IND29 最強、IND00 最弱）；每產業 10 檔
    universe = [{"id": f"S{i:03d}", "name": str(i), "market": "上市", "industry": f"IND{i % n_ind:02d}"}
                for i in range(n_stocks)]
    price_hist = {}
    for i in range(n_stocks):
        rate = (i % n_ind + 1) / n_ind          # 0.033 ~ 1.0
        by = {}
        for d, day in enumerate(dates):
            close = round(100 * (1 + rate * d / 60), 4)
            by[day] = [close, close, close, close, 1000, 0]
        price_hist[f"S{i:03d}"] = by
    cache = bt.build_xsect_cache(price_hist, {}, universe)
    last = dates[-1]
    assert last in cache
    strong = cache[last]["S029"]                 # 屬 IND29（最強產業）
    weak = cache[last]["S000"]                    # 屬 IND00（最弱產業）
    assert strong["rs_pct_60"] >= 0.80 and strong["industry_hot"] is True
    assert weak["rs_pct_60"] < 0.80 and weak["industry_hot"] is False
    # 併進 collect_events 後，最強股會有 rs_strong_60 訊號
    assert bt._xsect_flags(strong)["rs_strong_60"] is True
    assert bt._xsect_flags(weak)["rs_strong_60"] is False


def test_collect_events_併入橫斷面訊號():
    # 用同一組合成資料跑 collect_events，最強股的事件 fired 應含 rs_strong_60
    dates = _seq_dates(90)                        # 要夠長：min_bars 65 + forward 20
    universe = [{"id": f"S{i:03d}", "name": str(i), "market": "上市", "industry": f"IND{i % 30:02d}"}
                for i in range(300)]
    price_hist = {}
    for i in range(300):
        rate = (i % 30 + 1) / 30
        by = {}
        for d, day in enumerate(dates):
            close = round(100 * (1 + rate * d / 60), 4)
            by[day] = [close, close, close, close, 500000, 0]   # 50 萬股＝500 張，過流動性門檻
        price_hist[f"S{i:03d}"] = by
    xsect = bt.build_xsect_cache(price_hist, {}, universe)
    events, by_date = bt.collect_events(price_hist, {}, {}, universe, xsect=xsect)
    # 最強產業的股票應該有 rs_strong_60 事件（不保證每檔每日，但整體要出現）
    fired_all = set()
    for e in events:
        fired_all.update(e["raw_fired"])
    assert "rs_strong_60" in fired_all


def test_進場價用隔日開盤而非當日收盤():
    """Andy 收到名單時管線已收盤（18:17 發榜），最快隔天開盤才買得到——回測必須用同一把尺，
    不能用『訊號當日收盤』偷跑進場。實測用這把尺量出候選股隔夜跳空中位 +0.42%，用當日收盤
    進場會讓每筆交易的績效虛高約 0.5pp（2026-07-26 口徑更正）。

    造一檔：訊號日（i=70）收盤 135（100+70*0.5，見 _make_rows）、隔日開盤跳空到 110、
    第 20 交易日收盤 121。i=70 落在 collect_events 的可評估範圍
    [MIN_BARS-1, n-FORWARD) = [64, 80)（n=100）內，且上升序列保證多頭排列訊號恆成立。"""
    n = 100
    rows = _make_rows(n=n, close=100.0)
    i_sig = 70
    rows[i_sig + 1]["open"] = 110.0
    rows[i_sig + 20]["close"] = 121.0
    price_hist = {"9999": _rows_to_hist(rows)}
    universe = [{"id": "9999", "name": "測試", "market": "上市", "industry": "IND00"}]
    events, by_date = bt.collect_events(price_hist, {}, {}, universe)
    ev = [e for e in events if e["i"] == i_sig]
    assert ev, "訊號日應有事件（多頭排列訊號在單調上升序列中應恆成立）"
    # 用隔日開盤 110 進場 → 121/110-1 = 10%；若誤用訊號日收盤 135 進場會是 121/135-1 ≈ -10.4%
    assert abs(ev[0]["ret"] - 0.10) < 1e-6, f"實際 {ev[0]['ret']}"
    # by_date 基準母體必須用同一口徑（同一個 ret 值），否則超額報酬會被算偏
    di = rows[i_sig]["date"]
    assert any(abs(r - 0.10) < 1e-6 for r in by_date.get(di, [])), \
        f"by_date[{di}] 應含同一口徑算出的 0.10，實際 {by_date.get(di)}"


# ── Phase B-5：出場優化（exit_analysis）─────────────────────────────────
def test_net_return_成本後公式():
    # 進場 100、出場 110：毛報酬 10%，扣來回成本後淨報酬應略低於 10%
    net = bt._net_return(100, 110)
    gross = 110 / 100 - 1
    assert net < gross                                   # 成本拖累
    # 手算：110*(1-0.001425-0.003-0.001)/(100*(1+0.001425+0.001)) - 1
    expect = 110 * (1 - 0.001425 - 0.003 - 0.001) / (100 * (1 + 0.001425 + 0.001)) - 1
    assert abs(net - expect) < 1e-12


def test_exit_analysis_持有期比較與結構():
    dates = _seq_dates(120)
    # 線性上漲 close=100+d：持有越久毛報酬越高
    by = {d: [100 + i, 100 + i, 100 + i, 100 + i, 500000, 0] for i, d in enumerate(dates)}
    price_hist = {"A": by}
    events = [{"date": dates[64], "sid": "A", "i": 64, "ret": 0.1,
               "fired": ["signal_ma"], "raw_fired": ["signal_ma"]}]
    res = bt.exit_analysis(events, price_hist, {})
    assert res["n_events"] == 1 and res["control"] == "h20"
    rows = {s["key"]: s for s in res["strategies"]}
    assert set(rows) == {"h5", "h10", "h20", "h40", "trail10"}
    # 進場＝次日收盤 ac[65]=165；持有 20 日 → 出場 ac[85]=185
    expect_h20 = round(bt._net_return(165, 185) * 100, 2)
    assert rows["h20"]["avg_net_return"] == expect_h20
    # 上漲行情：持有越久淨報酬越高
    assert rows["h5"]["avg_net_return"] < rows["h20"]["avg_net_return"] < rows["h40"]["avg_net_return"]
    # 單一股票時，基準＝自己的毛報酬 → 淨超額約等於「負的成本拖累」
    assert rows["h20"]["avg_net_excess"] < 0
    # 一路上漲不會回落 10% → 停利策略持有到 40 日上限
    assert rows["trail10"]["avg_holding_days"] == 40.0
    # 停利持有天數變動，沒有乾淨的同持有期基準 → 淨超額留 None（不硬用 20 日基準）
    assert rows["trail10"]["avg_net_excess"] is None


def test_exit_analysis_進場價用隔日開盤而非收盤():
    """跟 collect_events 用同一把尺（2026-07-26 口徑更正）：exit_analysis 的『次日進場』
    也要用開盤價，不能用次日收盤——否則 signal_weights（勝率榜）跟 signal_exits（出場優化）
    這兩份報表對同一批交易算出不同的進場成本，數字會對不起來。"""
    dates = _seq_dates(120)
    by = {d: [100 + i, 100 + i, 100 + i, 100 + i, 500000, 0] for i, d in enumerate(dates)}
    entry_i = 65                      # i=64 的隔日（i+1），即實際進場那天
    by[dates[entry_i]][0] = 130.0     # 進場日開盤跳空，跟當日收盤（165）不同
    price_hist = {"A": by}
    events = [{"date": dates[64], "sid": "A", "i": 64, "ret": 0.1,
               "fired": ["signal_ma"], "raw_fired": ["signal_ma"]}]
    res = bt.exit_analysis(events, price_hist, {})
    rows = {s["key"]: s for s in res["strategies"]}
    # 進場＝隔日開盤 130（不是隔日收盤 165）；持有 20 日 → 出場 close[85] = 185
    expect_h20 = round(bt._net_return(130, 185) * 100, 2)
    assert rows["h20"]["avg_net_return"] == expect_h20


def test_exit_analysis_路徑不足略過():
    # 進場後不足 40 日完整路徑的事件要被略過（各持有期才公平可比）
    dates = _seq_dates(90)
    by = {d: [100 + i, 100 + i, 100 + i, 100 + i, 500000, 0] for i, d in enumerate(dates)}
    events = [{"date": dates[64], "sid": "A", "i": 64, "ret": 0.1,
               "fired": ["signal_ma"], "raw_fired": ["signal_ma"]}]  # 65+40=105 >= 90 → 略過
    res = bt.exit_analysis(events, {"A": by}, {})
    assert res["n_events"] == 0


# ── Phase C：防騙指標（signal_quality）─────────────────────────────────
def test_apply_cost_扣成本():
    assert bt._apply_cost(0.0) < 0                        # 沒漲也要付來回成本 → 淨為負
    assert bt._apply_cost(0.10) < 0.10                    # 毛 10% 淨 <10%


def test_signal_quality_高勝率陷阱():
    # 19 筆小賺 +2%（撐得過成本）、1 筆大賠 −30%：勝率 95% 但一次大賠讓成本後期望值為負 → 陷阱成立
    # by_date 給空的＝大盤持平，此時成本後超額等於成本後絕對報酬
    events = [{"date": f"d{i}", "sid": str(i), "i": 0, "ret": 0.02,
               "fired": ["signal_ma"]} for i in range(19)]
    events.append({"date": "dX", "sid": "X", "i": 0, "ret": -0.30, "fired": ["signal_ma"]})
    q = bt.signal_quality(events, {})["signal_ma"]
    assert q["samples"] == 20
    assert q["net_win_rate"] >= 0.90                               # 高勝率
    assert q["net_expectancy"] < 0                                  # 但成本後期望值為負
    assert q["net_excess_expectancy"] < 0                           # 大盤持平 → 超額同樣為負
    assert q["high_win_trap"] is True                              # 陷阱旗標成立
    assert q["payoff_ratio"] is not None and q["payoff_ratio"] < 1  # 賺賠比 <1（賺小賠大）


def test_signal_quality_正常訊號不觸發陷阱():
    events = [{"date": f"d{i}", "sid": str(i), "i": 0, "ret": 0.05,
               "fired": ["signal_ma"]} for i in range(30)]
    q = bt.signal_quality(events, {})["signal_ma"]
    assert q["net_expectancy"] > 0 and q["high_win_trap"] is False
    assert q["profit_factor"] is None or q["profit_factor"] > 1


def test_signal_quality_贏不過大盤要現形():
    """迴歸測試（2026-07-25 修的 bug）：訊號絕對報酬是正的，但輸給同日大盤時，
    「成本後期望」必須為負並亮 loses_to_market——原本只算絕對報酬，這種訊號會顯示正數且被塗成好色。
    真實案例：破底翻 avg_excess −0.91pp（樣本 7101）卻顯示 net_expectancy +0.79pp。"""
    # 訊號 +4%，同日大盤 +8% → 絕對是賺的，但明顯跑輸大盤
    events = [{"date": f"d{i}", "sid": str(i), "i": 0, "ret": 0.04,
               "fired": ["signal_ma"]} for i in range(40)]
    by_date = {f"d{i}": [0.08] * 50 for i in range(40)}
    q = bt.signal_quality(events, by_date)["signal_ma"]
    assert q["net_expectancy"] > 0                     # 絕對報酬正（這是舊版唯一看到的數字）
    assert q["net_excess_expectancy"] < 0              # 但成本後超額為負 ← 修好的關鍵
    assert q["loses_to_market"] is True                # 且要亮警示
    assert q["beat_market_rate"] == 0.0                # 沒有一筆贏過大盤
    assert q["median_net_excess"] < 0                  # 中位數同樣為負


def test_collect_events_排除跨越價格斷點的樣本():
    """分割/減資的假漲跌（price_breaks.json）會生出 ±100% 的假報酬。
    跨過斷點的 20 日報酬樣本必須整筆丟掉——連基準母體 by_date 也要丟，
    否則假報酬會拉歪當日全市場平均（實測 0050 −74%、2380 +279% 都是這種）。"""
    # 造一檔連續上漲的價格序列，長度足夠算指標＋持有期
    n = 120
    price_hist = {"9999": {f"2025-{1 + i // 28:02d}-{1 + i % 28:02d}": [10 + i * 0.1] * 4 + [500000, 0]
                           for i in range(n)}}
    uni = [{"id": "9999", "name": "測試", "industry": "其他"}]
    # 不給斷點 → 應該收到基準母體
    _, by_date_clean = bt.collect_events(price_hist, {}, {}, uni, breaks=set())
    assert by_date_clean, "沒有斷點時應該有可評估樣本"

    # 把「某一天」標成斷點 → 跨過它的那些報酬窗全部要消失（含基準母體）。
    # 斷點索引必須落在 (MIN_BARS-1, n-1] 內才會有報酬窗跨過它——選 60 的話進場最早也是
    # 第 64 根（指標暖身），窗口 (64, 84] 根本跨不到 60，什麼都不會被排除。
    broken_date = sorted(price_hist["9999"])[80]
    _, by_date_brk = bt.collect_events(price_hist, {}, {}, uni, breaks={("9999", broken_date)})
    dates_clean, dates_brk = set(by_date_clean), set(by_date_brk)
    assert dates_brk < dates_clean, "標了斷點後基準母體的日期應該變少"
    # 報酬窗 = (i, i+20]，所以進場日落在斷點前 20 天內的都該被排除
    idx = {d: i for i, d in enumerate(sorted(price_hist["9999"]))}
    removed = dates_clean - dates_brk
    assert removed, "應該有樣本被排除"
    for d in removed:
        assert idx[d] < idx[broken_date] <= idx[d] + bt.FORWARD


def test_signal_quality_中位數揭露右偏():
    """平均被少數飆股拉高、中位數為負的情境要看得出來（訊號報酬極度右偏）。"""
    events = [{"date": f"d{i}", "sid": str(i), "i": 0, "ret": -0.01,
               "fired": ["signal_ma"]} for i in range(39)]
    events.append({"date": "dBig", "sid": "B", "i": 0, "ret": 3.0, "fired": ["signal_ma"]})
    q = bt.signal_quality(events, {})["signal_ma"]
    assert q["net_excess_expectancy"] > 0              # 平均被那一筆 +300% 拉成正的
    assert q["median_net_excess"] < 0                  # 但典型結果是虧的


# ── 市況分層回測（build_regime_series / regime_stratified_stats）──────────
def test_breadth_status_門檻():
    assert bt._breadth_status(0.60, 0.01) == "green"     # 多數站上月線、報酬正
    assert bt._breadth_status(0.30, -0.02) == "red"      # 多數在月線下、報酬負
    assert bt._breadth_status(0.50, 0.0) == "yellow"     # 中間


def test_build_regime_series_多頭與空頭():
    dates = _seq_dates(30)
    up = {f"S{i}": {d: [100 + j, 100 + j, 100 + j, 100 + j, 500000, 0]
                    for j, d in enumerate(dates)} for i in range(120)}
    assert bt.build_regime_series(up, {})[dates[-1]] == "green"     # 一路漲 → 綠
    down = {f"S{i}": {d: [200 - j * 2, 200 - j * 2, 200 - j * 2, 200 - j * 2, 500000, 0]
                      for j, d in enumerate(dates)} for i in range(120)}
    assert bt.build_regime_series(down, {})[dates[-1]] == "red"     # 一路跌 → 紅


def test_build_regime_series_樣本不足unknown():
    dates = _seq_dates(30)
    few = {f"S{i}": {d: [100 + j] * 4 + [500000, 0] for j, d in enumerate(dates)} for i in range(50)}
    assert bt.build_regime_series(few, {})[dates[-1]] == "unknown"  # <100 檔不判


def test_regime_stratified_stats_依市況分層():
    events = [
        {"date": "g1", "sid": "A", "i": 0, "ret": 0.05, "fired": ["signal_ma"]},
        {"date": "r1", "sid": "B", "i": 0, "ret": -0.03, "fired": ["signal_ma"]},
    ]
    by_date = {"g1": [0.0], "r1": [0.0]}
    regime = {"g1": "green", "r1": "red"}
    out = bt.regime_stratified_stats(events, by_date, regime)["signal_ma"]
    assert out["green"]["samples"] == 1 and out["green"]["avg_excess"] == 5.0
    assert out["red"]["samples"] == 1 and out["red"]["avg_excess"] == -3.0
    assert out["yellow"]["samples"] == 0                 # 無盤整事件


# ── 除權息回填涵蓋範圍警告（只印警告，不改任何統計計算）───────────────────
def test_dividend_coverage_gap_全落在範圍內為零():
    import history_store as hs
    div_hist = {}
    hs.set_div_coverage(div_hist, "2024-08-01", "2026-07-24")
    dates = _seq_dates(5, start="2025-01-01")
    gap, start, end, src = bt.dividend_coverage_gap(dates, div_hist)
    assert gap == 0.0 and src == "meta" and (start, end) == ("2024-08-01", "2026-07-24")


def test_dividend_coverage_gap_真的沒有任何事件才算全部在範圍外():
    dates = _seq_dates(5, start="2025-01-01")
    gap, start, end, src = bt.dividend_coverage_gap(dates, {})
    assert gap == 1.0 and src == "none" and start is None


def test_dividend_coverage_gap_沒metadata時用實際事件日期推估():
    """迴歸測試（2026-07-25）：原本沒有 __meta__ 就一律回 1.0，等於把「已經抓到並還原好的
    區間」也謊報成沒還原（實測 dividends.json 有 2026-01-13~07-24 的真實事件，卻報 100%）。
    現在改用事件日期的 min/max 推估。"""
    div_hist = {"8021": {"2025-01-03": 0.99, "2025-01-08": 0.98}}   # 沒有 __meta__
    dates = _seq_dates(5, start="2025-01-01")   # 01-01 ~ 01-05
    gap, start, end, src = bt.dividend_coverage_gap(dates, div_hist)
    assert src == "inferred" and (start, end) == ("2025-01-03", "2025-01-08")
    assert gap == 0.4        # 01-01、01-02 在推估涵蓋範圍之前 → 2/5
    # __meta__ 這類保留鍵不可被當成股票代號
    assert bt.dividend_coverage_gap(dates, {"__meta__": {"x": 1}})[3] == "none"


def test_dividend_coverage_gap_部分落在範圍外():
    import history_store as hs
    div_hist = {}
    hs.set_div_coverage(div_hist, "2025-01-03", "2025-01-10")
    dates = _seq_dates(5, start="2025-01-01")   # 01-01, 01-02, 01-03, 01-04, 01-05
    # 01-01、01-02 落在涵蓋範圍之前 → 2/5 = 0.4
    assert bt.dividend_coverage_gap(dates, div_hist)[0] == 0.4


def test_dividend_coverage_gap_空日期列表回零():
    assert bt.dividend_coverage_gap([], {})[0] == 0.0
