import { useMemo } from 'react'
import { Target as TargetIcon, CalendarClock, Layers } from 'lucide-react'
import { targetPrice, holdUntil, concentration, HOLD_DAYS } from '../lib/position'

// 個股觀察位卡：**近 20 日前高（觀察位）、20 日績效檢視日**
//
// 2026-07-26「誠實化」第一段拿掉：資金配置／波動平價／買幾張／出場價／賺賠空間／持有到期日
// （Andy 明確表示「不用提供給我購買組合，我會自行評估是否買入」）。
// 原因：
//   ・目標價 = 現價 ×(1+13.7%) 那個 13.7% 是「賺的時候」的平均幅度，忽略了虧損事件，
//     不是這檔的預期報酬——已移除，只留 recent_high20 這個事實性的技術觀察位。
//   ・出場價 −15% 的驗證腳本不在 repo 裡、無法重現，Phase 3 會用逐日 OHLC 重做，
//     在那之前不掛結論性文案——整欄移除。
//   ・買幾張／資金配置屬於「購買組合」，Andy 說會自己評估，不需要系統給。
const pctOf = v => `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`

export default function PositionPlan({ picks, dataDate }) {
  const conc = useMemo(() => concentration(picks || []), [picks])
  const until = holdUntil(dataDate)
  if (!picks?.length) return null

  return (
    <section className="pp" data-region="個股觀察位">
      <header className="pp-head">
        <span className="badge-pill"><TargetIcon size={14} strokeWidth={1.75} />近 20 日前高（觀察位）</span>
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

      <div className="pp-scroll">
        <table className="pp-table">
          <thead><tr>
            <th>個股</th>
            <th>現價</th>
            <th title="近 20 日內的最高價——單純的技術觀察位，不是預期報酬，也不是投資建議">近 20 日前高（觀察位）</th>
          </tr></thead>
          <tbody>
            {picks.map(p => {
              const t = targetPrice(p)
              return (
                <tr key={p.id}>
                  <td className="pp-name">{p.id} {p.name}</td>
                  <td>{p.close ?? '—'}</td>
                  <td className="pp-target">
                    {t ? <>{t.high}<small>距現價 {pctOf(t.upsidePct)}</small></> : '—'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <p className="pp-note">
        <CalendarClock size={14} strokeWidth={2} />
        <span>
          <b>20 日績效檢視日：{until || '—'}</b>（訊號日起 {HOLD_DAYS} 個交易日後）。
          這是回測結算的口徑，<b>不是建議賣出日</b>——買不買、抱多久由你決定。
        </span>
      </p>
    </section>
  )
}
