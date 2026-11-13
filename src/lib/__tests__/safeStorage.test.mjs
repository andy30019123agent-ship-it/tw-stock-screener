import { safeGet, safeSet, getStore, readDense, writeDense, DENSE_KEY } from '../safeStorage.js'
import { signalSummary } from '../signalSummary.js'
let pass = 0, fail = 0
const ok = (cond, msg) => { if (cond) { pass++ } else { fail++; console.log('  ❌', msg) } }
const mem = () => { const m = {}; return { getItem: k => (k in m ? m[k] : null), setItem: (k, v) => { m[k] = String(v) }, _m: m } }
const throwing = { getItem() { throw new Error('SecurityError') }, setItem() { throw new Error('QuotaExceeded') } }

ok(safeGet('k', 'fb', mem()) === 'fb', '沒值 → fallback')
ok(safeGet('k', 'fb', throwing) === 'fb', 'getItem 丟例外 → fallback')
ok(safeGet('k', 'fb', null) === 'fb', '沒有 storage → fallback')
ok(safeSet('k', 'v', throwing) === false && safeSet('k', 'v', null) === false, '寫入失敗 → false 不丟')
const s = mem()
ok(safeSet('k', 5, s) === true && safeGet('k', null, s) === '5', '寫入後讀回（轉字串）')
ok(getStore() === null, 'Node 環境無 localStorage → null')

// 存取 localStorage 這個物件本身就丟 SecurityError（getter 丟例外）
Object.defineProperty(globalThis, 'localStorage', { configurable: true, get() { throw new Error('SecurityError') } })
ok(getStore() === null, 'localStorage getter 丟例外 → null')
ok(safeGet('k', 'fb') === 'fb' && safeSet('k', 'v') === false, 'getter 丟例外時讀寫都安全')
ok(readDense() === true && writeDense(false) === false, 'dense：getter 丟例外 → 預設精簡、寫入回 false')
delete globalThis.localStorage

ok(readDense(mem()) === true, 'dense 預設精簡')
const d = mem()
ok(writeDense(false, d) && d._m[DENSE_KEY] === 'full' && readDense(d) === false, '寫完整 → 讀回完整')
ok(writeDense(true, d) && d._m[DENSE_KEY] === 'dense' && readDense(d) === true, '寫精簡 → 讀回精簡')
ok(readDense(throwing) === true, 'dense：getItem 丟例外 → 精簡')

// signalSummary
ok(signalSummary(null) === null && signalSummary({ signals: {} }) === null, '沒資料 → null')
const w = { signals: {
  a: { samples: 10, excess_win_rate: 0.37 }, b: { samples: 5, excess_win_rate: 0.43 },
  c: { samples: 0, excess_win_rate: 0.9 }, d: { samples: 8, excess_win_rate: null }, e: null } }
const r = signalSummary(w)
ok(r && r.n === 2 && r.min === 0.37 && r.max === 0.43 && r.anyHalf === false, '最小～最大只算有樣本且有數字的')
ok(signalSummary({ signals: { a: { samples: 3, excess_win_rate: 0.52 } } }).anyHalf === true, '有過半 → anyHalf')
console.log(`safeStorage+signalSummary: ${pass} pass, ${fail} fail`)
if (fail) process.exit(1)
