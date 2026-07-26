import { defendPrice, holdUntil, concentration, STOP_PCT, targetPrice } from '../position.js'
let pass = 0, fail = 0
const ok = (cond, msg) => { if (cond) { pass++ } else { fail++; console.log('  ❌', msg) } }

// 2026-07-26 誠實化：volatilityParity（資金配置／買幾張）與 TARGET_PCT（統計目標）已從
// position.js 移除（Andy 說不用購買組合，13.7% 目標幅度忽略虧損事件、會誤導）。
// 對應的測試一併拿掉，不留對已刪除 export 的斷言。

// 防守價：−15% 與月線取較高者（計算邏輯保留供 Phase 3 參考，未在畫面上呈現）
const d1 = defendPrice({ close: 100, ma20: 95 })
ok(d1.stop === 85 && d1.suggested === 95 && d1.usedMa === true, '月線 95 在現價下且比停損近 → 用月線')
const d2 = defendPrice({ close: 100, ma20: 70 })
ok(d2.suggested === 85 && d2.usedMa === false, '月線太遠 → 用固定 −15%')
// 🔴 2026-07-25 迴歸測試：月線**高於現價**時不可當停損（實測全市場 76% 的股票處於月線下）
const d3 = defendPrice({ close: 100, ma20: 110 })
ok(d3.suggested === 85 && d3.usedMa === false, '月線高於現價 → 退回固定停損，不可產生高於現價的停損')
ok(d3.downsidePct < 0, 'downsidePct 一律為負（到防守價的跌幅）')
ok(d3.belowMa20 === true, '現價在月線下要標記（趨勢轉弱警訊）')
const d4 = defendPrice({ close: 100, ma20: 100 })
ok(d4.suggested === 85 && d4.usedMa === false, '月線等於現價 → 不採用（沒有下方空間）')
// 浮點運算（85/100−1）×100 = −15.000000000000002，不可用嚴格相等
ok(Math.abs(defendPrice({ close: 100 }).downsidePct + 15) < 1e-9, '無月線 → 固定 −15%')
ok(defendPrice({ close: 0 }) === null, '無效價格回 null')
ok(STOP_PCT === 0.15, '停損預設 15%（⚠️ 2026-07-26：舊「實測 8% 會砍掉 22% 大贏家」的驗證腳本不在 repo、無法重現，Phase 3 待重做）')

// 持有到期：只數交易日
// 🔴 2026-07-25 修正：原本斷言 07-30 / 08-20 是**錯的**——我當時「手算驗證」自己數錯，
// 而程式又有時區 bug（本地遞增、UTC 輸出，台北會倒退一天），兩個錯誤剛好抵銷所以測試綠。
// 正解（Python datetime 獨立驗算）：2026-07-24 是週五 → 往後 5 個交易日＝7/27,28,29,30,31 → **07-31**。
ok(holdUntil('2026-07-24', 5) === '2026-07-31', '5 個交易日後（跳過週末）')
ok(holdUntil('2026-07-24', 20) === '2026-08-21', '20 個交易日後')
// 跨月、跨週末邊界
ok(holdUntil('2026-07-31', 1) === '2026-08-03', '週五 +1 交易日 → 下週一（跨月）')
ok(holdUntil('2026-07-25', 1) === '2026-07-27', '週六 +1 交易日 → 下週一')
ok(holdUntil('2026-12-31', 1) === '2027-01-01', '跨年')
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

// ── 近 20 日前高（觀察位，2026-07-25 加，2026-07-26 拿掉統計目標只留前高）─────────────────────────────
{
  // 尚未突破前高 → 回傳前高與距離
  const t1 = targetPrice({ close: 100, recent_high20: 105 })
  ok(t1.high === 105, '前高 105 → 回傳前高')
  ok(Math.abs(t1.upsidePct - 5) < 1e-9, '距現價 5%')
  // 已突破前高 → 沒有觀察位可用，回傳 null
  const t2 = targetPrice({ close: 100, recent_high20: 98 })
  ok(t2 === null, '已突破前高（現價 ≥ 前高）→ 沒有觀察位，回傳 null')
  const t3 = targetPrice({ close: 100, recent_high20: 200 })
  ok(t3.high === 200 && Math.abs(t3.upsidePct - 100) < 1e-9, '前高很遠也照實呈現，不做「先到哪個」的目標邏輯')
  ok(targetPrice({ close: 0 }) === null, '無效價格回 null')
  console.log(`近 20 日前高（觀察位）: 追加 4 項斷言`)
}

console.log(`\nposition.js: ${pass} 通過, ${fail} 失敗`)
process.exit(fail ? 1 : 0)
