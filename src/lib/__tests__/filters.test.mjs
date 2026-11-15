import { DEFAULT_CONDITIONS, countActiveConditions, describeActiveConditions } from '../filters.js'
let pass = 0, fail = 0
const ok = (cond, msg) => { if (cond) { pass++ } else { fail++; console.log('  ❌', msg) } }

// 預設條件：多頭排列＋外資連買 3 天＋投信連買 3 天（兩個都要）
const d = describeActiveConditions(DEFAULT_CONDITIONS)
ok(d.length === countActiveConditions(DEFAULT_CONDITIONS) && d.length === 3, '預設 3 個條件，說明條數與計數一致')
ok(d[0] === '多頭排列' && d[1] === '外資連買 3 天以上' && d[2].startsWith('投信連買 3 天以上') && d[2].includes('兩個都要'), '預設條件逐條寫出')
const or = describeActiveConditions({ ...DEFAULT_CONDITIONS, chipLogic: 'or' })
ok(or[2].includes('擇一'), 'OR 邏輯寫成擇一')
const blank = { ...DEFAULT_CONDITIONS, bullAligned: false, foreignDays: 0, trustDays: 0 }
ok(describeActiveConditions(blank).length === 0 && countActiveConditions(blank) === 0, '全清掉 → 空陣列（畫面不顯示那一行）')
const mix = { ...DEFAULT_CONDITIONS, bullAligned: false, foreignDays: 0, trustDays: 5, rsConfirmed: true, market: '上櫃', minMoney: 1, keyword: ' 台 ' }
const m = describeActiveConditions(mix)
ok(m.length === countActiveConditions(mix) && m.includes('強勢雙確認') && m.includes('投信連買 5 天以上') && m.includes('上櫃') && !m.some(x => x.includes('兩個都要')), '混合條件：條數一致、只有一邊籌碼時不寫兩個都要')
console.log(`filters: ${pass} pass, ${fail} fail`)
if (fail) process.exit(1)
