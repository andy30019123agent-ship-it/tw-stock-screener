// 樣本外（OOS）穩健度的共用判讀。原本只寫在 ConditionPanel 裡，組合戰績排行榜也要用同一套
// 判準（否則兩張表對同一個訊號會給出不一致的可靠度），故抽出來當單一來源。
//
// 白話：robust＝訓練期看好、沒看過的日子也站得住；overfit＝訓練期看好但樣本外變負（等於背答案）；
// 其餘為縮水／挑市況／樣本不足。狀態字串由後端 walk_forward_oos 產生。

export const OOS_BADGE = {
  robust: ['穩健', 'oos-robust', '樣本外仍為正、效力保留過半、跨多個市況、樣本足'],
  regime_specific: ['挑市況', 'oos-warn', '樣本外為正，但只有少數市況合格，換市況可能失靈'],
  fragile: ['脆弱', 'oos-warn', '樣本外效力縮水一半以上，不太穩'],
  severe_shrinkage: ['大幅縮水', 'oos-bad', '樣本外只剩不到四分之一，多半是過擬合'],
  overfit: ['過擬合', 'oos-bad', '訓練期看好、樣本外卻變負 → 等於背答案，不是真本事'],
  insufficient_oos: ['資料不足', 'oos-muted', '樣本外事件太少或集中在少數日期，還無法判斷'],
  insufficient_history: ['資料不足', 'oos-muted', '全歷史樣本 <30，無法做樣本外驗證'],
  never_qualified: ['未達標', 'oos-muted', '沒有任何一段訓練期看好過這個策略'],
  no_selected_oos_events: ['資料不足', 'oos-muted', '合格期間內樣本外剛好沒有事件'],
  no_events: ['—', 'oos-muted', '此策略沒有回測事件'],
}

export function oosBadge(stat) {
  const b = OOS_BADGE[stat?.oos?.status]
  return b ? { text: b[0], cls: b[1], title: b[2] } : null
}

// 單一訊號的可靠度分級（給組合排行榜逐一標記成分訊號用）。
// pass＝通過樣本外驗證；weak＝樣本外撐不住（過擬合/縮水）；unknown＝樣本不足還無法判斷。
const TIER = {
  robust: 'pass',
  regime_specific: 'weak', fragile: 'weak', severe_shrinkage: 'weak', overfit: 'weak',
}
export function sigTier(stat) {
  if (!stat?.oos?.status) return 'unknown'
  return TIER[stat.oos.status] || 'unknown'
}

// 組合的可靠度摘要：逐一看成分訊號過不過樣本外驗證。
// 不過濾、不隱藏任何組合（Andy 要保留全部自行判斷），只把「靠不可靠訊號撐起來的」標出來。
export function comboReliability(sigs, weights) {
  const parts = sigs.map(s => {
    const stat = weights?.signals?.[s]
    const tier = sigTier(stat)
    const b = OOS_BADGE[stat?.oos?.status]
    return { sig: s, tier, status: stat?.oos?.status || null, label: b?.[0] || null, title: b?.[2] || null }
  })
  const pass = parts.filter(p => p.tier === 'pass').length
  const weak = parts.filter(p => p.tier === 'weak').length
  // 整體分級：有任一成分「樣本外撐不住」最嚴重；其次是全部過驗證；再其次是有成分還無法判斷。
  const overall = weak ? 'weak' : pass === parts.length ? 'pass' : 'unknown'
  return { parts, pass, weak, total: parts.length, overall }
}

// 成分訊號旁的小記號（inline 標在名稱後面，讓 Andy 一眼看出是「哪一個」不可靠）
export const TIER_MARK = {
  pass: null,
  weak: { mark: '⚠', cls: 'sig-weak' },
  unknown: { mark: '?', cls: 'sig-unknown' },
}
