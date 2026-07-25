import { useState, useMemo } from 'react'
import { ChevronDown, ChevronRight, Trophy } from 'lucide-react'
import { comboReliability, sigTier, TIER_MARK, OOS_BADGE } from '../lib/oos'

// 組合戰績排行榜：把「多個訊號同時成立」的回測戰績（signal_combos.json）依平均超額排名，
// 讓使用者一眼找到最高勝率的組合；可點策略 chip 篩選只看含該策略的組合；桌機另給熱力圖。
//
// 可靠度標記（Andy 2026-07-25 選「保留全部＋標記不可靠」）：排行榜頂端天生會被「小樣本 ×
// 樣本外撐不住的訊號」佔據（勝率 83% / 樣本 6 筆那種），但**不過濾也不重排**——只把每個成分
// 訊號的樣本外驗證結果標在名稱旁，讓他自己判斷。判準與策略戰績表共用 ../lib/oos。
export default function ComboBoard({ combos, weights = null }) {
  const [open, setOpen] = useState(false)
  const [sel, setSel] = useState([])   // 選中的訊號 → 只看「同時包含這些」的組合

  const list = combos?.combos || []
  // 熱力圖用「完整兩兩配對」（後端另輸出，不會因被高排名 triple 擠出前 N 而缺格）；舊資料沒有時退回從 list 篩
  const pairsList = combos?.pairs || list.filter(c => c.sigs.length === 2)
  const minS = combos?.min_sample || 5

  // 出現在組合/配對裡的所有訊號 → 篩選 chip；label 從資料就地取
  const sigLabel = useMemo(() => {
    const m = {}
    for (const c of [...list, ...pairsList]) c.sigs.forEach((s, i) => { m[s] = c.labels[i] })
    return m
  }, [list, pairsList])
  const allSigs = Object.keys(sigLabel)

  const toggle = s => setSel(x => (x.includes(s) ? x.filter(v => v !== s) : [...x, s]))
  const filtered = sel.length ? list.filter(c => sel.every(s => c.sigs.includes(s))) : list

  // 熱力圖（桌機）：兩兩組合的平均超額矩陣（用完整 pairsList）
  const { axis, pairMap } = useMemo(() => {
    const pm = {}
    pairsList.forEach(c => { pm[[...c.sigs].sort().join('|')] = c })
    const seen = []
    pairsList.flatMap(c => c.sigs).forEach(s => { if (!seen.includes(s)) seen.push(s) })
    return { axis: seen, pairMap: pm }
  }, [pairsList])

  const heatBg = v => {
    if (v == null) return 'transparent'
    const pct = Math.min(80, Math.abs(v) * 22)   // 超額越大顏色越深
    return `color-mix(in srgb, var(${v >= 0 ? '--up' : '--down'}) ${pct}%, transparent)`
  }

  if (!list.length) return null

  return (
    <div className="combo-board">
      <button className="combo-toggle" onClick={() => setOpen(o => !o)} aria-expanded={open}>
        {open ? <ChevronDown size={16} strokeWidth={2} /> : <ChevronRight size={16} strokeWidth={2} />}
        <Trophy size={15} strokeWidth={1.75} />組合戰績排行榜（多個訊號同時成立）
      </button>
      {open && (<>
        <p className="combo-intro">
          「A＋B 同時成立」的歷史戰績，依平均超額由高到低排。點下面的策略可篩選只看含它的組合。
          <b>「穩健下界」欄</b>是樣本數感知的保守估計（樣本少/波動大會被壓低）——<b>平均超額高、但穩健下界也高</b>的才是「又高又穩」；
          若平均超額很高但穩健下界很低甚至負的，多半是小樣本巧合。樣本 &lt;30 標「參考」不隱藏，自行斟酌。
        </p>
        <p className="combo-intro combo-legend">
          <b>成分訊號後面的記號＝該訊號的樣本外驗證結果</b>（滑過/長按看說明）：無記號＝通過驗證；
          <span className="sig-weak">⚠</span> ＝樣本外撐不住（過擬合或大幅縮水）；
          <span className="sig-unknown">?</span> ＝樣本太少還無法判斷。
          「過驗證」欄顯示這個組合有幾個成分通過。<b>排行榜頂端常常是「小樣本 × 帶記號的訊號」堆出來的高勝率</b>，
          不代表未來會重現——這裡不過濾也不重排，資訊都給你，自己斟酌。
        </p>

        <div className="combo-filter">
          {allSigs.map(s => {
            const tm = TIER_MARK[sigTier(weights?.signals?.[s])]
            const st = weights?.signals?.[s]?.oos?.status
            return (
              <button key={s} className={`combo-chip ${sel.includes(s) ? 'on' : ''}`}
                onClick={() => toggle(s)} aria-pressed={sel.includes(s)}
                title={st ? `樣本外驗證：${OOS_BADGE[st]?.[0]}——${OOS_BADGE[st]?.[2]}` : undefined}>
                {sigLabel[s]}{tm && <sup className={tm.cls}>{tm.mark}</sup>}
              </button>
            )
          })}
          {sel.length > 0 && <button className="combo-clear" onClick={() => setSel([])}>清除</button>}
        </div>

        <div className="combo-scroll">
          <table className="combo-table">
            <thead><tr>
              <th>組合</th><th>平均超額</th>
              <th title="樣本數感知的保守下界（平均超額 − 1 標準誤）。樣本越少/越波動壓越低，用來分辨「又高又穩」與「小樣本巧合」">穩健下界</th>
              <th>跑贏率</th><th>樣本</th>
              <th title="這個組合有幾個成分訊號通過樣本外驗證（在沒訓練過的時期也站得住）。分母＝成分數">過驗證</th>
            </tr></thead>
            <tbody>
              {filtered.map(c => {
                const weak = c.samples < 30
                const rel = comboReliability(c.sigs, weights)
                return (
                  <tr key={c.sigs.join('+')} className={rel.overall === 'weak' ? 'combo-unreliable' : ''}>
                    <td className="combo-name">
                      {rel.parts.map((p, i) => {
                        const tm = TIER_MARK[p.tier]
                        return (
                          <span key={p.sig}>
                            {i > 0 && '＋'}
                            {/* combo-sig 必須 nowrap：欄寬被擠窄時中文會逐字斷行，整欄變成一個字寬的直條 */}
                            <span className="combo-sig" title={p.label ? `樣本外驗證：${p.label}——${p.title}` : undefined}>
                              {c.labels[i]}{tm && <sup className={tm.cls}>{tm.mark}</sup>}
                            </span>
                          </span>
                        )
                      })}
                    </td>
                    <td className={c.avg_excess > 0 ? 'good' : c.avg_excess < 0 ? 'bad' : ''}>
                      {c.avg_excess >= 0 ? '+' : ''}{c.avg_excess}pp</td>
                    <td className={`combo-lb ${c.excess_lb > 0 ? 'good' : c.excess_lb < 0 ? 'bad' : ''}`}>
                      {c.excess_lb != null ? `${c.excess_lb >= 0 ? '+' : ''}${c.excess_lb}pp` : '—'}</td>
                    <td>{Math.round(c.excess_win_rate * 100)}%</td>
                    <td className={weak ? 'combo-weak' : ''}>{c.samples}{weak && <small> 參考</small>}</td>
                    <td className={`combo-rel combo-rel-${rel.overall}`}
                      title={rel.parts.map((p, i) => `${c.labels[i]}：${p.label || '無資料'}`).join('\n')}>
                      {rel.pass}/{rel.total}</td>
                  </tr>
                )
              })}
              {!filtered.length && <tr><td colSpan={6} className="combo-empty">這個組合沒有足夠樣本（&lt;{minS} 筆）</td></tr>}
            </tbody>
          </table>
        </div>

        {/* 熱力圖（桌機才顯示）：一眼看哪些兩兩配對最強 */}
        {axis.length >= 2 && (
          <div className="combo-heat-wrap">
            <div className="combo-heat-title">兩兩組合熱力圖（顏色越紅＝平均超額越高）</div>
            <div className="combo-heat-scroll">
              <table className="combo-heat">
                <thead>
                  <tr><th /> {axis.map(s => <th key={s}>{sigLabel[s]}</th>)}</tr>
                </thead>
                <tbody>
                  {axis.map(rs => (
                    <tr key={rs}>
                      <th>{sigLabel[rs]}</th>
                      {axis.map(cs => {
                        if (rs === cs) return <td key={cs} className="heat-diag">—</td>
                        const c = pairMap[[rs, cs].sort().join('|')]
                        const v = c ? c.avg_excess : null
                        return (
                          <td key={cs} style={{ background: heatBg(v) }}
                            title={c ? `${sigLabel[rs]}＋${sigLabel[cs]}：超額 ${v}pp、樣本 ${c.samples}` : '樣本不足'}>
                            {v == null ? '' : v}
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </>)}
    </div>
  )
}
