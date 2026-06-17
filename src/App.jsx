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

  // 抓太少判斷：實際檔數低於清單應有的 90% 視為資料可能不完整
  const expected = data?.expected || 0
  const incomplete = expected > 0 && data.count < expected * 0.9

  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <h1>台股電子選股</h1>
          <p className="subtitle">糾結轉強 × 法人連買</p>
        </div>
        {data && (
          <span className="updated">
            <span className="updated-dot" />
            資料更新 {data.updated}
          </span>
        )}
      </header>

      {error && <div className="banner banner-error" role="alert">{error}</div>}

      {data && incomplete && (
        <div className="banner banner-warn" role="status">
          本次只更新 <b>{data.count}</b> ／ {expected} 檔，部分股票抓取失敗，資料可能不完整，請稍後再看或等下次自動更新。
        </div>
      )}

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
