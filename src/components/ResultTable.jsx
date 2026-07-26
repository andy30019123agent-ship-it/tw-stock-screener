import { SearchX } from 'lucide-react'
import Sparkline from './Sparkline'

// 'YYYY-MM-DD' → 'M/D'，法說會徽章用
const mmdd = iso => iso.split('-').slice(1).join('/').replace(/^0/, '').replace('/0', '/')

// 相對強弱：個股近 20 日報酬 － 加權指數近 20 日報酬。正值＝強於大盤（綠），負值＝弱於大盤（紅）。
function RS({ s }) {
  if (s.rs20 == null) return <span className="rs-badge rs-na">RS —</span>
  const pos = s.rs20 > 0
  return (
    <span className={`rs-badge ${pos ? 'rs-pos' : 'rs-neg'}`}>
      RS {pos ? '+' : ''}{s.rs20}%
    </span>
  )
}

// 建立一檔的所有標籤（[文字, class]），桌機與手機共用
function buildTags(s) {
  const tags = []
  if (s.signal_breakout) tags.push(['爆量突破', 'tag-breakout'])
  ;(s.sn_tags || []).forEach(t => tags.push([t, 'tag-shishi']))
  if (s.signal_ma) tags.push(['糾結後多頭', 'tag-signal'])
  else if (s.bull_aligned) tags.push(['多頭排列', 'tag-bull'])
  if (s.golden_cross_recent) tags.push(['黃金交叉', 'tag-gc'])
  if (s.foreign_streak >= 3) tags.push([`外資連買${s.foreign_streak}`, 'tag-foreign'])
  if (s.trust_streak >= 3) tags.push([`投信連買${s.trust_streak}`, 'tag-trust'])
  if (s.undervalued) tags.push(['同業低估', 'tag-value'])
  // 填息：已填息標天數（越少越強）、貼息中標已過幾天。標籤不用漲跌紅綠——
  // 紅綠在這個站只留給漲跌與 RS（MASTER 設計鐵則）。
  if (s.div_fill?.fill_days != null) tags.push([`${s.div_fill.fill_days}天填息`, 'tag-value'])
  else if (s.div_fill?.pending_days != null) tags.push([`貼息${s.div_fill.pending_days}天`, 'tag-value'])
  if (s.holder_rising) tags.push([`千張大戶↑${s.holder_pct}%`, 'tag-holder'])
  if (s.earnings_date) tags.push([`${mmdd(s.earnings_date)}法說會`, 'tag-earnings'])
  return tags
}

// 手機卡片首要「主訊號」：依重要度挑一個技術/估值訊號當頭條
const SIG_PRIORITY = ['tag-breakout', 'tag-signal', 'tag-shishi', 'tag-bull', 'tag-gc', 'tag-value']
function pickPrimary(tags) {
  for (const cls of SIG_PRIORITY) {
    const t = tags.find(([, c]) => c === cls)
    if (t) return t
  }
  return null
}

function Tags({ s }) {
  const tags = buildTags(s)
  return (
    <div className="tags">
      {tags.map(([t, cls]) => <span key={t} className={`tag ${cls}`}>{t}</span>)}
    </div>
  )
}

// 估值：本益比 / 本淨比 / 殖利率（缺值以 — 顯示）
function Valuation({ s }) {
  const g = v => (v === null || v === undefined) ? '—' : v
  return (
    <div className="valuation">
      <span>PE <b>{s.pe > 0 ? s.pe : '—'}</b></span>
      <span>PB <b>{g(s.pb)}</b></span>
      <span>殖 <b className={s.yield_pct >= 5 ? 'hot' : ''}>{s.yield_pct != null ? `${s.yield_pct}%` : '—'}</b></span>
    </div>
  )
}

function SortArrow() {
  return (
    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="sort-arrow">
      <polyline points="6 9 12 15 18 9" />
    </svg>
  )
}

// 表格內行情箭頭一律用 SVG 三角（MASTER 第 4 節第 6 點）：取代原本的 Unicode ↑ 字元
// （字重/對齊會因系統字型飄動，且屬於「emoji/符號當 icon」需要改 SVG 的同一類問題）。
function UpTriangle() {
  return (
    <svg width="9" height="9" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" className="trend-arrow trend-up">
      <polygon points="12 3 22 20 2 20" />
    </svg>
  )
}

export default function ResultTable({ stocks, sortKey, onSort, onPick, dense = true }) {
  // 可排序表頭：th 帶 aria-sort，內含可聚焦按鈕（pe 為升冪，其餘降冪）
  const col = (key, label) => (
    <th className={`sortable ${sortKey === key ? 'active' : ''}`}
      aria-sort={sortKey === key ? (key === 'pe' ? 'ascending' : 'descending') : 'none'}>
      <button type="button" className="th-sort-btn" onClick={() => onSort(key)}>
        {label}{sortKey === key && <SortArrow />}
      </button>
    </th>
  )
  const onRowKey = (e, s) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onPick(s) }
  }

  if (!stocks.length) {
    return (
      <div className="empty">
        <SearchX size={28} strokeWidth={1.5} />
        沒有符合條件的股票，試著放寬條件看看
      </div>
    )
  }

  return (
    <>
      {/* 手機排序改由 sticky 工具列的「排序 ▾」點開選單（見 App.jsx），這裡不再放參差的 pill 列 */}
      {/* 手機：卡片列表 —— 首列代號/價格，第二列 3 個關鍵判斷（RS｜法人連買｜主訊號），估值降級小字 */}
      <div className="card-list">
        {stocks.map((s, i) => {
          const up = s.change >= 0
          const tags = buildTags(s)
          const primary = pickPrimary(tags)
          // 其餘標籤：排除已在第二列呈現的主訊號與法人連買（避免重複）
          const rest = tags.filter(t => t !== primary && t[1] !== 'tag-foreign' && t[1] !== 'tag-trust')
          return (
            <button key={s.id} className={`stock-card ${dense ? 'dense' : ''}`} style={{ '--i': Math.min(i, 12) }}
              onClick={() => onPick(s)}>
              {/* 卡頭：第一行 代號+名稱｜收盤+漲跌；第二行 市場+產業（不再直向堆四行）*/}
              <div className="sc-top">
                <div className="sc-name">
                  <div className="sc-name-1">
                    <span className="sid">{s.id}</span>
                    <span className="sname">{s.name}</span>
                  </div>
                  <div className="sc-name-2">
                    <span className={`smarket ${s.market === '上櫃' ? 'otc' : ''}`}>{s.market}</span>
                    <span className="sindustry">{s.industry}</span>
                  </div>
                </div>
                <div className={`sc-price ${up ? 'up' : 'down'}`}>
                  <span className="close">{s.close}</span>
                  <span className="chg">{up ? '+' : ''}{s.change_pct}%</span>
                </div>
              </div>
              {/* 關鍵資料固定四欄格線：RS｜外資｜投信｜主訊號（多檔沿同一直線比較）*/}
              <div className="sc-key">
                <RS s={s} />
                <span className="sc-col"><span className="k-lbl">外資</span>
                  <b className={s.foreign_streak >= 3 ? 'hot' : ''}>{s.foreign_streak > 0 ? `${s.foreign_streak}天` : '—'}</b></span>
                <span className="sc-col"><span className="k-lbl">投信</span>
                  <b className={s.trust_streak >= 3 ? 'hot' : ''}>{s.trust_streak > 0 ? `${s.trust_streak}天` : '—'}</b></span>
                {primary ? <span className={`tag ${primary[1]}`}>{primary[0]}</span> : <span className="sc-nosig" />}
              </div>
              {/* 走勢線恆留；估值 PE/PB/殖在精簡模式收起（完整模式才顯示）*/}
              <div className="sc-mid">
                <Sparkline data={s.spark} />
                {!dense && <Valuation s={s} />}
              </div>
              {/* 其餘標籤：精簡模式收成「+N 訊號」提示；完整模式全展開 */}
              {rest.length > 0 && (
                dense
                  ? <span className="sc-more">＋{rest.length} 個訊號／估值</span>
                  : <div className="tags">{rest.map(([t, cls]) => <span key={t} className={`tag ${cls}`}>{t}</span>)}</div>
              )}
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
              {col('rs', '相對強弱')}
              {col('yield', '估值 PE/PB/殖利')}
              {col('foreign', '外資連買')}
              {col('trust', '投信連買')}
              <th>訊號</th>
            </tr>
          </thead>
          <tbody>
            {stocks.map((s, i) => {
              const up = s.change >= 0
              return (
                <tr key={s.id} style={{ '--i': Math.min(i, 12) }} onClick={() => onPick(s)}
                  role="button" tabIndex={0} onKeyDown={e => onRowKey(e, s)}
                  aria-label={`${s.id} ${s.name}，開啟 K 線圖`}>
                  <td className="cell-name">
                    <span className="sid">{s.id}</span>
                    <span className="sname">{s.name}</span>
                    <span className={`smarket ${s.market === '上櫃' ? 'otc' : ''}`}>{s.market}</span>
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
                    {s.ma_rising && <span className="ma-up"><UpTriangle />翻揚</span>}
                    <span className="disp">離散 {s.dispersion_pct}%</span>
                  </td>
                  <td className="cell-rs"><RS s={s} /></td>
                  <td className="cell-value"><Valuation s={s} /></td>
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
