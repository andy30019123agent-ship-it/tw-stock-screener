import { useMemo } from 'react'
import { Target as TargetIcon, CalendarClock, Layers } from 'lucide-react'
import ExitDefense from './ExitDefense'
import { holdUntil, concentration, HOLD_DAYS } from '../lib/position'

// 個股觀察位卡：**近 20 日前高（觀察位）、20 日績效檢視日**
//
// 2026-07-26「誠實化」第一段拿掉：資金配置／波動平價／買幾張／出場價／賺賠空間／持有到期日
// （Andy 明確表示「不用提供給我購買組合，我會自行評估是否買入」）。
// 原因：
//   ・目標價 = 現價 ×(1+13.7%) 那個 13.7% 是「賺的時候」的平均幅度，忽略了虧損事件，
//     不是這檔的預期報酬——已移除，只留 recent_high20 這個事實性的技術觀察位。
//   ・出場價 −15% 原本的驗證腳本不在 repo 裡、無法重現——整欄移除。2026-11-13 出場研究做完（見
//     _reports/研究_出場規則_2026-11-13.md），欄位仍不放回；改在下方收合區照實說明防守價並附各條停損線的代價表。
//   ・買幾張／資金配置屬於「購買組合」，Andy 說會自己評估，不需要系統給。
// 2026-11-13 可讀性改版（審計 A2）：「近 20 日前高（觀察位）」46 列表格在手機上切掉關鍵欄、又長 4 屏，
// 改成每張候選卡上直接寫「近 20 日前高 X，距 +Y%」（同一個 recent_high20、同一個 targetPrice 定義），
// 這裡只留集中度警示、20 日績效檢視日、防守價代價表。

export default function PositionPlan({ picks, dataDate, exitSummary }) {
  const conc = useMemo(() => concentration(picks || []), [picks])
  const until = holdUntil(dataDate)
  if (!picks?.length) return null

  return (
    <section className="pp" data-region="個股觀察位">
      <header className="pp-head">
        <span className="badge-pill"><TargetIcon size={14} strokeWidth={1.75} />持有口徑與停損代價</span>
      </header>

      {conc.warn && (
        <p className="pp-warn">
          <Layers size={15} strokeWidth={2} />
          <span>
            <b>集中度偏高</b>：{picks.length} 檔裡有 {conc.topCount} 檔同屬「{conc.topIndustry}」
            （{Math.round(conc.topRatio * 100)}%）。同產業容易一起漲也一起跌，
            <b>名義上分散 {picks.length} 檔、實際大約只有 {conc.effectiveBets} 個獨立賭注</b>。
          </span>
        </p>
      )}

      <p className="pp-note">
        <CalendarClock size={14} strokeWidth={2} />
        <span>
          <b>20 日績效檢視日：{until || '—'}</b>（訊號日起 {HOLD_DAYS} 個交易日後）。
          這是回測結算的口徑，<b>不是建議賣出日</b>——買不買、抱多久由你決定。
        </span>
      </p>

      {/* 防守價（−15% 與月線取較高者）的照實說明＋各條停損線的代價表：預設收合，不佔首屏。 */}
      <details className="pp-exit">
        <summary>想看「防守價／停損」怎麼看？（歷史上各條停損線的代價）</summary>
        <ExitDefense exitSummary={exitSummary} />
      </details>
    </section>
  )
}
