// 各訊號「贏過大盤比例」的最小～最大（說明書 HelpGuide 與進階篩選 ConditionPanel 共用同一個來源，
// 2026-11-13 可讀性改版：原本兩處各自寫死「37%～43%」，現在一律讀 signal_weights.json）。
// 只算有樣本、且有數字的訊號；讀不到（沒資料、全是缺值）回 null，呼叫端要自己處理「取不到」的文案。
export const okNum = v => typeof v === 'number' && Number.isFinite(v)

export function signalSummary(weights) {
  const list = Object.values(weights?.signals || {}).filter(x => x && x.samples > 0 && okNum(x.excess_win_rate))
  if (!list.length) return null
  const rates = list.map(x => x.excess_win_rate)
  return { n: list.length, min: Math.min(...rates), max: Math.max(...rates), anyHalf: rates.some(r => r >= 0.5) }
}
