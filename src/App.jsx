import { useState, useEffect, useMemo } from 'react'
import ConditionPanel from './components/ConditionPanel'
import ResultTable from './components/ResultTable'
import StockChartModal from './components/StockChartModal'
import Opportunities from './components/Opportunities'
import { DEFAULT_CONDITIONS, applyFilters, SORTS } from './lib/filters'

export default function App() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [conditions, setConditions] = useState(DEFAULT_CONDITIONS)
  const [sortKey, setSortKey] = useState('signal')
  const [picked, setPicked] = useState(null)

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
      <header className="app-header">
        <div className="brand">
          <h1>台股全市場選股</h1>
          <p className="subtitle">糾結轉強 × 法人連買 · 上市＋上櫃</p>
        </div>
        {data && (
          <span className="updated" title={`管線建置時間 ${data.updated}`}>
            <span className={`updated-dot${stale ? ' updated-dot-stale' : ''}`} />
            資料日期（交易日）{data.data_date || '—'}
          </span>
        )}
      </header>

      {error && <div className="banner banner-error" role="alert">{error}</div>}

      {data && stale && (
        <div className="banner banner-warn" role="alert">
          ⚠️ 資料可能未更新，最後交易日 <b>{data.data_date || '未知'}</b>
          {data.fetch_ok === false
            ? '（上次自動抓取最新交易日失敗，目前顯示的是沿用的舊資料）'
            : daysStale !== null && `（已經 ${daysStale} 天沒有新交易資料，請留意）`}
        </div>
      )}

      {!data && !error && <div className="loading">載入資料中…</div>}

      <Opportunities />

      {data && (
        <>
          <ConditionPanel
            conditions={conditions}
            onChange={setConditions}
            total={data.count}
            shown={filtered.length}
            holderReady={!!data.holder_ready}
            industries={industries}
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

      <StockChartModal stock={picked} onClose={() => setPicked(null)} />

      <footer className="app-footer">
        資料來源：TWSE／TPEX 官方公開資料 · 僅供研究參考，非投資建議
      </footer>
    </div>
  )
}
