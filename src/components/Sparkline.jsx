export default function Sparkline({ data, width = 88, height = 28 }) {
  if (!data || data.length < 2) return <svg width={width} height={height} />
  const min = Math.min(...data)
  const max = Math.max(...data)
  const range = max - min || 1
  const step = width / (data.length - 1)
  const pts = data.map((v, i) => {
    const x = i * step
    const y = height - ((v - min) / range) * (height - 4) - 2
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
  const up = data[data.length - 1] >= data[0]
  return (
    <svg width={width} height={height} className="spark">
      <polyline points={pts} fill="none" className={up ? 'spark-up' : 'spark-down'} strokeWidth="1.5" />
    </svg>
  )
}
