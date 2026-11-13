// 條件層級「同日配對比較」的文字判讀（2026-11-13 驗收後新增）。
// 結論句一律由 tier_stats.json 的 paired（每天先算 A−B 再 bootstrap）決定怎麼講，不寫死：
//   CI 下限 > 0 → 「比較常賺／賺比較多」；上限 < 0 → 「比較少」；跨 0 → 「量不出差別」。
// 資料缺欄位、null、NaN、或整份統計 stale（最近一次重算失敗）→ 一律回 null，呼叫端顯示不帶數字的中性句。
// 禁止用「兩層各自的 CI 有沒有重疊」下結論（OutcomeShape.jsx 註解寫明的硬性限制）。
//
// 🔴 2026-11-13 分類簡化：網站只剩一個分類「相對優勢」（成交金額在當日候選池前 1/3），
// 主訊息＝paired.cat_edge_vs_rest（相對優勢 vs 當日其餘全部候選）。「乖離高」是純描述標籤。
// 這裡的句子與 TG 快報（pipeline/notify_tg.py 的 tier_disclaimer／gate_note／bias_note）逐字同一套，
// 改一邊要改另一邊。
// 幅度宣稱（平均每筆多賺）規則：CI 下限 ≥ 0.5pp 才講「也多約 X」；0 < 下限 < 0.5 講「略高，但接近量不出」；
// 一律附誤差範圍數字。

const isNum = v => typeof v === 'number' && Number.isFinite(v)
const okCi = c => Array.isArray(c) && c.length === 2 && isNum(c[0]) && isNum(c[1])
export const EV_NEAR_ZERO_PP = 0.5

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

// 幅度專用：下限 >0 但很接近 0 時是 'marginal'（保守說法）。
export function evVerdictOf(ci) {
  const v = verdictOf(ci)
  if (v === 'better' && ci[0] < EV_NEAR_ZERO_PP) return 'marginal'
  return v
}

// 四捨五入一律 floor(|x|×10+0.5)：toFixed 與 Python 格式化對 .x5 的進位規則不同，
// 用同一個算式網站與 TG（notify_tg._r1）才會逐字相同。
const r1 = v => (Math.floor(Math.abs(v) * 10 + 0.5) / 10).toFixed(1)
const pp = v => r1(v)
const num1 = v => `${v < 0 && r1(v) !== '0.0' ? '−' : ''}${r1(v)}`
export const ciTxt = c => `${num1(c[0])}～${num1(c[1])}`

// 賺錢比例差的一句話；不可用回 null。
export function winDiffText(p) {
  const v = p && okCi(p.win_ci90) && isNum(p.win_pp) ? verdictOf(p.win_ci90) : null
  if (!v) return null
  if (v === 'better') return `賺錢比例高約 ${pp(p.win_pp)} 個百分點（誤差範圍 ${ciTxt(p.win_ci90)}）`
  if (v === 'worse') return `賺錢比例低約 ${pp(p.win_pp)} 個百分點（誤差範圍 ${ciTxt(p.win_ci90)}）`
  return `賺錢比例量不出差別（差 ${p.win_pp >= 0 ? '+' : '−'}${pp(p.win_pp)} 個百分點，誤差範圍 ${ciTxt(p.win_ci90)}）`
}

// 平均每筆報酬差的一句話；不可用回 null（舊 JSON 沒有 ev 欄位時只講賺錢比例）。一律附誤差範圍。
export function evDiffText(p) {
  const v = p && okCi(p.ev_ci90) && isNum(p.ev_pp) ? evVerdictOf(p.ev_ci90) : null
  if (!v) return null
  const r = `（誤差範圍 ${ciTxt(p.ev_ci90)}）`
  if (v === 'better') return `平均每筆也多約 ${pp(p.ev_pp)} 個百分點${r}`
  if (v === 'marginal') return `平均每筆略高約 ${pp(p.ev_pp)} 個百分點，但接近量不出${r}`
  if (v === 'worse') return `平均每筆少約 ${pp(p.ev_pp)} 個百分點${r}`
  return `平均每筆量不出差別${r}`
}

// 「同一天比『vs』：…」；不可用回 null。
export function pairSentence(p, vs) {
  const w = winDiffText(p)
  if (!w) return null
  const e = evDiffText(p)
  return `同一天比「${vs}」：${w}${e ? `、${e}` : ''}`
}

// 短版：給分類卡片首句用。幅度部分照樣附誤差範圍（規則見檔頭）。
export function pairShort(p, vs) {
  const vw = p ? verdictOf(p.win_ci90) : null
  if (!vw) return null
  const w = vw === 'better' ? '比較常賺' : vw === 'worse' ? '比較少賺' : '賺錢比例量不出差別'
  const e = evDiffText(p)
  return `同一天比「${vs}」：${w}${e ? `、${e}` : ''}`
}

// ── 2026-11-13 新主訊息 ─────────────────────────────────────────────

// 主訊息：「同一天的候選裡，相對優勢這群比其他候選的賺錢機率多約 X 個百分點（誤差範圍 a～b），平均每筆…」
// 與 notify_tg.tier_disclaimer 的 head 逐字相同。不可用（缺／stale）回 null。
export function edgeSentence(tierStats) {
  const p = usablePair(tierStats, 'cat_edge_vs_rest')
  if (!p) return null
  const v = verdictOf(p.win_ci90)
  const r = ciTxt(p.win_ci90)
  let head
  if (v === 'better') head = `同一天的候選裡，相對優勢這群比其他候選的賺錢機率多約 ${pp(p.win_pp)} 個百分點（誤差範圍 ${r}）`
  else if (v === 'worse') head = `同一天的候選裡，相對優勢這群比其他候選的賺錢機率少約 ${pp(p.win_pp)} 個百分點（誤差範圍 ${r}）`
  else head = `同一天的候選裡，相對優勢這群跟其他候選的賺錢機率量不出差別（差 ${p.win_pp >= 0 ? '+' : '−'}${pp(p.win_pp)} 個百分點，誤差範圍 ${r}）`
  const e = evDiffText(p)
  return e ? `${head}，${e}` : head
}

// 相對優勢的單檔賺錢機率一句話（照實講是否不到一半，文字由數字決定）；不可用回 null。
export function edgeWinRateText(tierStats) {
  if (!tierStats || tierStats.stale) return null
  const wr = tierStats.categories?.edge?.win_rate
  if (!isNum(wr)) return null
  const t = (wr * 100).toFixed(1)
  return wr < 0.5 ? `但單檔賺錢機率只有 ${t}%，不到一半` : `單檔賺錢機率 ${t}%，過半也不代表穩賺`
}

// 統計過期的可見字樣；沒過期回 null。stale 時檔案裡的 date 是上一次成功重算的日期。
export function staleText(tierStats) {
  if (!tierStats?.stale) return null
  return `統計已過期（上次成功重算 ${tierStats.date || '—'}）`
}

// 門檻退回日提醒（不切換整組統計數字）。門檻有套用回 null。與 notify_tg.gate_note 同句。
export function gateNote(gate, tierStats) {
  if (!gate || gate.applied !== false) return null
  if (gate.reason !== 'pool_too_small') return '今天強弱資料算不出來、強勢門檻沒套用，分類請保守看。'
  const base = '今天過強勢門檻的候選不足，門檻已放寬；'
  const cats = tierStats?.by_gate?.fallback?.categories || {}
  const e = cats.edge?.win_rate, r = cats.rest?.win_rate
  if (tierStats?.stale || !isNum(e) || !isNum(r)) return `${base}這種日子的歷史數字讀不到，分類請保守看。`
  const nums = `（相對優勢賺錢機率 ${(e * 100).toFixed(1)}%、其他候選 ${(r * 100).toFixed(1)}%）`
  return e < r
    ? `${base}歷史上這種日子分類方向曾經相反${nums}。`
    : `${base}歷史上這種日子分類的差距跟平常不一樣${nums}，請保守看。`
}

// 「乖離高」描述標籤的說明；與 notify_tg.bias_note 同句。
export function biasNote(tierStats) {
  const p = usablePair(tierStats, 'bias_high_vs_rest')
  const ev = p ? verdictOf(p.ev_ci90) : null
  if (p && verdictOf(p.win_ci90) === 'nodiff' && (ev === 'nodiff' || ev === null)) {
    return '「乖離高」只是描述（當天候選裡乖離前 1/3），量不出比較常賺或賺比較多。'
  }
  return '「乖離高」只是描述（當天候選裡乖離前 1/3），不代表比較好。'
}

// 任何版本的 pick → { tier: 'edge'|null, biasHigh: bool }。與 opportunities.normalize_tier 同一套對應：
// 2026-11-13 以前的舊值 both/win（成交金額前 1/3）＝相對優勢、return＝無分類＋乖離高；未知值＝無分類。
export function normalizeTier(p) {
  const t = p?.tier
  if (t === 'both' || t === 'win') return { tier: 'edge', biasHigh: t === 'both' || !!p.bias_high }
  if (t === 'return') return { tier: null, biasHigh: true }
  return { tier: t === 'edge' ? 'edge' : null, biasHigh: !!p?.bias_high }
}
