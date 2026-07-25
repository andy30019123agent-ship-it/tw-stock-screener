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
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import notify_tg as nt  # noqa: E402
import opportunities as opp  # noqa: E402


def _stock(**kw):
    base = {"id": "1111", "name": "股1111", "close": 100.0, "bias20_pct": 0.0,
            "change_pct": 1.5, "ma20": 98.0}
    base.update(kw)
    return base


def _write_opp(tmp_path, monkeypatch, date, ids):
    p = tmp_path / "opportunities.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"date": date, "picks": [{"id": i} for i in ids]}, f, ensure_ascii=False)
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
    """快報順序必須與網站完全一致（同一份結論，不重新排序）。"""
    ids = ["3577", "6166", "2395"]
    _write_opp(tmp_path, monkeypatch, "2026-07-24", ids)
    stocks = [_stock(id=i, name=f"股{i}") for i in reversed(ids)]   # 故意給反的順序
    text, _ = nt.build_message({"data_date": "2026-07-24", "count": 925, "stocks": stocks})
    pos = [text.index(f"股{i}") for i in ids]
    assert pos == sorted(pos), "訊息裡的順序要照 opportunities.json，不可自己排"


def test_top_n_stocks_render_without_crash(tmp_path, monkeypatch):
    """TOP_N 檔實際建訊息（含編號）不可爆——這條路徑要真的走到，見檔頭的前提教訓。"""
    ids = [str(9000 + i) for i in range(opp.TOP_N)]
    _write_opp(tmp_path, monkeypatch, "2026-07-24", ids)
    stocks = [_stock(id=i, name=f"測試{i}", signal_ma=True) for i in ids]
    text, dd = nt.build_message({"data_date": "2026-07-24", "count": 925, "stocks": stocks})
    assert dd == "2026-07-24"
    assert f"精選 {opp.TOP_N} 檔" in text, "檔數要跟 TOP_N 一致"
    for i in ids:
        assert f"測試{i}" in text
    assert nt._num(opp.TOP_N - 1) in text, "最後一檔的編號要真的出現在訊息裡"


def test_numbering_survives_any_count():
    """迴歸：2026-07-25 TOP_N 5→10 時寫死的 5 個圈號 IndexError → 推播失敗 →
    連帶擋掉存檔回 main 與部署（workflow 循序，前一步 fail 後面全 skip）。"""
    assert nt._num(0) == "①" and nt._num(9) == "⑩" and nt._num(19) == "⑳"
    assert nt._num(20) == "21." and nt._num(99) == "100."
    for i in range(200):
        assert isinstance(nt._num(i), str) and nt._num(i)
