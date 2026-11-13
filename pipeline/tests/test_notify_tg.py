"""TG 快報訊息組裝的單元測試。

2026-07-25 大改：快報的排名**完全來自 opportunities.json**（網站那份），
原本的 score() 退路排序已刪除（Andy 裁示「候選不足就不用硬要呈現」）。
所以這支檔案不再測評分，改測三件更重要的事：

1. **管線故障不可講成市場結論**——名單檔案缺席時，訊息必須說「沒產出」，
   絕對不能說「今日沒有明顯符合標的，先觀望」（那是憑空的看空判斷）。
   2026-07-25 真的發生過：引擎掛掉、網站是空的，而快報卻讓人以為今天大盤沒機會。
2. **真的零檔要照實說**，而且要跟故障分得清楚。
3. **編號對任何檔數都不能爆**（TOP_N 從 5 改成 10 時寫死的 5 個圈號炸掉了整條部署）。

⚠️ 測試前提的教訓：這支檔案原本有個「用 TOP_N 檔假資料建訊息」的測試，
但它沒有提供 opportunities.json，所以退路被刪除後它其實走到「故障訊息」那條路——
測試還是綠的，卻**完全沒測到編號**。現在改成寫一份真的 opportunities.json 再測。

2026-07-26 再改：Andy 裁示「不用幫我配好購買組合，我自己會挑」。opportunities.json 的
picks 不再截斷成固定檔數（今天實跑 142 檔），每檔多了 tier（2026-11-13 起 edge/None，舊檔可能有 win/both/return）。
快報從「①②③…⑩ 編號單一清單」改成「勝率偏優／報酬偏優／雙優」三分類摘要，不再有任何
暗示購買順序或組合的字樣（圈號 ①②③、「精選」、「Top」都不行）。
`_num`/`CIRCLED`（圈號防爆）連同它的迴歸測試一起移除——不是「放寬斷言讓它綠」，而是
被保護的功能（序號本身）已經因為新規格整個拿掉了，繼續留著圈號防爆邏輯反而是死碼；
「大量候選不會 crash」這件事改由新測試 test_many_candidates_render_without_crash_and_group_by_tier
守住（見下方）。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import notify_tg as nt  # noqa: E402


def _stock(**kw):
    base = {"id": "1111", "name": "股1111", "close": 100.0, "bias20_pct": 0.0,
            "change_pct": 1.5, "ma20": 98.0}
    base.update(kw)
    return base


def _write_opp(tmp_path, monkeypatch, date, ids, tiers=None):
    """寫一份假 opportunities.json。

    tiers：None＝全部不分類（舊測試不關心 tier 時用）；單一字串＝全部套用同一 tier；
    跟 ids 等長的 list＝逐檔指定。2026-07-26 起每個 pick 多了 tier 欄位（win/both/return/None），
    這個 kwarg 讓舊測試（不關心分類）跟新測試（要測三分類摘要）共用同一個 fixture helper，
    不用另開一個重複的 helper。
    """
    if tiers is None:
        tier_list = [None] * len(ids)
    elif isinstance(tiers, str):
        tier_list = [tiers] * len(ids)
    else:
        tier_list = list(tiers)
    p = tmp_path / "opportunities.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"date": date,
                   "picks": [{"id": i, "tier": t} for i, t in zip(ids, tier_list)]},
                  f, ensure_ascii=False)
    monkeypatch.setattr(nt, "OPP_PATH", str(p))
    return p


# ── ① 管線故障 vs 真的零檔（講錯會讓人做錯決定）────────────────────────────────

def test_missing_file_says_pipeline_problem_not_market_view(tmp_path, monkeypatch):
    monkeypatch.setattr(nt, "OPP_PATH", str(tmp_path / "no_such_file.json"))
    text, _ = nt.build_message({"data_date": "2026-07-24", "count": 925,
                                "stocks": [_stock()]})
    assert "沒有產出" in text and "管線" in text
    assert "先觀望" not in text, "故障不可講成『先觀望』——那是憑空的市場判斷"
    assert "不是市場結論" in text


def test_date_mismatch_is_treated_as_failure(tmp_path, monkeypatch):
    """名單是昨天的 → 等於今天沒產出，不可拿舊名單當今天的推薦。"""
    _write_opp(tmp_path, monkeypatch, "2026-07-23", ["1111"])
    text, _ = nt.build_message({"data_date": "2026-07-24", "count": 925,
                                "stocks": [_stock()]})
    assert "沒有產出" in text and "股1111" not in text


def test_empty_picks_says_zero_and_is_a_valid_conclusion(tmp_path, monkeypatch):
    _write_opp(tmp_path, monkeypatch, "2026-07-24", [])
    text, _ = nt.build_message({"data_date": "2026-07-24", "count": 925,
                                "stocks": [_stock()]})
    assert "沒有個股通過門檻" in text and "有效結論" in text
    assert "管線" not in text, "零檔是正常結果，不該讓人以為系統壞了"


def test_ids_not_in_screener_counts_as_failure(tmp_path, monkeypatch):
    """名單有代號、但 screener 裡查不到 → 資料不一致，屬故障而非零檔。"""
    _write_opp(tmp_path, monkeypatch, "2026-07-24", ["9999"])
    text, _ = nt.build_message({"data_date": "2026-07-24", "count": 925,
                                "stocks": [_stock(id="1111")]})
    assert "沒有產出" in text


def test_no_hand_written_ranking_remains():
    """退路排序已刪除：不可再有自己一套分數（會跟網站說不同的話）。"""
    assert not hasattr(nt, "score"), "score() 已刪除，不要復活——排名一律以 opportunities.json 為準"
    assert not hasattr(nt, "load_weights")


# ── ② 排名與檔數 ──────────────────────────────────────────────────────────

def test_uses_website_order_exactly(tmp_path, monkeypatch):
    """快報順序必須與網站完全一致（同一份結論，不重新排序）。

    新版只顯示有 tier 分類的候選（tier=None 的多數候選只在網站看得到，不上快報），
    這裡固定給三檔同一個 tier（"win"）才能讓它們一起進到同一段落、測出順序有沒有被打亂。
    """
    ids = ["3577", "6166", "2395"]
    _write_opp(tmp_path, monkeypatch, "2026-07-24", ids, tiers="win")
    stocks = [_stock(id=i, name=f"股{i}") for i in reversed(ids)]   # 故意給反的順序
    text, _ = nt.build_message({"data_date": "2026-07-24", "count": 925, "stocks": stocks})
    pos = [text.index(f"股{i}") for i in ids]
    assert pos == sorted(pos), "訊息裡的順序要照 opportunities.json，不可自己排"


def test_many_candidates_render_without_crash_and_group_by_tier(tmp_path, monkeypatch):
    """大量候選不會 crash（迴歸 2026-07-25 TOP_N 5→10 時圈號 IndexError 炸掉整條推播的教訓）；
    2026-11-13 起只有「相對優勢」一段：edge 才列、超過顯示上限截斷且保留順序、None 不列。
    同時混入舊三分類值（both/win/return）驗證歷史檔相容：both/win＝相對優勢、return＝無分類。"""
    tiers = (["edge"] * 3 + ["win"] * 2 + ["both"] * 3 + ["return"] * 6 + [None] * 6)   # 共 20 檔
    ids = [str(9000 + i) for i in range(len(tiers))]
    _write_opp(tmp_path, monkeypatch, "2026-07-24", ids, tiers=tiers)
    stocks = [_stock(id=i, name=f"測試{i}", signal_ma=True) for i in ids]
    text, dd = nt.build_message({"data_date": "2026-07-24", "count": 925, "stocks": stocks})
    assert dd == "2026-07-24"
    assert "相對優勢候選（共 8 檔，這裡列前 5 檔）" in text
    for i in ids[0:5]:
        assert f"測試{i}" in text
    for i in ids[5:]:
        assert f"測試{i}" not in text, "超過顯示上限或沒有分類的候選不該出現"
    assert "其他候選 12 檔沒有分類稱號" in text


# ── ③ 候選情報分類（2026-11-13 起只有「相對優勢」＋「乖離排前段」描述標籤）───────────────

def test_no_purchase_order_or_selection_wording(tmp_path, monkeypatch):
    """「精選」「建議買」「Top」和圈號 ①②③ 都在暗示『照這個順序/這個組合買』，
    Andy 拍板「不用幫我配好組合、我自己會挑」之後這些字樣一律不能出現。"""
    ids = ["9001", "9002", "9003"]
    _write_opp(tmp_path, monkeypatch, "2026-07-24", ids, tiers=["edge", "edge", None])
    stocks = [_stock(id=i, name=f"股{i}") for i in ids]
    text, _ = nt.build_message({"data_date": "2026-07-24", "count": 925, "stocks": stocks})
    for bad in ("精選", "建議買", "Top", "①", "②", "③", "保證", "一定", "過半會賺"):
        assert bad not in text, f"不該出現「{bad}」"


def test_舊三分類稱號不再出現(tmp_path, monkeypatch):
    """2026-11-13：沒證據的稱號留在訊息上＝替它背書。就算讀到舊檔的舊值也不可印出舊稱號。"""
    ids = ["9001", "9002", "9003"]
    _write_opp(tmp_path, monkeypatch, "2026-07-24", ids, tiers=["both", "win", "return"])
    stocks = [_stock(id=i, name=f"股{i}") for i in ids]
    text, _ = nt.build_message({"data_date": "2026-07-24", "count": 925, "stocks": stocks})
    for bad in ("雙優", "勝率偏優", "報酬偏優"):
        assert bad not in text
    assert "相對優勢" in text
    assert text.count("股9001") == 1, "同一檔只出現一次"


def _write_tiers(tmp_path, monkeypatch, obj):
    p = tmp_path / "tier_stats.json"
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(nt, "TIER_STATS_PATH", str(p))


TS = {"date": "2026-11-13", "stale": False,
      "categories": {"edge": {"win_rate": 0.471}, "rest": {"win_rate": 0.43}},
      "paired": {"cat_edge_vs_rest": {"win_pp": 6.3, "win_ci90": [3.1, 9.4], "ev_pp": 1.9, "ev_ci90": [0.6, 3.3]},
                 "bias_high_vs_rest": {"win_pp": 0.4, "win_ci90": [-1.8, 2.6], "ev_pp": 0.5, "ev_ci90": [-0.8, 1.7]}},
      "by_gate": {"fallback": {"categories": {"edge": {"win_rate": 0.388}, "rest": {"win_rate": 0.427}}}}}


def test_主訊息是同日配對差且數字讀檔(tmp_path, monkeypatch):
    """主訊息＝相對優勢 vs 當日其餘候選的同日配對差（不是高 vs 低、不是單層勝率）；
    單檔賺錢機率照實放旁邊、不到一半要明講。數字一律讀 JSON，這裡用假數字驗證不是寫死。"""
    _write_opp(tmp_path, monkeypatch, "2026-07-24", ["9001"], tiers=["edge"])
    _write_tiers(tmp_path, monkeypatch, TS)
    text, _ = nt.build_message({"data_date": "2026-07-24", "count": 925, "stocks": [_stock(id="9001")]})
    assert "這不是購買組合" in text
    assert "同一天的候選裡，相對優勢這群比其他候選的賺錢機率多約 6.3 個百分點（誤差範圍 3.1～9.4）" in text
    assert "平均每筆也多約 1.9 個百分點（誤差範圍 0.6～3.3）" in text
    assert "單檔賺錢機率只有 47.1%，不到一半" in text
    assert "49%" not in text and "52%" not in text, "寫死的舊數字不可復活"


def test_幅度CI下限接近0用保守說法_跨0說量不出():
    t = dict(TS, paired={"cat_edge_vs_rest": {"win_pp": 6.3, "win_ci90": [3.1, 9.4],
                                              "ev_pp": 1.0, "ev_ci90": [0.2, 2.0]}})
    s = nt.tier_disclaimer(t)
    assert "略高約 1.0 個百分點，但接近量不出（誤差範圍 0.2～2.0）" in s and "也多約" not in s
    t2 = dict(TS, paired={"cat_edge_vs_rest": {"win_pp": 1.2, "win_ci90": [-0.8, 3.0],
                                               "ev_pp": 0.4, "ev_ci90": [-0.9, 1.5]}})
    s2 = nt.tier_disclaimer(t2)
    assert "量不出差別（差 +1.2 個百分點，誤差範圍 −0.8～3.0）" in s2
    assert "平均每筆量不出差別（誤差範圍 −0.9～1.5）" in s2 and "多約" not in s2


def test_單檔賺錢機率過半時照實講不寫死不到一半():
    t = dict(TS, categories={"edge": {"win_rate": 0.512}})
    s = nt.tier_disclaimer(t)
    assert "51.2%" in s and "不到一半" not in s and "過半也不代表穩賺" in s


def test_disclaimer_讀不到或缺欄位時不印數字(tmp_path, monkeypatch):
    """JSON 不在、欄位缺、或 null 都不能 crash，也不能印出數字。"""
    monkeypatch.setattr(nt, "TIER_STATS_PATH", str(tmp_path / "nope.json"))
    for t in (nt.load_tier_stats(), {}, {"paired": {}}, {"paired": {"cat_edge_vs_rest": None}},
              {"paired": {"cat_edge_vs_rest": {"win_pp": None, "win_ci90": [1, 2]}}}, "壞資料"):
        s = nt.tier_disclaimer(t)
        assert "這不是購買組合" in s and "%" not in s and "個百分點" not in s


def test_stale_顯示過期與上次成功日期且不引用數字():
    s = nt.tier_disclaimer(dict(TS, stale=True, date="2026-11-06"))
    assert "統計已過期，上次成功重算 2026-11-06" in s and "個百分點" not in s and "%" not in s


def test_門檻退回日加一句提醒_數字讀by_gate(tmp_path, monkeypatch):
    _write_tiers(tmp_path, monkeypatch, TS)
    opp_p = tmp_path / "opportunities.json"
    opp_p.write_text(json.dumps({"date": "2026-07-24", "gate": {"applied": False, "reason": "pool_too_small"},
                                 "picks": [{"id": "9001", "tier": "edge"}]}), encoding="utf-8")
    monkeypatch.setattr(nt, "OPP_PATH", str(opp_p))
    text, _ = nt.build_message({"data_date": "2026-07-24", "count": 925, "stocks": [_stock(id="9001")]})
    assert "今天過強勢門檻的候選不足，門檻已放寬；歷史上這種日子分類方向曾經相反" in text
    assert "相對優勢賺錢機率 38.8%、其他候選 42.7%" in text
    # 門檻有套用 → 不加這句；by_gate 缺 → 不印數字、不 crash
    assert nt.gate_note({"applied": True}, TS) == ""
    assert "%" not in nt.gate_note({"applied": False, "reason": "pool_too_small"}, {})
    assert nt.gate_note(None, TS) == ""


def test_乖離排前段只是描述_量不出時照實講(tmp_path, monkeypatch):
    _write_opp(tmp_path, monkeypatch, "2026-07-24", ["9001"], tiers=["both"])   # 舊值 both＝相對優勢＋乖離排前段
    _write_tiers(tmp_path, monkeypatch, TS)
    text, _ = nt.build_message({"data_date": "2026-07-24", "count": 925, "stocks": [_stock(id="9001")]})
    assert "［乖離排前段］" in text
    assert "「乖離排前段」只是描述（當天候選裡乖離前 1/3），量不出比較常賺或賺比較多。" in text


def test_pipeline_failure_vs_zero_candidates_still_distinguished(tmp_path, monkeypatch):
    """既有行為不可回歸（2026-07-25 踩過的雷，見檔頭）：三分類改版不能連帶把這個區分改壞。
    這裡直接複測一次管線故障 vs 真的零檔，確保三分類的程式路徑沒有動到這段既有邏輯。"""
    monkeypatch.setattr(nt, "OPP_PATH", str(tmp_path / "no_such_file.json"))
    text_missing, _ = nt.build_message({"data_date": "2026-07-24", "count": 925,
                                        "stocks": [_stock()]})
    assert "沒有產出" in text_missing and "管線" in text_missing
    assert "先觀望" not in text_missing

    _write_opp(tmp_path, monkeypatch, "2026-07-24", [])
    text_empty, _ = nt.build_message({"data_date": "2026-07-24", "count": 925,
                                      "stocks": [_stock()]})
    assert "沒有個股通過門檻" in text_empty and "有效結論" in text_empty
    assert "管線" not in text_empty


def test_分類段落明說順序不是排名(tmp_path, monkeypatch):
    """榜內順序沒有證據支撐，畫面必須講清楚它不是好壞排名（2026-07-25 實測「前 3 名 vs
    第 4~8 名」配對差 −0.26%／t −0.22，第 2 名反而是全場最差）。"""
    _write_opp(tmp_path, monkeypatch, "2026-07-24", ["9001", "9002", "9003"],
               tiers=["edge", "edge", None])
    stocks = [_stock(id="9001", name="股9001"), _stock(id="9002", name="股9002"),
              _stock(id="9003", name="股9003")]
    text, _ = nt.build_message({"data_date": "2026-07-24", "count": 925, "stocks": stocks})
    assert text.count("不是好壞排名") == 1, text


def test_四捨五入與網站同規則():
    """網站 tierVerdict.js 用 floor(|x|×10+0.5)；Python 預設是銀行家進位（1.25→1.2），會差 0.1。"""
    s = nt.tier_disclaimer({"paired": {"cat_edge_vs_rest": {"win_pp": 1.25, "win_ci90": [0.25, 2.25]}}})
    assert "多約 1.3 個百分點（誤差範圍 0.3～2.3）" in s
