"""同業比（annotate_valuation）測試：以同產業本益比中位數判斷是否被低估。"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import build_data as bd  # noqa: E402


def test_undervalued_below_industry_median():
    results = [
        {"industry": "半導體業", "pe": 10.0},   # 低於中位數 20 → 被低估
        {"industry": "半導體業", "pe": 20.0},   # 等於中位數 → 不算低估
        {"industry": "半導體業", "pe": 30.0},   # 高於中位數
        {"industry": "航運業", "pe": None},      # 無本益比 → 不列入計算、不算低估
        {"industry": "航運業", "pe": -5.0},      # 虧損（負 PE）→ 不列入、不算低估
    ]
    bd.annotate_valuation(results)
    assert results[0]["undervalued"] is True
    assert results[1]["undervalued"] is False   # 等於中位數不算
    assert results[2]["undervalued"] is False
    assert results[3]["undervalued"] is False
    assert results[4]["undervalued"] is False
    # 半導體業中位數 = median(10,20,30) = 20
    assert results[0]["industry_pe_median"] == 20.0


def test_single_stock_industry_not_undervalued():
    # 產業只有一檔 → 中位數等於自己，不會低於自己 → 不算低估
    results = [{"industry": "生技醫療", "pe": 15.0}]
    bd.annotate_valuation(results)
    assert results[0]["undervalued"] is False
    assert results[0]["industry_pe_median"] == 15.0
