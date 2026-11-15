// 過關清單卡片（2026-11-16，方向 B 卡片＋方向 C 分頁）的事實組裝。重點是欄位缺漏時的行為：
// 新欄位 fired_labels／rs_pct_120／avg_vol_lots 線上舊資料沒有，必須優雅省略、不得編造。
import { passChecks, strengthLine, cautionList, hasCaution, highGapLine, vsMarketText, GATE_LABELS, MIN_VOL_LOTS } from '../cardFacts.js'
let pass = 0, fail = 0
const ok = (cond, msg) => { if (cond) { pass++ } else { fail++; console.log('  ❌', msg) } }
const eq = (a, b) => JSON.stringify(a) === JSON.stringify(b)
const by = (rows, k) => rows.find(r => r.key === k)

const gate = { signal: 'rs_confirmed_60_120', applied: true, label: '強勢雙確認', reason: 'applied' }

// ── 過關清單：新欄位齊全 ──
const full = { id: '2466', rs_pct_60: 1.0, rs_pct_120: 0.9987, fired_labels: ['千張大戶增加', '破底翻'], avg_vol_lots: 2369.4, revenue_yoy: 54.17 }
const c = passChecks(full, gate)
ok(eq(c.map(r => r.key), ['strong', 'signal', 'volume', 'revenue']), '四關、順序固定')
ok(eq(c.map(r => r.label), [GATE_LABELS.strong, GATE_LABELS.signal, GATE_LABELS.volume, GATE_LABELS.revenue]), '關卡叫法與依據分頁共用 GATE_LABELS')
ok(by(c, 'strong').text === '60 天贏過全市場 100.0%，120 天贏過 99.9%', '強勢雙確認帶 60／120 天實際數字')
ok(by(c, 'signal').text === '千張大戶增加、破底翻', '訊號照 fired_labels 列出')
ok(by(c, 'volume').text === `近 20 日平均 2,369 張（門檻 ${MIN_VOL_LOTS} 張）`, '成交量帶實際張數與門檻')
ok(by(c, 'revenue').text === '營收年增 +54.2%' && by(c, 'revenue').ok === true, '營收年增打勾')
ok(c.every(r => r.ok === true), '全部過關 → 全部打勾')

// ── 過關清單：線上舊資料（沒有三個新欄位） ──
const old = { id: '2466', rs_pct_60: 0.997, revenue_yoy: 8.5 }
const o = passChecks(old, gate)
ok(by(o, 'strong').text === '60 天贏過全市場 99.7%', '沒有 rs_pct_120 → 只寫 60 天')
ok(!by(o, 'signal'), '沒有 fired_labels → 整行不顯示（不重算、不編造）')
ok(by(o, 'volume').text === `近 20 日均量達 ${MIN_VOL_LOTS} 張門檻` && !/\d,?\d* 張（/.test(by(o, 'volume').text), '沒有 avg_vol_lots → 不帶數字')
ok(!by(passChecks({ ...old, fired_labels: [] }, gate), 'signal'), 'fired_labels 空陣列 → 不顯示')
ok(!by(passChecks({ ...old, fired_labels: ['', '  ', null] }, gate), 'signal'), 'fired_labels 全是空值 → 不顯示')
ok(!by(passChecks({ ...old, fired_labels: '破底翻' }, gate), 'signal'), 'fired_labels 不是陣列 → 不當真')
ok(by(passChecks({ ...old, rs_pct_120: null }, gate), 'strong').text === '60 天贏過全市場 99.7%', 'rs_pct_120 null → 只寫 60 天')
ok(by(passChecks({ revenue_yoy: 1 }, gate), 'strong').text.includes('前段'), '連 60 天都沒有 → 不帶數字的說法')
ok(by(passChecks({ ...old, avg_vol_lots: 'x' }, gate), 'volume').text.includes('門檻'), 'avg_vol_lots 不是數字 → 不帶數字')

// ── 營收查不到：中性記號、不打勾 ──
const nr = by(passChecks({ rs_pct_60: 0.9, revenue_yoy: null }, gate), 'revenue')
ok(nr.ok === false && nr.text === '查不到營收資料，沒有因此被刷掉', '營收查不到 → 不打勾、照實說')
ok(by(passChecks({ revenue_yoy: 0 }, gate), 'revenue').ok === true, '年增 0 也算沒衰退')

// ── 門檻 ──
const ng = by(passChecks(old, { ...gate, applied: false, reason: 'pool_too_small' }), 'strong')
ok(ng.ok === false && ng.text.includes('沒套用'), '門檻沒套用 → 不打勾、照實說沒過這一關')
ok(!by(passChecks(old, null), 'strong'), '沒有 gate 資料 → 不寫強勢那一關（不猜）')
ok(by(passChecks(old, { signal: 'x', applied: true, label: '別的門檻' }), 'strong').label === '別的門檻', '換了門檻 → 用資料給的名稱')
ok(eq(passChecks(null, gate), []), '缺 pick → 空')

// ── 強在哪 ──
ok(strengthLine({ tier: 'edge' }) === '成交金額排今天候選前 1/3', '相對優勢才有強在哪')
ok(strengthLine({ tier: 'win' }) && strengthLine({ tier: 'both' }), '舊值 win／both 也是相對優勢')
ok(strengthLine({ tier: null }) === null && strengthLine({ tier: 'return' }) === null && strengthLine(null) === null, '其他候選沒有強在哪')

// ── 要小心＋橘點（同一個判定） ──
ok(eq(cautionList({}), []) && hasCaution({}) === false, '沒有標記 → 不顯示、不畫橘點')
ok(eq(cautionList(null), []) && hasCaution(undefined) === false, '缺值不炸')
ok(eq(cautionList({ risk_flags: ['乖離大'] }), ['乖離大']) && hasCaution({ risk_flags: ['乖離大'] }), '乖離大 → 要小心＋橘點')
ok(eq(cautionList({ risk_flags: ['營收資料缺'] }), ['營收資料缺']), '營收資料缺')
ok(eq(cautionList({ bias_high: true }), ['乖離排前段']), 'bias_high → 乖離排前段')
ok(eq(cautionList({ tier: 'both' }), ['乖離排前段']) && eq(cautionList({ tier: 'return' }), ['乖離排前段']), '舊值 both／return 也算乖離排前段')
ok(eq(cautionList({ tier: 'edge' }), []) && eq(cautionList({ tier: 'win' }), []), '相對優勢本身不是要小心')
ok(eq(cautionList({ earnings_date: '2026-11-18' }), ['法說會將近（11-18）']), '法說會將近帶日期')
ok(eq(cautionList({ rs20: -6.31 }), ['近 20 天輸大盤 6.3 個百分點']), 'rs20 負 → 近 20 天輸大盤')
ok(eq(cautionList({ rs20: 94.3 }), []) && eq(cautionList({ rs20: -0.04 }), []) && eq(cautionList({ rs20: null }), []), 'rs20 正、約 0、缺值 → 不列')
ok(eq(cautionList({ risk_flags: ['乖離大', '乖離大', '', null], bias_high: true, earnings_date: '2026-11-18', rs20: -2 }),
  ['乖離大', '乖離排前段', '法說會將近（11-18）', '近 20 天輸大盤 2.0 個百分點']), '去重、略過空值、順序固定')
ok(eq(cautionList({ risk_flags: '乖離大' }), []), 'risk_flags 不是陣列 → 不當真')
// 不新增門檻：乖離 14%、離前高 50%、營收衰退，但後端沒給旗標 → 前端不自己判斷
ok(hasCaution({ close: 114, support_ma20: 100, recent_high20: 171, revenue_yoy: -1 }) === false, '前端不自己判斷好壞')
ok(hasCaution({ rs20: -1 }) === true, '橘點與要小心同一判定')

// ── 離前高（中性事實） ──
ok(highGapLine(100, 133) === '離近 20 日前高還差 33.0%', '離前高還差')
ok(highGapLine(100, 100) === '已在近 20 日高點' && highGapLine(100, 90) === '已在近 20 日高點', '已在高點')
ok(highGapLine(null, 100) === null && highGapLine(100, undefined) === null, '缺值 → null')

// ── 近 20 天比大盤 ──
ok(eq(vsMarketText(94.26), { word: '多漲', value: '94.3', dir: 'up' }), '正 → 多漲')
ok(eq(vsMarketText(-6.31), { word: '少漲', value: '6.3', dir: 'down' }), '負 → 少漲，數字不帶負號')
ok(vsMarketText(0.04).dir === 'flat' && vsMarketText(null) === null, '約 0／缺值')

ok(!/NaN|undefined|null/.test(JSON.stringify([c, o, ng, nr, cautionList({ earnings_date: '2026-11-18', rs20: -3 })])), '輸出沒有 NaN／undefined／null 字樣')

console.log(`passCard: ${pass} pass, ${fail} fail`)
if (fail) process.exit(1)
