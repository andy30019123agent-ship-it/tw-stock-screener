// 三分頁「今天／依據／工具」的網址雜湊（2026-11-16 Andy 核准方向 A＋C）。純函式、有單測。
//
// 分頁狀態放在 location.hash（#today／#basis／#tools）：重新整理會停在同一頁、上一頁會回到前一個分頁，
// 不必新增路由套件、GitHub Pages 也不用改設定。既有的 #help（以及 #help/s1 這種章節連結）照舊是使用說明。
// 空雜湊或不認得的雜湊一律當「今天」，不丟例外。

export const TABS = [
  ['today', '今天'],
  ['basis', '依據'],
  ['tools', '工具'],
]
export const TAB_KEYS = TABS.map(t => t[0])
export const DEFAULT_TAB = 'today'

// '#tools' → { route: 'main', tab: 'tools' }；'#help' 或 '#help/s2' → { route: 'help', tab: null }
export function parseHash(hash) {
  const h = typeof hash === 'string' ? hash.replace(/^#/, '') : ''
  if (h === 'help' || h.startsWith('help/')) return { route: 'help', tab: null }
  const key = h.split(/[/?&]/)[0]
  return { route: 'main', tab: TAB_KEYS.includes(key) ? key : DEFAULT_TAB }
}

export function tabHash(tab) {
  return `#${TAB_KEYS.includes(tab) ? tab : DEFAULT_TAB}`
}

// 分頁列鍵盤操作（WAI-ARIA tabs pattern）：左右鍵循環、Home／End 跳頭尾；其他鍵回 null（不處理）。
export function tabKeyTarget(current, key) {
  const i = TAB_KEYS.indexOf(current)
  const at = i < 0 ? 0 : i
  const n = TAB_KEYS.length
  if (key === 'ArrowRight') return TAB_KEYS[(at + 1) % n]
  if (key === 'ArrowLeft') return TAB_KEYS[(at - 1 + n) % n]
  if (key === 'Home') return TAB_KEYS[0]
  if (key === 'End') return TAB_KEYS[n - 1]
  return null
}
