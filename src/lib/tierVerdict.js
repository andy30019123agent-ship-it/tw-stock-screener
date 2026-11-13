// 條件層級「同日配對比較」的文字判讀（2026-11-13 驗收後新增）。
// 結論句一律由 tier_stats.json 的 paired（每天先算 A−B 再 bootstrap）決定怎麼講，不寫死：
//   CI 下限 > 0 → 「比較常賺／賺比較多」；上限 < 0 → 「比較少」；跨 0 → 「量不出差別」。
// 資料缺欄位、null、NaN、或整份統計 stale（最近一次重算失敗）→ 一律回 null，呼叫端顯示不帶數字的中性句。
// 禁止用「兩層各自的 CI 有沒有重疊」下結論（OutcomeShape.jsx 註解寫明的硬性限制）。

const isNum = v => typeof v === 'number' && Number.isFinite(v)
const okCi = c => Array.isArray(c) && c.length === 2 && isNum(c[0]) && isNum(c[1])

// 取出可用的 paired 項；不可用（缺欄位／stale）回 null。
export function usablePair(tierStats, key) {
  if (!tierStats || tierStats.stale) return null
  const p = tierStats.paired?.[key]
  if (!p || !isNum(p.win_pp) || !okCi(p.win_ci90)) return null
  return p
}

export function verdictOf(ci) {
  if (!okCi(ci)) return null
  return ci[0] > 0 ? 'better' : ci[1] < 0 ? 'worse' : 'nodiff'
}

const pp = v => Math.abs(v).toFixed(1)
const ciTxt = c => `${c[0].toFixed(1)}～${c[1].toFixed(1)}`

// 賺錢比例差的一句話；不可用回 null。
export function winDiffText(p) {
  const v = p && okCi(p.win_ci90) && isNum(p.win_pp) ? verdictOf(p.win_ci90) : null
  if (!v) return null
  if (v === 'better') return `賺錢比例高約 ${pp(p.win_pp)} 個百分點（90% CI ${ciTxt(p.win_ci90)}）`
  if (v === 'worse') return `賺錢比例低約 ${pp(p.win_pp)} 個百分點（90% CI ${ciTxt(p.win_ci90)}）`
  return `賺錢比例量不出差別（差 ${p.win_pp >= 0 ? '+' : '−'}${pp(p.win_pp)} 個百分點，90% CI ${ciTxt(p.win_ci90)} 跨過 0）`
}

// 平均每筆報酬差的一句話；不可用回 null（舊 JSON 沒有 ev 欄位時只講賺錢比例）。
export function evDiffText(p) {
  const v = p && okCi(p.ev_ci90) && isNum(p.ev_pp) ? verdictOf(p.ev_ci90) : null
  if (!v) return null
  if (v === 'better') return `平均每筆多約 ${pp(p.ev_pp)} 個百分點`
  if (v === 'worse') return `平均每筆少約 ${pp(p.ev_pp)} 個百分點`
  return '平均每筆量不出差別'
}

// 「同一天比『vs』：…」；不可用回 null。
export function pairSentence(p, vs) {
  const w = winDiffText(p)
  if (!w) return null
  const e = evDiffText(p)
  return `同一天比「${vs}」：${w}${e ? `、${e}` : ''}`
}

// 短版（不帶 CI 數字）：給分類卡片首句用。
export function pairShort(p, vs) {
  const vw = p ? verdictOf(p.win_ci90) : null
  if (!vw) return null
  const ve = p ? verdictOf(p.ev_ci90) : null
  const w = vw === 'better' ? '比較常賺' : vw === 'worse' ? '比較少賺' : '賺錢比例量不出差別'
  const e = ve === 'better' ? '平均也賺得多' : ve === 'worse' ? '平均賺得少' : ve === 'nodiff' ? '平均報酬量不出差別' : null
  return `同一天比「${vs}」：${w}${e ? `、${e}` : ''}`
}
