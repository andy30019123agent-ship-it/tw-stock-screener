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

  return (
    <div className="app">
      <header className="app-header">
        <h1>📈 台股電子選股</h1>
        <span className="updated">
          {data ? `資料更新：${data.updated}` : ''}
        </span>
      </header>

      {error && <div className="error">⚠️ {error}</div>}

      {!data && !error && <div className="loading">載入資料中…</div>}

      {data && (
        <>
          <ConditionPanel
            conditions={conditions}
            onChange={setConditions}
            total={data.count}
            shown={filtered.length}
          />
          <ResultTable
            stocks={filtered}
            sortKey={sortKey}
            onSort={setSortKey}
            onPick={setPicked}
          />
        </>
      )}

      <StockChartModal stock={picked} onClose={() => setPicked(null)} />

      <footer className="app-footer">
        資料來源：FinMind ＋ TradingView · 僅供研究參考，非投資建議
      </footer>
    </div>
  )
}
