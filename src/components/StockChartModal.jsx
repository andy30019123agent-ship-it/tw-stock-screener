import { useEffect, useRef, useState, useCallback } from 'react'
import { createChart, LineStyle } from 'lightweight-charts'
import { X } from 'lucide-react'

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

// 讀取 CSS token 的實際色值（lightweight-charts 是 canvas 繪圖，無法直接吃 CSS var()，
// 但顏色本身仍要來自 App.css 的 :root token，維持單一色彩來源）
const cssVar = (name) => (typeof document !== 'undefined'
  ? getComputedStyle(document.documentElement).getPropertyValue(name).trim() : '')

function hexToRgba(hex, a) {
  const h = hex.replace('#', '')
  const r = parseInt(h.slice(0, 2), 16)
  const g = parseInt(h.slice(2, 4), 16)
  const b = parseInt(h.slice(4, 6), 16)
  return `rgba(${r},${g},${b},${a})`
}

// 時間範圍（交易日數）：半年 = 給滿全部可用歷史（chart json 約 110 根）。預設半年、日 K。
const RANGES = [['1m', '近1月', 22], ['3m', '近3月', 66], ['6m', '半年', 9999]]
const DEFAULT_RANGE = '6m'

// 十字準星日期格式化：資料的 time 是 'YYYY-MM-DD' 字串，lightweight-charts 可能回字串或 BusinessDay 物件
function fmtDate(t) {
  if (!t) return ''
  if (typeof t === 'string') return t.replace(/-/g, '/')
  if (typeof t === 'object' && t.year) return `${t.year}/${t.month}/${t.day}`
  return String(t)
}

function applyRange(chart, len, range) {
  const bars = RANGES.find(r => r[0] === range)?.[2] ?? 9999
  const from = Math.max(0, len - bars)
  chart.timeScale().setVisibleLogicalRange({ from: from - 0.5, to: len - 0.5 })
}

export default function StockChartModal({ stock, onClose }) {
  const wrapRef = useRef(null)
  const modalRef = useRef(null)
  const lastActiveRef = useRef(null)       // 關閉後把 focus 還原到開窗前的元素
  const chartRef = useRef(null)            // { chart, candle }：range 切換時直接更新可視範圍、不重建
  const [status, setStatus] = useState('loading')  // loading | ready | empty | error
  const [ohlc, setOhlc] = useState(null)
  const [range, setRange] = useState(DEFAULT_RANGE)
  const [readout, setReadout] = useState(null)     // 十字準星讀數 {date,o,h,l,c,up}
  const [levels, setLevels] = useState(null)       // 支撐/壓力 {support, resistance}

  // K 線按需載入（charts/<id>.json）；把「載入中／無資料／載入失敗」分成三態
  const load = useCallback(() => {
    if (!stock) return
    setStatus('loading'); setOhlc(null); setReadout(null)
    let alive = true
    fetch(`${import.meta.env.BASE_URL}data/charts/${stock.id}.json`)
      .then(r => (r.ok ? r.json() : Promise.reject(new Error('http'))))
      .then(d => {
        if (!alive) return
        const arr = d?.ohlc || []
        setOhlc(arr); setStatus(arr.length ? 'ready' : 'empty')
      })
      .catch(() => { if (alive) { setOhlc([]); setStatus('error') } })
    return () => { alive = false }
  }, [stock])

  useEffect(() => { const cancel = load(); return cancel }, [load])

  // 建圖：只在資料 ready 時建；支撐/壓力就地由 ohlc 算（避免多一次 state 觸發重建）
  useEffect(() => {
    if (status !== 'ready' || !ohlc?.length) return
    const el = wrapRef.current
    el.innerHTML = ''

    const inkMuted = cssVar('--ink-muted')
    const border = cssVar('--border')
    const up = cssVar('--up')
    const down = cssVar('--down')
    const primary = cssVar('--primary')
    const ma5Color = cssVar('--accent')
    const ma20Color = cssVar('--primary')
    const ma60Color = cssVar('--deco-lavender')

    const chart = createChart(el, {
      autoSize: true,
      layout: { background: { color: 'transparent' }, textColor: inkMuted, fontFamily: 'inherit' },
      grid: { vertLines: { color: border }, horzLines: { color: border } },
      rightPriceScale: { borderColor: border },
      timeScale: { borderColor: border, timeVisible: false },
      crosshair: { mode: 0 },
      localization: {
        locale: 'zh-TW',
        // 底部時間軸用簡短 M/D（跨年才顯示年）
        timeFormatter: t => (typeof t === 'object' && t.year ? `${t.month}/${t.day}` : fmtDate(t)),
      },
    })

    // 台股漲紅跌綠
    const candle = chart.addCandlestickSeries({
      upColor: up, downColor: down, borderUpColor: up, borderDownColor: down,
      wickUpColor: up, wickDownColor: down,
    })
    candle.setData(ohlc.map(d => ({ time: d.t, open: d.o, high: d.h, low: d.l, close: d.c })))

    const vol = chart.addHistogramSeries({ priceScaleId: 'vol', priceFormat: { type: 'volume' } })
    chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } })
    vol.setData(ohlc.map(d => ({ time: d.t, value: d.v, color: d.c >= d.o ? hexToRgba(up, 0.4) : hexToRgba(down, 0.4) })))

    const closes = ohlc.map(d => d.c)
    const times = ohlc.map(d => d.t)
    for (const [n, color] of [[5, ma5Color], [20, ma20Color], [60, ma60Color]]) {
      const s = chart.addLineSeries({ color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false })
      const m = ma(closes, n)
      s.setData(times.map((t, i) => (m[i] == null ? null : { time: t, value: m[i] })).filter(Boolean))
    }

    // 支撐／壓力：近 60 個交易日的低/高，畫成水平參考線並標數值（粉色虛線＝參考位，非漲跌語意）
    const recent = ohlc.slice(-60)
    const resistance = Math.round(Math.max(...recent.map(d => d.h)) * 100) / 100
    const support = Math.round(Math.min(...recent.map(d => d.l)) * 100) / 100
    setLevels({ support, resistance })
    candle.createPriceLine({ price: resistance, color: primary, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: '壓力' })
    candle.createPriceLine({ price: support, color: primary, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: '支撐' })

    // 十字準星讀數：手指點到哪天就顯示那天日期＋開高低收
    chart.subscribeCrosshairMove(param => {
      const d = param.time ? param.seriesData.get(candle) : null
      if (!d) { setReadout(null); return }
      setReadout({ date: fmtDate(param.time), o: d.open, h: d.high, l: d.low, c: d.close, up: d.close >= d.open })
    })

    chartRef.current = { chart, candle }
    applyRange(chart, ohlc.length, range)
    return () => { chart.remove(); chartRef.current = null }
    // range 不放 deps：切範圍走下面那個 effect、不重建圖
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, ohlc])

  // 切換時間範圍：直接更新可視範圍，不重建圖
  useEffect(() => {
    const c = chartRef.current
    if (c && ohlc?.length) applyRange(c.chart, ohlc.length, range)
  }, [range, ohlc])

  // 無障礙：focus 移入、Esc 關、Tab focus trap、關閉還原 focus；並鎖背景捲動
  useEffect(() => {
    if (!stock) return
    lastActiveRef.current = document.activeElement
    modalRef.current?.querySelector('.modal-close')?.focus()
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const onKey = e => {
      if (e.key === 'Escape') { onClose(); return }
      if (e.key !== 'Tab') return
      const node = modalRef.current
      if (!node) return
      const items = Array.from(
        node.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')
      ).filter(el => !el.disabled && el.offsetParent !== null)
      if (!items.length) return
      const first = items[0], last = items[items.length - 1]
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = prevOverflow
      lastActiveRef.current?.focus?.()
    }
  }, [stock, onClose])

  // 下滑關閉：只綁在頂部把手（不碰圖表，免與 K 線拖動衝突）
  const dragY = useRef(null)
  const onHandleStart = e => { dragY.current = e.touches[0].clientY }
  const onHandleMove = e => {
    if (dragY.current == null) return
    const dy = e.touches[0].clientY - dragY.current
    if (dy > 70) { dragY.current = null; onClose() }
  }
  const onHandleEnd = () => { dragY.current = null }

  if (!stock) return null
  const priceUp = stock.change >= 0

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" ref={modalRef} onClick={e => e.stopPropagation()}
        role="dialog" aria-modal="true" aria-labelledby="modal-title">
        <div className="modal-handle" onTouchStart={onHandleStart} onTouchMove={onHandleMove} onTouchEnd={onHandleEnd}
          aria-hidden="true"><span /></div>
        <div className="modal-head">
          <div className="modal-title" id="modal-title">
            <span className="m-id">{stock.id}</span>
            <span className="m-name">{stock.name}</span>
            <span className={`m-price ${priceUp ? 'up' : 'down'}`}>
              {stock.close} <small>{priceUp ? '+' : ''}{stock.change_pct}%</small>
            </span>
          </div>
          <button className="modal-close" onClick={onClose} aria-label="關閉"><X size={18} strokeWidth={1.75} /></button>
        </div>

        {/* 圖例 ＋ 時間範圍切換（同一列/相鄰列，不橫向捲動）*/}
        <div className="modal-toolbar">
          <div className="ma-legend">
            <span className="lg-ma5">MA5</span>
            <span className="lg-ma20">MA20</span>
            <span className="lg-ma60">MA60</span>
          </div>
          <div className="range-seg" role="group" aria-label="時間範圍">
            {RANGES.map(([k, label]) => (
              <button key={k} className={range === k ? 'on' : ''} aria-pressed={range === k}
                onClick={() => setRange(k)}>{label}</button>
            ))}
          </div>
        </div>

        {/* 籌碼摘要：固定三欄、換行不橫捲 */}
        <div className="modal-stats">
          <span>外資連買 <b>{stock.foreign_streak}</b> 天</span>
          <span>投信連買 <b>{stock.trust_streak}</b> 天</span>
          <span>20日均量 <b>{stock.avg_vol_lots?.toLocaleString() ?? '—'}</b> 張</span>
        </div>

        {/* 參考價位：支撐／壓力＋MA20＋近20高，最後獨立一句「參考位非建議」 */}
        <div className="modal-levels">
          <span>支撐 <b>{levels ? levels.support : '—'}</b></span>
          <span>壓力 <b>{levels ? levels.resistance : '—'}</b></span>
          <span>MA20 <b>{stock.ma20 ?? '—'}</b></span>
          <span>近20高 <b>{stock.recent_high20 ?? '—'}</b></span>
          <span className="lv-note">支撐＝近60日低、壓力＝近60日高，參考位非建議</span>
        </div>

        <div className="tv-chart">
          <div className="tv-canvas" ref={wrapRef} />
          {readout && (
            <div className="chart-readout">
              <span className="ro-date">{readout.date}</span>
              <span>開 <b>{readout.o}</b></span>
              <span>高 <b>{readout.h}</b></span>
              <span>低 <b>{readout.l}</b></span>
              <span className={readout.up ? 'up' : 'down'}>收 <b>{readout.c}</b></span>
            </div>
          )}
          {status === 'loading' && <div className="chart-msg">載入 K 線中…</div>}
          {status === 'empty' && <div className="chart-msg">此標的暫無 K 線資料</div>}
          {status === 'error' && (
            <div className="chart-msg">載入失敗
              <button className="chart-retry" onClick={load}>重試</button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
