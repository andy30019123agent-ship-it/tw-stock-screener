import { useEffect, useRef } from 'react'
import { createChart } from 'lightweight-charts'

function ma(closes, n) {
  const out = []
  for (let i = 0; i < closes.length; i++) {
    if (i + 1 < n) { out.push(null); continue }
    let s = 0
    for (let j = i + 1 - n; j <= i; j++) s += closes[j]
    out.push(s / n)
  }
  return out
}

export default function StockChartModal({ stock, onClose }) {
  const wrapRef = useRef(null)

  useEffect(() => {
    if (!stock || !stock.ohlc?.length) return
    const el = wrapRef.current
    el.innerHTML = ''

    const chart = createChart(el, {
      autoSize: true,
      layout: { background: { color: '#181f2e' }, textColor: '#8b97ab' },
      grid: {
        vertLines: { color: 'rgba(42,52,71,0.5)' },
        horzLines: { color: 'rgba(42,52,71,0.5)' },
      },
      rightPriceScale: { borderColor: '#2a3447' },
      timeScale: { borderColor: '#2a3447', timeVisible: false },
      crosshair: { mode: 0 },
    })

    const candle = chart.addCandlestickSeries({
      upColor: '#e0484b', downColor: '#16a34a',           // 台股紅漲綠跌
      borderUpColor: '#e0484b', borderDownColor: '#16a34a',
      wickUpColor: '#e0484b', wickDownColor: '#16a34a',
    })
    candle.setData(stock.ohlc.map(d => ({
      time: d.t, open: d.o, high: d.h, low: d.l, close: d.c,
    })))

    // 量（底部 20% 區域）
    const vol = chart.addHistogramSeries({
      priceScaleId: 'vol', priceFormat: { type: 'volume' },
    })
    chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } })
    vol.setData(stock.ohlc.map(d => ({
      time: d.t, value: d.v, color: d.c >= d.o ? 'rgba(224,72,75,0.4)' : 'rgba(22,163,74,0.4)',
    })))

    // 均線：MA5 / MA20 / MA60
    const closes = stock.ohlc.map(d => d.c)
    const times = stock.ohlc.map(d => d.t)
    const lines = [[5, '#f5b942'], [20, '#4f8cff'], [60, '#c79bff']]
    for (const [n, color] of lines) {
      const s = chart.addLineSeries({ color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false })
      const m = ma(closes, n)
      s.setData(times.map((t, i) => (m[i] == null ? null : { time: t, value: m[i] })).filter(Boolean))
    }

    chart.timeScale().fitContent()
    const onKey = e => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => { window.removeEventListener('keydown', onKey); chart.remove() }
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
          <span className="lg-ma5">MA5</span>
          <span className="lg-ma20">MA20</span>
          <span className="lg-ma60">MA60</span>
          <span className="sep">|</span>
          <span>外資連買 <b>{stock.foreign_streak}</b> 天</span>
          <span>投信連買 <b>{stock.trust_streak}</b> 天</span>
          <span>20日均量 <b>{stock.avg_vol_lots?.toLocaleString()}</b> 張</span>
        </div>
        <div className="tv-chart" ref={wrapRef} />
      </div>
    </div>
  )
}
