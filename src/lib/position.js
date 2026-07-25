// 部位計算：把「該買多少」「防守價放哪」「持有到哪天」算出來（Andy 2026-07-25 要求）。
//
// 為什麼需要：站上原本只告訴使用者「買哪 5 檔」，但實際下單還缺三件事——買多少錢、跌到哪要走、
// 抱到什麼時候。而且 Top5 常出現一張要幾十萬甚至五百多萬的股票（實測緯穎一張 573 萬），
// 若使用者的標準部位是 20 萬，等於根本買不了整張。
//
// 純函式、不碰 I/O，方便單測與前端重用。

/** 一張＝1000 股（台股整股單位） */
export const LOT = 1000

/**
 * 波動平價（volatility parity）配置金額：波動越大、投入越少，讓每檔的「風險貢獻」接近。
 *
 * 為什麼不用等金額：Top5 的年化波動實測從 10% 到 132% 都有（中位約 59%）。等金額買
 * 一檔波動 100% 與一檔 30% 的，前者對組合損益的影響是後者的三倍多，名義分散但實際沒分散。
 *
 * 做法：權重 ∝ 1/波動，再正規化到總預算。缺波動資料的用中位數當替代（不因缺資料就給極端權重）。
 * clamp 上下限避免極端值吃掉整個預算或被壓到買不到一股。
 */
export function volatilityParity(picks, budget, { fallbackVol = 60, minShare = 0.08, maxShare = 0.40 } = {}) {
  if (!picks?.length || !(budget > 0)) return []
  const vols = picks.map(p => (p.rv20_pct > 0 ? p.rv20_pct : fallbackVol))
  const raw = vols.map(v => 1 / v)
  const sum = raw.reduce((a, b) => a + b, 0)
  let share = raw.map(r => r / sum)
  // clamp 後重新正規化（單純 clamp 會讓總和不等於 1）
  share = share.map(s => Math.min(maxShare, Math.max(minShare, s)))
  const s2 = share.reduce((a, b) => a + b, 0)
  share = share.map(s => s / s2)
  return picks.map((p, i) => {
    const amount = budget * share[i]
    const px = p.close > 0 ? p.close : null
    const shares = px ? Math.floor(amount / px) : 0
    return {
      share: share[i],
      amount,                                   // 建議投入金額
      shares,                                   // 可買股數（零股）
      lots: px ? amount / (px * LOT) : 0,        // 換算成幾張（<1 代表買不到整張）
      lotPrice: px ? px * LOT : null,             // 一張多少錢
      affordable: px ? px * LOT <= budget : false, // 整個預算買不買得起一張
      vol: vols[i],
    }
  })
}

/**
 * 防守價（停損參考）。
 *
 * ⚠️ 刻意用 −15% 而不是常見的 −8%：實測 26,425 筆歷史交易（用區間最低價判斷是否觸發），
 * −8% 會觸發 56% 的交易並砍掉 22% 的「最終漲幅 ≥20%」大贏家；−15% 只砍掉 5%。
 * 這套系統的報酬形狀是「多數小輸、少數大贏」，停損太緊會先把大贏家砍掉，反而毀掉整體期望值。
 *
 * 同時給「離 20 日均線」的距離當第二參考——跌破月線是趨勢轉弱的常見訊號。
 */
export const STOP_PCT = 0.15

export function defendPrice(p) {
  if (!(p?.close > 0)) return null
  const stop = p.close * (1 - STOP_PCT)
  const ma20 = p.ma20 > 0 ? p.ma20 : null
  return {
    stop: Math.round(stop * 100) / 100,
    ma20,
    // 兩者取較高者當實際防守位：跌破月線通常先發生，但若月線離太遠就用固定 −15% 兜底
    suggested: Math.round(Math.max(stop, ma20 ?? 0) * 100) / 100,
    usedMa: ma20 != null && ma20 > stop,
    downsidePct: ma20 != null && ma20 > stop ? (ma20 / p.close - 1) * 100 : -STOP_PCT * 100,
  }
}

/** 建議持有到期日：回測用固定持有 20 交易日結算，所以「到期」就是那一天。 */
export const HOLD_DAYS = 20

export function holdUntil(dataDate, days = HOLD_DAYS) {
  if (!dataDate) return null
  // 只數交易日（跳過週末）；不處理國定假日——標示為「約」即可，不必假精確
  const d = new Date(`${dataDate}T00:00:00`)
  let left = days
  while (left > 0) {
    d.setDate(d.getDate() + 1)
    const wd = d.getDay()
    if (wd !== 0 && wd !== 6) left--
  }
  return d.toISOString().slice(0, 10)
}

/**
 * 集中度：同產業檔數占比。
 * 為什麼要看：實測今天 Top5 有 4~5 檔同屬「電腦及週邊設備」，名義分散 5 檔、實際是同一個賭注
 * 下多次。同產業個股的相關性高，一起漲也一起跌。
 */
export function concentration(picks) {
  const by = {}
  for (const p of picks || []) {
    const k = p.industry || '未分類'
    by[k] = (by[k] || 0) + 1
  }
  const entries = Object.entries(by).sort((a, b) => b[1] - a[1])
  const top = entries[0]
  const n = picks?.length || 0
  return {
    groups: entries,
    topIndustry: top?.[0] ?? null,
    topCount: top?.[1] ?? 0,
    topRatio: n ? (top?.[1] ?? 0) / n : 0,
    // 有效獨立注數的粗估：同產業視為高度相關（用 0.6 當同產業相關係數的保守代理）
    effectiveBets: n ? +(n / (1 + 0.6 * (n / entries.length - 1))).toFixed(2) : 0,
    warn: n >= 3 && (top?.[1] ?? 0) / n >= 0.6,
  }
}
