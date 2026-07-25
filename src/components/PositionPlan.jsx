import { useState, useEffect, useMemo } from 'react'
import { Wallet, ShieldAlert, CalendarClock, Layers } from 'lucide-react'
import { volatilityParity, defendPrice, holdUntil, concentration, STOP_PCT, HOLD_DAYS } from '../lib/position'

// 操作卡（Andy 2026-07-25 要求「Top5 卡片變可操作卡」）。
//
// 為什麼需要：站上原本只回答「買哪 5 檔」，但真的要下單還缺三件事——**買多少錢、跌到哪要走、
// 抱到什麼時候**。而且實測 Top5 常出現一張幾十萬甚至 573 萬的股票（緯穎），若標準部位是 20 萬
// 就根本買不了整張，站上卻完全沒提這件事。
//
// 三個刻意的設計決定，都有實測依據：
// 1. **金額用波動平價**而非等額：Top5 的年化波動從 10% 到 132%（中位 59%），等額買
//    等於讓高波動那檔主宰整個組合損益，名義分散但實際沒分散。
// 2. **防守價用 −15% 而不是 −8%**：實測 26,425 筆交易，−8% 會觸發 56% 的交易並砍掉 22% 的
//    「最終漲幅 ≥20%」大贏家；−15% 只砍 5%。這套系統靠少數大贏家撐起整體，停太緊會先砍到它們。
// 3. **顯示同產業集中度**：實測今天 Top5 有 4~5 檔同屬「電腦及週邊設備」，名義 5 檔實際上是
//    同一個賭注下多次。
//
// 預算存 localStorage，預設 20 萬（Andy 的標準部位）。
const BUDGET_KEY = 'tw-screener:budget'
const DEFAULT_BUDGET = 200000
const MIN_BUDGET = 10000
const MAX_BUDGET = 100000000     // 1 億上限：防打錯一個 0 讓整張表變成看不懂的數字

const money = n => (n >= 10000 ? `${Math.round(n / 10000 * 10) / 10} 萬` : `${Math.round(n).toLocaleString()} 元`)

export default function PositionPlan({ picks, dataDate }) {
  const [budget, setBudget] = useState(() => {
    if (typeof localStorage === 'undefined') return DEFAULT_BUDGET
    const v = Number(localStorage.getItem(BUDGET_KEY))
    // 也要 clamp：舊版沒有上限，可能已經存進壞值
    return v > 0 ? Math.min(MAX_BUDGET, Math.max(MIN_BUDGET, v)) : DEFAULT_BUDGET
  })
  useEffect(() => {
    try { localStorage.setItem(BUDGET_KEY, String(budget)) } catch { /* 無痛失敗：隱私模式不能寫 */ }
  }, [budget])

  const plan = useMemo(() => volatilityParity(picks || [], budget), [picks, budget])
  const conc = useMemo(() => concentration(picks || []), [picks])
  const until = holdUntil(dataDate)
  if (!picks?.length) return null

  // 兩個不同概念，講的時候不能混（第一版混了會出現「4 檔超過預算」但 5 列都寫「買不到整張」）：
  //   noLot     ＝ 用**配置到的金額**買不到一張（配置只有幾萬，通常整批都是）
  //   overBudget＝ 一張的價格連**整個總預算**都不夠（真正貴到不合理的那種）
  const noLot = plan.filter(p => p.lots < 1).length
  const overBudget = plan.filter(p => !p.affordable).length

  return (
    <section className="pp" data-region="操作計畫">
      <header className="pp-head">
        <span className="badge-pill"><Wallet size={14} strokeWidth={1.75} />怎麼下單</span>
        <label className="pp-budget">
          這批總預算
          {/* onFocus 全選：手機上點進來多半是想「換一個數字」，不全選的話新輸入會接在舊值後面
              變成天文數字（實測打 1000000 接在 200000 後面 → 顯示「248245.9 萬」）。
              上限 1 億：不是限制誰，是避免打錯一個 0 就讓整張表的金額變成看不懂的數字。 */}
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
      </header>

      {conc.warn && (
        <p className="pp-warn">
          <Layers size={15} strokeWidth={2} />
          <span>
            <b>集中度偏高</b>：{picks.length} 檔裡有 {conc.topCount} 檔同屬「{conc.topIndustry}」
            （{Math.round(conc.topRatio * 100)}%）。同產業個股容易一起漲也一起跌，
            <b>名義上分散 {picks.length} 檔、實際大約只有 {conc.effectiveBets} 個獨立賭注</b>。
            要真的分散，考慮自己換掉幾檔或降低這批的總金額。
          </span>
        </p>
      )}

      <div className="pp-scroll">
        <table className="pp-table">
          <thead><tr>
            <th>個股</th>
            <th title="按波動度反向配置：波動大的少買，讓每檔對組合的風險貢獻接近">建議金額</th>
            <th title="用建議金額除以股價；台股一張＝1000 股，不足一張就是買零股">可買</th>
            <th title={`防守價＝收盤 −${STOP_PCT * 100}% 與 20 日均線取較高者。刻意不用 −8%：實測那會砍掉 22% 的大贏家`}>防守價</th>
            <th title="年化已實現波動度，越高代表價格擺動越大">波動</th>
          </tr></thead>
          <tbody>
            {picks.map((p, i) => {
              const a = plan[i]
              const d = defendPrice(p)
              return (
                <tr key={p.id}>
                  <td className="pp-name">{p.id} {p.name}</td>
                  <td>{money(a.amount)}<small>（{Math.round(a.share * 100)}%）</small></td>
                  <td className={a.affordable ? '' : 'pp-odd'}>
                    {a.lots >= 1
                      ? <>{Math.floor(a.lots)} 張<small>（一張 {money(a.lotPrice)}）</small></>
                      : <>{a.shares} 股
                        {/* 區分兩種「買不到整張」：配置金額不夠（正常，分散的必然結果）
                            vs 一張連總預算都不夠（這檔對這個資金規模來說太貴） */}
                        <small>{a.affordable
                          ? `零股（一張 ${money(a.lotPrice)}，配置金額不足一張）`
                          : `零股｜一張 ${money(a.lotPrice)} 超過總預算`}</small></>}
                  </td>
                  <td>
                    {d ? <>{d.suggested}<small>{d.usedMa ? '月線' : `−${STOP_PCT * 100}%`}</small></> : '—'}
                  </td>
                  <td className={p.rv20_pct > 90 ? 'pp-hot' : ''}>{p.rv20_pct != null ? `${p.rv20_pct}%` : '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <p className="pp-note">
        <CalendarClock size={14} strokeWidth={2} />
        <span>
          <b>建議持有到 {until || '—'}</b>（{HOLD_DAYS} 個交易日後）——所有戰績都是用「固定持有 {HOLD_DAYS} 個交易日」
          結算的，提早賣或抱更久都不在回測範圍內。
          {noLot > 0 && (
            <> 這批 {picks.length} 檔裡有 <b>{noLot} 檔要買零股</b>——把 {money(budget)} 分散到 {picks.length} 檔後，
              每檔只有幾萬元，買不到一張（1000 股）。
              {overBudget > 0 && <> 其中 <b>{overBudget} 檔更是「一張的錢連你的總預算都不夠」</b>
                （最貴的一張要 {money(Math.max(...plan.map(p => p.lotPrice || 0)))}）。</>}
              零股手續費通常有最低收費，金額小的時候成本占比會拉高，下單前確認。</>
          )}
        </span>
      </p>
      <p className="pp-note pp-note-warn">
        <ShieldAlert size={14} strokeWidth={2} />
        <span>
          防守價刻意<b>放寬到 −{STOP_PCT * 100}%</b>而不是常見的 −8%：實測 26,425 筆歷史交易，
          −8% 會觸發 <b>56%</b> 的交易、並砍掉 <b>22%</b> 的「最終漲幅 ≥20%」大贏家；−15% 只砍掉 5%。
          這套系統靠少數大贏家撐起整體報酬，<b>停損太緊會先把它們砍掉</b>。
          金額與防守價都是參考，不是投資建議。
        </span>
      </p>
    </section>
  )
}
