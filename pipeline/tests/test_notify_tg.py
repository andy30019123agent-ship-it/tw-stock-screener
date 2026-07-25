"""TG 快報評分（notify_tg.score）的單元測試。

背景：score() 曾經是手寫的 +2/+3 規則，跟回測結論相反——例如「破底翻」回測平均超額
−0.91pp（weight=0），手寫卻給 +2；「外資/投信連買」回測 samples=0（沒有證據），手寫也給 +2。
改成讀 pipeline/signal_weights.json 的 weight 之後，這裡驗證：weight 為 0 或缺 key 一律不加分，
真的有正權重的訊號才加分，乖離扣分（既有設計）維持不變。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import notify_tg as nt


def _stock(**kw):
    base = {"id": "1111", "name": "股1111", "close": 100.0, "bias20_pct": 0.0}
    base.update(kw)
    return base


def test_weight_zero_signal_does_not_score():
    # 破底翻 weight=0（回測平均超額 -0.91pp）→ 手寫規則曾給 +2，現在要是 0 分
    weights = {"sn_break_low_recover": {"weight": 0}}
    s = _stock(sn_break_low_recover=True)
    assert nt.score(s, weights) == 0


def test_missing_key_does_not_score():
    # 訊號沒出現在 signal_weights.json（快取未重算、或缺檔）→ 一律 0 分，不是舊的手寫預設分
    s = _stock(signal_ma=True, signal_breakout=True)
    assert nt.score(s, {}) == 0


def test_weight_positive_signal_adds_score():
    weights = {"signal_ma": {"weight": 3}, "signal_breakout": {"weight": 2}}
    s = _stock(signal_ma=True, signal_breakout=True)
    assert nt.score(s, weights) == 5


def test_foreign_trust_streak_zero_weight_no_bonus():
    # 外資/投信連買回測 samples=0、weight=0 → 不該再像舊規則一樣各 +2
    weights = {"foreign_buy": {"weight": 0}, "trust_buy": {"weight": 0}}
    s = _stock(foreign_streak=5, trust_streak=5)
    assert nt.score(s, weights) == 0


def test_foreign_streak_below_3_never_fires():
    weights = {"foreign_buy": {"weight": 3}}
    s = _stock(foreign_streak=2)
    assert nt.score(s, weights) == 0


def test_乖離不再扣分_因為實測方向是反的():
    """2026-07-25 規格變更：移除「抑制追高」的乖離扣分。

    原本 ≥12/15/20 各扣 1/2/3 分，假設「漲一大段再追風險高」。用兩年 375,659 筆樣本複驗
    （verify_bias_penalty.py）後推翻：成本後超額隨乖離**單調遞增**（<0 組 −1.59pp、
    ≥25 組 +2.36pp），風險調整後與紅黃綠三種市況都同方向。原本扣分的那組其實是最好的。

    這個測試現在守的是「不可以再把乖離寫回評分」——不論高低乖離都不影響分數。
    """
    weights = {"signal_ma": {"weight": 3}}
    for bias in (-10, 0, 11, 12, 15, 20, 30):
        s = _stock(signal_ma=True, bias20_pct=bias)
        assert nt.score(s, weights) == 3, f"乖離 {bias}% 不該影響分數"
    # 也不該反過來加分：中位數每組都是負的、最高乖離組波動最大，加分沒有證據支持
    assert nt.score(_stock(signal_ma=True, bias20_pct=40), weights) == 3


def test_non_engine_signal_ignored_even_with_weight():
    # bull_aligned 是 DISPLAY_ONLY_SIGNALS（不進引擎，太常見會亂洗排名），即使 weight>0 也不該加分
    weights = {"bull_aligned": {"weight": 2}}
    s = _stock(bull_aligned=True, diverging=True)
    assert nt.score(s, weights) == 0


def test_load_weights_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(nt, "WEIGHTS_PATH", str(tmp_path / "no_such_file.json"))
    assert nt.load_weights() == {}
