import Sparkline from './Sparkline'

function Tags({ s }) {
  const tags = []
  if (s.signal_ma) tags.push(['✨ 糾結後多頭', 'tag-signal'])
  else if (s.bull_aligned) tags.push(['多頭排列', 'tag-bull'])
  if (s.golden_cross_recent) tags.push(['黃金交叉', 'tag-gc'])
  if (s.foreign_streak >= 3) tags.push([`外資連買${s.foreign_streak}`, 'tag-foreign'])
  if (s.trust_streak >= 3) tags.push([`投信連買${s.trust_streak}`, 'tag-trust'])
  return (
    <div className="tags">
      {tags.map(([t, cls]) => <span key={t} className={`tag ${cls}`}>{t}</span>)}
    </div>
  )
}

export default function ResultTable({ stocks, sortKey, onSort, onPick }) {
  const col = (key, label) => (
    <th className={`sortable ${sortKey === key ? 'active' : ''}`} onClick={() => onSort(key)}>
      {label}{sortKey === key ? ' ▾' : ''}
    </th>
  )

  if (!stocks.length) {
    return <div className="empty">沒有符合條件的股票，試著放寬條件看看 🔍</div>
  }

  return (
    <div className="table-wrap">
      <table className="result-table">
        <thead>
          <tr>
            <th>股票</th>
            {col('change', '收盤 / 漲跌')}
            <th>走勢</th>
            <th>均線狀態</th>
            {col('foreign', '外資連買')}
            {col('trust', '投信連買')}
            <th>訊號</th>
          </tr>
        </thead>
        <tbody>
          {stocks.map(s => {
            const up = s.change >= 0
            return (
              <tr key={s.id} onClick={() => onPick(s)}>
                <td className="cell-name">
                  <span className="sid">{s.id}</span>
                  <span className="sname">{s.name}</span>
                  <span className="sindustry">{s.industry}</span>
                </td>
                <td className={`cell-price ${up ? 'up' : 'down'}`}>
                  <span className="close">{s.close}</span>
                  <span className="chg">{up ? '+' : ''}{s.change_pct}%</span>
                </td>
                <td><Sparkline data={s.spark} /></td>
                <td className="cell-ma">
                  {s.bull_aligned ? <span className="ma-bull">多頭排列</span>
                    : <span className="ma-flat">—</span>}
                  {s.ma_rising && <span className="ma-up">↑翻揚</span>}
                  <span className="disp">離散 {s.dispersion_pct}%</span>
                </td>
                <td className="cell-streak">{s.foreign_streak > 0
                  ? <b className={s.foreign_streak >= 3 ? 'hot' : ''}>{s.foreign_streak} 天</b> : '—'}</td>
                <td className="cell-streak">{s.trust_streak > 0
                  ? <b className={s.trust_streak >= 3 ? 'hot' : ''}>{s.trust_streak} 天</b> : '—'}</td>
                <td><Tags s={s} /></td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
