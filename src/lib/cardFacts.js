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
