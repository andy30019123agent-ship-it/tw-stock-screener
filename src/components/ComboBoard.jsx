import { useState, useMemo } from 'react'
import { ChevronDown, ChevronRight, Trophy } from 'lucide-react'

// 組合戰績排行榜：把「多個訊號同時成立」的回測戰績（signal_combos.json）依平均超額排名，
// 讓使用者一眼找到最高勝率的組合；可點策略 chip 篩選只看含該策略的組合；桌機另給熱力圖。
export default function ComboBoard({ combos }) {
  const [open, setOpen] = useState(false)
  const [sel, setSel] = useState([])   // 選中的訊號 → 只看「同時包含這些」的組合

  const list = combos?.combos || []
  const minS = combos?.min_sample || 5

  // 出現在組合裡的所有訊號 → 篩選 chip；label 從組合資料就地取
  const sigLabel = useMemo(() => {
    const m = {}
    for (const c of list) c.sigs.forEach((s, i) => { m[s] = c.labels[i] })
    return m
  }, [list])
  const allSigs = Object.keys(sigLabel)

  const toggle = s => setSel(x => (x.includes(s) ? x.filter(v => v !== s) : [...x, s]))
  const filtered = sel.length ? list.filter(c => sel.every(s => c.sigs.includes(s))) : list

  // 熱力圖（桌機）：兩兩組合的平均超額矩陣
  const { axis, pairMap } = useMemo(() => {
    const pairs = list.filter(c => c.sigs.length === 2)
    const pm = {}
    pairs.forEach(c => { pm[[...c.sigs].sort().join('|')] = c })
    const seen = []
    pairs.flatMap(c => c.sigs).forEach(s => { if (!seen.includes(s)) seen.push(s) })
    return { axis: seen, pairMap: pm }
  }, [list])

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
          <b>樣本少的（&lt;30）只標「參考」不隱藏</b>——組合越多樣本掉越快，高勝率可能只是巧合，自行斟酌。
        </p>

        <div className="combo-filter">
          {allSigs.map(s => (
            <button key={s} className={`combo-chip ${sel.includes(s) ? 'on' : ''}`}
              onClick={() => toggle(s)} aria-pressed={sel.includes(s)}>{sigLabel[s]}</button>
          ))}
          {sel.length > 0 && <button className="combo-clear" onClick={() => setSel([])}>清除</button>}
        </div>

        <div className="combo-scroll">
          <table className="combo-table">
            <thead><tr><th>組合</th><th>平均超額</th><th>跑贏率</th><th>樣本</th></tr></thead>
            <tbody>
              {filtered.map(c => {
                const weak = c.samples < 30
                return (
                  <tr key={c.sigs.join('+')}>
                    <td className="combo-name">{c.labels.join('＋')}</td>
                    <td className={c.avg_excess > 0 ? 'good' : c.avg_excess < 0 ? 'bad' : ''}>
                      {c.avg_excess >= 0 ? '+' : ''}{c.avg_excess}pp</td>
                    <td>{Math.round(c.excess_win_rate * 100)}%</td>
                    <td className={weak ? 'combo-weak' : ''}>{c.samples}{weak && <small> 參考</small>}</td>
                  </tr>
                )
              })}
              {!filtered.length && <tr><td colSpan={4} className="combo-empty">這個組合沒有足夠樣本（&lt;{minS} 筆）</td></tr>}
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
