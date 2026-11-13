import { usablePair, verdictOf, pairSentence, pairShort, winDiffText, evDiffText, evVerdictOf, edgeSentence, edgeWinRateText, staleText, gateNote, biasNote, normalizeTier } from '../tierVerdict.js'
let pass = 0, fail = 0
const ok = (cond, msg) => { if (cond) { pass++ } else { fail++; console.log('  ❌', msg) } }
const P = (win, wci, ev, eci) => ({ win_pp: win, win_ci90: wci, ev_pp: ev, ev_ci90: eci })

ok(verdictOf([0.1, 5]) === 'better', 'CI 下限>0 → better')
ok(verdictOf([-0.3, 5]) === 'nodiff', 'CI 跨 0 → nodiff')
ok(verdictOf([-5, -0.1]) === 'worse', 'CI 上限<0 → worse')
ok(verdictOf([0, 5]) === 'nodiff', 'CI 下限剛好 0 不算 better')
ok(verdictOf(null) === null && verdictOf([1]) === null && verdictOf([NaN, 1]) === null, '壞 CI → null')

const good = { paired: { a: P(7.8, [4.2, 11.3], 2.5, [0.7, 4.3]), b: P(1.6, [-0.6, 4.1], 0.8, [-0.5, 2.1]), nul: null, bad: { win_pp: NaN, win_ci90: [1, 2] } } }
ok(/比較常賺/.test(pairShort(good.paired.a, 'X')), 'better 短句')
ok(/量不出差別/.test(pairShort(good.paired.b, 'X')) && !/比較常賺/.test(pairShort(good.paired.b, 'X')), 'nodiff 短句不說比較常賺')
ok(/高約 7\.8/.test(pairSentence(good.paired.a, 'X')), '長句帶數字')
ok(usablePair(good, 'nul') === null && usablePair(good, 'bad') === null && usablePair(good, 'missing') === null, 'null／NaN／缺 key → null')
ok(usablePair({ ...good, stale: true }, 'a') === null, 'stale → null（中性句）')
ok(usablePair(null, 'a') === null && usablePair({}, 'a') === null, '整份缺 → null')
ok(winDiffText(null) === null && pairSentence(undefined, 'X') === null && pairShort(null, 'X') === null, 'null 輸入不 crash')
const none = [pairSentence(good.paired.b, 'X'), pairShort(good.paired.b, 'X'), winDiffText(good.paired.a)].join('')
ok(!/NaN|undefined|null/.test(none), '輸出沒有 NaN／undefined')

// ── 2026-11-13 分類簡化：主訊息、幅度保守說法、門檻退回、stale、舊值相容 ──
const TS = {
  date: '2026-11-13', stale: false,
  categories: { edge: { win_rate: 0.471 }, rest: { win_rate: 0.43 } },
  paired: {
    cat_edge_vs_rest: P(6.3, [3.1, 9.4], 1.9, [0.6, 3.3]),
    bias_high_vs_rest: P(0.4, [-1.8, 2.6], 0.5, [-0.8, 1.7]),
  },
  by_gate: { fallback: { categories: { edge: { win_rate: 0.388 }, rest: { win_rate: 0.427 } } } },
}
ok(edgeSentence(TS) === '同一天的候選裡，相對優勢這群比其他候選的賺錢機率多約 6.3 個百分點（誤差範圍 3.1～9.4），平均每筆也多約 1.9 個百分點（誤差範圍 0.6～3.3）', '主訊息句（與 TG 逐字同）：' + edgeSentence(TS))
ok(edgeWinRateText(TS) === '但單檔賺錢機率只有 47.1%，不到一半', '單檔不到一半')
ok(/過半也不代表穩賺/.test(edgeWinRateText({ categories: { edge: { win_rate: 0.512 } } })) && !/不到一半/.test(edgeWinRateText({ categories: { edge: { win_rate: 0.512 } } })), '過半照實講')
ok(evVerdictOf([0.2, 2]) === 'marginal' && evVerdictOf([0.5, 2]) === 'better', 'CI 下限 <0.5 → marginal')
ok(/略高約 1\.0 個百分點，但接近量不出（誤差範圍 0\.2～2\.0）/.test(evDiffText(P(1, [1, 2], 1.0, [0.2, 2.0]))), '保守說法帶誤差範圍')
ok(/量不出差別（差 \+1\.2 個百分點，誤差範圍 −0\.8～3\.0）/.test(edgeSentence({ paired: { cat_edge_vs_rest: P(1.2, [-0.8, 3.0], 0.4, [-0.9, 1.5]) } })), 'CI 跨 0 → 量不出、負號用 −')
ok(edgeSentence({ ...TS, stale: true }) === null && edgeWinRateText({ ...TS, stale: true }) === null, 'stale → 不引用數字')
ok(staleText({ ...TS, stale: true, date: '2026-11-06' }) === '統計已過期（上次成功重算 2026-11-06）' && staleText(TS) === null, 'stale 字樣帶上次成功日期')
ok(edgeSentence({}) === null && edgeSentence(null) === null && edgeSentence({ paired: { cat_edge_vs_rest: { win_pp: null } } }) === null, '缺欄位 → null')
ok(/曾經相反（相對優勢賺錢機率 38\.8%、其他候選 42\.7%）/.test(gateNote({ applied: false, reason: 'pool_too_small' }, TS)), '門檻退回日提醒讀 by_gate')
ok(gateNote({ applied: true }, TS) === null && gateNote(null, TS) === null, '門檻有套用 → 不提醒')
ok(!/%/.test(gateNote({ applied: false, reason: 'pool_too_small' }, {})), 'by_gate 缺 → 不印數字')
ok(/量不出比較常賺或賺比較多/.test(biasNote(TS)) && /不代表比較好/.test(biasNote(null)), '乖離排前段說明')
ok(normalizeTier({ tier: 'both' }).tier === 'edge' && normalizeTier({ tier: 'both' }).biasHigh, '舊 both → 相對優勢＋乖離排前段')
ok(normalizeTier({ tier: 'win' }).tier === 'edge' && !normalizeTier({ tier: 'win' }).biasHigh, '舊 win → 相對優勢')
ok(normalizeTier({ tier: 'return' }).tier === null && normalizeTier({ tier: 'return' }).biasHigh, '舊 return → 無分類＋乖離排前段')
ok(normalizeTier({ tier: 'xx' }).tier === null && normalizeTier(null).tier === null && normalizeTier({}).biasHigh === false, '未知值／null 不 crash')
ok(/^1\.3$|^1\.2$/.test('1.3') && edgeSentence({ paired: { cat_edge_vs_rest: P(1.25, [0.25, 2.25], 0, null) } }).includes('多約 1.3 個百分點（誤差範圍 0.3～2.3）'), '四捨五入規則固定 floor(x*10+0.5)')
const all = [edgeSentence(TS), edgeWinRateText(TS), gateNote({ applied: false, reason: 'pool_too_small' }, TS), biasNote(TS)].join('')
ok(!/NaN|undefined|null|雙優|勝率偏優|報酬偏優|保證/.test(all), '輸出沒有 NaN／舊稱號／保證')
console.log(`tierVerdict: ${pass} pass, ${fail} fail`)
if (fail) process.exit(1)
