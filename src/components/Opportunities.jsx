import { useState, useEffect } from 'react'
import { Target, TrendingUp, Calendar, AlertTriangle, ChevronRight, ChevronDown } from 'lucide-react'

// 機會股 Top 5 區塊：讀 opportunities.json（跨 repo 契約）＋ scoreboard.json ＋ signal_weights.json。
// 三者都採「抓不到就靜默省略該部分」，不讓機會股區塊拖垮既有選股頁。
export default function Opportunities({ stocks, onPick, onCount }) {
  const [opp, setOpp] = useState(null)
  const [board, setBoard] = useState(null)
  const [weights, setWeights] = useState(null)
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

      {weights?.signals && (
        <div className="opp-weights">
          <button className="opp-weights-toggle" onClick={() => setShowWeights(v => !v)}>
            {showWeights ? <ChevronDown size={14} strokeWidth={2} /> : <ChevronRight size={14} strokeWidth={2} />}
            各訊號回測勝率（權重依據，透明化）
          </button>
          {showWeights && (
            <div className="opp-weights-body">
              <p className="opp-muted">
                回測「訊號成立日的下 {weights.forward_days} 交易日報酬 &gt; 0」的勝率；
                權重 = max(0, round((勝率−0.5)×20))，樣本 &lt; {weights.min_sample || 30} 用預設 1。
              </p>
              <div className="opp-weights-scroll">
                <table className="opp-weights-table">
                  <thead>
                    <tr><th>訊號</th><th>勝率</th><th>平均報酬</th><th>樣本</th><th>權重</th></tr>
                  </thead>
                  <tbody>
                    {Object.values(weights.signals)
                      .sort((a, b) => b.weight - a.weight || b.samples - a.samples)
                      .map(s => (
                        <tr key={s.label}>
                          <td>{s.label}</td>
                          <td>{s.win_rate != null ? `${Math.round(s.win_rate * 100)}%` : '—'}</td>
                          <td className={s.avg_ret >= 0 ? 'good' : ''}>{s.avg_ret != null ? `${s.avg_ret >= 0 ? '+' : ''}${s.avg_ret}%` : '—'}</td>
                          <td>{s.samples || '—'}</td>
                          <td><b>{s.weight}</b></td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
              <p className="opp-muted opp-weights-note">
                註：外資／投信連買、千張大戶、同業低估屬「當下籌碼/估值快照」，缺逐日歷史 → 樣本不足、暫用預設權重 1。
              </p>
            </div>
          )}
        </div>
      )}
      </>)}
    </section>
  )
}
