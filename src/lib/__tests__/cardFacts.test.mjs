import { sortRuleText, engineWeightNote, ENGINE_KEYS } from '../cardFacts.js'
let pass = 0, fail = 0
const ok = (cond, msg) => { if (cond) { pass++ } else { fail++; console.log('  ❌', msg) } }

// 排序規則：分數全 0＝照近 60 天漲幅；有人有分數＝先比分數
ok(sortRuleText([{ score: 0 }, { score: 0 }]) === '照近 60 天漲幅由高到低排', '全 0 → 只講 60 天漲幅')
ok(/先照訊號權重分/.test(sortRuleText([{ score: 0 }, { score: 2 }])), '有分數 → 先比權重分')
ok(sortRuleText(null) === '照近 60 天漲幅由高到低排' && sortRuleText([]) === '照近 60 天漲幅由高到低排', '缺資料不 crash')

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
console.log(`cardFacts: ${pass} pass, ${fail} fail`)
if (fail) process.exit(1)
