// 過關清單卡片（2026-11-16，方向 B 卡片＋方向 C 分頁）的事實組裝。重點是欄位缺漏時的行為：
// 新欄位 fired_labels／rs_pct_120／avg_vol_lots 線上舊資料沒有，必須優雅省略、不得編造。
import {
  passChecks, edgeLine, EDGE_TEXT, cautionList, riskDotMarks, hasRiskDot, highGapLine, vsMarketText, beatText,
  GATE_LABELS, MIN_VOL_LOTS, RS_STRONG_PCT, RS_CONFIRM_120_PCT,
} from '../cardFacts.js'
let pass = 0, fail = 0
const ok = (cond, msg) => { if (cond) { pass++ } else { fail++; console.log('  ❌', msg) } }
const eq = (a, b) => JSON.stringify(a) === JSON.stringify(b)
const by = (rows, k) => rows.find(r => r.key === k)

const gate = { signal: 'rs_confirmed_60_120', applied: true, label: '強勢雙確認', reason: 'applied' }

// ── 贏過全市場 X ──
ok(beatText(0.997) === '99.7%' && beatText(0.8) === '80.0%', '一位小數')
ok(beatText(1) === '99.9% 以上' && beatText(0.9996) === '99.9% 以上' && beatText(1.3) === '99.9% 以上', '會變成 100.0% 的一律寫 99.9% 以上')
ok(beatText(0.9994) === '99.9%', '99.94 → 99.9%')
ok(beatText(null) === null && beatText(NaN) === null, '缺值 → null')

// ── 過關清單：新欄位齊全 ──
const full = { id: '2466', rs_pct_60: 1.0, rs_pct_120: 0.9987, fired_labels: ['千張大戶增加', '破底翻'], avg_vol_lots: 2369.4, revenue_yoy: 54.17 }
const c = passChecks(full, gate)
ok(eq(c.map(r => r.key), ['strong', 'signal', 'volume', 'revenue']), '四關、順序固定')
ok(eq(c.map(r => r.label), [GATE_LABELS.strong, GATE_LABELS.signal, GATE_LABELS.volume, GATE_LABELS.revenue]), '關卡叫法與依據分頁共用 GATE_LABELS')
ok(by(c, 'strong').text === '60 天贏過全市場 99.9% 以上（門檻 80%），120 天贏過 99.9%（門檻 70%）', '強勢雙確認帶 60／120 天實際數字與門檻、不印 100%')
ok(RS_STRONG_PCT === 0.8 && RS_CONFIRM_120_PCT === 0.7, '門檻常數')
ok(by(c, 'signal').text === '千張大戶增加、破底翻', '訊號照 fired_labels 列出')
ok(by(c, 'volume').text === `近 20 日平均 2,369 張（門檻 ${MIN_VOL_LOTS} 張）`, '成交量帶實際張數與門檻')
ok(by(c, 'revenue').text === '營收年增 +54.2%' && by(c, 'revenue').ok === true, '營收年增打勾')
ok(c.every(r => r.ok === true), '全部過關 → 全部打勾')

// ── 過關清單：線上舊資料（沒有三個新欄位） ──
const old = { id: '2466', rs_pct_60: 0.997, revenue_yoy: 8.5 }
const o = passChecks(old, gate)
ok(by(o, 'strong').text === '60 天贏過全市場 99.7%（門檻 80%）', '沒有 rs_pct_120 → 只寫 60 天')
ok(!by(o, 'signal'), '沒有 fired_labels → 整行不顯示（不重算、不編造）')
ok(by(o, 'volume').text === `近 20 日均量達 ${MIN_VOL_LOTS} 張門檻`, '沒有 avg_vol_lots → 不帶數字')
ok(o.length === 3, '舊資料只有 3 行')
ok(!by(passChecks({ ...old, fired_labels: [] }, gate), 'signal'), 'fired_labels 空陣列 → 不顯示')
ok(!by(passChecks({ ...old, fired_labels: ['', '  ', null] }, gate), 'signal'), 'fired_labels 全是空值 → 不顯示')
ok(!by(passChecks({ ...old, fired_labels: '破底翻' }, gate), 'signal'), 'fired_labels 不是陣列 → 不當真')
ok(by(passChecks({ ...old, rs_pct_120: null }, gate), 'strong').text === '60 天贏過全市場 99.7%（門檻 80%）', 'rs_pct_120 null → 只寫 60 天')
ok(by(passChecks({ revenue_yoy: 1 }, gate), 'strong').text.includes('前段'), '連 60 天都沒有 → 不帶數字的說法')
ok(by(passChecks({ ...old, avg_vol_lots: 'x' }, gate), 'volume').text.includes('門檻'), 'avg_vol_lots 不是數字 → 不帶數字')

// ── 營收 ──
const nr = by(passChecks({ rs_pct_60: 0.9, revenue_yoy: null }, gate), 'revenue')
ok(nr.ok === false && nr.text === '查不到營收資料，沒有因此被刷掉', '營收查不到 → 不打勾、照實說')
ok(by(passChecks({ revenue_yoy: 0 }, gate), 'revenue').ok === true, '年增 0 也算沒衰退')
const neg = by(passChecks({ revenue_yoy: -3 }, gate), 'revenue')
ok(neg.ok === false && neg.text === '營收年增 −3.0%', '年增為負（不該出現）→ 不打勾，數字照實寫')

// ── 門檻 ──
const ng = by(passChecks(old, { ...gate, applied: false, reason: 'pool_too_small' }), 'strong')
ok(ng.ok === false && ng.text.includes('沒套用'), '門檻沒套用 → 不打勾、照實說沒過這一關')
ok(!by(passChecks(old, null), 'strong'), '沒有 gate 資料 → 不寫強勢那一關（不猜）')
const other = by(passChecks(old, { signal: 'x', applied: true, label: '別的門檻' }), 'strong')
ok(other.label === '別的門檻' && !other.text.includes('門檻 80%'), '換了門檻 → 用資料給的名稱、不套強勢雙確認的門檻數字')
ok(eq(passChecks(null, gate), []), '缺 pick → 空')

// ── 相對優勢一行 ──
ok(edgeLine({ tier: 'edge' }) === EDGE_TEXT && EDGE_TEXT === '成交金額排今天候選前 1/3', '相對優勢才有')
ok(edgeLine({ tier: 'win' }) && edgeLine({ tier: 'both' }), '舊值 win／both 也是相對優勢')
ok(edgeLine({ tier: null }) === null && edgeLine({ tier: 'return' }) === null && edgeLine(null) === null, '其他候選沒有')

// ── 橘點：只看硬狀況（risk_flags＋法說會將近） ──
ok(eq(riskDotMarks({}), []) && hasRiskDot({}) === false, '沒有標記 → 不畫')
ok(eq(riskDotMarks(null), []) && hasRiskDot(undefined) === false, '缺值不炸')
ok(hasRiskDot({ risk_flags: ['乖離大'] }) && hasRiskDot({ risk_flags: ['營收資料缺'] }), 'risk_flags（乖離大、營收資料缺）→ 橘點')
ok(eq(riskDotMarks({ earnings_date: '2026-11-18' }), ['法說會將近（11-18）']), '法說會將近（有日期就算，沿用舊規則）→ 橘點')
ok(hasRiskDot({ rs20: -6.3 }) === false, '近 20 天輸大盤 → 不觸發橘點')
ok(hasRiskDot({ bias_high: true }) === false && hasRiskDot({ tier: 'both' }) === false, '乖離排前段 → 不觸發橘點')
ok(eq(riskDotMarks({ risk_flags: ['乖離大', '乖離大', '', null], earnings_date: '2026-11-18', rs20: -2, bias_high: true }), ['乖離大', '法說會將近（11-18）']), '去重、略過空值、只列硬狀況')
ok(eq(riskDotMarks({ risk_flags: '乖離大' }), []), 'risk_flags 不是陣列 → 不當真')
ok(hasRiskDot({ close: 114, support_ma20: 100, recent_high20: 171, revenue_yoy: -1 }) === false, '前端不自己判斷好壞')

// ── 卡片「要小心」 ──
ok(eq(cautionList({}), []) && eq(cautionList(null), []), '沒有 → 空')
ok(eq(cautionList({ risk_flags: ['乖離大'] }), ['乖離大']), '乖離大')
ok(eq(cautionList({ risk_flags: ['營收資料缺'] }), []), '營收資料缺不重複列（過關清單已講）')
ok(hasRiskDot({ risk_flags: ['營收資料缺'] }) === true, '但營收資料缺仍觸發橘點')
ok(eq(cautionList({ bias_high: true }), ['乖離排前段']), '只有乖離排前段 → 列')
ok(eq(cautionList({ risk_flags: ['乖離大'], bias_high: true }), ['乖離大']), '同時有乖離大 → 不再列乖離排前段')
ok(eq(cautionList({ tier: 'both' }), ['乖離排前段']) && eq(cautionList({ tier: 'return' }), ['乖離排前段']), '舊值 both／return 也算乖離排前段')
ok(eq(cautionList({ tier: 'edge' }), []), '相對優勢本身不是要小心')
ok(eq(cautionList({ earnings_date: '2026-11-18' }), ['法說會將近（11-18）']), '法說會將近帶日期')
ok(eq(cautionList({ rs20: -6.31 }), ['近 20 天輸大盤 6.3 個百分點']), 'rs20 負 → 近 20 天輸大盤（保留在要小心）')
ok(eq(cautionList({ rs20: 94.3 }), []) && eq(cautionList({ rs20: -0.04 }), []) && eq(cautionList({ rs20: null }), []), 'rs20 正、約 0、缺值 → 不列')
ok(eq(cautionList({ risk_flags: ['乖離大', '營收資料缺'], bias_high: true, earnings_date: '2026-11-18', rs20: -2 }),
  ['乖離大', '法說會將近（11-18）', '近 20 天輸大盤 2.0 個百分點']), '組合：去重後順序固定')

// ── 離前高（中性事實） ──
ok(highGapLine(100, 133) === '離近 20 日前高還差 33.0%', '離前高還差')
ok(highGapLine(100, 100) === '已在近 20 日高點' && highGapLine(100, 90) === '已在近 20 日高點', '已在高點')
ok(highGapLine(null, 100) === null && highGapLine(100, undefined) === null, '缺值 → null')

// ── 近 20 天比大盤 ──
ok(eq(vsMarketText(94.26), { word: '多漲', value: '94.3', dir: 'up' }), '正 → 多漲')
ok(eq(vsMarketText(-6.31), { word: '少漲', value: '6.3', dir: 'down' }), '負 → 少漲，數字不帶負號')
ok(vsMarketText(0.04).dir === 'flat' && vsMarketText(null) === null, '約 0／缺值')

ok(!/NaN|undefined|null/.test(JSON.stringify([c, o, ng, nr, neg, cautionList({ earnings_date: '2026-11-18', rs20: -3 })])), '輸出沒有 NaN／undefined／null 字樣')

console.log(`passCard: ${pass} pass, ${fail} fail`)
if (fail) process.exit(1)
