// 預設篩選條件
export const DEFAULT_CONDITIONS = {
  signalMa: false,        // 糾結後黃金交叉→多頭發散（綜合訊號）
  bullAligned: true,      // 多頭排列
  goldenCross: false,     // 近期黃金交叉
  maRising: false,        // 均線上彎
  bigHolderRising: false, // 千張大戶占比較上週上升
  foreignDays: 3,         // 外資連買 ≥ N 天（0 = 不限）
  trustDays: 3,           // 投信連買 ≥ N 天（0 = 不限）
  chipLogic: 'and',       // 'and' 外資與投信都要 / 'or' 任一即可
  keyword: '',
}

export function applyFilters(stocks, c) {
  return stocks.filter(s => {
    if (c.signalMa && !s.signal_ma) return false
    if (c.bullAligned && !s.bull_aligned) return false
    if (c.goldenCross && !s.golden_cross_recent) return false
    if (c.maRising && !s.ma_rising) return false
    if (c.bigHolderRising && !s.holder_rising) return false

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

export const SORTS = {
  signal: (a, b) => (b.signal_ma - a.signal_ma) || (b.foreign_streak - a.foreign_streak),
  foreign: (a, b) => b.foreign_streak - a.foreign_streak,
  trust: (a, b) => b.trust_streak - a.trust_streak,
  change: (a, b) => b.change_pct - a.change_pct,
  close: (a, b) => b.close - a.close,
}
