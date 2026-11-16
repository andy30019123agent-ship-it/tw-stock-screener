import { parseHash, tabHash, tabKeyTarget, TAB_KEYS, DEFAULT_TAB } from '../tabs.js'
let pass = 0, fail = 0
const ok = (cond, msg) => { if (cond) { pass++ } else { fail++; console.log('  ❌', msg) } }
const eq = (a, b) => JSON.stringify(a) === JSON.stringify(b)

ok(eq(TAB_KEYS, ['today', 'basis', 'tools']) && DEFAULT_TAB === 'today', '三個分頁、預設今天')
ok(eq(parseHash(''), { route: 'main', tab: 'today' }), '空雜湊 → 今天')
ok(eq(parseHash('#'), { route: 'main', tab: 'today' }), '只有 # → 今天')
ok(eq(parseHash(undefined), { route: 'main', tab: 'today' }) && eq(parseHash(null), { route: 'main', tab: 'today' }), '缺值不炸')
ok(eq(parseHash('#today'), { route: 'main', tab: 'today' }), '#today')
ok(eq(parseHash('#basis'), { route: 'main', tab: 'basis' }), '#basis')
ok(eq(parseHash('#tools'), { route: 'main', tab: 'tools' }), '#tools')
ok(eq(parseHash('tools'), { route: 'main', tab: 'tools' }), '沒有 # 也認得')
ok(eq(parseHash('#help'), { route: 'help', tab: null }), '#help → 使用說明')
ok(eq(parseHash('#help/s2'), { route: 'help', tab: null }), '#help/s2 章節連結 → 使用說明')
ok(parseHash('#helpme').route === 'main' && parseHash('#helpme').tab === 'today', '#helpme 不是說明書 → 今天')
ok(eq(parseHash('#nope'), { route: 'main', tab: 'today' }), '不認得 → 今天')
ok(eq(parseHash('#tools/x'), { route: 'main', tab: 'tools' }), '分頁後面帶東西仍認得分頁')
ok(eq(parseHash('#TOOLS'), { route: 'main', tab: 'today' }), '大小寫不同 → 今天（不猜）')

ok(tabHash('basis') === '#basis' && tabHash('weird') === '#today' && tabHash() === '#today', 'tabHash')

ok(tabKeyTarget('today', 'ArrowRight') === 'basis', '右鍵下一個')
ok(tabKeyTarget('tools', 'ArrowRight') === 'today', '右鍵到底循環回頭')
ok(tabKeyTarget('today', 'ArrowLeft') === 'tools', '左鍵從頭循環到尾')
ok(tabKeyTarget('basis', 'Home') === 'today' && tabKeyTarget('basis', 'End') === 'tools', 'Home／End')
ok(tabKeyTarget('basis', 'Enter') === null && tabKeyTarget('basis', 'a') === null, '其他鍵不處理')
ok(tabKeyTarget('??', 'ArrowRight') === 'basis', '目前值不認得 → 當作第一個')

console.log(`tabs: ${pass} pass, ${fail} fail`)
if (fail) process.exit(1)
