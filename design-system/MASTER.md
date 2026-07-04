# Design System — tw-stock-screener（粉色 urbi 風）

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
| Up | `#D0303C` | `--up` | 上漲（台股紅漲；刻意深於 --primary 避免混淆） |
| Up BG | `#FBE9EA` | `--up-bg` | 上漲底色 |
| Down | `#0F8A5F` | `--down` | 下跌 |
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
