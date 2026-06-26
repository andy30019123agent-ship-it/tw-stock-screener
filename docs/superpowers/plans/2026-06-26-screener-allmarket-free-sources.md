# 全市場選股 + 免費資料源（移除 FinMind）實作計劃

> 2026-06-26 規劃。目標：把選股範圍從「111 檔電子股」擴到「全市場上市+上櫃約 1,800 檔」，
> 並把資料源從 FinMind（額度受限）整個換成 TWSE/TPEX 官方免費端點。
> Andy 已拍板：方案 2（全市場）。本文件先求「規劃清楚」，可分階段執行。

---

## 一句話目標
全市場（上市+上櫃）每日技術面＋籌碼面選股，資料全部用免費官方源，FinMind 退場。

## 為什麼可行（已驗證的資料源）
| 資料 | 上市（TWSE） | 上櫃（TPEX） | 能否「指定過去日、一次全市場」 |
|---|---|---|---|
| 個股 OHLCV（算均線/突破） | `STOCK_DAY_ALL`（**只給最新日**）/ `STOCK_DAY` 單股月表（吃 date，但一檔一檔） | `afterTrading/dailyQuotes?date=`（✅ 吃 date、全上櫃） | 上市回填＝慢、上櫃＝快 |
| 三大法人（算連買） | `fund/T86?date=`（✅ 吃 date、全上市 1326 檔） | `insti/dailyTrade?date=`（✅ 吃 date、全上櫃） | ✅ 兩邊都快 |
| 千張大戶（既有條件） | 集保 TDCC OpenData（不變） | 同左 | 既有、不動 |

**唯一技術卡點**：上市個股「歷史」OHLCV 無「指定過去日、一次全上市」的免費端點
（`STOCK_DAY_ALL` 只回當天）。**解法**：回填時用單股月表 `STOCK_DAY`（一檔一檔、約 1,000 檔 × 3~4 個月請求＝一次性 ~1 小時），之後每天用 `STOCK_DAY_ALL` 累積最新日即可（快）。上櫃無此問題。

## 核心架構：從「一檔抓多天」改成「一天抓全部、累積成歷史」
FinMind 給「一檔的多天」；TWSE/TPEX 給「一天的全部」——方向相反。所以改成
**像現有『千張大戶』那樣，每天把全市場快照累積進歷史檔**，再從歷史算指標。
`compute_indicators()` 吃的格式不變（price_rows: date/open/max/min/close/Trading_Volume/Trading_money；
chip_rows: date/name/buy/sell），所以**指標邏輯一行都不用改**——只換「餵資料的來源」。

### 效能設計（1,800 檔的關鍵）
- 現在 `screener.json` 每檔都帶 K 線歷史，1,800 檔全帶會變超大、手機載很慢。
- 改成**兩層**：
  - `screener.json`＝精簡清單（全部 1,800 檔的選股指標 + 60 點迷你走勢，輕量，約 0.5~1MB）。
  - `charts/<id>.json`＝個股 K 線（點開彈窗才載入），不再塞進主清單。

---

## 資料源端點（實作備查，皆已實測 200）
- 上市 OHLCV 最新日：`https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_ALL?date=&response=csv`
  （CSV 表頭：日期,證券代號,證券名稱,成交股數,成交金額,開盤價,最高價,最低價,收盤價,漲跌價差,成交筆數）
- 上市 OHLCV 回填（單股月）：`.../STOCK_DAY?stockNo=<id>&date=<YYYYMM01>&response=json`
- 上市 法人（吃 date）：`https://www.twse.com.tw/rwd/zh/fund/T86?date=<YYYYMMDD>&selectType=ALLBUT0999&response=json`
- 上櫃 OHLCV（吃 date）：`https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?date=<YYYY/MM/DD>&type=EW&response=json`
  （tables[0].fields: 代號,名稱,收盤,漲跌,開盤,最高,最低,均價,成交股數,成交金額(元)…）
- 上櫃 法人（吃 date）：`https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade?date=<YYYY/MM/DD>&type=Daily&sect=EW&response=json`
- 民國日期換算：roc = (西元年-1911)，TPEX 用 `YYYY/MM/DD`、TWSE 用 `YYYYMMDD`。

---

## 分階段任務

### Phase 1 — 資料源層（market_sources.py）＋驗證
**檔案**：新增 `pipeline/market_sources.py`、`pipeline/tests/test_market_sources.py`
- 寫 `fetch_listed_ohlc_latest()`、`fetch_listed_ohlc_month(id, yyyymm)`、`fetch_otc_ohlc(date)`、
  `fetch_listed_chip(date)`、`fetch_otc_chip(date)`，各自把回應**正規化**成
  `compute_indicators` 吃的 row 格式（OHLCV: {date,open,max,min,close,Trading_Volume,Trading_money}；
  chip: {date,name∈{Foreign_Investor,Investment_Trust},buy,sell}）。
- 數字清洗：去逗號、去「+/-」色碼、空值→None（沿用戰報 `_f` 寫法）。
- **驗證關卡**：抓 1 個過去日，核對 2330 台積電 OHLCV、外資買賣超與公開資料一致；上櫃抓一檔知名股核對。
- 產出給 Phase 2/4 用的乾淨函式。

### Phase 2 — 全市場清單（build_universe 改寫）
**檔案**：改寫 `pipeline/build_universe.py` → 輸出 `pipeline/universe.json`
- 清單來源改用「最新日的 STOCK_DAY_ALL（上市）+ dailyQuotes（上櫃）」列出所有 **4 碼純數字普通股**
  （排除 ETF/ETN/權證/DR/特別股：濾掉非 4 碼數字代號）。
- 每檔記 `{id,name,market(上市/上櫃),industry}`。產業：上市用 TWSE `t187ap03_L`、上櫃用 TPEX 對照（或先留空，Phase 5 補）。
- 預期約 1,700~1,900 檔。

### Phase 3 — 歷史累積 + 回填（核心）
**檔案**：新增 `pipeline/backfill.py`、改 `pipeline/build_data.py`，歷史存 `pipeline/history/`（或單檔 rolling）
- **回填（一次性）**：
  - 上櫃 OHLCV：loop 過去 ~96 個交易日，每日一支 `dailyQuotes` → 累積 per-stock。
  - 上市 OHLCV：loop 各上市股 `STOCK_DAY` 抓近 4 個月（~1,000 檔，禮貌間隔；一次性 ~1 小時）。
  - 法人（上市 T86 + 上櫃 insti）：loop 過去 ~40 個交易日。
- **歷史存法**：per-stock rolling window（OHLCV 留最近 ~130 個交易日、法人留 ~40 日），
  壓縮格式，**每天 git commit 回 main**（沿用千張大戶的累積模式）。注意 repo 體積→用緊湊鍵、定期 prune。
- **每日更新**：抓最新日（STOCK_DAY_ALL + dailyQuotes + T86 + insti）append 進歷史。
- **build_data.py**：改成「讀歷史 → 還原成 price_rows/chip_rows → `compute_indicators`（不動）」；
  移除所有 FinMind 呼叫（`api_get`/TOKEN/TaiwanStockPrice/InstitutionalInvestors…）。
- 輸出：精簡 `screener.json`（全市場、含 market 欄位）+ 逐檔 `charts/<id>.json`。

### Phase 4 — 前端（全市場 + 效能 + 市場/產業篩選）
**檔案**：`src/App.jsx`、`src/components/*`、`src/lib/filters.js`、`StockChartModal.jsx`
- K 線改**按需載入** `charts/<id>.json`（點開彈窗才 fetch），主清單不帶 ohlc。
- 新增「市場」篩選（上市/上櫃/全部）、（可選）產業篩選；維持現有所有條件與動畫。
- 清單顯示量大：預設只顯示「符合條件」結果（本來就是）；無條件時限制顯示筆數或加分頁，避免 render 1,800 列。
- 維持淺色毛玻璃風格、手機卡片版。

### Phase 5 — 自動化 + 收尾
**檔案**：`.github/workflows/daily.yml`、`pipeline/notify_tg.py`
- workflow：移除 FinMind step、加每日累積 + commit 歷史回 main；保留集保千張大戶累積。
- `notify_tg.py`：選股池變全市場後，重新確認挑股邏輯（評分不變，但可考慮對上櫃小型股加風險提示）。
- 移除 `FINMIND_TOKEN` secret 依賴（程式不再用）。
- 全尺寸截圖驗證、端到端跑一次、部署。

---

## 需 Andy 決策 / 風險
1. **回填那一次性 ~1 小時**（上市單股月表）：可接受嗎？（之後每天就很快）。或要不要先只上線「上櫃即時可回填」+ 上市邊跑邊補。
2. **歷史檔 commit 回 repo**：1,800 檔歷史每天 commit 會讓 repo 慢慢變大（沿用千張大戶模式但更大）。可接受；要不要設更短 window / 定期 squash。
3. **產業分類**：上櫃產業對照要不要做（多一點工），還是先只做「市場（上市/上櫃）」篩選。
4. **TWSE 禮貌限流**：單股月表大量請求可能被 TWSE 短暫擋（戰報就遇過）→ 回填腳本要慢、可續跑（斷點續傳）。

## 不做（YAGNI）
- 不接基本面/財報（TWSE/TPEX 不給；選股目前純技術＋籌碼）。
- 不做即時/分線（免費源只有每日收盤）。
- 不引入新前端框架/圖表庫（沿用 lightweight-charts + 純 CSS 動畫）。

## 驗收標準
- screener.json 含 ~1,800 檔、有 market 欄位、檔案 < ~1.5MB。
- 隨機抽 5 檔（含上市+上櫃）OHLCV/法人對公開資料正確。
- 既有條件（糾結→黃金交叉→發散、連買、千張大戶、爆量突破）全部正常。
- 前端市場篩選可用、K 線按需載入、手機不卡。
- 每日 workflow 自動累積 + 部署，完全不用 FinMind。
