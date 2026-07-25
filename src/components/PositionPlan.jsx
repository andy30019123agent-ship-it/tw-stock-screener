import { useState, useEffect, useMemo } from 'react'
import { Target as TargetIcon, ShieldAlert, CalendarClock, Layers } from 'lucide-react'
import {
  volatilityParity, defendPrice, targetPrice, holdUntil, concentration,
  STOP_PCT, HOLD_DAYS, TARGET_PCT, TYPICAL_DRAWDOWN_PCT,
} from '../lib/position'

// 操作計畫卡：**目標價、出場價、持有到期日**
// （Andy 2026-07-25：「先不用管 20 萬這件事 但可以提供給我建議的目標價與出場價」）
//
// 每個價位都標明「根據什麼算的」，不給沒有依據的神奇數字：
//   目標價 = ①統計目標：現價 ×(1+13.7%)——實測持有 20 交易日「賺的時候」的平均幅度
//            ②技術目標：近 20 日高點（壓力位）；兩者取**先到**的那個
//   出場價 = 現價 −15% 與 20 日均線的較高者。刻意不用 −8%：實測那會砍掉 22% 的大贏家
//   到期日 = 20 個交易日後（回測就是這樣結算的，所以這才是「戰績成立的前提」）
//
// 金額配置（波動平價）保留但收進 details——Andy 說先不管預算，所以不再用它當主軸。
const BUDGET_KEY = 'tw-screener:budget'
const DEFAULT_BUDGET = 200000
const MIN_BUDGET = 10000
const MAX_BUDGET = 100000000     // 1 億上限：防打錯一個 0 讓整張表變成看不懂的數字

const money = n => (n >= 10000 ? `${Math.round(n / 10000 * 10) / 10} 萬` : `${Math.round(n).toLocaleString()} 元`)
const pctOf = v => `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`

export default function PositionPlan({ picks, dataDate }) {
  const [budget, setBudget] = useState(() => {
    if (typeof localStorage === 'undefined') return DEFAULT_BUDGET
    const v = Number(localStorage.getItem(BUDGET_KEY))
    // 也要 clamp：舊版沒有上限，可能已經存進壞值
    return v > 0 ? Math.min(MAX_BUDGET, Math.max(MIN_BUDGET, v)) : DEFAULT_BUDGET
  })
  useEffect(() => {
    try { localStorage.setItem(BUDGET_KEY, String(budget)) } catch { /* 隱私模式不能寫，無痛失敗 */ }
  }, [budget])

  const plan = useMemo(() => volatilityParity(picks || [], budget), [picks, budget])
  const conc = useMemo(() => concentration(picks || []), [picks])
  const until = holdUntil(dataDate)
  if (!picks?.length) return null

  return (
    <section className="pp" data-region="操作計畫">
      <header className="pp-head">
        <span className="badge-pill"><TargetIcon size={14} strokeWidth={1.75} />目標價與出場價</span>
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
            <th title={`統計目標＝現價 ×(1+${(TARGET_PCT * 100).toFixed(1)}%)，那是實測「持有 20 交易日、賺的時候」的平均幅度；若近 20 日高點更近，就先看那個壓力位`}>目標價</th>
            <th title={`出場價＝現價 −${STOP_PCT * 100}% 與 20 日均線取較高者。刻意不用 −8%：實測那會觸發 56% 的交易並砍掉 22% 的大贏家`}>出場價</th>
            <th title="到目標價的距離 ÷ 到出場價的距離。大於 1 代表上方空間比下方風險大">賺賠空間</th>
          </tr></thead>
          <tbody>
            {picks.map(p => {
              const t = targetPrice(p)
              const d = defendPrice(p)
              const up = t?.upsidePct ?? 0
              const down = d ? Math.abs(d.downsidePct) : 0
              const rr = down > 0 ? up / down : null
              return (
                <tr key={p.id}>
                  <td className="pp-name">{p.id} {p.name}</td>
                  <td>{p.close ?? '—'}</td>
                  <td className="pp-target">
                    {t ? <>{t.first}<small>{t.firstIsHigh ? `前高 ${pctOf(up)}` : `統計 ${pctOf(up)}`}</small></> : '—'}
                  </td>
                  <td className="pp-stop">
                    {d ? <>{d.suggested}<small>{d.usedMa ? `月線 ${pctOf(d.downsidePct)}` : `−${STOP_PCT * 100}%`}</small></> : '—'}
                  </td>
                  {/* <1 在這個系統裡是常態（目標用前高、出場用月線，前高通常更近），
                      所以只在「明顯偏低」時才標色——否則整欄都是警示色，等於沒有訊息量。 */}
                  <td className={rr != null && rr < 0.5 ? 'pp-odd' : ''}>
                    {rr != null ? `${rr.toFixed(2)} : 1` : '—'}
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
          <b>建議持有到 {until || '—'}</b>（{HOLD_DAYS} 個交易日後）。
          所有戰績都是用「固定持有 {HOLD_DAYS} 個交易日」結算的——提早賣或抱更久都不在回測範圍。
          三個出場條件<b>先到哪個算哪個</b>：碰到目標價、跌破出場價、或到期。
        </span>
      </p>

      <p className="pp-note pp-note-warn">
        <ShieldAlert size={14} strokeWidth={2} />
        <span>
          <b>中途會先虧錢是正常的</b>：實測持有 {HOLD_DAYS} 交易日期間，
          <b>平均最多會先虧 {(TYPICAL_DRAWDOWN_PCT * 100).toFixed(1)}%</b>——<b>即使最後是賺的</b>。
          這就是為什麼出場價設在 −{STOP_PCT * 100}% 而不是 −8%：實測 −8% 會觸發 56% 的交易、
          並砍掉 <b>22% 的「最終漲幅 ≥20%」大贏家</b>；−15% 只砍掉 5%。
          這套系統靠少數大贏家撐起整體，<b>停損太緊會先把它們砍掉</b>。
          目標價與出場價都是歷史統計的參考位，不是投資建議。
        </span>
      </p>

      <details className="pp-money">
        <summary>要算金額配置的話（選用）</summary>
        <label className="pp-budget">
          這批總預算
          <input type="number" inputMode="numeric" min={MIN_BUDGET} max={MAX_BUDGET} step={10000}
            value={budget}
            onFocus={e => e.target.select()}
            onChange={e => {
              const v = Number(e.target.value)
              if (!Number.isFinite(v) || v <= 0) return setBudget(DEFAULT_BUDGET)
              setBudget(Math.min(MAX_BUDGET, Math.max(MIN_BUDGET, v)))
            }} />
          元
        </label>
        <div className="pp-scroll">
          <table className="pp-table pp-table-money">
            <thead><tr>
              <th>個股</th>
              <th title="按波動度反向配置：波動大的少買，讓每檔對組合的風險貢獻接近">建議金額</th>
              <th>可買</th>
              <th>波動</th>
            </tr></thead>
            <tbody>
              {picks.map((p, i) => {
                const a = plan[i]
                return (
                  <tr key={p.id}>
                    <td className="pp-name">{p.id} {p.name}</td>
                    <td>{money(a.amount)}<small>（{Math.round(a.share * 100)}%）</small></td>
                    <td>{a.lots >= 1
                      ? <>{Math.floor(a.lots)} 張</>
                      : <>{a.shares} 股<small>零股（一張 {money(a.lotPrice)}）</small></>}</td>
                    <td className={p.rv20_pct > 90 ? 'pp-hot' : ''}>{p.rv20_pct != null ? `${p.rv20_pct}%` : '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  )
}
