import { fmtRange } from '../fmtRange.js'
let pass = 0, fail = 0
const ok = (c, m) => { c ? pass++ : (fail++, console.log('  ❌ ' + m)) }
ok(fmtRange([-4.06, 3.39]) === '−4.06%～+3.39%', '跨 0')
ok(fmtRange([-5.3, -1.2]) === '−5.30%～−1.20%', '全負')
ok(fmtRange([36.55, 58.03], { sign: false }) === '36.55%～58.03%', '勝率不帶 +')
ok(fmtRange([0.004, 1]) === '0.00%～+1.00%', '近 0 不帶號')
ok(fmtRange(null) === '—' && fmtRange([1]) === '—' && fmtRange([NaN, 1]) === '—' && fmtRange(undefined) === '—', '缺值')
console.log(`fmtRange: ${pass} pass, ${fail} fail`)
if (fail) process.exit(1)
