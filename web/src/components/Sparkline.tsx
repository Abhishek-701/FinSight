import type { HistoryRow } from '../lib/types'

interface Props {
  rows: HistoryRow[]
  width?: number
  height?: number
}

export default function Sparkline({ rows, width = 70, height = 22 }: Props) {
  if (!rows || rows.length < 2) {
    return <svg width={width} height={height} aria-hidden="true" />
  }

  const closes = rows.map((r) => r.close)
  const min = Math.min(...closes)
  const max = Math.max(...closes)
  const span = max - min || 1
  const pad = 2
  const stepX = (width - pad * 2) / (closes.length - 1)

  const points = closes.map((close, i) => {
    const x = pad + i * stepX
    const y = pad + (1 - (close - min) / span) * (height - pad * 2)
    return `${x.toFixed(1)},${y.toFixed(1)}`
  })

  const changePercent = ((closes[closes.length - 1] - closes[0]) / closes[0]) * 100
  const positive = changePercent >= 0
  const stroke = positive ? 'var(--green)' : 'var(--red)'
  const label = `${positive ? 'up' : 'down'} ${Math.abs(changePercent).toFixed(1)}% over period`

  return (
    <svg width={width} height={height} role="img" aria-label={label}>
      <title>{label}</title>
      <polyline
        points={points.join(' ')}
        fill="none"
        stroke={stroke}
        strokeWidth={1.75}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
