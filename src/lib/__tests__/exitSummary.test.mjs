import { normalizeExitSummary, fmtPct, siteRow } from '../exitSummary.js'
let pass = 0, fail = 0
const ok = (cond, msg) => { if (cond) { pass++ } else { fail++; console.log('  ❌', msg) } }
const row = (key, o = {}) => ({ key, label: key, stop_rate: 0.5, miscut_winners: 0.2, win_rate: 0.4, p5: -0.2, worst: -0.3, ...o })
const good = () => ({ as_of: '2026-11-13', hold_days: 20, n: 100, batches: 5, first_date: '2025-01-16', last_date: '2026-10-12', rows: [row('hold'), row('site15ma')] })

const s = normalizeExitSummary(good())
ok(s && s.rows.length === 2 && s.batches === 5 && s.holdDays === 20, '正常資料可解析')
ok(siteRow(s)?.key === 'site15ma' && siteRow(null) === null, 'siteRow')
ok(normalizeExitSummary(null) === null && normalizeExitSummary(undefined) === null && normalizeExitSummary('x') === null && normalizeExitSummary({}) === null, '壞輸入 → null')
const missing = good(); delete missing.rows[1].p5
ok(normalizeExitSummary(missing) === null, '缺欄位 → null（整塊不顯示）')
const nan = good(); nan.rows[0].win_rate = NaN
ok(normalizeExitSummary(nan) === null, 'NaN → null')
const str = good(); str.rows[0].worst = '−30%'
ok(normalizeExitSummary(str) === null, '字串數字 → null')
const nodate = good(); delete nodate.first_date
ok(normalizeExitSummary(nodate) === null, '缺量測期間 → null')
const one = good(); one.rows = [row('hold')]
ok(normalizeExitSummary(one) === null, '只剩一列不成表 → null')
ok(fmtPct(0.502) === '50.2%' && fmtPct(-0.257) === '−25.7%' && fmtPct(0) === '0.0%' && fmtPct(NaN) === '—' && fmtPct(undefined) === '—', 'fmtPct')
const holdNull = good(); holdNull.rows[0] = row('hold', { stop_rate: null, miscut_winners: null })
ok(normalizeExitSummary(holdNull)?.rows.length === 2 && fmtPct(null) === '—', '對照組觸發／誤砍為 null → 仍成表、顯示「—」')
const siteNull = good(); siteNull.rows[1] = row('site15ma', { stop_rate: null })
ok(normalizeExitSummary(siteNull) === null, '非對照組的 null 仍視為缺欄位 → null')
const holdWinNull = good(); holdWinNull.rows[0] = row('hold', { win_rate: null })
ok(normalizeExitSummary(holdWinNull) === null, '對照組的賺錢率不可為 null')
console.log(`exitSummary: ${pass} pass, ${fail} fail`)
if (fail) process.exit(1)
