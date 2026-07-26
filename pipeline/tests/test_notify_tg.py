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
picks 不再截斷成固定檔數（今天實跑 142 檔），每檔多了 tier（win/both/return/None）。
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
    """142 檔的實際候選規模不可能全塞進手機訊息，這裡用 20 檔（涵蓋三個 tier + None）驗證：
    ① 大量候選不會 crash（迴歸 2026-07-25 TOP_N 5→10 時圈號 IndexError 炸掉整條推播的教訓，
       這是新設計下「候選檔數變動不能讓訊息組裝爆掉」這件事的守門測試）
    ② tier 正確分流到三個段落，None 不進任何分類段落
    ③ 每段落超過顯示上限時會被截斷（不是全部塞進去），且順序保留（截斷取「前幾筆」不是亂選）。
    """
    tiers = (["both"] * 3 + ["win"] * 8 + ["return"] * 6 + [None] * 3)   # 共 20 檔
    ids = [str(9000 + i) for i in range(len(tiers))]
    _write_opp(tmp_path, monkeypatch, "2026-07-24", ids, tiers=tiers)
    stocks = [_stock(id=i, name=f"測試{i}", signal_ma=True) for i in ids]
    text, dd = nt.build_message({"data_date": "2026-07-24", "count": 925, "stocks": stocks})
    assert dd == "2026-07-24"

    assert "共 3 檔" in text   # 雙優（3 檔，不截斷）
    assert "共 8 檔" in text   # 勝率偏優（8 檔，超過顯示上限）
    assert "共 6 檔" in text   # 報酬偏優（6 檔，超過顯示上限）

    # 雙優 3 檔全顯示
    for i in ids[0:3]:
        assert f"測試{i}" in text
    # 勝率偏優：只顯示前 5 筆（保留原始順序），第 6~8 筆不顯示
    for i in ids[3:8]:
        assert f"測試{i}" in text
    for i in ids[8:11]:
        assert f"測試{i}" not in text, "超過顯示上限的候選不該出現，不然『列前 M 檔』的措辭就是假的"
    # None tier 的 3 檔不進任何分類段落
    for i in ids[17:20]:
        assert f"測試{i}" not in text


# ── ③ 候選情報三分類（2026-07-26：拿掉「配好組合」語意，改成情報摘要）───────────────

def test_no_purchase_order_or_selection_wording(tmp_path, monkeypatch):
    """「精選」「建議買」「Top」和圈號 ①②③ 都在暗示『照這個順序/這個組合買』，
    Andy 拍板「不用幫我配好組合、我自己會挑」之後這些字樣一律不能出現。"""
    ids = ["9001", "9002", "9003"]
    _write_opp(tmp_path, monkeypatch, "2026-07-24", ids, tiers=["both", "win", "return"])
    stocks = [_stock(id=i, name=f"股{i}") for i in ids]
    text, _ = nt.build_message({"data_date": "2026-07-24", "count": 925, "stocks": stocks})
    for bad in ("精選", "建議買", "Top", "①", "②", "③"):
        assert bad not in text, f"不該出現「{bad}」——暗示照順序/組合買"


def test_three_tier_category_headers_present(tmp_path, monkeypatch):
    """訊息要能看出三個分類：雙優／勝率偏優／報酬偏優。"""
    ids = ["9001", "9002", "9003"]
    _write_opp(tmp_path, monkeypatch, "2026-07-24", ids, tiers=["both", "win", "return"])
    stocks = [_stock(id=i, name=f"股{i}") for i in ids]
    text, _ = nt.build_message({"data_date": "2026-07-24", "count": 925, "stocks": stocks})
    assert "雙優" in text
    assert "勝率偏優" in text
    assert "報酬偏優" in text


def test_contains_fixed_disclaimer_verbatim(tmp_path, monkeypatch):
    """固定提醒必須同時講兩件事，缺一就會誤導：
    ① 這不是購買組合
    ② 就算落在最好的層級，單檔賺錢機率也不到一半（49%）——**而且優勢在賺賠幅度不是勝率**

    🔴 2026-07-26 更新：原本寫「約 52%」是「當天收盤進場」時代的數字。改成隔日開盤進場、
    扣 0.785% 成本重算後（tier_stats.json，n=93,901、19 個約當獨立批次）是 48.6%，
    最差層級 41.4%，三層全都不到 50%。只寫勝率會讓人以為「上榜＝比較會賺」，所以這裡
    強制要求把不對稱（賺時 +16%／賠時 −10%）一起寫進去——期望值的來源是它，不是勝率。"""
    _write_opp(tmp_path, monkeypatch, "2026-07-24", ["9001"], tiers=["win"])
    stocks = [_stock(id="9001", name="股9001")]
    text, _ = nt.build_message({"data_date": "2026-07-24", "count": 925, "stocks": stocks})
    assert "這不是購買組合" in text
    assert "49%（不到一半）" in text
    assert "賺時約 +16%" in text and "賠時約 −10%" in text
    assert "不是在勝率" in text
    assert "52%" not in text, "舊口徑數字不可復活"


def test_both_tier_listed_once_not_duplicated_across_sections(tmp_path, monkeypatch):
    """tier=='both' 的候選只在雙優段落出現一次，不可以在勝率偏優、報酬偏優段落各再出現一次
    ——同一檔股票在訊息裡出現兩次，手機讀起來會像是兩檔不同的推薦。"""
    _write_opp(tmp_path, monkeypatch, "2026-07-24", ["9001"], tiers=["both"])
    stocks = [_stock(id="9001", name="股9001雙優")]
    text, _ = nt.build_message({"data_date": "2026-07-24", "count": 925, "stocks": stocks})
    assert text.count("股9001雙優") == 1


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


def test_每個分類都明說順序不是排名(tmp_path, monkeypatch):
    """2026-07-26 主對話加：榜內順序沒有證據支撐，畫面必須講清楚它不是好壞排名。

    背景（不可回歸）：實測支持的是「同日三分位的層級差異」（前 1/3 賺錢機率 51.9% vs
    後 1/3 43.8%），沒有測出層級「之內」名次有區辨力——2026-07-25 實測「前 3 名 vs
    第 4~8 名」配對差 −0.26%／t −0.22（測不出），第 2 名反而是全場最差（45.1%）。
    所以只要畫面列出有順序的清單，就必須同時否認那是排名，否則等於用介面說謊。"""
    _write_opp(tmp_path, monkeypatch, "2026-07-24", ["9001", "9002", "9003"],
               tiers=["both", "win", "return"])
    stocks = [_stock(id="9001", name="股9001"), _stock(id="9002", name="股9002"),
              _stock(id="9003", name="股9003")]
    text, _ = nt.build_message({"data_date": "2026-07-24", "count": 925, "stocks": stocks})
    # 三個分類各出現一次否認排名的註記（雙優／勝率偏優／報酬偏優）
    assert text.count("不是好壞排名") == 3, text
