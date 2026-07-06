import { useMemo, useRef, useState } from 'react'
import type { HistoryRow } from '../lib/types'

export interface ChartSeries {
  ticker: string
  color: string
  rows: HistoryRow[]
}

interface Props {
  series: ChartSeries[]
  height?: number
}

const VIEW_W = 640
const PAD_LEFT = 44
const PAD_RIGHT = 56
const PAD_TOP = 16
const PAD_BOTTOM = 24

export default function PriceChart({ series, height = 260 }: Props) {
  const svgRef = useRef<SVGSVGElement>(null)
  const [hoverIdx, setHoverIdx] = useState<number | null>(null)

  const usable = series.filter((s) => s.rows.length >= 2)
  const plotWidth = VIEW_W - PAD_LEFT - PAD_RIGHT
  const plotHeight = height - PAD_TOP - PAD_BOTTOM
  const maxLen = Math.max(0, ...usable.map((s) => s.rows.length))

  const normalized = useMemo(
    () =>
      usable.map((s) => {
        const base = s.rows[0].close
        return {
          ...s,
          pct: s.rows.map((r) => ((r.close - base) / base) * 100),
        }
      }),
    [usable]
  )

  const allPct = normalized.flatMap((s) => s.pct)
  const minPct = allPct.length ? Math.min(...allPct, 0) : -1
  const maxPct = allPct.length ? Math.max(...allPct, 0) : 1
  const spanPct = maxPct - minPct || 1

  const xAt = (i: number, len: number) => PAD_LEFT + (len > 1 ? (i / (len - 1)) * plotWidth : 0)
  const yAt = (pct: number) => PAD_TOP + (1 - (pct - minPct) / spanPct) * plotHeight

  function handleMove(e: React.MouseEvent<SVGSVGElement>) {
    if (!svgRef.current || maxLen < 2) return
    const rect = svgRef.current.getBoundingClientRect()
    const px = ((e.clientX - rect.left) / rect.width) * VIEW_W
    const frac = Math.min(1, Math.max(0, (px - PAD_LEFT) / plotWidth))
    setHoverIdx(Math.round(frac * (maxLen - 1)))
  }

  if (!normalized.length) {
    return <div className="chart-empty">No history data available.</div>
  }

  const hoverX = hoverIdx !== null ? PAD_LEFT + (hoverIdx / (maxLen - 1)) * plotWidth : null

  return (
    <div className="price-chart">
      <div className="chart-legend">
        {normalized.map((s) => (
          <span key={s.ticker} className="legend-item">
            <span className="legend-swatch" style={{ background: s.color }} />
            {s.ticker}
          </span>
        ))}
      </div>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${VIEW_W} ${height}`}
        width="100%"
        height={height}
        onMouseMove={handleMove}
        onMouseLeave={() => setHoverIdx(null)}
        role="img"
        aria-label="Normalized price history comparison"
      >
        <line
          x1={PAD_LEFT}
          x2={VIEW_W - PAD_RIGHT}
          y1={yAt(0)}
          y2={yAt(0)}
          stroke="var(--line)"
          strokeWidth={1}
        />
        <text x={4} y={yAt(maxPct) + 4} className="chart-axis-label">
          {maxPct.toFixed(0)}%
        </text>
        <text x={4} y={yAt(minPct) + 4} className="chart-axis-label">
          {minPct.toFixed(0)}%
        </text>

        {hoverX !== null && (
          <line
            x1={hoverX}
            x2={hoverX}
            y1={PAD_TOP}
            y2={height - PAD_BOTTOM}
            stroke="var(--muted)"
            strokeWidth={1}
            strokeDasharray="3,3"
          />
        )}

        {normalized.map((s) => {
          const points = s.pct.map((p, i) => `${xAt(i, s.pct.length).toFixed(1)},${yAt(p).toFixed(1)}`)
          const lastIdx = s.pct.length - 1
          return (
            <g key={s.ticker}>
              <polyline
                points={points.join(' ')}
                fill="none"
                stroke={s.color}
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <circle cx={xAt(lastIdx, s.pct.length)} cy={yAt(s.pct[lastIdx])} r={3} fill={s.color} />
              <text
                x={xAt(lastIdx, s.pct.length) + 8}
                y={yAt(s.pct[lastIdx]) + 4}
                className="chart-end-label"
              >
                {s.ticker} {s.pct[lastIdx] >= 0 ? '+' : ''}
                {s.pct[lastIdx].toFixed(1)}%
              </text>
            </g>
          )
        })}
      </svg>
      {hoverIdx !== null && (
        <div className="chart-tooltip">
          {normalized.map((s) => {
            const idx = Math.min(hoverIdx, s.pct.length - 1)
            return (
              <div key={s.ticker} className="chart-tooltip-row">
                <span className="legend-swatch" style={{ background: s.color }} />
                <span>{s.ticker}</span>
                <span>{s.rows[idx]?.date}</span>
                <strong>
                  {s.pct[idx] >= 0 ? '+' : ''}
                  {s.pct[idx].toFixed(1)}%
                </strong>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
