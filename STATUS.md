# STATUS — 台股電子股選股網頁

> 最後更新：2026-06-20（台北）｜ 啟動觸發語：**「繼續台股選股專案」**

## 現況（一句話）
React 選股網頁＋Python 管線，每天自動更新並推「選股快報」到 Telegram，已上線運作。

## 上次做到哪
- 選股條件：均線糾結→黃金交叉→多頭發散、外資/投信連買、千張大戶占比上升。
- 資料：FinMind 一檔一檔抓（限有量電子股，約 111 檔主流），千張大戶走集保 TDCC 免費週更。
- 自動化：GitHub Actions 每天台北 18:17 跑管線→build→部署；每日 TG 選股快報（按規則挑 score≥2 前 5 檔）。
- 手機版卡片化、抓太少橘色警告。

## 下一步（1–3 件）
1. 實跑幾天後微調選股參數（糾結鬆緊、連買天數），觀察 TG 快報挑股角度是否要調。
2. 千張大戶：等下次集保更新累積到第 2 週，確認開關自動啟用。
3. （可選）納入上櫃股、加千張大戶權重。

## 怎麼啟動 / 在哪
- 資料夾：`~/Desktop/agent/tw-stock-screener/`；repo 同名（github.com/andy30019123agent-ship-it/tw-stock-screener）。
- 線上：https://andy30019123agent-ship-it.github.io/tw-stock-screener/
- 自動化：`.github/workflows/daily.yml`（FINMIND_TOKEN／TG_BOT_TOKEN 在 GitHub Secret，勿入版控）。
- 本機：前端 `npm run build && npm run preview`；TG 測試 `python pipeline/notify_tg.py --dry-run`。
- 詳細脈絡：專案記憶 `project_tw_stock_screener.md`。
