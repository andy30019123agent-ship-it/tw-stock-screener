import Sparkline from './Sparkline'

function Tags({ s }) {
  const tags = []
  if (s.signal_breakout) tags.push(['🚀爆量突破', 'tag-breakout'])
  if (s.signal_ma) tags.push(['糾結後多頭', 'tag-signal'])
  else if (s.bull_aligned) tags.push(['多頭排列', 'tag-bull'])
  if (s.golden_cross_recent) tags.push(['黃金交叉', 'tag-gc'])
  if (s.foreign_streak >= 3) tags.push([`外資連買${s.foreign_streak}`, 'tag-foreign'])
  if (s.trust_streak >= 3) tags.push([`投信連買${s.trust_streak}`, 'tag-trust'])
  if (s.holder_rising) tags.push([`千張大戶↑${s.holder_pct}%`, 'tag-holder'])
  return (
    <div className="tags">
      {tags.map(([t, cls]) => <span key={t} className={`tag ${cls}`}>{t}</span>)}
    </div>
  )
}

const MOBILE_SORTS = [
  ['signal', '訊號'],
  ['breakout', '突破'],
  ['change', '漲跌幅'],
  ['foreign', '外資'],
  ['trust', '投信'],
]

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
    <>
      {/* 手機：排序列 */}
      <div className="sort-bar">
        <span className="sort-bar-label">排序</span>
        {MOBILE_SORTS.map(([key, label]) => (
          <button key={key} className={`sort-chip ${sortKey === key ? 'on' : ''}`}
            onClick={() => onSort(key)}>{label}</button>
        ))}
      </div>

      {/* 手機：卡片列表 */}
      <div className="card-list">
        {stocks.map((s, i) => {
          const up = s.change >= 0
          return (
            <button key={s.id} className="stock-card" style={{ '--i': Math.min(i, 12) }}
              onClick={() => onPick(s)}>
              <div className="sc-top">
                <div className="sc-name">
                  <span className="sid">{s.id}</span>
                  <span className="sname">{s.name}</span>
                  <span className="sindustry">{s.industry}</span>
                </div>
                <div className={`sc-price ${up ? 'up' : 'down'}`}>
                  <span className="close">{s.close}</span>
                  <span className="chg">{up ? '+' : ''}{s.change_pct}%</span>
                </div>
              </div>
              <div className="sc-mid">
                <Sparkline data={s.spark} />
                <div className="sc-streaks">
                  <span>外資 <b className={s.foreign_streak >= 3 ? 'hot' : ''}>
                    {s.foreign_streak > 0 ? `${s.foreign_streak}天` : '—'}</b></span>
                  <span>投信 <b className={s.trust_streak >= 3 ? 'hot' : ''}>
                    {s.trust_streak > 0 ? `${s.trust_streak}天` : '—'}</b></span>
                </div>
              </div>
              <Tags s={s} />
            </button>
          )
        })}
      </div>

      {/* 桌機：表格 */}
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
            {stocks.map((s, i) => {
              const up = s.change >= 0
              return (
                <tr key={s.id} style={{ '--i': Math.min(i, 12) }} onClick={() => onPick(s)}>
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
    </>
  )
}
