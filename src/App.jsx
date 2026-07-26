import { useState, useEffect, useMemo, useCallback } from 'react'
import { AlertTriangle, CircleAlert, SlidersHorizontal, RotateCcw, ChevronDown, Check, ArrowUpDown, BookOpen } from 'lucide-react'
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
  const [tierStats, setTierStats] = useState(null)   // tier_stats.json：候選情報條件層級的歷史分佈（Opportunities/OutcomeShape 用）
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
  // 「進階篩選」整組（舊版篩選器＋結果列表）2026-07-26 降級為次要工具，預設收合——
  // 這是核准方向第 1 條「砍掉雙軌候選機制」的落地：候選情報是唯一預設可見的候選清單，
  // 這一整塊（工具列／面板／表格）只在使用者主動點開才出現。
  const [advancedOpen, setAdvancedOpen] = useState(false)
  // 穩定的關閉函式（避免每次渲染都是新函式，害 StockChartModal 的 focus-trap effect 反覆 cleanup/重跑搶焦）
  const closeModal = useCallback(() => setPicked(null), [])

  const activeConds = useMemo(() => countActiveConditions(conditions), [conditions])
  const resetAll = () => { setConditions(DEFAULT_CONDITIONS); setSortKey('signal'); setPanelOpen(false) }
  // 本週市況建議「套用」：從乾淨預設疊上該訊號條件、展開進階篩選＋面板、捲到清單。
  // 進階篩選現在預設收合（DOM 裡還沒有 #cond-panel），要等 advancedOpen 觸發的那次渲染
  // commit 完才找得到節點，所以捲動改用 requestAnimationFrame 延後一拍，不直接同步呼叫。
  const applyAdvice = patch => {
    setConditions({ ...DEFAULT_CONDITIONS, bullAligned: false, ...patch })
    setAdvancedOpen(true)
    setPanelOpen(true)
    requestAnimationFrame(() => {
      document.getElementById('cond-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
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
    // 條件層級歷史分佈（同模式：抓不到就 null，Opportunities/OutcomeShape 各自優雅降級，不拖垮整頁）
    fetch(`${import.meta.env.BASE_URL}data/tier_stats.json`)
      .then(r => (r.ok ? r.json() : null)).then(setTierStats).catch(() => setTierStats(null))
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

  // 本週市況建議是否有內容可顯示——App 層要先知道，才能決定要不要印出它上面那句引導語，
  // 否則 MarketAdvice 內部判斷沒東西時直接 return null，畫面會剩一句話講給空氣聽。
  const hasAdvice = !!(data?.market_breadth && regime?.signals)

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
            {/* 使用說明入口跟徽章同一列（不是只放 footer）：手機第一眼就要看得到，否則等於沒做
                ——站上概念不少，看不懂時人不會捲到頁尾找說明。原本塞在副標段落裡會因為 44px
                觸控高度把整句擠成兩行，2026-07-26 改成跟徽章並排省一整行。 */}
            {/* 2026-07-26 二次壓縮：原本這列有一個「全市場選股 · Screener」膠囊徽章，但它跟正下方
                的 h1「台股全市場選股」講同一件事，屬於純裝飾。首屏每一個 px 都在跟「第一檔候選要
                多久才看得到」競爭，而警語類內容一律不准砍（MASTER.md 核准第 3 條），所以能砍的
                只有這種重複的裝飾。使用說明連結保留——它是功能入口，不是裝飾。 */}
            <div className="hero-badge-row">
              <a className="help-link" href="#help">
                <BookOpen size={13} strokeWidth={2} />使用說明
              </a>
            </div>
            <h1 style={{ marginTop: 6 }}>台股全市場選股</h1>
            {/* 2026-07-26 單欄故事線改版：舊副標「糾結轉強 × 法人連買」是舊篩選器的訊號組合，
                跟現在唯一的候選來源（候選情報／三分類）對不起來，改成描述候選情報本身。 */}
            {/* 「買哪幾檔由你決定」搬掉——候選情報自己的頭條句（下面 opp-tagline）已經講過同一件事，
                這裡留短一點是為了保證單行，不要在 390 寬度上多包一行把候選卡片往下推。 */}
            <p className="subtitle">全市場候選情報 · 上市＋上櫃</p>
          </div>
        </div>
        {/* 大數字統計列（2026-07-26 砍掉「符合條件」）：那是舊篩選器的結果，跟「今日候選」並排
            會讓人分不清該看哪個（審計實測兩者差 40 倍）。全站候選來源只剩「今日候選」一個數字；
            資料日期原本是 hero-right 獨立一整列 pill，併進同一行省掉一整段高度。 */}
        {data && (
          <div className="hero-stats">
            <span className="hero-stat"><b className="mono">{data.count}</b><small>檔</small>全市場掃描</span>
            <span className="hero-stat-sep" aria-hidden="true" />
            <span className="hero-stat"><b className="mono">{oppCount ?? '—'}</b><small>檔</small>今日候選</span>
            <span className={`updated-pill ${stale ? 'stale' : ''}`}>
              <span className={`live-dot ${stale ? 'stale' : ''}`} />
              {data.data_date || '—'}
            </span>
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

      {/* 「今天大盤怎樣」：市況轉弱時的警示放最前面，跟大盤偏強時的「本週市況建議」（挪到候選
          清單之後）分工——這裡只講大盤好不好，訊號怎麼用留給後面。 */}
      {data?.market_breadth && ['red', 'severe_red', 'yellow'].includes(data.market_breadth.status) && (
        <div className={`banner ${data.market_breadth.status === 'yellow' ? 'banner-warn' : 'banner-error'}`} role="status">
          <AlertTriangle size={18} strokeWidth={1.75} />
          <span>
            {data.market_breadth.status === 'severe_red' ? '大盤明顯走弱' :
              data.market_breadth.status === 'red' ? '大盤廣度轉弱' : '大盤廣度中性偏弱'}
            ——全市場僅 <b>{Math.round(data.market_breadth.breadth20 * 100)}%</b> 的股票站上月線
            （20 日報酬中位 {data.market_breadth.median_ret20_pct >= 0 ? '+' : ''}{data.market_breadth.median_ret20_pct}%）。
            候選情報仍照常產生，<b>請自行斟酌降低曝險</b>。（此為市場廣度代理、非大盤指數；僅供參考、不改選股）
          </span>
        </div>
      )}

      {!data && !error && (
        <div className="center-state">
          <div className="spin" />
          載入資料中…
        </div>
      )}

      {/* 「今天有幾檔候選」＋「雙優這幾檔」＋「其他兩類」＋「這些數字怎麼來的」都在 Opportunities
          裡由上而下排好（2026-07-26 單欄故事線核准方向第 2 條）；候選情報現在預設展開、
          不用點「展開」才看得到第一檔股票。 */}
      <ErrorBoundary name="opportunities" label="候選情報">
        <Opportunities stocks={data?.stocks} onPick={setPicked} onCount={setOppCount}
          engineStatus={data?.engine_status} tierStats={tierStats} />
      </ErrorBoundary>

      {data && (
        <>
          {hasAdvice && (
            <>
              <h2 className="opp-section-title">想直接套用歷史最強的訊號？</h2>
              <ErrorBoundary name="advice" label="本週市況建議">
                <MarketAdvice breadth={data.market_breadth} regime={regime} onApply={applyAdvice} />
              </ErrorBoundary>
            </>
          )}

          {/* 「想自己篩？進階篩選」：舊版「篩選＋訊號排序」候選列表（ConditionPanel＋ResultTable）
              整組降級為進階工具，預設收合，用一條分隔線＋標題跟上面的候選情報隔開（核准方向第 1 條）。 */}
          <section className="advanced-tools" data-region="進階篩選（舊版篩選器）">
            <button
              className="advanced-toggle"
              onClick={() => setAdvancedOpen(o => !o)}
              aria-expanded={advancedOpen}
              aria-controls="advanced-tools-body"
            >
              <SlidersHorizontal size={16} strokeWidth={1.75} />
              想自己下條件？進階篩選
              <ChevronDown className={`chevron ${advancedOpen ? 'up' : ''}`} size={18} strokeWidth={2} />
            </button>
            <p className="advanced-hint">
              這是舊版的手動篩選器：自己勾條件、自己排序，跟上面「候選情報」是兩套獨立工具，互不影響。
            </p>
            {advancedOpen && (
              <div id="advanced-tools-body">
                {/* 手機常駐（sticky）單一工具列：篩選數｜符合檔數｜排序（點開選單）｜重設。 */}
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

                {/* 排序選單：底部彈出，固定二欄格線 */}
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
              </div>
            )}
          </section>
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
