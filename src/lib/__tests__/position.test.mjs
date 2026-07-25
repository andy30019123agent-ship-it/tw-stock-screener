import { volatilityParity, defendPrice, holdUntil, concentration, LOT, STOP_PCT } from '../position.js'
let pass = 0, fail = 0
const ok = (cond, msg) => { if (cond) { pass++ } else { fail++; console.log('  ❌', msg) } }

// 波動平價：波動大的應該配到較少錢
const picks = [
  { id: 'A', close: 100, rv20_pct: 30, industry: '半導體' },
  { id: 'B', close: 100, rv20_pct: 90, industry: '半導體' },
]
const alloc = volatilityParity(picks, 200000)
ok(alloc[0].amount > alloc[1].amount, '低波動應配到更多錢')
ok(Math.abs(alloc.reduce((s, a) => s + a.amount, 0) - 200000) < 1, '總額應等於預算')
// clamp 之後還要正規化成總和 1，所以兩檔時不可能都落在 0.08~0.40（一檔 0.40 → 另一檔 0.60）。
// 真正要驗的性質是「極端波動差不會把某檔壓到趨近 0」：
const ext = volatilityParity([{ id: 'L', close: 100, rv20_pct: 10 }, { id: 'H', close: 100, rv20_pct: 130 }], 100000)
ok(Math.min(...ext.map(a => a.share)) >= 0.08, '極端波動差時最小配置仍不低於下限')
ok(Math.abs(ext.reduce((s2, a) => s2 + a.share, 0) - 1) < 1e-9, 'share 總和應為 1')

// 買不起一張的情境（緯穎 5730 → 一張 573 萬）
const rich = volatilityParity([{ id: 'W', close: 5730, rv20_pct: 76 }], 200000)
ok(rich[0].affordable === false, '一張 573 萬、預算 20 萬 → affordable=false')
ok(rich[0].lots < 1 && rich[0].shares > 0, '買不到整張但可買零股')
ok(rich[0].lotPrice === 5730 * LOT, '一張價格計算正確')

// 缺波動資料 → 用中位數替代，不給極端權重
const noVol = volatilityParity([{ id: 'X', close: 50 }, { id: 'Y', close: 50, rv20_pct: 60 }], 100000)
ok(Math.abs(noVol[0].amount - noVol[1].amount) < 1, '缺波動資料應與 fallback 同權重')

// 防守價：−15% 與月線取較高者
const d1 = defendPrice({ close: 100, ma20: 95 })
ok(d1.stop === 85 && d1.suggested === 95 && d1.usedMa === true, '月線 95 > 停損 85 → 用月線')
const d2 = defendPrice({ close: 100, ma20: 70 })
ok(d2.suggested === 85 && d2.usedMa === false, '月線太遠 → 用固定 −15%')
ok(defendPrice({ close: 0 }) === null, '無效價格回 null')
ok(STOP_PCT === 0.15, '停損預設 15%（實測 8% 會砍掉 22% 的大贏家）')

// 持有到期：只數交易日
// 2026-07-24 是週五 → 下週一(27)…週四(30) 共 5 個交易日（7/25、7/26 是週末要跳過）
ok(holdUntil('2026-07-24', 5) === '2026-07-30', '5 個交易日後（跳過週末）')
ok(holdUntil('2026-07-24', 20) === '2026-08-20', '20 個交易日後（手算驗證過）')
ok(holdUntil(null) === null, '無日期回 null')

// 集中度
const c = concentration([
  { industry: '電腦及週邊設備' }, { industry: '電腦及週邊設備' },
  { industry: '電腦及週邊設備' }, { industry: '電腦及週邊設備' }, { industry: '鋼鐵' },
])
ok(c.topRatio === 0.8 && c.warn === true, '5 檔裡 4 檔同產業 → 應警示')
ok(c.effectiveBets < 5, '有效獨立注數應小於名義檔數')
const c2 = concentration([{ industry: 'A' }, { industry: 'B' }, { industry: 'C' }])
ok(c2.warn === false, '產業分散 → 不警示')

console.log(`\nposition.js: ${pass} 通過, ${fail} 失敗`)
process.exit(fail ? 1 : 0)
