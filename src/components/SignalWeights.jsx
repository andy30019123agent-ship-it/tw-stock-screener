import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { engineWeightNote } from '../lib/cardFacts'

// 各訊號回測戰績（權重依據，透明化）。2026-11-16 三分頁改版：從 Opportunities 原樣搬到「工具」分頁，
// 內容與行為不變（預設收合、點欄位標題切換排序聚焦）。

// 勝率榜一格：主數字＝平均超額（單位個百分點，權重依據），次行＝超額勝率與樣本。
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
      <span className={`wq-exc ${excCls}`}>{exc >= 0 ? '+' : ''}{exc}</span>
      <span className="wq-sub">贏大盤 {wr != null ? `${wr}%` : '—'} · {c.samples}</span>
    </td>
  )
}

// 趨勢符號：SVG 三角（取代 Unicode ↑↓→，MASTER 第 4 節第 6 點——表格內行情箭頭一律用 SVG）。
function TrendGlyph({ t }) {
  if (t === 'flat') return <span className="wq-trend-flat" aria-hidden="true">─</span>
  return (
    <svg width="9" height="9" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      {t === 'up' ? <polygon points="12 3 22 20 2 20" /> : <polygon points="12 21 2 4 22 4" />}
    </svg>
  )
}

// 趨勢箭頭：近半年 vs 歷史的平均超額（兩者都要夠樣本才判，否則不顯示，避免拿雜訊嚇人）。
function trendOf(row) {
  const r = row['6m'], h = row['all']
  if (!r?.validated || !h?.validated || r.avg_excess == null || h.avg_excess == null) return null
  const d = r.avg_excess - h.avg_excess
  return d >= 0.1 ? 'up' : d <= -0.1 ? 'down' : 'flat'
}

export default function SignalWeights({ windows, weights }) {
  const [sortWin, setSortWin] = useState('all')   // 目前聚焦／排序的時間窗欄
  const [showWeights, setShowWeights] = useState(false)
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
  const weightRows = win
    ? Object.entries(win.signals).map(([key, r]) => ({ key, label: r.label, w: r.all?.weight || 0 }))
        .sort((a, b) => b.w - a.w)
    : []
  if (!(win || weights?.signals)) return null
  return (
        <div className="opp-weights">
          <button className="opp-weights-toggle" onClick={() => setShowWeights(v => !v)} aria-expanded={showWeights}>
            {showWeights ? <ChevronDown size={16} strokeWidth={2} /> : <ChevronRight size={16} strokeWidth={2} />}
            各訊號回測戰績（權重依據，透明化）
          </button>
          {showWeights && (win ? (
            <div className="opp-weights-body">
              <p className="opp-muted">
                每格＝訊號成立後 {win.forward_days} 交易日的<b>平均超額報酬</b>（單位：個百分點；減去同日全市場平均，
                衡量「有沒有比隨便買強」）。<b>點欄位標題</b>可切換排序聚焦；三角形＝近半年比歷史變強／變弱；
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
                            }><TrendGlyph t={t} /></span>}
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
              {weightRows.length > 0 && (
                <p className="opp-muted opp-weights-note">
                  {engineWeightNote(weightRows)}
                  回測母體＝約兩年長歷史（{win.as_of} 為止）。
                </p>
              )}
            </div>
          ) : (
            <div className="opp-weights-body">
              <p className="opp-muted">
                回測訊號成立日的下 {weights.forward_days} 交易日報酬，並減去「同一天全市場的平均報酬」
                得到超額報酬——只看有沒有漲，多頭時亂選也會贏，那是大盤的功勞不是訊號的。
                權重 = 平均超額（個百分點）×2，取 1~5；平均超額 ≤ 0 或樣本 &lt; {weights.min_sample || 30} 一律 0。
              </p>
              <div className="opp-weights-scroll">
                <table className="opp-weights-table">
                  <thead>
                    <tr><th>訊號</th><th>賺錢機率</th><th>平均報酬</th><th>平均超額（個百分點）</th><th>樣本</th><th>權重</th></tr>
                  </thead>
                  <tbody>
                    {Object.values(weights.signals)
                      .sort((a, b) => b.weight - a.weight || b.samples - a.samples)
                      .map(s => (
                        <tr key={s.label}>
                          <td>{s.label}</td>
                          <td>{s.win_rate != null ? `${Math.round(s.win_rate * 100)}%` : '—'}</td>
                          <td className={s.avg_ret >= 0 ? 'good' : ''}>{s.avg_ret != null ? `${s.avg_ret >= 0 ? '+' : ''}${s.avg_ret}%` : '—'}</td>
                          <td className={s.avg_excess > 0 ? 'good' : ''}>{s.avg_excess != null ? `${s.avg_excess >= 0 ? '+' : ''}${s.avg_excess}` : '—'}</td>
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
  )
}
