import { useState, useEffect, useMemo, useCallback } from 'react'
import { Filter, AlertTriangle, CircleAlert, SlidersHorizontal, RotateCcw } from 'lucide-react'
import ConditionPanel from './components/ConditionPanel'
import ResultTable from './components/ResultTable'
import StockChartModal from './components/StockChartModal'
import Opportunities from './components/Opportunities'
import { DEFAULT_CONDITIONS, applyFilters, SORTS, SORT_LABELS, countActiveConditions } from './lib/filters'

export default function App() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [conditions, setConditions] = useState(DEFAULT_CONDITIONS)
  const [sortKey, setSortKey] = useState('signal')
  const [picked, setPicked] = useState(null)
  const [oppCount, setOppCount] = useState(null)
  const [panelOpen, setPanelOpen] = useState(false)   // 手機常駐工具列與篩選面板連動；桌機面板恆展開（CSS）
  // 穩定的關閉函式（避免每次渲染都是新函式，害 StockChartModal 的 focus-trap effect 反覆 cleanup/重跑搶焦）
  const closeModal = useCallback(() => setPicked(null), [])

  const activeConds = useMemo(() => countActiveConditions(conditions), [conditions])
  const resetAll = () => { setConditions(DEFAULT_CONDITIONS); setSortKey('signal'); setPanelOpen(false) }

  useEffect(() => {
    fetch(`${import.meta.env.BASE_URL}data/screener.json`)
      .then(r => { if (!r.ok) throw new Error('讀取資料失敗'); return r.json() })
      .then(setData)
      .catch(e => setError(e.message))
  }, [])

  const filtered = useMemo(() => {
    if (!data) return []
    const list = applyFilters(data.stocks, conditions)
    return [...list].sort(SORTS[sortKey] || SORTS.signal)
  }, [data, conditions, sortKey])

  // 資料日期誠實化：主顯示「資料日期（交易日）」而非 build 時間，落後太多天要醒目警告。
  const daysStale = useMemo(() => {
    if (!data?.data_date) return null
    return Math.floor((Date.now() - new Date(data.data_date).getTime()) / 86400000)
  }, [data])
  const stale = data && (daysStale === null || daysStale > 5 || data.fetch_ok === false)

  // 全市場可選產業清單（依檔數多寡排序）
  const industries = useMemo(() => {
    if (!data) return []
    const cnt = {}
    for (const s of data.stocks) cnt[s.industry] = (cnt[s.industry] || 0) + 1
    return Object.keys(cnt).sort((a, b) => cnt[b] - cnt[a])
  }, [data])

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
            <p className="subtitle">糾結轉強 × 法人連買 · 上市＋上櫃</p>
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

      {!data && !error && (
        <div className="center-state">
          <div className="spin" />
          載入資料中…
        </div>
      )}

      <Opportunities stocks={data?.stocks} onPick={setPicked} onCount={setOppCount} />

      {data && (
        <>
          {/* 手機常駐（sticky）篩選/排序工具列：條件數｜目前排序｜重設；點左側展開完整篩選面板 */}
          <div className="mobile-toolbar">
            <button className="mtb-btn" onClick={() => setPanelOpen(o => !o)}
              aria-expanded={panelOpen} aria-controls="cond-panel">
              <SlidersHorizontal size={16} strokeWidth={1.75} />條件<b>{activeConds}</b>
            </button>
            <span className="mtb-sort">排序<b>{SORT_LABELS[sortKey] || sortKey}</b></span>
            <button className="mtb-reset" onClick={resetAll}>
              <RotateCcw size={14} strokeWidth={1.75} />重設
            </button>
          </div>
          <ConditionPanel
            id="cond-panel"
            conditions={conditions}
            onChange={setConditions}
            total={data.count}
            shown={filtered.length}
            holderReady={!!data.holder_ready}
            industries={industries}
            open={panelOpen}
            onOpenChange={setPanelOpen}
          />
          <ResultTable
            key={`${sortKey}:${filtered.length}`}
            stocks={filtered}
            sortKey={sortKey}
            onSort={setSortKey}
            onPick={setPicked}
          />
        </>
      )}

      <StockChartModal stock={picked} onClose={closeModal} />

      <footer className="app-footer">
        資料來源：TWSE／TPEX 官方公開資料 · 僅供研究參考，非投資建議
      </footer>
    </div>
  )
}
