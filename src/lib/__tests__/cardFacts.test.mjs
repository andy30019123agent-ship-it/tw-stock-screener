import { readFileSync } from 'node:fs'
import { sortRuleText, engineWeightNote, ENGINE_KEYS, MIN_VOL_LOTS, engineWeightsAllZero, RS_STRONG_PCT, RS_CONFIRM_120_PCT, MAIN_LIST_N, splitMain, smallPoolText } from '../cardFacts.js'
let pass = 0, fail = 0
const ok = (cond, msg) => { if (cond) { pass++ } else { fail++; console.log('  ❌', msg) } }

// 排序規則：分數全 0＝照近 60 天漲幅；有人有分數＝先比分數
ok(sortRuleText([{ score: 0 }, { score: 0 }]) === '照近 60 天漲幅由高到低排', '全 0 → 只講 60 天漲幅')
ok(/先照訊號權重分/.test(sortRuleText([{ score: 0 }, { score: 2 }])), '有分數 → 先比權重分')
ok(sortRuleText(null) === '照近 60 天漲幅由高到低排' && sortRuleText([]) === '照近 60 天漲幅由高到低排', '缺資料不 crash')
// 2026-11-16 起相對優勢排前面：今天有分類才講「先排成交熱絡的」
ok(sortRuleText([{ score: 0, tier: 'edge' }, { score: 0 }]) === '先排成交熱絡的，再比 60 天強弱', '有相對優勢 → 先排成交熱絡的')
ok(sortRuleText([{ score: 2, tier: 'edge' }, { score: 0 }]) === '先比訊號權重分，同分先排成交熱絡的，再比 60 天強弱', '有分數＋相對優勢')
ok(sortRuleText([{ score: 0 }, { score: 0, tier: 'edge' }]) === '照近 60 天漲幅由高到低排', '舊資料（相對優勢沒排在前面）→ 不可宣稱先排成交熱絡的')

// 主名單切段：前 main_n 檔、其餘收進其他候選；舊資料沒有 main_n 用前端常數
const ps = Array.from({ length: 25 }, (_, i) => ({ id: String(i) }))
const s1 = splitMain(ps, 20)
ok(s1.main.length === 20 && s1.other.length === 5 && s1.other[0].id === '20', 'main_n=20 切 20／5')
const s2 = splitMain(ps, undefined)
ok(s2.main.length === MAIN_LIST_N && s2.other.length === 25 - MAIN_LIST_N, '缺 main_n → 前端常數')
ok(splitMain(ps.slice(0, 3), 20).other.length === 0 && splitMain(null, 20).main.length === 0, '不足 20 檔、缺資料不 crash')
ok(splitMain(ps, 0).main.length === MAIN_LIST_N && splitMain(ps, 'x').main.length === MAIN_LIST_N, '壞值 → 前端常數')

// 弱勢日一句話
const sp = { applied: true, reason: 'applied_small_pool' }
ok(smallPoolText(sp, 3) === '今天強勢股太少，只有 3 檔過關', 'N=3')
ok(smallPoolText(sp, 0) === '今天沒有股票過關', 'N=0')
ok(smallPoolText({ applied: true, reason: 'applied' }, 30) === null && smallPoolText(null, 3) === null
  && smallPoolText({ applied: false, reason: 'pool_too_small' }, 3) === null, '其他情況不顯示')

// 權重表下的說明（G4）：rs_* 有權重但不在計分名單
const rows = [
  { key: 'rs_confirmed_60_120', label: '強勢雙確認', w: 1 },
  { key: 'rs_strong_60', label: '強勢股60日', w: 1 },
  { key: 'sn_break_low_recover', label: '破底翻', w: 0 },
]
const n0 = engineWeightNote(rows)
ok(n0.includes(`只算 ${ENGINE_KEYS.length} 種`) && n0.includes('權重全部是 0') && n0.includes('照近 60 天漲幅排'), '引擎訊號全 0 → 照實說')
ok(n0.includes('強勢雙確認 1、強勢股60日 1 雖然有權重，但不在計分名單裡') && n0.includes('強勢雙確認是入場門檻'), 'rs_* 不得被說成排序用')
ok(!/採用.*排序：強勢股60日/.test(n0), '舊錯句不再出現')
const n1 = engineWeightNote([{ key: 'signal_breakout', label: '爆量突破', w: 3 }, ...rows])
ok(n1.includes('目前有權重的是：爆量突破 3') && !n1.includes('權重全部是 0'), '引擎訊號有權重 → 列出')
ok(!/NaN|undefined|null/.test(n0 + n1 + engineWeightNote(null)), '輸出沒有 NaN／undefined')
ok(ENGINE_KEYS.length === 11 && ENGINE_KEYS.every(k => !k.startsWith('rs_')), '計分名單 11 種且不含 rs_*（對照 pipeline/backtest_signals.py ENGINE_SIGNALS）')

// ENGINE_KEYS／MIN_VOL_LOTS 是抄自 pipeline 的：直接讀 .py 對照，pipeline 改了這裡就會紅
const py = name => readFileSync(new URL(`../../../pipeline/${name}`, import.meta.url), 'utf8')
const bt = py('backtest_signals.py')
const m = bt.match(/^ENGINE_SIGNALS\s*=\s*\[([\s\S]*?)\]/m)
const pyKeys = m ? [...m[1].matchAll(/"([^"]+)"/g)].map(x => x[1]) : []
ok(pyKeys.length > 0, '解析得到 ENGINE_SIGNALS')
ok(JSON.stringify([...pyKeys].sort()) === JSON.stringify([...ENGINE_KEYS].sort()), 'ENGINE_KEYS 與 pipeline ENGINE_SIGNALS 完全相同')
const mv = py('opportunities.py').match(/^MIN_VOL_LOTS\s*=\s*(\d+)/m)
ok(mv && Number(mv[1]) === MIN_VOL_LOTS, 'MIN_VOL_LOTS 與 pipeline/opportunities.py 相同')
const mn = py('opportunities.py').match(/^MAIN_LIST_N\s*=\s*(\d+)/m)
ok(mn && Number(mn[1]) === MAIN_LIST_N, 'MAIN_LIST_N 與 pipeline/opportunities.py 相同')
// 強勢雙確認兩個門檻（卡片過關清單會印出來）
const rs = bt.match(/^RS_STRONG_PCT\s*=\s*([\d.]+)/m), rc = bt.match(/^RS_CONFIRM_120_PCT\s*=\s*([\d.]+)/m)
ok(rs && Number(rs[1]) === RS_STRONG_PCT, 'RS_STRONG_PCT 與 pipeline/backtest_signals.py 相同')
ok(rc && Number(rc[1]) === RS_CONFIRM_120_PCT, 'RS_CONFIRM_120_PCT 與 pipeline/backtest_signals.py 相同')

ok(engineWeightsAllZero({ signal_ma: { weight: 0 }, signal_breakout: { weight: 0 }, rs_strong_60: { weight: 1 } }) === true, '引擎訊號全 0（rs_* 不算）→ true')
ok(engineWeightsAllZero({ signal_ma: { weight: 2 } }) === false, '有權重 → false')
ok(engineWeightsAllZero(null) === null && engineWeightsAllZero({}) === null, '缺資料 → null')
console.log(`cardFacts: ${pass} pass, ${fail} fail`)
if (fail) process.exit(1)
