// 候選區「卡片／清單」檢視偏好（2026-11-13 可讀性改版，Andy 核准：可一鍵切換、記住上次選擇）。
// 讀寫 localStorage 一律包 try/catch：隱私模式、被封鎖的 site data、預覽環境都可能直接丟例外，
// 讀不到或讀到不認得的值就回預設「卡片」，寫不進去就算了（只是下次不記得，不影響畫面）。
// storage 參數讓單測可以塞假物件，不必依賴瀏覽器。

export const VIEW_KEY = 'tw-screener:opp-view'
export const VIEWS = ['cards', 'list']
export const DEFAULT_VIEW = 'cards'

const getStore = storage => {
  if (storage !== undefined) return storage
  try { return typeof localStorage === 'undefined' ? null : localStorage } catch { return null }
}

export function readView(storage) {
  try {
    const s = getStore(storage)
    const v = s ? s.getItem(VIEW_KEY) : null
    return VIEWS.includes(v) ? v : DEFAULT_VIEW
  } catch {
    return DEFAULT_VIEW
  }
}

// 回傳實際採用的值（不認得的值一律當預設，不寫進去）；寫入失敗回傳 false 方便測試。
export function writeView(view, storage) {
  const v = VIEWS.includes(view) ? view : DEFAULT_VIEW
  try {
    const s = getStore(storage)
    if (!s) return false
    s.setItem(VIEW_KEY, v)
    return true
  } catch {
    return false
  }
}
