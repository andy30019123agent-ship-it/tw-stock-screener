# Design System — tw-stock-screener（粉色 urbi 風）

> **Andy 於 2026-11-16 核准（資訊減量改版）：方向「A＋C」——三分頁＋瘦身卡片。**
> 依據 `_reports/設計審計_全盤盤點_2026-11-16.md`，示意 `_reports/mockups-2026-11-16/A.html`、`C.html`。
> 色票／字體／間距 token 不換。核准內容：
> 1. **全站拆成三個分頁：「今天／依據／工具」**（取代 2026-07-26 的單欄故事線）。「今天」只放
>    股票；所有說明、回測依據、但書搬到「依據」；進階篩選、市況建議、權重表、停損代價表等
>    研究工具搬到「工具」。
> 2. **「今天」分頁**：資料日、大盤一行、一句關鍵事實（單檔賺錢機率不到一半、排前面不代表
>    比較會賺）、檢視切換（預設「清單」，一屏 5～6 檔，記住上次選擇）。清單一列＝名稱、代號、
>    近 60 天強弱、現價漲跌、有風險標記時一個橘點；點開一列是瘦身卡片。
> 3. **卡片＝過關清單（方向 B；Andy 同日稍後改口：「還是加入過關清單好了」，取代原本的
>    方向 A 瘦身卡片）**，示意 `_reports/mockups-2026-11-16/B.html`：名稱代號產業、現價漲跌；
>    每關一行帶實際數字（強勢雙確認 60／120 天、今天亮的訊號、成交量夠、營收沒衰退）；
>    一行「強在哪」（相對優勢才有）；一行「要小心」（有才出現，只列事實：既有風險標記＋近 20 天
>    輸大盤，不新增好壞門檻）；一行中性事實「離近 20 日前高還差 X%」。拿掉位置條、候選百分位、
>    成交金額那一行、月線與前高兩格（價位收進 K 線視窗）。
>    資料欄位 `fired_labels`／`rs_pct_120`／`avg_vol_lots` 於 2026-11-16 加進 opportunities.json；
>    舊資料沒有這些欄位時，對應那一行省略，不得重算或編造。
> 4. **狀態型警示不屬於可搬走的說明**：資料過期、門檻今天沒套用、統計過期，出現時一律在
>    「今天」分頁首屏直接可見。
> 5. 「相對優勢」名稱 Andy 尚未決定是否改名：先沿用，但在名稱旁就地寫明它的意思（成交金額
>    排今天候選前 1/3）。「橘點」只用既有的風險標記判定，不新增好壞門檻。

> **Andy 於 2026-11-16 鬆綁誠實性約束（原話：「這可以收起來不用展開來」）。**
> 誠實性內容（但書、警語、回測限制、「這不是購買組合」等）**可以預設收合**，不必再直接攤在
> 首屏或卡片上；**但仍不可刪除**，使用者點開要找得到。
> **受眾（Andy 2026-11-16 說明）：只有他自己和身邊朋友在用，不是對外公開產品。** 不需要對
> 陌生大眾的免責式寫法；優先讓「第一次打開的朋友」看懂這檔為什麼被選出來、依據是什麼。
> 這一條**取代**下方 2026-11-13 第 3 點與 2026-07-26 第 3 點中「不可藏到要點兩下才看得到」
> 「不是收進要點兩下才看得到的地方」的要求；那兩段保留為歷史原文。

> **Andy 於 2026-11-13 核准（可讀性改版）：方向 3️⃣「先看股票」＋可切換成掃描清單。**
> 色票／字體／間距 token 不換，這次核准的是**首屏順序與候選呈現方式**。核准內容：
> 1. **一打開先看到今天的相對優勢股**：首屏在標題與資料日之後，緊接著就是相對優勢候選；
>    大盤提醒收成一行摘要（可展開），統計說明與回測數字跟在候選區之後，不擋在股票前面。
> 2. **候選區提供兩種檢視，可一鍵切換、記住上次選擇**：預設「卡片」（每檔附白話說明，示意
>    `_reports/mockups-2026-11-13/B.html`）；另一種「清單」（一行一檔、可快速掃過，點開才看
>    說明，示意 `_reports/mockups-2026-11-13/C.html`）。兩種檢視資料與排序完全相同。
> 3. 🔴 2026-07-26 的硬約束第 3 點**照舊有效**：誠實性內容不可刪、不可藏到要點兩下才看得到。
>    「先看股票」的做法是把警語**縮短並貼在對應數字旁**（例：相對優勢標題旁一句「單檔賺錢機率
>    仍不到一半」），不是拿掉。清單檢視同樣要在清單上方保留這一句與「這不是購買組合」。
> 4. 一併處理審計的共同底線：內文 ≥16px、對比 ≥4.5:1（含下跌綠 `--down` 調深）、觸控 ≥44px、
>    390 寬無橫向捲動、名詞統一（區間一律叫「誤差範圍」）、說明書數字改讀資料檔不寫死。
> 5. 依據：`_reports/設計審計_可讀性_2026-11-13.md`（49 張截圖）。

> **Andy 於 2026-07-26 核准（版面架構）：方向 1️⃣ 單欄故事線。** 色票／字級／間距仍照本檔既有規範，
> 這次核准的是**資訊架構**，不是換配色。核准內容：
> 1. **砍掉雙軌候選機制**——「篩選＋訊號」那組獨立候選列表退場，全站只留「候選情報」一套。
>    首屏三個大數字裡的「符合條件 N 檔」（舊篩選器結果）必須移除，它與「今日候選 N 檔」並排會讓
>    使用者無從判斷該看哪個（審計實測：兩數字差 40 倍）。篩選器降級成「進階工具」預設收合。
> 2. **整頁改成由上而下的單欄敘事**：今天大盤怎樣 → 有幾檔候選 → 雙優這幾檔（最有根據） →
>    想自己篩再往下。用敘事順序取代並列的統計牆。
>    （📌 分類已於 2026-11-13 簡化：這個節點現在是「相對優勢這幾檔」，舊三分類稱號已從介面拿掉，
>    依據 `_reports/重算_候選池層級統計_2026-11-13.md`「分類簡化」一節；上面是 07-26 核准時的原文。）
> 3. 🔴 **不可為了精簡而刪除或隱藏誠實性內容**（這是本次改版的硬性約束，違反即不可交付）：
>    「這不是購買組合」「不是好壞排名」「三層都不到一半」「信賴區間」「未扣成本」這類警語，
>    要**嵌進故事的對應節點**（講到那個數字時就在旁邊講清楚），不是集中在首屏轟炸、
>    也不是收進要點兩下才看得到的地方。精簡呈現 ≠ 隱藏真相。
> 4. 依據：`_reports/設計審計_候選情報版_2026-07-26.md`（390/768/1280 三尺寸實測，12 張截圖）。
>    審計量到的核心問題：首屏 76% 是警語、第一檔候選要捲 1 屏＋點展開才看得到、
>    手機層級分佈表 623px 塞進 308px 框、「套用」鈕觸控高 28.5px、「使用說明」對比 4.07:1。
>
> **Andy 於 2026-07-04 核准**：方向＝urbi.ae 版面語言＋粉色系（Discord 選 2️⃣ 完整改版，「顏色ok」）。
> 本檔為此專案唯一的色／字／距權威。頁面級例外寫 `design-system/pages/<page>.md`，否則一律照本檔。
> 參考站：https://www.urbi.ae —— 精髓＝大圓角區塊、膠囊按鈕與徽章、淡底＋超深色粗標題、大數字統計、柔和有機色塊點綴、大量留白。

---

## 1. 色票（全部經由 CSS variable 引用，元件內禁止裸 hex）

### 基底

| Role | Hex | CSS Variable | 用法 |
|------|-----|--------------|------|
| Background | `#F7F3F7` | `--bg` | 頁面底色（淡粉紫） |
| Surface | `#FFFFFF` | `--surface` | 卡片、面板 |
| Surface Tint | `#FDEEF4` | `--surface-tint` | 強調卡、hover 底、區塊交錯 |
| Surface Deep | `#2B0A20` | `--surface-deep` | 深莓面板（footer、nav 選單鈕、反白區塊） |
| Ink | `#3D1130` | `--ink` | 標題、大數字（深莓近黑） |
| Ink Body | `#5A3B50` | `--ink-body` | 內文（對 --bg 對比 ≈ 8:1） |
| Ink Muted | `#7E6274` | `--ink-muted` | 說明文字、表頭（對 --bg ≥ 4.5:1；不得再淡） |
| On Deep | `#F7F3F7` | `--on-deep` | 深莓面板上的文字 |
| Border | `#ECDCE7` | `--border` | 卡片框線、分隔線 |
| Border Strong | `#DCC3D3` | `--border-strong` | 輸入框、需要更明確的框 |

### 品牌／互動

| Role | Hex | CSS Variable | 用法 |
|------|-----|--------------|------|
| Primary | `#FF4D8D` | `--primary` | 主 CTA、選中態、關鍵強調（亮桃紅） |
| Primary Hover | `#E63677` | `--primary-strong` | hover／active |
| On Primary | `#2B0A20` | `--on-primary` | 主鈕文字用深莓（urbi 是深字配亮鈕，白字對比不足） |
| Primary Tint | `#FFD6E5` | `--primary-tint` | 徽章底、選中列底 |
| Accent | `#FFC24B` | `--accent` | 琥珀點綴（向 urbi 黃致敬）：小徽章、標記，一頁最多一處 |
| On Accent | `#3D1130` | `--on-accent` | 琥珀上的文字 |
| Ring | `#FF4D8D` | `--ring` | focus ring（2px offset 2px） |

### 行情語意色（鐵則：紅漲綠跌不可被主題吃掉）

| Role | Hex | CSS Variable | 用法 |
|------|-----|--------------|------|
| Up | `#BE2733` | `--up` | 上漲（台股紅漲；刻意深於 --primary 避免混淆）。2026-11-13 由 `#D0303C` 調深：原色對 `--surface-tint` 僅 4.49:1；新色對白 5.95、對 `--bg` 5.42、對 `--surface-tint` 5.30、對 `--up-bg` 5.09、對 `--primary-tint` 4.54 |
| Up BG | `#FBE9EA` | `--up-bg` | 上漲底色 |
| Down | `#0A7650` | `--down` | 下跌（2026-11-13 由 `#0F8A5F` 調深：原色對白底僅 4.36:1；新色對白 5.64、對 `--bg` 5.14、對 `--surface-tint` 5.03、對 `--down-bg` 4.99） |
| Risk dot | `#C8570A` | `--risk-dot` | 清單列的橘點（2026-11-16 新增）：這檔有硬性風險標記（乖離大、營收資料缺、法說會將近）。刻意不用紅綠，避免和漲跌混淆。圖形用色，對白底 3.9:1（圖形門檻 3:1），不可拿來當文字色 |
| Down BG | `#E7F4EE` | `--down-bg` | 下跌底色 |
| Flat | `#8A7A85` | `--flat` | 平盤／無資料 |

規則：漲跌數字一律 `--up`/`--down` ＋ font-weight 700；漲跌與 `--primary` 永不同時承擔「強調」語意（粉紅只做 UI 強調，不做行情語意）。

### 裝飾色塊（僅限 hero／空狀態的有機圓潤色塊，不進資料區）

`#FFB1CC`（粉）、`#E7C6F5`（薰衣草紫）、`#FFD9A6`（杏）、`#F2E3ED`（霧粉）。柔和實心或 blur ≥ 60px 的光暈；禁止彩虹漸層。

## 2. 字體

- **標題／大數字：Manrope**（700／800；數字開 `font-variant-numeric: tabular-nums`）
- **內文：Noto Sans TC**（400／500／700）——介面是繁中，內文必須用 TC 字重完整的字體
- 引入：
```css
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@500;700;800&family=Noto+Sans+TC:wght@400;500;700&display=swap');
```
- 字級（rem 基準 16px）：hero 標題 `clamp(2rem, 5vw, 2.75rem)`／區塊標題 1.5rem／卡片標題 1.125rem／內文 1rem／輔助 0.875rem（只准用於次要說明）／大統計數字 `clamp(1.75rem, 4vw, 2.5rem)` Manrope 800。
- 行高：標題 1.2、內文 1.6。中文與英數之間半形空格。
- 全站文字下限 14px（0.875rem）；唯一例外：圖表（SVG/canvas）內的軸標籤與圖例最小 12px，且色彩對比不得低於 --ink-muted 等級。

## 3. 圓角／陰影／間距

| Token | 值 | 用法 |
|-------|-----|------|
| `--r-sm` | `10px` | 小元件（input、tag） |
| `--r-md` | `16px` | 一般卡片內元素 |
| `--r-lg` | `24px` | 卡片、面板 |
| `--r-xl` | `32px` | 區塊級大容器（hero、footer） |
| `--r-pill` | `999px` | 按鈕、徽章、tab —— urbi 簽名 |
| `--shadow-sm` | `0 1px 2px rgba(61,17,48,.06)` | 微浮 |
| `--shadow-md` | `0 6px 16px rgba(61,17,48,.08)` | 卡片 |
| `--shadow-lg` | `0 16px 40px rgba(61,17,48,.12)` | modal、彈窗 |

間距一律 4/8 倍數：4/8/12/16/24/32/48/64。縱向節奏：區塊間 48–64、卡片內 padding 20–24、卡片間 gap 16–24。整頁內容 max-width 1200px、左右 padding 手機 16 桌機 32。

## 4. urbi 簽名元素（改版必須做到的版面語言）

1. **膠囊徽章**：區塊標題上方放 pill 徽章（tint 底＋SVG icon＋小字），如「📍 Geo-intelligence platform」的做法但 icon 用 Lucide SVG。
2. **大數字統計列**：關鍵指標用 Manrope 800 大數字＋一行小說明（urbi 的 7.8M/65M/5.5M 語法）。
3. **膠囊按鈕**：主鈕 `--primary` 底＋`--on-primary` 深字＋右側圓形箭頭 icon；次鈕 `--surface` 底＋`--border`。
4. **大圓角區塊**：hero 與 footer 用 `--r-xl` 大容器（hero 淡粉光暈＋有機色塊裝飾，footer 用 `--surface-deep` 反白）。
5. **留白與主從**：一頁一個主 CTA；區塊有大小節奏，不做等距卡片牆。
6. **icon**：一律 Lucide SVG（stroke 1.75），同一套到底；**emoji 不得當 icon**（表格內行情箭頭用 SVG 三角）。

## 5. 元件規格

```css
.btn-primary {
  background: var(--primary); color: var(--on-primary);
  padding: 12px 24px; border-radius: var(--r-pill);
  font-weight: 700; transition: background 200ms ease, transform 200ms ease;
  cursor: pointer; min-height: 44px;
}
.btn-primary:hover { background: var(--primary-strong); transform: translateY(-1px); }

.card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--r-lg); padding: 24px; box-shadow: var(--shadow-sm);
}
.card:hover { box-shadow: var(--shadow-md); }

.badge-pill {
  display: inline-flex; align-items: center; gap: 8px;
  background: var(--primary-tint); color: var(--ink);
  border-radius: var(--r-pill); padding: 6px 14px;
  font-size: .875rem; font-weight: 500;
}

.input {
  padding: 12px 16px; border: 1px solid var(--border-strong);
  border-radius: var(--r-sm); font-size: 1rem; background: var(--surface);
}
.input:focus { outline: none; border-color: var(--primary); box-shadow: 0 0 0 3px rgba(255,77,141,.18); }

.modal-overlay { background: rgba(43,10,32,.45); }
.modal { background: var(--surface); border-radius: var(--r-lg); box-shadow: var(--shadow-lg); }

table th { color: var(--ink-muted); font-size: .875rem; font-weight: 500; }
table td { color: var(--ink-body); }
tr:hover td { background: var(--surface-tint); }
```

## 6. 動效

150–300ms、只動 transform/opacity/background、`prefers-reduced-motion` 全域尊重；數字更新可 200ms 淡入；禁止為動而動的進場動畫串。
例外：「即時更新」狀態圓點允許 ≤3s 柔和 pulse（限 opacity/transform），必須尊重 reduced-motion。

## 7. Anti-patterns（違反＝不可交付）

- ❌ emoji 當 icon（含 🔴🟡🟢 當狀態燈 → 改 SVG 圓點＋文字）
- ❌ 元件內裸 hex（一律 var(--token)）
- ❌ 無來由漸層／毛玻璃／彩虹陰影（只允許第 1 節裝飾色塊規則內的光暈）
- ❌ 等距卡片牆無主從、間距非 4/8 倍數
- ❌ 內文 <16px、行高 <1.5、對比 <4.5:1
- ❌ 觸控目標 <44px、手機橫向捲動
- ❌ 一頁多個同權重 CTA
- ❌ 漲跌色與粉紅強調混用

## 8. 交付前檢查

- [ ] 三斷點實測：390 / 768 / 1280（版面驗證必須在 390 真實寬度跑 scrollWidth／溢出掃描；Playwright viewport 或 chrome-devtools emulate 都能正確 390，量測前先 assert innerWidth）
- [ ] 對比 4.5:1（主文字全部驗過）
- [ ] focus 可見、cursor-pointer、reduced-motion
- [ ] 漲跌色語意正確（紅漲綠跌）且與 primary 區隔
- [ ] 所有色／字／距來自本檔 token
