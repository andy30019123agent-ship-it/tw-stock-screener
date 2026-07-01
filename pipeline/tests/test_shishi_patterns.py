"""小詩技術形態偵測器測試（布林軌道系列）。

用合成資料驗證：
- 平盤（零波動）不會誤報任何形態。
- 刻意造出「縮口 → 帶量突破」情境會觸發 sn_squeeze_breakout。
- 刻意造出「連續黑K跌破下軌 → 翻紅」情境會觸發 sn_lower_reversal。
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import build_data as bd  # noqa: E402


def _rows(closes, opens=None, highs=None, lows=None, vols=None):
    """把收盤序列包成 compute_indicators 吃的 price_rows。缺的 OHLC 用收盤填。"""
    n = len(closes)
    opens = opens or list(closes)
    highs = highs or [max(o, c) for o, c in zip(opens, closes)]
    lows = lows or [min(o, c) for o, c in zip(opens, closes)]
    vols = vols or [1_000_000] * n
    rows = []
    for i in range(n):
        rows.append({
            "date": f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}",
            "open": opens[i], "max": highs[i], "min": lows[i], "close": closes[i],
            "Trading_Volume": vols[i], "Trading_money": vols[i] * closes[i],
        })
    return rows


def test_flat_price_no_false_positive():
    ind = bd.compute_indicators(_rows([100.0] * 80), [])
    assert ind is not None
    assert ind["signal_shishi"] is False
    assert ind["sn_tags"] == []
    for k in ("sn_squeeze_breakout", "sn_lower_reversal", "sn_break_low_recover",
              "sn_immortal_guide", "sn_volume_support"):
        assert ind[k] is False


def test_squeeze_breakout_triggers():
    # 前 60 天大幅震盪（高帶寬）→ 接著 19 天緊縮盤整在 100（縮口）→ 最後一天帶量突破。
    closes = [90 + 20 * (i % 2) for i in range(60)]   # 90/110 來回 = 高波動
    closes += [100.0] * 19                             # 縮口盤整
    closes += [109.0]                                  # 突破日
    vols = [1_000_000] * 79 + [4_000_000]              # 突破日爆量 4 倍
    ind = bd.compute_indicators(_rows(closes, vols=vols), [])
    assert ind is not None
    assert ind["sn_squeeze_breakout"] is True
    assert ind["signal_shishi"] is True
    assert "縮口帶量突破" in ind["sn_tags"]


def test_lower_reversal_triggers():
    # 長期盤整在 100 → 連續黑K急殺跌破布林下軌 → 最後一天翻紅站回。
    closes = [100.0] * 74
    closes += [96.0, 92.0, 88.0]     # 連續 3 根黑K下殺（跌破下軌）
    closes += [93.0]                 # 翻紅反彈
    opens = [100.0] * 74 + [100.0, 96.0, 92.0, 88.5]   # 前 3 根 open>close=黑；最後 open<close=紅
    ind = bd.compute_indicators(_rows(closes, opens=opens), [])
    assert ind is not None
    assert ind["sn_lower_reversal"] is True
    assert "破下軌翻紅" in ind["sn_tags"]
