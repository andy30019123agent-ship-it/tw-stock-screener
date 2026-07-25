import { useState, useEffect, useMemo, useCallback } from 'react'
import { Filter, AlertTriangle, CircleAlert, SlidersHorizontal, RotateCcw, ChevronDown, Check, ArrowUpDown, BookOpen } from 'lucide-react'
import ConditionPanel from './components/ConditionPanel'
import HelpGuide from './components/HelpGuide'
import ErrorBoundary from './components/ErrorBoundary'
import ResultTable from './components/ResultTable'
import StockChartModal from './components/StockChartModal'
import Opportunities from './components/Opportunities'
import MarketAdvice from './components/MarketAdvice'
import { DEFAULT_CONDITIONS, applyFilters, SORTS, SORT_LABELS, MOBILE_SORTS, countActiveConditions } from './lib/filters'

export default function App() {
  // 使用說明書用 hash 路由（#help）：零新依賴、可加書籤、GitHub Pages 不必改設定。
  // 監聽 hashchange 才能讓上一頁/下一頁與直接貼連結都正常。
  const [route, setRoute] = useState(() =>
    (typeof window !== 'undefined' && window.location.hash.startsWith('#help')) ? 'help' : 'main')
  useEffect(() => {
    const onHash = () => setRoute(window.location.hash.startsWith('#help') ? 'help' : 'main')
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  useEffect(() => {           // 切到說明書時捲回頂端，否則會停在選股頁的捲動位置
    if (route === 'help') window.scrollTo(0, 0)
  }, [route])

  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [conditions, setConditions] = useState(DEFAULT_CONDITIONS)
  const [sortKey, setSortKey] = useState('signal')
  const [sortOpen, setSortOpen] = useState(false)   // 手機排序選單（工具列「排序 ▾」點開）
  const [weights, setWeights] = useState(null)       // signal_weights.json：快速套用依勝率排序用
  const [combos, setCombos] = useState(null)         // signal_combos.json：組合戰績排行榜
  const [exits, setExits] = useState(null)           // signal_exits.json：出場優化分析
  const [regime, setRegime] = useState(null)         // signal_regime.json：市況分層回測
  // 手機卡片密度：精簡（預設，省滑）／完整；記住上次選擇
  const [dense, setDense] = useState(() => {
    if (typeof localStorage === 'undefined') return true
    return localStorage.getItem('tw-screener:dense') !== 'full'
  })
  const toggleDense = () => setDense(d => {
    const next = !d
    try { localStorage.setItem('tw-screener:dense', next ? 'dense' : 'full') } catch { /* 隱私模式忽略 */ }
    return next
  })
  const [picked, setPicked] = useState(null)
  const [oppCount, setOppCount] = useState(null)
  const [panelOpen, setPanelOpen] = useState(false)   // 手機常駐工具列與篩選面板連動；桌機面板恆展開（CSS）
  // 穩定的關閉函式（避免每次渲染都是新函式，害 StockChartModal 的 focus-trap effect 反覆 cleanup/重跑搶焦）
  const closeModal = useCallback(() => setPicked(null), [])

  const activeConds = useMemo(() => countActiveConditions(conditions), [conditions])
  const resetAll = () => { setConditions(DEFAULT_CONDITIONS); setSortKey('signal'); setPanelOpen(false) }
  // 本週市況建議「套用」：從乾淨預設疊上該訊號條件、展開面板、捲到清單
  const applyAdvice = patch => {
    setConditions({ ...DEFAULT_CONDITIONS, bullAligned: false, ...patch })
    setPanelOpen(true)
    document.getElementById('cond-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  useEffect(() => {
    fetch(`${import.meta.env.BASE_URL}data/screener.json`)
      .then(r => { if (!r.ok) throw new Error('讀取資料失敗'); return r.json() })
      .then(setData)
      .catch(e => setError(e.message))
    // 回測權重：給「快速套用」依超額報酬排序用（抓不到就維持原順序）
    fetch(`${import.meta.env.BASE_URL}data/signal_weights.json`)
      .then(r => (r.ok ? r.json() : null)).then(setWeights).catch(() => setWeights(null))
    fetch(`${import.meta.env.BASE_URL}data/signal_combos.json`)
      .then(r => (r.ok ? r.json() : null)).then(setCombos).catch(() => setCombos(null))
    fetch(`${import.meta.env.BASE_URL}data/signal_exits.json`)
      .then(r => (r.ok ? r.json() : null)).then(setExits).catch(() => setExits(null))
    fetch(`${import.meta.env.BASE_URL}data/signal_regime.json`)
      .then(r => (r.ok ? r.json() : null)).then(setRegime).catch(() => setRegime(null))
  }, [])

  const filtered = useMemo(() => {
    if (!data) return []
    const list = applyFilters(data.stocks, conditions)
    return [...list].sort(SORTS[sortKey] || SORTS.signal)
  }, [data, conditions, sortKey])

  // 資料日期誠實化：主顯示「資料日期（交易日）」而非 build 時間，落後太多天要醒目警告。
  const daysStale = useMemo(() => {
    if (!data?.data_date) return null
    // 兩邊都換算成「台北日曆日」再相減。原本用 Date.now() 直接減 new Date('YYYY-MM-DD')
    // （會被當成 UTC 午夜＝台北 08:00），天數要到台北早上 8 點才跳動，凌晨到 8 點之間
    // 一律少算一天——資料其實已經過期，畫面卻還說沒過期。
    const todayTaipei = new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Taipei' })
    const today = Date.parse(`${todayTaipei}T00:00:00Z`)
    const dataDay = Date.parse(`${data.data_date}T00:00:00Z`)
    if (Number.isNaN(today) || Number.isNaN(dataDay)) return null
    return Math.round((today - dataDay) / 86400000)
  }, [data])
  const stale = data && (daysStale === null || daysStale > 5 || data.fetch_ok === false)

  // 全市場可選產業清單（依檔數多寡排序）
  const industries = useMemo(() => {
    if (!data) return []
    const cnt = {}
    for (const s of data.stocks) cnt[s.industry] = (cnt[s.industry] || 0) + 1
    return Object.keys(cnt).sort((a, b) => cnt[b] - cnt[a])
  }, [data])

  if (route === 'help') {
    return (
      <div className="app">
        <HelpGuide onBack={() => { window.location.hash = '' }} />
      </div>
    )
  }

  return (
    <div className="app">
      <section className="hero" data-region="Hero / 標題與大數字統計">
        <span className="hero-blob b1" aria-hidden="true" />
        <span className="hero-blob b2" aria-hidden="true" />
        <span className="hero-blob b3" aria-hidden="true" />
        <div className="hero-top">
          <div className="hero-titles">
            <span className="badge-pill"><Filter size={14} strokeWidth={1.75} />全市場選股 · Screener</span>
            <h1 style={{ marginTop: 14 }}>台股全市場選股</h1>
            <p className="subtitle">
              糾結轉強 × 法人連買 · 上市＋上櫃
              {/* 說明書入口放這裡（不是只放 footer）：手機第一眼就要看得到，
                  否則等於沒做——站上概念不少，看不懂時人不會捲到頁尾找說明。 */}
              <a className="help-link" href="#help">
                <BookOpen size={13} strokeWidth={2} />使用說明
              </a>
            </p>
          </div>
          {data && (
            <div className="hero-right">
              <span className={`updated-pill ${stale ? 'stale' : ''}`}>
                <span className={`live-dot ${stale ? 'stale' : ''}`} />
                資料日期（交易日）{data.data_date || '—'}
              </span>
            </div>
          )}
        </div>
        {data && (
          <div className="stat-grid">
            <div className="stat-tile">
              <div className="st-name">全市場掃描</div>
              <div className="st-value mono">{data.count}<small> 檔</small></div>
            </div>
            <div className="stat-tile">
              <div className="st-name">符合條件</div>
              <div className="st-value mono">{filtered.length}<small> 檔</small></div>
            </div>
            <div className="stat-tile">
              <div className="st-name">今日機會股</div>
              <div className="st-value mono">{oppCount ?? '—'}<small> 檔</small></div>
            </div>
          </div>
        )}
      </section>

      {error && (
        <div className="banner banner-error" role="alert">
          <CircleAlert size={18} strokeWidth={1.75} />{error}
        </div>
      )}

      {data && stale && (
        <div className="banner banner-warn" role="alert">
          <AlertTriangle size={18} strokeWidth={1.75} />
          <span>
            資料可能未更新，最後交易日 <b>{data.data_date || '未知'}</b>
            {data.fetch_ok === false
              ? '（上次自動抓取最新交易日失敗，目前顯示的是沿用的舊資料）'
              : daysStale !== null && `（已經 ${daysStale} 天沒有新交易資料，請留意）`}
          </span>
        </div>
      )}

      {data?.market_breadth && ['red', 'severe_red', 'yellow'].includes(data.market_breadth.status) && (
        <div className={`banner ${data.market_breadth.status === 'yellow' ? 'banner-warn' : 'banner-error'}`} role="status">
          <AlertTriangle size={18} strokeWidth={1.75} />
          <span>
            {data.market_breadth.status === 'severe_red' ? '大盤明顯走弱' :
              data.market_breadth.status === 'red' ? '大盤廣度轉弱' : '大盤廣度中性偏弱'}
            ——全市場僅 <b>{Math.round(data.market_breadth.breadth20 * 100)}%</b> 的股票站上月線
            （20 日報酬中位 {data.market_breadth.median_ret20_pct >= 0 ? '+' : ''}{data.market_breadth.median_ret20_pct}%）。
            Top5 仍照常產生，<b>請自行斟酌降低曝險</b>。（此為市場廣度代理、非大盤指數；僅供參考、不改選股）
          </span>
        </div>
      )}

      {data && (
        <ErrorBoundary name="advice" label="本週市況建議">
          <MarketAdvice breadth={data.market_breadth} regime={regime} onApply={applyAdvice} />
        </ErrorBoundary>
      )}

      {!data && !error && (
        <div className="center-state">
          <div className="spin" />
          載入資料中…
        </div>
      )}

      <ErrorBoundary name="opportunities" label="今日機會股">
        <Opportunities stocks={data?.stocks} onPick={setPicked} onCount={setOppCount} />
      </ErrorBoundary>

      {data && (
        <>
          {/* 手機常駐（sticky）單一工具列：篩選數｜符合檔數｜排序（點開選單）｜重設。
              取代舊版「mobile-toolbar＋ConditionPanel 標題」兩條重複列。桌機隱藏（用完整面板）。 */}
          <div className="mobile-toolbar">
            <button className={`mtb-btn ${panelOpen ? 'on' : ''}`} onClick={() => setPanelOpen(o => !o)}
              aria-expanded={panelOpen} aria-controls="cond-panel">
              <SlidersHorizontal size={16} strokeWidth={1.75} />篩選<b>{activeConds}</b>
            </button>
            <span className="mtb-count">符合 <b key={filtered.length}>{filtered.length}</b> 檔</span>
            <button className={`mtb-sortbtn ${sortOpen ? 'on' : ''}`} onClick={() => setSortOpen(true)}
              aria-haspopup="listbox" aria-expanded={sortOpen}>
              <ArrowUpDown size={14} strokeWidth={1.75} /><b>{SORT_LABELS[sortKey] || sortKey}</b>
              <ChevronDown size={13} strokeWidth={2} />
            </button>
            <button className="mtb-reset" onClick={resetAll} aria-label="重設條件與排序">
              <RotateCcw size={15} strokeWidth={1.75} />
            </button>
          </div>

          {/* 排序選單：底部彈出，固定二欄格線（取代原本清單前參差的 10 顆排序 pill） */}
          {sortOpen && (
            <div className="sort-sheet-backdrop" onClick={() => setSortOpen(false)}>
              <div className="sort-sheet" role="listbox" aria-label="排序方式" onClick={e => e.stopPropagation()}>
                <div className="sort-sheet-head">排序方式</div>
                <div className="sort-sheet-grid">
                  {MOBILE_SORTS.map(([key, label]) => (
                    <button key={key} role="option" aria-selected={sortKey === key}
                      className={`sort-opt ${sortKey === key ? 'on' : ''}`}
                      onClick={() => { setSortKey(key); setSortOpen(false) }}>
                      {label}{sortKey === key && <Check size={15} strokeWidth={2.5} />}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}
          <ConditionPanel
            id="cond-panel"
            conditions={conditions}
            onChange={setConditions}
            total={data.count}
            shown={filtered.length}
            holderReady={!!data.holder_ready}
            industries={industries}
            weights={weights}
            combos={combos}
            exits={exits}
            regime={regime}
            open={panelOpen}
            onOpenChange={setPanelOpen}
          />
          {/* 手機卡片密度切換（桌機用表格、不顯示）：精簡預設，一鍵看完整 */}
          <div className="density-bar">
            <span className="density-label">顯示</span>
            <div className="density-seg" role="group" aria-label="卡片顯示密度">
              <button className={`density-btn ${dense ? 'on' : ''}`} aria-pressed={dense}
                onClick={() => dense || toggleDense()}>精簡</button>
              <button className={`density-btn ${!dense ? 'on' : ''}`} aria-pressed={!dense}
                onClick={() => dense && toggleDense()}>完整</button>
            </div>
          </div>
          <ResultTable
            key={`${sortKey}:${filtered.length}`}
            stocks={filtered}
            sortKey={sortKey}
            onSort={setSortKey}
            onPick={setPicked}
            dense={dense}
          />
        </>
      )}

      {/* 各自包 error boundary：任何一塊壞掉不該讓整站變白畫面（2026-07-25 K 線圖崩站的教訓） */}
      <ErrorBoundary name="chart" label="K 線圖">
        <StockChartModal stock={picked} onClose={closeModal} />
      </ErrorBoundary>

      <footer className="app-footer">
        <a className="help-link" href="#help"><BookOpen size={13} strokeWidth={2} />使用說明書</a>
        <span className="footer-sep">·</span>
        資料來源：TWSE／TPEX 官方公開資料 · 僅供研究參考，非投資建議
      </footer>
    </div>
  )
}
