import { usablePair, verdictOf, pairSentence, pairShort, winDiffText } from '../tierVerdict.js'
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
console.log(`tierVerdict: ${pass} pass, ${fail} fail`)
if (fail) process.exit(1)
