import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { AlertTriangle, CircleAlert, SlidersHorizontal, RotateCcw, ChevronDown, Check, ArrowUpDown, BookOpen, TrendingDown, Info } from 'lucide-react'
import ConditionPanel from './components/ConditionPanel'
import HelpGuide from './components/HelpGuide'
import ErrorBoundary from './components/ErrorBoundary'
import ResultTable from './components/ResultTable'
import StockChartModal from './components/StockChartModal'
import Opportunities from './components/Opportunities'
import MarketAdvice from './components/MarketAdvice'
import BasisTab from './components/BasisTab'
import SignalWeights from './components/SignalWeights'
import OutcomeShape from './components/OutcomeShape'
import PositionPlan from './components/PositionPlan'
import { TABS, parseHash, tabHash, tabKeyTarget } from './lib/tabs'
import { normalizeTier } from './lib/tierVerdict'
import { readDense, writeDense } from './lib/safeStorage'
import { DEFAULT_CONDITIONS, applyFilters, SORTS, SORT_LABELS, MOBILE_SORTS, countActiveConditions, describeActiveConditions } from './lib/filters'

export default function App() {
  // 2026-11-16 三分頁改版（Andy 核准方向 A＋C）：分頁與使用說明都走網址雜湊（lib/tabs.js）。
  // #today／#basis／#tools＝三個分頁；#help（含 #help/s1 章節連結）＝使用說明。
  // 監聽 hashchange，上一頁/下一頁、重新整理、直接貼連結都會停在對的地方；零新依賴、GitHub Pages 不必改設定。
  const [loc, setLoc] = useState(() => parseHash(typeof window !== 'undefined' ? window.location.hash : ''))
  const route = loc.route
  const [tab, setTab] = useState(() => loc.tab || 'today')   // 進說明書時記住剛才在哪個分頁，回來用
  const [visited, setVisited] = useState(() => new Set([loc.tab || 'today']))   // 看過的分頁才掛載，之後保留狀態
  useEffect(() => {
    const onHash = () => {
      const next = parseHash(window.location.hash)
      setLoc(next)
      if (next.tab) {
        setTab(next.tab)
        setVisited(v => (v.has(next.tab) ? v : new Set(v).add(next.tab)))
      }
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  useEffect(() => {           // 切到說明書時捲回頂端，否則會停在選股頁的捲動位置
    if (route === 'help') window.scrollTo(0, 0)
  }, [route])
  const tabRefs = useRef({})
  const goTab = (key, focus = false) => {
    if (window.location.hash !== tabHash(key)) window.location.hash = tabHash(key)   // 觸發 hashchange、留上一頁紀錄
    // 換分頁時，若已經捲過頁首，捲回分頁列的位置（不然會停在上一頁的捲動深度）
    const bar = document.getElementById('tabbar')
    if (bar && window.scrollY > bar.offsetTop) window.scrollTo(0, bar.offsetTop)
    if (focus) tabRefs.current[key]?.focus()
  }
  const onTabKey = e => {
    const next = tabKeyTarget(tab, e.key)
    if (!next) return
    e.preventDefault()
    goTab(next, true)
  }

  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [conditions, setConditions] = useState(DEFAULT_CONDITIONS)
  const [sortKey, setSortKey] = useState('signal')
  const [sortOpen, setSortOpen] = useState(false)   // 手機排序選單（工具列「排序 ▾」點開）
  const [weights, setWeights] = useState(null)       // signal_weights.json：快速套用依勝率排序用
  const [combos, setCombos] = useState(null)         // signal_combos.json：組合戰績排行榜
  const [exits, setExits] = useState(null)           // signal_exits.json：出場優化分析
  const [regime, setRegime] = useState(null)         // signal_regime.json：市況分層回測
  const [exitSummary, setExitSummary] = useState(null) // exit_rules_summary.json：停損線代價對照表（抓不到＝表格不顯示）
  const [tierStats, setTierStats] = useState(null)   // tier_stats.json：候選情報條件層級的歷史分佈（Opportunities/OutcomeShape 用）
  // 手機卡片密度：精簡（預設，省滑）／完整；記住上次選擇
  const [dense, setDense] = useState(() => readDense())
  const toggleDense = () => setDense(d => {
    const next = !d
    writeDense(next)   // 寫不進去（隱私模式）就算了，只是下次不記得
    return next
  })
  const [picked, setPicked] = useState(null)        // { stock, pick }：K 線視窗；pick＝候選清單那一筆（進階篩選開的沒有）
  const [opp, setOpp] = useState(undefined)          // opportunities.json（undefined＝載入中、null＝抓不到）
  const [board, setBoard] = useState(null)           // scoreboard.json：真實績效紀錄
  const [windows, setWindows] = useState(null)       // signal_windows.json：多時間窗勝率榜
  // 大盤提醒：2026-11-13 可讀性改版收成一行摘要（含「請自行斟酌降低曝險」），點開看完整說明
  const [mktOpen, setMktOpen] = useState(false)
  const [panelOpen, setPanelOpen] = useState(false)   // 手機常駐工具列與篩選面板連動；桌機面板恆展開（CSS）
  // 「進階篩選」整組（舊版篩選器＋結果列表）2026-07-26 降級為次要工具，預設收合——
  // 這是核准方向第 1 條「砍掉雙軌候選機制」的落地：候選情報是唯一預設可見的候選清單，
  // 這一整塊（工具列／面板／表格）只在使用者主動點開才出現。
  const [advancedOpen, setAdvancedOpen] = useState(false)
  // 穩定的關閉函式（避免每次渲染都是新函式，害 StockChartModal 的 focus-trap effect 反覆 cleanup/重跑搶焦）
  const closeModal = useCallback(() => setPicked(null), [])
  const pickStock = useCallback((stock, pick = null) => setPicked(stock ? { stock, pick } : null), [])
  const oppCount = opp === undefined ? null : (opp?.pool_n ?? opp?.picks?.length ?? 0)

  const activeConds = useMemo(() => countActiveConditions(conditions), [conditions])
  const activeCondText = useMemo(() => describeActiveConditions(conditions), [conditions])
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
    fetch(`${import.meta.env.BASE_URL}data/exit_rules_summary.json`)
      .then(r => (r.ok ? r.json() : null)).then(setExitSummary).catch(() => setExitSummary(null))
    // 候選情報三件（原本在 Opportunities 裡抓；三分頁後今天／依據／工具都要用，提到這層抓一次）
    fetch(`${import.meta.env.BASE_URL}data/opportunities.json`)
      .then(r => (r.ok ? r.json() : null)).then(setOpp).catch(() => setOpp(null))
    fetch(`${import.meta.env.BASE_URL}data/scoreboard.json`)
      .then(r => (r.ok ? r.json() : null)).then(setBoard).catch(() => setBoard(null))
    fetch(`${import.meta.env.BASE_URL}data/signal_windows.json`)
      .then(r => (r.ok ? r.json() : null)).then(setWindows).catch(() => setWindows(null))
  }, [])

  // 持有口徑區的集中度警示要用相對優勢那組（picks 本身沒有產業，從 screener.json 併回來）
  const edgePicks = useMemo(() => {
    if (!opp?.picks) return []
    const byId = new Map((data?.stocks || []).map(s => [s.id, s]))
    return opp.picks.filter(p => normalizeTier(p).tier === 'edge').map(p => {
      const full = byId.get(p.id)
      return { id: p.id, name: p.name, close: p.close ?? full?.close ?? null, industry: full?.industry ?? null }
    })
  }, [opp, data])

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
        <HelpGuide tierStats={tierStats} exitSummary={exitSummary} weights={weights} combos={combos}
          exits={exits} regime={regime} marketCount={data?.count ?? null}
          onBack={() => { window.location.hash = tabHash(tab) }} />
      </div>
    )
  }

  const panelProps = key => ({
    role: 'tabpanel', id: `panel-${key}`, 'aria-labelledby': `tab-${key}`, tabIndex: -1,
    hidden: tab !== key, className: `tabpanel tabpanel-${key}`,
  })

  return (
    <div className="app">
      {/* 頁首：標題＋資料日一行。2026-11-16 起「使用說明」入口搬到「工具」分頁與頁尾，頁首只留資訊。 */}
      <header className="hero" data-region="Hero / 標題與資料日">
        <span className="hero-blob b1" aria-hidden="true" />
        <span className="hero-blob b2" aria-hidden="true" />
        <h1>台股全市場選股</h1>
        {data && (
          <p className="hero-meta">
            <span className="hero-meta-seg">
              <span className={`live-dot ${stale ? 'stale' : ''}`} aria-hidden="true" />
              資料日 <b className="mono">{data.data_date || '—'}</b>
            </span>
            <span className="hero-meta-sep">・</span>
            <span className="hero-meta-seg">掃描 <b className="mono">{data.count}</b> 檔</span>
            <span className="hero-meta-sep">・</span>
            <span className="hero-meta-seg">候選 <b className="mono">{oppCount ?? '—'}</b> 檔</span>
          </p>
        )}
      </header>

      {/* 三分頁列：頁首下方、捲動時黏在頂端（WAI-ARIA tabs：左右鍵／Home／End 切換） */}
      <nav className="tabbar" id="tabbar" aria-label="分頁">
        <div className="tabbar-inner" role="tablist" aria-label="今天／依據／工具" onKeyDown={onTabKey}>
          {TABS.map(([key, label]) => (
            <button key={key} id={`tab-${key}`} ref={el => { tabRefs.current[key] = el }}
              role="tab" aria-selected={tab === key} aria-controls={`panel-${key}`} tabIndex={tab === key ? 0 : -1}
              className={`tab${tab === key ? ' on' : ''}`} onClick={() => goTab(key)}>
              {label}
            </button>
          ))}
        </div>
      </nav>

      {/* 狀態型警示（資料抓取失敗、資料過期）：顯示條件不變；放在分頁列正下方，三個分頁都看得到，
          「今天」分頁首屏一定可見（MASTER 2026-11-16 第 4 點）。 */}
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

      {!data && !error && (
        <div className="center-state">
          <div className="spin" />
          載入資料中…
        </div>
      )}

      {/* ===== 今天：只放股票 ===== */}
      <div {...panelProps('today')}>
          {/* 「今天大盤怎樣」：2026-11-13 收成一行摘要（Andy 核准第 1 條），摘要裡保留最重要的一句
              「請自行斟酌降低曝險」；完整數字與「市場廣度代理、非大盤指數」在展開內容，
              後者也同時寫在「這些數字怎麼來的 → 限制」（預設可見）。 */}
          {data?.market_breadth && ['red', 'severe_red', 'yellow'].includes(data.market_breadth.status) && (() => {
            const mb = data.market_breadth
            const label = mb.status === 'severe_red' ? '大盤明顯走弱' : mb.status === 'red' ? '大盤廣度轉弱' : '大盤廣度中性偏弱'
            return (
              <div className={`mkt ${mb.status === 'yellow' ? 'mkt-warn' : 'mkt-down'}`} role="status">
                <button className="mkt-sum" onClick={() => setMktOpen(o => !o)} aria-expanded={mktOpen} aria-controls="mkt-detail">
                  <TrendingDown size={18} strokeWidth={1.75} aria-hidden="true" />
                  <span><b>{label}</b>：僅 {Math.round(mb.breadth20 * 100)}% 站上月線，請自行斟酌降低曝險</span>
                  <ChevronDown className={`chevron ${mktOpen ? 'up' : ''}`} size={18} strokeWidth={2} aria-hidden="true" />
                </button>
                {mktOpen && (
                  <p className="mkt-detail" id="mkt-detail">
                    {label}——全市場僅 <b>{Math.round(mb.breadth20 * 100)}%</b> 的股票站上月線
                    （20 日報酬中位 {mb.median_ret20_pct >= 0 ? '+' : ''}{mb.median_ret20_pct}%）。
                    候選情報仍照常產生，<b>請自行斟酌降低曝險</b>。
                  </p>
                )}
              </div>
            )
          })()}

        <ErrorBoundary name="opportunities" label="候選情報">
          <Opportunities opp={opp} stocks={data?.stocks} onPick={pickStock} engineStatus={data?.engine_status}
            tierStats={tierStats} onGoBasis={e => { e.preventDefault(); goTab('basis') }} />
        </ErrorBoundary>
      </div>

      {/* ===== 依據：清單怎麼來的、真實績效、回測結論與證據、限制與但書 ===== */}
      {visited.has('basis') && (
        <div {...panelProps('basis')}>
          <ErrorBoundary name="basis" label="依據">
            <BasisTab opp={opp} tierStats={tierStats} board={board} />
          </ErrorBoundary>
        </div>
      )}

      {/* ===== 工具：市況建議、進階篩選、訊號戰績、條件層級分佈、持有口徑與停損代價、使用說明 ===== */}
      {visited.has('tools') && (
        <div {...panelProps('tools')}>
          <a className="tools-help" href="#help">
            <BookOpen size={20} strokeWidth={1.75} aria-hidden="true" />
            <span><b>使用說明</b><small>第一次用？每個名詞、每張表怎麼看都在這裡</small></span>
          </a>
          {data && hasAdvice && (
            <section className="tools-sec" data-region="今日市況建議">
              <h2 className="opp-section-title">想直接套用歷史最強的訊號？</h2>
              <p className="tools-note">
                <Info size={16} strokeWidth={1.75} aria-hidden="true" />
                <span>按「套用」會在下面的進階篩選開出另一份清單，<b>跟「今天」分頁的候選不是同一份</b>（那份還多過了量、營收、當天訊號幾關）。</span>
              </p>
              <ErrorBoundary name="advice" label="今日市況建議">
                <MarketAdvice breadth={data.market_breadth} regime={regime} onApply={applyAdvice} />
              </ErrorBoundary>
            </section>
          )}
          {/* 「想自己篩？進階篩選」：舊版「篩選＋訊號排序」候選列表（ConditionPanel＋ResultTable）
              整組降級為進階工具，預設收合（2026-07-26 核准方向第 1 條）；2026-11-16 起搬到「工具」分頁。 */}
          {data && (
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
              這是舊版的手動篩選器：自己勾條件、自己排序，跟「今天」分頁的候選情報是兩套獨立工具，互不影響。
            </p>
            {advancedOpen && (
              <div id="advanced-tools-body">
                {/* 打開的第一行：寫出目前套用中的條件（預設就有條件時，使用者才知道清單為什麼這麼短） */}
                {activeCondText.length > 0 && (
                  <p className="advanced-active" data-active-conds>
                    目前套用了 <b>{activeConds}</b> 個條件：{activeCondText.join('、')}。工具列的重設鈕可以全部清掉。
                  </p>
                )}
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
                  onPick={pickStock}
                  dense={dense}
                />
              </div>
            )}
          </section>
          )}
          <section className="tools-sec" data-region="訊號戰績">
            <h2 className="opp-section-title">訊號戰績與條件層級</h2>
            <ErrorBoundary name="weights" label="各訊號回測戰績">
              <SignalWeights windows={windows} weights={weights} />
            </ErrorBoundary>
            <ErrorBoundary name="outcome" label="條件層級的歷史分佈">
              <OutcomeShape tierStats={tierStats} />
            </ErrorBoundary>
          </section>
          <ErrorBoundary name="position" label="持有口徑與停損代價">
            <PositionPlan dataDate={opp?.date} exitSummary={exitSummary} picks={edgePicks} />
          </ErrorBoundary>
        </div>
      )}

      {/* 各自包 error boundary：任何一塊壞掉不該讓整站變白畫面（2026-07-25 K 線圖崩站的教訓） */}
      <ErrorBoundary name="chart" label="K 線圖">
        <StockChartModal stock={picked?.stock || null} pick={picked?.pick || null} onClose={closeModal} />
      </ErrorBoundary>

      <footer className="app-footer">
        <a className="help-link" href="#help"><BookOpen size={16} strokeWidth={1.75} />使用說明</a>
        <span className="footer-sep">·</span>
        資料來源：TWSE／TPEX 官方公開資料
      </footer>
    </div>
  )
}
