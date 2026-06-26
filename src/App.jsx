import { useState, useEffect, useMemo } from 'react'
import ConditionPanel from './components/ConditionPanel'
import ResultTable from './components/ResultTable'
import StockChartModal from './components/StockChartModal'
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
          <span className="updated">
            <span className="updated-dot" />
            資料更新 {data.updated}
          </span>
        )}
      </header>

      {error && <div className="banner banner-error" role="alert">{error}</div>}

      {!data && !error && <div className="loading">載入資料中…</div>}

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
