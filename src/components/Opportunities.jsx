import { useState, useEffect } from 'react'
import { Target, TrendingUp, Calendar, AlertTriangle, ChevronRight, ChevronDown } from 'lucide-react'

// 勝率榜一格：主數字＝平均超額（pp，權重依據），次行＝超額勝率與樣本。
// 樣本不足（validated=false）整格轉灰＋提示，提醒「別信這個數字」；無資料顯示「—」。
function WinCell({ c, minS, active }) {
  const cls = `wq-cell${active ? ' wq-active' : ''}`
  if (!c || !c.samples || c.avg_excess == null) return <td className={`${cls} wq-empty`}>—</td>
  const weak = !c.validated
  const exc = c.avg_excess
  const excCls = weak ? '' : exc > 0 ? 'good' : exc < 0 ? 'bad' : ''
  const wr = c.excess_win_rate != null ? Math.round(c.excess_win_rate * 100) : null
  return (
    <td className={`${cls}${weak ? ' wq-weak' : ''}`}
      title={weak ? `樣本 ${c.samples}，不足 ${minS}，僅供參考` : `超額勝率 ${wr}%、樣本 ${c.samples}`}>
      <span className={`wq-exc ${excCls}`}>{exc >= 0 ? '+' : ''}{exc}<small>pp</small></span>
      <span className="wq-sub">勝 {wr != null ? `${wr}%` : '—'} · {c.samples}</span>
    </td>
  )
}

// 趨勢箭頭：近半年 vs 歷史的平均超額（兩者都要夠樣本才判，否則不顯示，避免拿雜訊嚇人）。
function trendOf(row) {
  const r = row['6m'], h = row['all']
  if (!r?.validated || !h?.validated || r.avg_excess == null || h.avg_excess == null) return null
  const d = r.avg_excess - h.avg_excess
  return d >= 0.1 ? 'up' : d <= -0.1 ? 'down' : 'flat'
}

// 機會股 Top 5 區塊：讀 opportunities.json（跨 repo 契約）＋ scoreboard.json ＋ signal_weights/windows.json。
// 都採「抓不到就靜默省略該部分」，不讓機會股區塊拖垮既有選股頁。
export default function Opportunities({ stocks, onPick, onCount }) {
  const [opp, setOpp] = useState(null)
  const [board, setBoard] = useState(null)
  const [weights, setWeights] = useState(null)
  const [windows, setWindows] = useState(null)   // 多時間窗勝率榜（signal_windows.json）
  const [sortWin, setSortWin] = useState('all')   // 目前聚焦／排序的時間窗欄
  const [showWeights, setShowWeights] = useState(false)
  // 手機預設收合機會股 Top5（省捲動，Andy 2026-07-09 指定）；桌機不顯示收合鈕故恆展開。
  const [open, setOpen] = useState(() => (typeof window !== 'undefined' ? window.innerWidth > 640 : true))

  // 點卡片開 K 線彈窗：優先用 screener.json 的完整資料（欄位齊全），
  // 抓不到（如尚未載入）才用 pick 本身的欄位墊底，讓彈窗至少開得起來。
  const handlePick = p => {
    const full = stocks?.find(s => s.id === p.id)
    onPick?.(full || {
      ...p,
      ma20: p.support_ma20 ?? null,
      change: 0, change_pct: 0,
      foreign_streak: 0, trust_streak: 0,
      avg_vol_lots: null,
    })
  }

  useEffect(() => {
    const base = import.meta.env.BASE_URL
    const grab = (name, set) =>
      fetch(`${base}data/${name}.json`)
        .then(r => (r.ok ? r.json() : null)).then(set).catch(() => set(null))
    grab('opportunities', d => { setOpp(d); onCount?.(d?.picks?.length ?? 0) })
    grab('scoreboard', setBoard)
    grab('signal_weights', setWeights)
    grab('signal_windows', setWindows)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 桌機（≥641px）恆展開：視窗放大到桌機時強制 open=true，避免「手機載入收合→拉大到桌機、
  // 收合鈕被 CSS 藏起卻仍收合」導致桌機看不到機會股。
  useEffect(() => {
    const mq = window.matchMedia('(min-width: 641px)')
    const sync = () => { if (mq.matches) setOpen(true) }
    sync()
    mq.addEventListener('change', sync)
    return () => mq.removeEventListener('change', sync)
  }, [])

  if (!opp || !opp.picks || opp.picks.length === 0) return null

  // 勝率榜（多時間窗）衍生值：優先用 signal_windows.json，缺了才退回舊的單欄 signal_weights.json。
  const win = windows?.signals ? windows : null
  const winCols = win?.windows || []
  const minS = win?.min_sample || weights?.min_sample || 30
  const sortedRows = win
    ? Object.entries(win.signals).slice().sort((a, b) => {
        const av = a[1][sortWin], bv = b[1][sortWin]
        const ax = av?.validated && av.avg_excess != null ? av.avg_excess : -Infinity
        const bx = bv?.validated && bv.avg_excess != null ? bv.avg_excess : -Infinity
        return bx - ax
      })
    : []
  const activeWeights = win
    ? Object.values(win.signals).map(r => ({ label: r.label, w: r.all?.weight || 0 }))
        .filter(x => x.w > 0).sort((a, b) => b.w - a.w)
    : []

  return (
    <section className="opp" data-region="機會股 Top 5">
      <div className="opp-head">
        <div>
          <span className="badge-pill"><Target size={14} strokeWidth={1.75} />今日機會股 Top 5</span>
          <p className="opp-sub">當日有訊號者依「回測權重加總」排序 · 已過濾營收年減／低量 · 僅供參考，非投資建議</p>
        </div>
        <span className="opp-date">{opp.date || '—'}</span>
        <button className="opp-toggle" onClick={() => setOpen(v => !v)}
          aria-expanded={open} aria-label={open ? '收合今日機會股' : '展開今日機會股'}>
          {open ? <ChevronDown size={18} strokeWidth={2} /> : <ChevronRight size={18} strokeWidth={2} />}
          <span>{open ? '收合' : `展開 ${opp.picks.length} 檔`}</span>
        </button>
      </div>

      {open && (<>
      <div className="opp-cards">
        {opp.picks.map((p, i) => {
          const bias = p.support_ma20 ? ((p.close - p.support_ma20) / p.support_ma20 * 100) : null
          return (
            <div className={`opp-card ${i === 0 ? 'opp-card-lead' : ''}`} key={p.id}
              style={{ '--i': Math.min(i, 5) }} onClick={() => handlePick(p)}>
              <div className="opp-card-top">
                <span className="opp-rank">{String(i + 1).padStart(2, '0')}</span>
                <div className="opp-name">
                  <span className="opp-sid">{p.id}</span>
                  <span className="opp-sname">{p.name}</span>
                </div>
                <span className="opp-score" title="回測權重加總">{p.score}<small>分</small></span>
              </div>

              <div className="opp-reasons">
                {(p.reasons || []).map(r => <span className="opp-reason" key={r}>{r}</span>)}
              </div>

              <div className="opp-refs">
                <span>現價 <b>{p.close}</b></span>
                {p.support_ma20 && (
                  <span>MA20 <b>{p.support_ma20}</b>{p.close >= p.support_ma20 ? '撐' : '壓'}</span>
                )}
                {p.recent_high20 && <span>近高 <b>{p.recent_high20}</b></span>}
                {p.rs20 != null && (
                  <span className={`opp-rs ${p.rs20 >= 0 ? 'pos' : 'neg'}`}>
                    RS {p.rs20 >= 0 ? '+' : ''}{p.rs20}
                  </span>
                )}
                {p.revenue_yoy != null && (
                  <span>營收 YoY <b className={p.revenue_yoy >= 0 ? 'good' : ''}>{p.revenue_yoy >= 0 ? '+' : ''}{p.revenue_yoy}%</b></span>
                )}
              </div>

              <div className="opp-flags">
                {p.earnings_date && (
                  <span className="opp-earn"><Calendar size={12} strokeWidth={1.75} />{p.earnings_date.slice(5)} 法說會</span>
                )}
                {(p.risk_flags || []).map(f => (
                  <span className="opp-risk" key={f}><AlertTriangle size={12} strokeWidth={1.75} />{f}</span>
                ))}
                {bias != null && bias <= 15 && bias >= 8 && (
                  <span className="opp-muted">乖離 {bias.toFixed(0)}%</span>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {board && (
        <div className="opp-board">
          <span className="opp-board-title"><TrendingUp size={14} strokeWidth={1.75} />機會股成績單</span>
          {board.samples > 0 ? (
            <div className="opp-board-stats">
              <span>勝率 <b>{Math.round(board.win_rate * 100)}%</b></span>
              <span>平均報酬 <b className={board.avg_ret >= 0 ? 'good' : 'bad'}>{board.avg_ret >= 0 ? '+' : ''}{board.avg_ret}%</b></span>
              <span>樣本 <b>{board.samples}</b></span>
              <span className="opp-muted">（入選後 {board.forward_days} 交易日）</span>
              {board.samples < 20 && <span className="opp-muted">樣本尚少，參考即可</span>}
            </div>
          ) : (
            <span className="opp-muted">樣本累積中——每天留檔，滿 {board.forward_days || 20} 交易日的舊 picks 才計入實績。</span>
          )}
        </div>
      )}

      {(win || weights?.signals) && (
        <div className="opp-weights">
          <button className="opp-weights-toggle" onClick={() => setShowWeights(v => !v)}>
            {showWeights ? <ChevronDown size={14} strokeWidth={2} /> : <ChevronRight size={14} strokeWidth={2} />}
            各訊號回測勝率（權重依據，透明化）
          </button>
          {showWeights && (win ? (
            <div className="opp-weights-body">
              <p className="opp-muted">
                每格＝訊號成立後 {win.forward_days} 交易日的<b>平均超額報酬</b>（減去同日全市場平均，
                衡量「有沒有比隨便買強」）。<b>點欄位標題</b>可切換排序聚焦；↑↓＝近半年比歷史變強／變弱；
                <span className="wq-weak-inline">灰字</span>＝樣本不足 {minS}，僅供參考。
                權重 = 平均超額 ×2 取 1~5（≤0 或樣本不足＝0）。
              </p>
              <div className="opp-weights-scroll">
                <table className="opp-weights-table wq-table">
                  <thead>
                    <tr>
                      <th className="wq-sig">訊號</th>
                      {winCols.map(w => (
                        <th key={w.key} className={`wq-h${sortWin === w.key ? ' wq-active' : ''}`}
                          role="button" tabIndex={0} aria-sort={sortWin === w.key ? 'descending' : 'none'}
                          onClick={() => setSortWin(w.key)}
                          onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSortWin(w.key) } }}>
                          {w.label}{sortWin === w.key && <span className="wq-caret">▾</span>}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {sortedRows.map(([key, row]) => {
                      const t = trendOf(row)
                      return (
                        <tr key={key}>
                          <td className="wq-sig">
                            {row.label}
                            {t && <span className={`wq-trend wq-${t}`} title={
                              t === 'up' ? '近半年比歷史更強' : t === 'down' ? '近半年比歷史轉弱' : '近半年與歷史相當'
                            }>{t === 'up' ? '↑' : t === 'down' ? '↓' : '→'}</span>}
                          </td>
                          {winCols.map(w => (
                            <WinCell key={w.key} c={row[w.key]} minS={minS} active={sortWin === w.key} />
                          ))}
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
              {activeWeights.length > 0 && (
                <p className="opp-muted opp-weights-note">
                  目前機會股引擎採用「歷史」欄權重排序：
                  {activeWeights.map(x => `${x.label} ${x.w}`).join('、')}。
                  其餘（含外資／投信連買、千張大戶、同業低估）平均超額 ≤0 或樣本不足 → 權重 0。
                  回測母體＝約兩年長歷史（{win.as_of} 為止）。
                </p>
              )}
            </div>
          ) : (
            <div className="opp-weights-body">
              <p className="opp-muted">
                回測訊號成立日的下 {weights.forward_days} 交易日報酬，並減去「同一天全市場的平均報酬」
                得到超額報酬——只看有沒有漲，多頭時亂選也會贏，那是大盤的功勞不是訊號的。
                權重 = 平均超額（百分點）×2，取 1~5；平均超額 ≤ 0 或樣本 &lt; {weights.min_sample || 30} 一律 0。
              </p>
              <div className="opp-weights-scroll">
                <table className="opp-weights-table">
                  <thead>
                    <tr><th>訊號</th><th>勝率</th><th>平均報酬</th><th>平均超額</th><th>樣本</th><th>權重</th></tr>
                  </thead>
                  <tbody>
                    {Object.values(weights.signals)
                      .sort((a, b) => b.weight - a.weight || b.samples - a.samples)
                      .map(s => (
                        <tr key={s.label}>
                          <td>{s.label}</td>
                          <td>{s.win_rate != null ? `${Math.round(s.win_rate * 100)}%` : '—'}</td>
                          <td className={s.avg_ret >= 0 ? 'good' : ''}>{s.avg_ret != null ? `${s.avg_ret >= 0 ? '+' : ''}${s.avg_ret}%` : '—'}</td>
                          <td className={s.avg_excess > 0 ? 'good' : ''}>{s.avg_excess != null ? `${s.avg_excess >= 0 ? '+' : ''}${s.avg_excess}pp` : '—'}</td>
                          <td>{s.samples || '—'}</td>
                          <td><b>{s.weight}</b></td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      )}
      </>)}
    </section>
  )
}
