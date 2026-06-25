# 爆量突破條件 + 淺色毛玻璃改版 — 設計規格

日期：2026-06-25
專案：tw-stock-screener

## 背景

Andy 提供 6 張他喜歡的線圖（南電、台半、聯茂、立隆電、南亞科、禾伸堂），共同 DNA：
**長期橫盤/打底（均線糾結）→ 帶量突破創新高 → 均線翻多頭排列往上發散**，常搭配大戶持股比率上升。

兩個需求：
- A. 新增「爆量突破起漲」選股條件（前端可調量倍數與回看天數）。
- B. 整頁改成「淺色清爽毛玻璃」風格，並優化 UX。

## A. 爆量突破起漲 signal_breakout

### 判定（4 條件全中）
1. **突破前先悶**：突破日往前 20 個交易日內，均線曾糾結（離散度 dispersion < 3%，沿用現有 `SQUEEZE_TH`）。
2. **帶量突破**：最近 N 個交易日內某一天收盤「創前 20 日新高」，且當日量 ≥ M 倍「前 20 日均量」。
3. **站上所有均線**：突破日收盤站上 MA5/10/20/60。
4. **確認未垮**：目前仍多頭排列（MA5>10>20>60）且均線上彎（`bull_aligned && ma_rising`）。

預設 M=1.8 倍、N=3 天。

### 管線輸出（build_data.py）
為了讓前端旋鈕（量倍數、回看天數）即時生效，pipeline 對「最近 5 個交易日」中**已滿足結構條件**（站上均線 + 創 20 日新高 + 突破前有糾結）的日子，各輸出一個候選：
```
breakout_cands: [{ "ago": 幾天前(0=今天), "vr": 當日量/前20日均量 }, ...]
signal_breakout: bool   # 預設門檻(M=1.8,N=3 且 bull_aligned&&ma_rising) 下是否成立，給標籤與 TG 評分用
```

### 前端套用（filters.js）
- DEFAULT_CONDITIONS 增加：`breakout:false, breakoutMult:1.8, breakoutLookback:3`
- `hasBreakout(s, mult, lookback)` = `s.bull_aligned && s.ma_rising && (s.breakout_cands||[]).some(c => c.ago <= lookback && c.vr >= mult)`
- applyFilters：`if (c.breakout && !hasBreakout(s, c.breakoutMult, c.breakoutLookback)) return false`

### UI
- ConditionPanel 新增勾選「🚀 爆量突破起漲」+ 兩個 range 滑桿（量倍數 1.5–3，回看 1–5 天），只在勾選時顯示滑桿。
- ResultTable / 卡片：`signal_breakout` 或符合當前旋鈕時掛 `🚀爆量突破` 標籤。
- SORTS 增加 breakout 排序（突破優先）。

### TG 快報（notify_tg.py）
- score：`signal_breakout` +3。
- reasons：最前面加「爆量突破」。

## B. 淺色毛玻璃改版（App.css 重寫）

### 視覺基調
- 背景：柔和淺色漸層 + 模糊色塊（讓玻璃糊化效果看得出來），固定不捲動。
- 卡片/面板/表格：`background: rgba(255,255,255,0.55~0.65)` + `backdrop-filter: blur(18px)` + 1px 半透明白邊 + 柔和陰影。
- 文字：深 slate `#1f2937`，次要 `#64748b`。
- 漲跌：台股紅漲 `#e11d48` 柔化、綠跌 `#059669`；不刺眼。
- 圓角加大、留白加大，降低壓力感。

### UX 優化
1. 篩選條件分區：「技術面」「籌碼面」小標題分組，一眼看懂。
2. 常用組合「快速套用」chips（例：糾結轉強、爆量突破、外資連買），一鍵套條件。
3. 符合檔數即時、明顯顯示。
4. 載入 / 空狀態 / 錯誤帶改成柔和玻璃卡，文案更友善。
5. 手機觸控目標維持加大；滑桿好拉。
6. Modal、sparkline 配色跟著淺色系走。

## 自我測試
- `npm run build` 通過、`npm run preview` 起得來。
- Chrome `--headless=new --screenshot`（寬度 ≥500，手機版用 ≥500）截桌機與手機兩版，確認毛玻璃出得來、不跑版、條件可勾、滑桿可拉。
- pipeline：`python pipeline/build_data.py --sample 8046,5425,6213,2472,2408,3026` 跑得出 breakout_cands；`notify_tg.py --dry-run` 正常。

## 非目標（YAGNI）
- 不做深色/自動切換（Andy 選淺色）。
- 不改資料來源、不動排程架構。
- 「手動更新按鈕」維持不做（金鑰安全考量）。
