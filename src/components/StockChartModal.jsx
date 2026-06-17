import { useEffect, useRef } from 'react'

// 用 TradingView 官方免費「進階圖表」widget 顯示個股完整 K 線
export default function StockChartModal({ stock, onClose }) {
  const containerRef = useRef(null)

  useEffect(() => {
    if (!stock) return
    const exchange = stock.market === 'tpex' ? 'TPEX' : 'TWSE'
    const symbol = `${exchange}:${stock.id}`
    const container = containerRef.current
    container.innerHTML = ''

    const script = document.createElement('script')
    script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js'
    script.async = true
    script.innerHTML = JSON.stringify({
      symbol,
      interval: 'D',
      timezone: 'Asia/Taipei',
      theme: 'light',
      style: '1',
      locale: 'zh_TW',
      hide_side_toolbar: false,
      allow_symbol_change: false,
      studies: ['MASimple@tv-basicstudies'],
      autosize: true,
    })
    container.appendChild(script)

    const onKey = e => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [stock, onClose])

  if (!stock) return null
  const up = stock.change >= 0

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-head">
          <div className="modal-title">
            <span className="m-id">{stock.id}</span>
            <span className="m-name">{stock.name}</span>
            <span className={`m-price ${up ? 'up' : 'down'}`}>
              {stock.close} <small>{up ? '+' : ''}{stock.change_pct}%</small>
            </span>
          </div>
          <button className="modal-close" onClick={onClose} aria-label="關閉">✕</button>
        </div>
        <div className="modal-chips">
          <span>外資連買 <b>{stock.foreign_streak}</b> 天</span>
          <span>投信連買 <b>{stock.trust_streak}</b> 天</span>
          <span>MA20 {stock.ma20}</span>
          <span>MA60 {stock.ma60}</span>
        </div>
        <div className="tv-chart" ref={containerRef} />
      </div>
    </div>
  )
}
