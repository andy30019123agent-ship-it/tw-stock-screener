> 🧠 開工前先讀 `~/Desktop/agent/harness/thinking-core.md`（開工協定＋宣稱前防幻覺查核）；活大就派 subagent（`~/Desktop/agent/harness/model-dispatch.md` 紅線）。
> 回報、提問、要 Andy 選擇：一律照根目錄 `~/Desktop/agent/CLAUDE.md` 鐵則用 reply 工具發到頻道（純文字編號清單）；時間一律台北時間。
> 本專案現況與雷點以下文為準；改前先讀檔，改後實跑驗證才算完成。

# tw-stock-screener

台股電子股選股網頁，給 Andy 自己看盤用：React 前端 + Python 資料管線，每天自動更新選股清單並推播「選股快報」到 Telegram。

**技術棧**：Vite + React（lightweight-charts、lucide-react）
**指令**：`npm run dev` / `npm run build` / `npm run preview`
**部署**：`npm run deploy`（`vite build && gh-pages -d dist`）

專案現況與踩雷紀錄見記憶檔 `project_tw_stock_screener.md`（三專案共同現況以 `project_stock_projects_audit_2026_07.md` 為準）。

有 GitHub Actions 每天台北 18:17 自動跑管線＋部署＋TG 推播，正在線上運作中——改排程前先看記憶檔，別動到正在跑的排程。
