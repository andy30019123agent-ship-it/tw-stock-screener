// 候選卡／清單列上的「事實句」（2026-11-13 可讀性改版）。純函式、有單測。
//
// 審計 D2／D4：卡片上的百分位數字沒說在跟誰比、100% 代表哪一端，非工程師會套「越高越好」。
// 這裡每個數字都寫成「跟誰比、排在哪一端」的白話，不加任何好壞評語。
// 資料口徑（讀 pipeline/opportunities.py 確認過）：
//   ・p.rs_pct_60（pick 頂層）＝個股近 60 日報酬在「全市場」的百分位，也是清單排序依據；
//   ・p.feat_pct.*＝同一批數字在「當日候選池內」的百分位（_percentile_ranks，0＝最低、1＝最高）；
//   ・p.rs20＝個股近 20 日報酬 − 加權指數近 20 日報酬（百分點）。
// 缺值一律回 null，呼叫端整行不顯示，不印 NaN。

const isNum = v => typeof v === 'number' && Number.isFinite(v)

// 有正負號的數字：全形減號、正數帶 +、四捨五入後為 0 不帶號
export function signed(v, digits = 1) {
  if (!isNum(v)) return '—'
  const s = Math.abs(v).toFixed(digits)
  if (Number(s) === 0) return s
  return `${v < 0 ? '−' : '+'}${s}`
}

// 0~1 → 「排前 X%」：X 最小 1；剛好最高／最低用白話。
export function rankFront(p) {
  if (!isNum(p)) return null
  if (p >= 1) return '最高'
  if (p <= 0) return '最低'
  return `排前 ${Math.max(1, Math.round((1 - p) * 100))}%`
}

// 全市場 60 日強弱百分位 → 「贏過全市場 X% 的股票」用的數字（一位小數）
export function beatPct(p) {
  return isNum(p) ? (Math.min(1, Math.max(0, p)) * 100).toFixed(1) : null
}

// 離近 20 日前高還差多少（%）。前高不高於現價＝已在近 20 日高點。
export function gapToHigh(close, high) {
  if (!(isNum(close) && close > 0 && isNum(high) && high > 0)) return null
  const pct = (high / close - 1) * 100
  return { pct, atHigh: pct <= 0 }
}

// 「還差／距離」這類本身已帶方向的說法只印大小、不帶 +（「還差 +48.2%」讀起來像在漲）。
export function gapText(gap, digits = 1) {
  return gap && isNum(gap.pct) ? `${Math.abs(gap.pct).toFixed(digits)}%` : '—'
}

// 月線相對現價的位置
export function maSide(close, ma20) {
  if (!(isNum(close) && close > 0 && isNum(ma20) && ma20 > 0)) return null
  if (Math.abs(ma20 - close) < 1e-9) return '跟現價一樣'
  return ma20 > close ? '在現價上方' : '在現價下方'
}

// 漲跌方向（紅漲綠跌語意 class 用）
export function dirOf(v) {
  if (!isNum(v) || v === 0) return 'flat'
  return v > 0 ? 'up' : 'down'
}

// 每天所有候選的「理由」都一樣時，回傳那一組（提到區塊層講一次，卡片上不重複，審計 E1）；
// 只要有一檔不同就回 null，卡片照常各自顯示自己的理由。
export function commonReasons(picks) {
  if (!Array.isArray(picks) || picks.length === 0) return null
  const key = r => JSON.stringify(Array.isArray(r) ? r : [])
  const first = key(picks[0]?.reasons)
  if (first === '[]') return null
  return picks.every(p => key(p?.reasons) === first) ? picks[0].reasons : null
}

// 後端理由字串在門檻退回日會以「⚠️ 」開頭（pipeline/opportunities.py）。介面不用 emoji 當圖示
// （MASTER 第 7 節），拆成 { warn, text }，由元件改畫 SVG 警示圖示。
export function reasonView(r) {
  const s = typeof r === 'string' ? r : ''
  const m = s.match(/^\s*⚠️?\uFE0F?\s*/u)
  return m && m[0].includes('⚠') ? { warn: true, text: s.slice(m[0].length) } : { warn: false, text: s }
}

// ── 2026-11-16 快修 ──────────────────────────────────────────────
// 清單排序規則的一句話（只講真的在發生的）：pipeline/opportunities.py 排序鍵是
// (-score, -rs_pct_60)；今天所有候選 score 都是 0 時，實際上就是照近 60 天漲幅排。
export function sortRuleText(picks) {
  const anyScore = Array.isArray(picks) && picks.some(p => isNum(p?.score) && p.score > 0)
  return anyScore ? '先照訊號權重分、同分再照近 60 天漲幅由高到低排' : '照近 60 天漲幅由高到低排'
}

// 進引擎計分的訊號清單＝pipeline/backtest_signals.py ENGINE_SIGNALS（前端只用來判斷「有權重的訊號到底進不進計分」，
// 權重本身一律讀 signal_windows.json，不在這裡寫死）。
export const ENGINE_KEYS = [
  'signal_ma', 'signal_breakout', 'sn_squeeze_breakout', 'sn_lower_reversal', 'sn_break_low_recover',
  'sn_immortal_guide', 'sn_volume_support', 'foreign_buy', 'trust_buy', 'holder_rising', 'undervalued',
]

// 權重表下方那句說明。rows＝[{key,label,w}]（全部訊號，含權重 0）。
// 修正 G4：舊句把「強勢股60日、強勢雙確認」當成排序用的權重，但它們不在計分名單裡。
export function engineWeightNote(rows) {
  const list = Array.isArray(rows) ? rows : []
  const eng = list.filter(r => ENGINE_KEYS.includes(r.key) && r.w > 0)
  const other = list.filter(r => !ENGINE_KEYS.includes(r.key) && r.w > 0)
  const fmt = a => a.map(x => `${x.label} ${x.w}`).join('、')
  const parts = [eng.length
    ? `候選清單排序的計分只算 ${ENGINE_KEYS.length} 種技術／籌碼訊號，目前有權重的是：${fmt(eng)}。`
    : `候選清單排序的計分只算 ${ENGINE_KEYS.length} 種技術／籌碼訊號，目前它們的權重全部是 0，所以實際上是照近 60 天漲幅排。`]
  if (other.length) {
    parts.push(`${fmt(other)} 雖然有權重，但不在計分名單裡，沒有拿來排序${other.some(r => r.key === 'rs_confirmed_60_120') ? '（強勢雙確認是入場門檻）' : ''}。`)
  }
  parts.push('權重是 0 的原因：平均超額 ≤ 0 或樣本不足。')
  return parts.join('')
}

// 20 日均量門檻（張）＝pipeline/opportunities.py 的 MIN_VOL_LOTS（候選入場條件）。
// opportunities.json 沒帶這個數，前端只能抄；改 pipeline 時要一起改（cardFacts.test.mjs 會讀 .py 對照）。
export const MIN_VOL_LOTS = 500

// 引擎計分訊號的權重是不是全 0？rows＝signal_weights.json 的 signals（{key:{weight}}）。
// 缺資料回 null（呼叫端不下結論），全 0 回 true，任何一個 >0 回 false。
export function engineWeightsAllZero(signals) {
  if (!signals || typeof signals !== 'object') return null
  const ws = ENGINE_KEYS.map(k => signals[k]?.weight)
  if (ws.every(w => w == null)) return null
  return ws.every(w => !(isNum(w) && w > 0))
}

// ── 2026-11-16 三分頁＋「過關清單」卡片（Andy 核准：分頁照方向 C，卡片改方向 B）─────────
// 卡片檢視每張卡與清單展開內容共用同一份事實。全部只寫資料檔裡拿得到的事實：
//   ・不新增任何好壞門檻（MASTER 2026-11-16 第 5 點）；
//   ・pick 的新欄位 fired_labels／rs_pct_120／avg_vol_lots 由 pipeline 另外加，舊資料沒有——
//     有欄位就顯示、沒有就省略該行或改成不帶數字的說法，絕不自己重算或編造。
// 關卡叫法要跟「依據」分頁「這份清單怎麼來的」一一對應（GATE_LABELS 兩邊共用）。

export const GATE_LABELS = {
  strong: '強勢雙確認',
  signal: '今天亮的訊號',
  volume: '成交量夠',
  revenue: '營收沒衰退',
}

const fmtLots = v => Math.round(v).toLocaleString('en-US')
const isEdge = p => ['edge', 'both', 'win'].includes(p?.tier)   // 舊值 both/win 也是相對優勢（同 normalizeTier）

// 過關清單：回 [{ key, label, text, ok }]；ok=true 畫勾，ok=false 畫中性記號（沒過或查不到，不打勾）。
//   gate＝opportunities.json 的 gate（門檻是否套用）。
export function passChecks(p, gate) {
  if (!p || typeof p !== 'object') return []
  const out = []
  // 1. 強勢關：門檻有套用才打勾；沒套用照實說沒過這一關；不知道（舊資料沒有 gate）就不寫。
  if (gate && gate.applied === true) {
    const b60 = beatPct(p.rs_pct_60), b120 = beatPct(p.rs_pct_120)
    let text
    if (b60 != null && b120 != null) text = `60 天贏過全市場 ${b60}%，120 天贏過 ${b120}%`
    else if (b60 != null) text = `60 天贏過全市場 ${b60}%`
    else text = '近 60 天、近 120 天漲幅都排在全市場前段'
    const label = gate.signal === 'rs_confirmed_60_120' || !gate.label ? GATE_LABELS.strong : gate.label
    out.push({ key: 'strong', label, text, ok: true })
  } else if (gate && gate.applied === false) {
    out.push({ key: 'strong', label: gate.label || GATE_LABELS.strong, text: '今天這道門檻沒套用，這檔沒經過這一關', ok: false })
  }
  // 2. 今天亮的訊號：只認 fired_labels（字串陣列）；沒有這欄或空的就整行不顯示。
  const fired = Array.isArray(p.fired_labels) ? p.fired_labels.filter(x => typeof x === 'string' && x.trim()) : []
  if (fired.length) out.push({ key: 'signal', label: GATE_LABELS.signal, text: fired.join('、'), ok: true })
  // 3. 成交量
  out.push({
    key: 'volume', label: GATE_LABELS.volume, ok: true,
    text: isNum(p.avg_vol_lots)
      ? `近 20 日平均 ${fmtLots(p.avg_vol_lots)} 張（門檻 ${MIN_VOL_LOTS} 張）`
      : `近 20 日均量達 ${MIN_VOL_LOTS} 張門檻`,
  })
  // 4. 營收：查不到不打勾（中性記號），照實說沒有因此被刷掉
  out.push(isNum(p.revenue_yoy)
    ? { key: 'revenue', label: GATE_LABELS.revenue, text: `營收年增 ${signed(p.revenue_yoy)}%`, ok: true }
    : { key: 'revenue', label: GATE_LABELS.revenue, text: '查不到營收資料，沒有因此被刷掉', ok: false })
  return out
}

// 「強在哪」：只有相對優勢才有。
export function strengthLine(p) {
  return isEdge(p) ? '成交金額排今天候選前 1/3' : null
}

// 「要小心」：既有風險標記（照現有判定）＋近 20 天輸大盤（rs20 為負）。回字串陣列，空＝不顯示。
//   ・risk_flags（後端給的：乖離大、營收資料缺…）
//   ・乖離排前段（bias_high，或舊值 tier=both/return；同 tierVerdict.normalizeTier）
//   ・法說會將近（earnings_date 有值；後端只在未來 7 天內有法說會才填，見 pipeline/build_data.py）
export function cautionList(p) {
  if (!p || typeof p !== 'object') return []
  const out = []
  for (const f of (Array.isArray(p.risk_flags) ? p.risk_flags : [])) {
    if (typeof f === 'string' && f && !out.includes(f)) out.push(f)
  }
  if (p.tier === 'both' || p.tier === 'return' || !!p.bias_high) out.push('乖離排前段')
  if (typeof p.earnings_date === 'string' && p.earnings_date) {
    out.push(`法說會將近（${p.earnings_date.length >= 10 ? p.earnings_date.slice(5) : p.earnings_date}）`)
  }
  const vs = vsMarketText(p.rs20)
  if (vs && vs.dir === 'down') out.push(`近 20 天輸大盤 ${vs.value} 個百分點`)
  return out
}
// 清單列的橘點＝「要小心」有內容（同一個判定）
export const hasCaution = p => cautionList(p).length > 0

// 中性事實：離近 20 日前高還差多少（不放進要小心、不加判斷）
export function highGapLine(close, high) {
  const g = gapToHigh(close, high)
  if (!g) return null
  return g.atHigh ? '已在近 20 日高點' : `離近 20 日前高還差 ${gapText(g)}`
}

// 近 20 天比大盤：rs20＝個股近 20 日報酬 − 加權指數近 20 日報酬（百分點）。
// 回 { word, value, dir }：多漲／少漲；四捨五入後是 0 就說差不多；缺值回 null。
export function vsMarketText(rs20, digits = 1) {
  if (!isNum(rs20)) return null
  const s = Math.abs(rs20).toFixed(digits)
  if (Number(s) === 0) return { word: '跟大盤差不多', value: null, dir: 'flat' }
  return rs20 > 0 ? { word: '多漲', value: s, dir: 'up' } : { word: '少漲', value: s, dir: 'down' }
}
