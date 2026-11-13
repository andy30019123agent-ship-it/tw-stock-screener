// localStorage 安全讀寫（2026-11-13 可讀性改版）。
// 隱私模式、被封鎖的 site data、預覽環境會讓「存取 localStorage 這個物件本身」就丟 SecurityError，
// 不只是 getItem／setItem 丟例外；所以取得 store 與讀寫都要包 try/catch。
// 讀不到回 fallback、寫不進去回 false，都不往外丟——最多是「下次不記得偏好」，頁面照常顯示。
// storage 參數讓單測可以塞假物件；不傳就用瀏覽器的 localStorage。

export function getStore(storage) {
  if (storage !== undefined) return storage
  try { return typeof localStorage === 'undefined' ? null : localStorage } catch { return null }
}

export function safeGet(key, fallback = null, storage) {
  try {
    const s = getStore(storage)
    if (!s) return fallback
    const v = s.getItem(key)
    return v === null || v === undefined ? fallback : v
  } catch {
    return fallback
  }
}

export function safeSet(key, value, storage) {
  try {
    const s = getStore(storage)
    if (!s) return false
    s.setItem(key, String(value))
    return true
  } catch {
    return false
  }
}

// 手機卡片密度：精簡（預設）／完整
export const DENSE_KEY = 'tw-screener:dense'
export const readDense = storage => safeGet(DENSE_KEY, null, storage) !== 'full'
export const writeDense = (dense, storage) => safeSet(DENSE_KEY, dense ? 'dense' : 'full', storage)
