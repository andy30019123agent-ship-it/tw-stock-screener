import { readView, writeView, VIEW_KEY, DEFAULT_VIEW } from '../viewPref.js'
import { signed, rankFront, beatPct, gapToHigh, gapText, maSide, dirOf, commonReasons, reasonView } from '../cardFacts.js'
let pass = 0, fail = 0
const ok = (cond, msg) => { if (cond) { pass++ } else { fail++; console.log('  ❌', msg) } }

const mem = () => { const m = {}; return { getItem: k => (k in m ? m[k] : null), setItem: (k, v) => { m[k] = String(v) }, _m: m } }
const throwing = { getItem() { throw new Error('SecurityError') }, setItem() { throw new Error('QuotaExceeded') } }

// ── 檢視偏好 ──
ok(DEFAULT_VIEW === 'cards', '預設是卡片')
ok(readView(mem()) === 'cards', '空儲存 → 卡片')
ok(readView(null) === 'cards', '沒有 storage → 卡片')
ok(readView(throwing) === 'cards', 'getItem 丟例外 → 卡片，不往外丟')
const s = mem()
ok(writeView('list', s) === true && s._m[VIEW_KEY] === 'list', '寫入清單')
ok(readView(s) === 'list', '讀回清單')
ok(writeView('cards', s) && readView(s) === 'cards', '切回卡片')
s._m[VIEW_KEY] = 'grid'
ok(readView(s) === 'cards', '不認得的值 → 卡片')
ok(writeView('weird', s) && s._m[VIEW_KEY] === 'cards', '寫入不認得的值 → 存成預設')
ok(writeView('list', throwing) === false, 'setItem 丟例外 → 回 false、不往外丟')
ok(writeView('list', null) === false, '沒有 storage → 回 false')
// 沒傳 storage 時在 Node 沒有 localStorage → 仍回預設、不炸
ok(readView() === 'cards', 'Node 環境無 localStorage → 卡片')

// ── 卡片事實句 ──
ok(signed(1.234) === '+1.2' && signed(-1.25, 2) === '−1.25' && signed(0.04) === '0.0' && signed(null) === '—', 'signed 正負號與全形減號')
ok(rankFront(1) === '最高' && rankFront(0) === '最低', 'rankFront 兩端用白話')
ok(rankFront(0.71) === '排前 29%', '0.71 → 排前 29%')
ok(rankFront(0.999) === '排前 1%', '極接近最高 → 至少排前 1%')
ok(rankFront(null) === null && rankFront(NaN) === null, '缺值 → null')
ok(beatPct(0.997) === '99.7' && beatPct(1.2) === '100.0' && beatPct(undefined) === null, 'beatPct')
const g = gapToHigh(100, 149.4)
ok(g && Math.abs(g.pct - 49.4) < 1e-9 && g.atHigh === false, '離前高 +49.4%')
ok(gapToHigh(100, 100).atHigh === true && gapToHigh(100, 90).atHigh === true, '前高不高於現價 → 已在高點')
ok(gapText(g) === '49.4%' && !gapText(g).includes('+'), '還差 49.4%，不帶 + 號')
ok(gapText(null) === '—', 'gapText 缺值 → —')
ok(gapToHigh(0, 10) === null && gapToHigh(10, null) === null, '缺值 → null')
ok(maSide(100, 110) === '在現價上方' && maSide(100, 90) === '在現價下方' && maSide(100, null) === null, 'maSide')
ok(dirOf(1) === 'up' && dirOf(-0.1) === 'down' && dirOf(0) === 'flat' && dirOf(null) === 'flat', 'dirOf')
const R = ['僅符合門檻（強勢雙確認），無加權訊號、按相對強弱排序']
ok(JSON.stringify(commonReasons([{ reasons: R }, { reasons: [...R] }])) === JSON.stringify(R), '理由全同 → 回傳那組')
ok(commonReasons([{ reasons: R }, { reasons: ['糾結轉強'] }]) === null, '有一檔不同 → null')
ok(commonReasons([]) === null && commonReasons([{ reasons: [] }]) === null && commonReasons(null) === null, '空的 → null')

const rv = reasonView('⚠️ 今天沒套用強勢雙確認門檻（x）＝這檔未經強勢篩選')
ok(rv.warn === true && rv.text === '今天沒套用強勢雙確認門檻（x）＝這檔未經強勢篩選', '⚠️ 開頭 → warn＋去掉 emoji')
ok(reasonView('僅符合門檻').warn === false && reasonView('僅符合門檻').text === '僅符合門檻' && reasonView(null).text === '', '一般理由原樣')
console.log(`viewPref+cardFacts: ${pass} pass, ${fail} fail`)
if (fail) process.exit(1)
