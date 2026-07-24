// 預設篩選條件
export const DEFAULT_CONDITIONS = {
  signalMa: false,        // 糾結後黃金交叉→多頭發散（綜合訊號）
  breakout: false,        // 爆量突破起漲（悶久→帶量突破創新高→站上均線）
  breakoutMult: 1.8,      // 突破日量 ≥ N 倍 20 日均量
  breakoutLookback: 3,    // 最近 N 天內的突破才算
  bullAligned: true,      // 多頭排列
  goldenCross: false,     // 近期黃金交叉
  maRising: false,        // 均線上彎
  strongerThanMarket: false, // 相對強弱 RS20 > 0（近 20 日報酬贏過加權指數）
  // 小詩選股（布林軌道系列技術形態，近 3 交易日內成立）
  shishiAny: false,           // 符合任一小詩形態
  snSqueezeBreakout: false,   // 縮口帶量突破
  snLowerReversal: false,     // 破下軌翻紅
  snBreakLowRecover: false,   // 破底翻
  snImmortalGuide: false,     // 仙人指路
  snVolumeSupport: false,     // 大量紅K低點防守
  bigHolderRising: false, // 千張大戶占比較上週上升
  // 估值 / 同業比（0 = 不限）
  minYield: 0,            // 現金殖利率 ≥ N %
  maxPe: 0,               // 本益比 ≤ N（且 > 0）
  maxPb: 0,               // 本淨比 ≤ N
  undervalued: false,     // 同業被低估（本益比低於同產業中位數）
  // 填息（B 段第二段）：'all' 不限 / 'filled' 已填息 / 'pending' 尚未填息（貼息中）
  divFill: 'all',
  maxFillDays: 0,         // 已填息且天數 ≤ N（0 = 不限），越快填息代表填息能力越強
  foreignDays: 3,         // 外資連買 ≥ N 天（0 = 不限）
  trustDays: 3,           // 投信連買 ≥ N 天（0 = 不限）
  chipLogic: 'and',       // 'and' 外資與投信都要 / 'or' 任一即可
  market: 'all',          // 'all' / '上市' / '上櫃'
  industry: 'all',        // 'all' 或產業名稱
  keyword: '',
}

// 爆量突破：目前多頭排列＋翻揚，且最近 lookback 天內有量 ≥ mult 倍的突破候選
export function hasBreakout(s, mult, lookback) {
  if (!s.bull_aligned || !s.ma_rising) return false
  return (s.breakout_cands || []).some(c => c.ago <= lookback && c.vr >= mult)
}

export function applyFilters(stocks, c) {
  return stocks.filter(s => {
    if (c.signalMa && !s.signal_ma) return false
    if (c.breakout && !hasBreakout(s, c.breakoutMult, c.breakoutLookback)) return false
    if (c.bullAligned && !s.bull_aligned) return false
    if (c.goldenCross && !s.golden_cross_recent) return false
    if (c.maRising && !s.ma_rising) return false
    if (c.strongerThanMarket && !(s.rs20 > 0)) return false
    if (c.bigHolderRising && !s.holder_rising) return false

    // 小詩選股形態
    if (c.shishiAny && !s.signal_shishi) return false
    if (c.snSqueezeBreakout && !s.sn_squeeze_breakout) return false
    if (c.snLowerReversal && !s.sn_lower_reversal) return false
    if (c.snBreakLowRecover && !s.sn_break_low_recover) return false
    if (c.snImmortalGuide && !s.sn_immortal_guide) return false
    if (c.snVolumeSupport && !s.sn_volume_support) return false

    // 估值 / 同業比
    if (c.minYield > 0 && !(s.yield_pct >= c.minYield)) return false
    if (c.maxPe > 0 && !(s.pe > 0 && s.pe <= c.maxPe)) return false
    if (c.maxPb > 0 && !(s.pb > 0 && s.pb <= c.maxPb)) return false
    if (c.undervalued && !s.undervalued) return false

    // 填息狀態
    if (c.divFill === 'filled' && !(s.div_fill && s.div_fill.fill_days != null)) return false
    if (c.divFill === 'pending' && !(s.div_fill && s.div_fill.pending_days != null)) return false
    if (c.maxFillDays > 0 && !(s.div_fill && s.div_fill.fill_days > 0 && s.div_fill.fill_days <= c.maxFillDays)) return false

    // 市場 / 產業
    if (c.market && c.market !== 'all' && s.market !== c.market) return false
    if (c.industry && c.industry !== 'all' && s.industry !== c.industry) return false

    // 籌碼條件
    const fOk = c.foreignDays <= 0 || s.foreign_streak >= c.foreignDays
    const tOk = c.trustDays <= 0 || s.trust_streak >= c.trustDays
    if (c.foreignDays > 0 || c.trustDays > 0) {
      if (c.chipLogic === 'and' && !(fOk && tOk)) return false
      if (c.chipLogic === 'or' && !(fOk || tOk)) return false
    }

    if (c.keyword) {
      const k = c.keyword.trim()
      if (!s.id.includes(k) && !s.name.includes(k)) return false
    }
    return true
  })
}

// 取一檔最強的突破量倍數（沒有候選回 0），給排序用
const topVr = s => (s.breakout_cands || []).reduce((m, c) => Math.max(m, c.vr), 0)

// 小詩形態命中數（給排序用）
const snCount = s => (s.sn_tags || []).length

// 填息排序權重：已填息用天數（越少越強）、貼息中排在已填息之後、沒除權息的墊底。
// 不用 0 當「沒資料」的代表值——那會讓沒除權息的股票排到填息最快的位置。
const fillRank = s => {
  const f = s.div_fill
  if (!f) return Number.MAX_SAFE_INTEGER
  if (f.fill_days != null) return f.fill_days
  return 100000 + (f.pending_days || 0)
}

// 排序鍵 → 中文標籤（給手機常駐工具列顯示目前排序）
export const SORT_LABELS = {
  signal: '訊號', breakout: '突破', shishi: '小詩', rs: '相對強弱', fill: '填息天數',
  change: '漲跌幅', yield: '殖利率', pe: '本益比',
  foreign: '外資', trust: '投信', close: '收盤',
}

// 手機排序選單的顯示順序（工具列「排序 ▾」點開的選單共用；桌機用表頭排序不吃這個）
export const MOBILE_SORTS = [
  ['signal', '訊號'], ['breakout', '突破'], ['shishi', '小詩'], ['rs', '相對強弱'],
  ['change', '漲跌幅'], ['yield', '殖利率'], ['pe', '本益比'], ['fill', '填息天數'],
  ['foreign', '外資'], ['trust', '投信'],
]

// 目前有幾個條件在實際限縮清單（給工具列顯示「條件 N」）
export function countActiveConditions(c) {
  let n = 0
  const bools = [
    'signalMa', 'breakout', 'bullAligned', 'goldenCross', 'maRising', 'strongerThanMarket',
    'bigHolderRising', 'shishiAny', 'snSqueezeBreakout', 'snLowerReversal',
    'snBreakLowRecover', 'snImmortalGuide', 'snVolumeSupport', 'undervalued',
  ]
  for (const k of bools) if (c[k]) n++
  if (c.foreignDays > 0) n++
  if (c.trustDays > 0) n++
  if (c.minYield > 0) n++
  if (c.maxPe > 0) n++
  if (c.maxPb > 0) n++
  if (c.divFill && c.divFill !== 'all') n++
  if (c.maxFillDays > 0) n++
  if (c.market && c.market !== 'all') n++
  if (c.industry && c.industry !== 'all') n++
  if (c.keyword && c.keyword.trim()) n++
  return n
}

export const SORTS = {
  signal: (a, b) => (b.signal_ma - a.signal_ma) || (b.foreign_streak - a.foreign_streak),
  breakout: (a, b) => (b.signal_breakout - a.signal_breakout) || (topVr(b) - topVr(a)),
  shishi: (a, b) => (snCount(b) - snCount(a)) || (b.foreign_streak - a.foreign_streak),
  // 填息天數：越少越前面；尚未填息的排最後（用 Infinity），沒除權息的再後面
  fill: (a, b) => fillRank(a) - fillRank(b),
  foreign: (a, b) => b.foreign_streak - a.foreign_streak,
  trust: (a, b) => b.trust_streak - a.trust_streak,
  change: (a, b) => b.change_pct - a.change_pct,
  close: (a, b) => b.close - a.close,
  yield: (a, b) => (b.yield_pct || 0) - (a.yield_pct || 0),
  pe: (a, b) => (a.pe > 0 ? a.pe : 1e9) - (b.pe > 0 ? b.pe : 1e9),  // 本益比小→大（無/負殿後）
  rs: (a, b) => (b.rs20 ?? -999) - (a.rs20 ?? -999),  // 相對強弱：強於大盤越多排越前
}
