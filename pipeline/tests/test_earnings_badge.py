"""法說會標記（跨專案讀 tw-earnings-calendar 公開頁面）測試。

重點驗證「失敗安全」：來源掛掉/格式跑掉時要靜默回空 dict，不能讓例外往外炸、
拖垮整條選股 pipeline（build_data.py 的 fetch_earnings_badges 呼叫本身不包 try/except）。
"""
import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import build_data as bd  # noqa: E402
import market_sources as ms  # noqa: E402


def _payload(events):
    return {"range": ["2026-06-29", "2026-07-05"], "events": events}


def test_picks_events_within_window(monkeypatch):
    events = [
        {"id": "2330", "name": "台積電", "date": "2026-07-05"},   # 窗內（today+7）
        {"id": "2454", "name": "聯發科", "date": "2026-07-20"},   # 窗外，太遠
        {"id": "1101", "name": "台泥", "date": "2026-06-30"},     # 窗外，已過去
    ]
    monkeypatch.setattr(ms, "get_json", lambda url: _payload(events))
    out = bd.fetch_earnings_badges(days_ahead=7, today=dt.date(2026, 7, 3))
    assert out == {"2330": "2026-07-05"}


def test_same_stock_multiple_events_keeps_earliest(monkeypatch):
    events = [
        {"id": "2330", "name": "台積電", "date": "2026-07-08"},
        {"id": "2330", "name": "台積電", "date": "2026-07-05"},
    ]
    monkeypatch.setattr(ms, "get_json", lambda url: _payload(events))
    out = bd.fetch_earnings_badges(days_ahead=7, today=dt.date(2026, 7, 3))
    assert out == {"2330": "2026-07-05"}


def test_boundary_dates_are_inclusive(monkeypatch):
    events = [
        {"id": "1111", "name": "今天", "date": "2026-07-03"},
        {"id": "2222", "name": "第七天", "date": "2026-07-10"},
        {"id": "3333", "name": "第八天_窗外", "date": "2026-07-11"},
    ]
    monkeypatch.setattr(ms, "get_json", lambda url: _payload(events))
    out = bd.fetch_earnings_badges(days_ahead=7, today=dt.date(2026, 7, 3))
    assert set(out) == {"1111", "2222"}


def test_network_failure_returns_empty_dict_not_raise(monkeypatch):
    def boom(url):
        raise RuntimeError("模擬 URL 抓不到（改壞網址/斷線）")
    monkeypatch.setattr(ms, "get_json", boom)
    out = bd.fetch_earnings_badges(days_ahead=7, today=dt.date(2026, 7, 3))
    assert out == {}   # 失敗安全：不拋例外、回空 dict


def test_malformed_payload_returns_empty_dict_not_raise(monkeypatch):
    # 格式跑掉（例如來源改版、events 變成別的型別）也不能讓 build 掛掉
    monkeypatch.setattr(ms, "get_json", lambda url: {"events": "not-a-list"})
    out = bd.fetch_earnings_badges(days_ahead=7, today=dt.date(2026, 7, 3))
    assert out == {}
