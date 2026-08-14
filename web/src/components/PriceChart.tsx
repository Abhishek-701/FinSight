import { useEffect, useMemo, useRef } from 'react'
import { ColorType, CrosshairMode, LineSeries, createChart } from 'lightweight-charts'
import type { HistoryRow } from '../lib/types'

export interface ChartSeries {
  ticker: string
  color: string
  rows: HistoryRow[]
}

interface Props {
  series: ChartSeries[]
  height?: number
  mode?: 'percent' | 'price'
  variant?: 'panel' | 'embedded'
}

function toLineData(rows: HistoryRow[], mode: 'percent' | 'price'): { time: string; value: number }[] {
  const byDate = new Map<string, number>()
  for (const row of rows) {
    if (!row.date || typeof row.close !== 'number' || !Number.isFinite(row.close)) continue
    byDate.set(row.date.slice(0, 10), row.close)
  }
  const dates = [...byDate.keys()].sort()
  const base = dates.length ? byDate.get(dates[0]) ?? 0 : 0
  return dates.map((time) => {
    const close = byDate.get(time) ?? 0
    const value = mode === 'percent' && base ? ((close - base) / base) * 100 : close
    return { time, value }
  })
}

export default function PriceChart({
  series,
  height = 260,
  mode = 'percent',
  variant = 'panel',
}: Props) {
  const hostRef = useRef<HTMLDivElement>(null)
  const packed = JSON.stringify(series.map((s) => ({ ticker: s.ticker, color: s.color, rows: s.rows })))
  const plot = useMemo(() => {
    const parsed = JSON.parse(packed) as ChartSeries[]
    return parsed
      .map((s) => ({ ticker: s.ticker, color: s.color, data: toLineData(s.rows, mode) }))
      .filter((s) => s.data.length >= 2)
  }, [packed, mode])

  useEffect(() => {
    const el = hostRef.current
    if (!el || !plot.length) return

    const chart = createChart(el, {
      width: el.clientWidth || 640,
      height,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#7a766d',
        fontFamily: 'inherit',
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: '#e7e1d6' },
        horzLines: { color: '#e7e1d6' },
      },
      crosshair: { mode: CrosshairMode.Magnet },
      rightPriceScale: { borderColor: '#e7e1d6' },
      timeScale: { borderColor: '#e7e1d6' },
      localization: {
        priceFormatter: (value: number) =>
          mode === 'percent' ? `${value >= 0 ? '+' : ''}${value.toFixed(1)}%` : value.toFixed(2),
      },
    })

    for (const line of plot) {
      const api = chart.addSeries(LineSeries, {
        color: line.color,
        lineWidth: 2,
        title: line.ticker,
      })
      api.setData(line.data)
    }
    chart.timeScale().fitContent()

    const ro = new ResizeObserver(() => {
      chart.applyOptions({ width: el.clientWidth, height })
    })
    ro.observe(el)

    return () => {
      ro.disconnect()
      chart.remove()
    }
  }, [plot, height, mode])

  if (!plot.length) {
    return <div className="chart-empty">No history data available.</div>
  }

  return (
    <div className={variant === 'embedded' ? 'price-chart price-chart-embedded' : 'price-chart'}>
      <div className="chart-legend">
        {plot.map((s) => (
          <span key={s.ticker} className="legend-item">
            <span className="legend-swatch" style={{ background: s.color }} />
            {s.ticker}
          </span>
        ))}
      </div>
      <div ref={hostRef} className="chart-host" style={{ height }} />
    </div>
  )
}
