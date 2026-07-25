"""除權息長歷史回填的月份切塊邏輯（純函式，不碰網路）。"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import backfill_dividends_bt as bd  # noqa: E402


def test_month_chunks_covers_full_range_without_gaps_or_overlap():
    chunks = bd.month_chunks("2024-08-01", "2026-07-24", chunk_months=2)
    assert chunks[0][0] == "2024-08-01"
    assert chunks[-1][1] == "2026-07-24"
    # 相鄰區間首尾相接、不重疊、不留縫
    import datetime as dt
    for (_, prev_end), (next_start, _) in zip(chunks, chunks[1:]):
        gap = (dt.date.fromisoformat(next_start) - dt.date.fromisoformat(prev_end)).days
        assert gap == 1


def test_month_chunks_single_short_range():
    chunks = bd.month_chunks("2026-07-01", "2026-07-24", chunk_months=2)
    assert chunks == [("2026-07-01", "2026-07-24")]
