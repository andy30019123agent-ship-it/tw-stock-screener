# STATUS — 台股電子股選股網頁

> 最後更新：2026-06-20（台北）｜ 啟動觸發語：**「繼續台股選股專案」**

## 現況（一句話）
React 選股網頁＋Python 管線，每天自動更新並推「選股快報」到 Telegram，已上線運作。

## 上次做到哪
- 選股條件：技術面（均線糾結→黃金交叉→多頭發散、爆量突破）＋小詩 5 形態＋估值同業比＋填息＋籌碼＋**橫斷面相對強弱／產業輪動**；Top5 引擎 2026-07-25 起以「強勢雙確認」為入場門檻、權重看**成本後**超額。
- 資料：**TWSE／TPEX 免費官方端點抓全市場**（universe 約 1,966 檔、有量輸出約 925 檔；**已移除 FinMind**，僅留 finmind_fill.py 當補洞备援），千張大戶走集保 TDCC 免費週更。
- 自動化：GitHub Actions 每天台北 18:30（外部 cron-job.org 觸發 workflow_dispatch）跑管線→build→部署；每日 TG 選股快報優先讀 opportunities.json（與網站 Top5 同一份），退路排序改**讀回測權重**、候選門檻 score≥4；workflow 失敗會推 TG 通知。
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
