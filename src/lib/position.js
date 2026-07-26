// 部位計算：個股觀察位（近 20 日前高）與績效檢視日（Andy 2026-07-25 要求，2026-07-26 誠實化調整）。
//
// 2026-07-26：移除 volatilityParity（資金配置／買幾張）——Andy 明確表示「不用提供給我購買組合，
// 我會自行評估是否買入」，這屬於購買組合語意。defendPrice 保留計算邏輯供 Phase 3 參考，
// 但拿掉了「已驗證」的結論性文案（見下方函式註解）。
//
// 純函式、不碰 I/O，方便單測與前端重用。

/**
 * 防守價（停損參考，−15% 與 20 日均線取較高者）。
 *
 * ⚠️ 2026-07-26 更正：舊註解宣稱「實測 26,425 筆歷史交易驗證 −15% 優於 −8%」，
 * 但產生那組數字的腳本不在 repo 裡、無法重現，Phase 3 會用逐日 OHLC 重做驗證。
 * 在驗證補上前，這個函式只是一個未經驗證的參考位計算，前端不掛任何「已驗證」的結論性文案，
 * 也不在畫面上呈現（Task 7 已把「出場價」整欄移除）。
 *
 * 同時給「離 20 日均線」的距離當第二參考——跌破月線是趨勢轉弱的常見訊號。
 */
export const STOP_PCT = 0.15

export function defendPrice(p) {
  if (!(p?.close > 0)) return null
  const stop = p.close * (1 - STOP_PCT)
  const ma20 = p.ma20 > 0 ? p.ma20 : null
  // 🔴 2026-07-25 修（Codex 指出）：原本用 `Math.max(stop, ma20)`，但**月線可能高於現價**
  // （實測全市場 925 檔有 705 檔＝76% 處於月線下！只是當天 Top10 剛好都在月線上所以沒露餡）。
  // 那會產生「高於現價的停損價」＝邏輯上不成立（那是「已經跌破、該賣了」而不是防守位），
  // 而且 downsidePct 會變成正數，UI 取絕對值後偽裝成下方風險。
  // 正確條件：只有 `stop < ma20 < close` 時月線才是有效的防守位（在現價下方、又比固定停損近）。
  const maUsable = ma20 != null && ma20 > stop && ma20 < p.close
  const suggested = maUsable ? ma20 : stop
  return {
    stop: Math.round(stop * 100) / 100,
    ma20,
    suggested: Math.round(suggested * 100) / 100,
    usedMa: maUsable,
    // 一律是負數（到防守價的跌幅）；月線在現價之上時退回固定 −15%
    downsidePct: (suggested / p.close - 1) * 100,
    // 現價已在月線下＝趨勢已轉弱，值得單獨提示（不是停損位，是「訊號品質」警訊）
    belowMa20: ma20 != null && p.close < ma20,
  }
}

/** 20 日績效檢視日：回測用固定持有 20 交易日結算，這是回測口徑，不是建議賣出日。 */
export const HOLD_DAYS = 20

/**
 * 近 20 日前高（觀察位）。
 * 2026-07-26 移除原本的「統計目標」（收盤 ×(1+13.7%)）：13.7% 是歷史上「持有 20 日、
 * 賺的時候」的平均幅度，忽略了虧損事件，不能代表這檔的預期報酬，掛出來會誤導成「目標價」。
 * 現在只呈現一個事實性數字：近 20 日內的最高價，單純的技術觀察位。
 */
export function targetPrice(p) {
  if (!(p?.close > 0)) return null
  const high = p.recent_high20 > p.close ? p.recent_high20 : null
  if (high == null) return null
  return {
    high: Math.round(high * 100) / 100,
    upsidePct: (high / p.close - 1) * 100,
  }
}

export function holdUntil(dataDate, days = HOLD_DAYS) {
  if (!dataDate) return null
  // 只數交易日（跳過週末）；不處理國定假日——標示為「約」即可，不必假精確。
  // 🔴 2026-07-25 修時區 bug（Codex 指出）：原本用 `new Date('...T00:00:00')`（**本地**午夜）
  // 遞增，卻用 `toISOString()`（**UTC**）輸出 → 台北 (UTC+8) 的本地午夜換成 UTC 是前一天 16:00，
  // 日期整個倒退一天。實測 2026-07-24（週五）往後 5 個交易日：正解 07-31，台北卻算出 07-30。
  // 全程改用 UTC（Date.UTC + getUTCDay + setUTCDate）→ 與時區無關，任何機器結果一致。
  const [y, m, dd] = dataDate.split('-').map(Number)
  const d = new Date(Date.UTC(y, m - 1, dd))
  let left = days
  while (left > 0) {
    d.setUTCDate(d.getUTCDate() + 1)
    const wd = d.getUTCDay()
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
