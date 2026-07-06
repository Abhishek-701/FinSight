import { useState } from 'react'
import { useScreener } from '../hooks/useScreener'
import { useHistories } from '../hooks/useHistories'
import PriceChart from './PriceChart'
import { money, num, pct } from '../lib/format'
import type { HistoryPeriod, ScreenerRow } from '../lib/types'

const SERIES_COLORS = ['#2a78d6', '#1baf7a', '#eda100']
const PERIODS: HistoryPeriod[] = ['1mo', '3mo', '6mo', '1y']

const METRIC_ROWS: { key: keyof ScreenerRow; label: string; format: (v: number | null) => string | null; higherIsBetter: boolean }[] = [
  { key: 'revenue', label: 'Revenue', format: money, higherIsBetter: true },
  { key: 'operating_margin', label: 'Operating Margin', format: (v) => pct(v), higherIsBetter: true },
  { key: 'net_margin', label: 'Net Margin', format: (v) => pct(v), higherIsBetter: true },
  { key: 'revenue_growth_yoy', label: 'Revenue Growth YoY', format: (v) => pct(v), higherIsBetter: true },
  { key: 'roe', label: 'ROE', format: (v) => pct(v), higherIsBetter: true },
  { key: 'market_cap', label: 'Market Cap', format: money, higherIsBetter: true },
  { key: 'ps_ratio', label: 'P/S Ratio', format: (v) => num(v, 1), higherIsBetter: false },
]

interface Props {
  tickers: string[]
}

export default function CompareView({ tickers }: Props) {
  const { rows } = useScreener()
  const [period, setPeriod] = useState<HistoryPeriod>('3mo')
  const { histories } = useHistories(tickers, period)

  const selectedRows = tickers.map((t) => rows.find((r) => r.ticker === t)).filter((r): r is ScreenerRow => !!r)

  if (!tickers.length) {
    return (
      <div className="compare-view">
        <h2>Compare</h2>
        <p className="muted">Select 2-3 companies from the Screener to compare them here.</p>
      </div>
    )
  }

  const series = tickers.map((ticker, i) => ({
    ticker,
    color: SERIES_COLORS[i % SERIES_COLORS.length],
    rows: histories[ticker] || [],
  }))

  return (
    <div className="compare-view">
      <div className="view-header">
        <h2>Compare</h2>
        <div className="period-pills">
          {PERIODS.map((p) => (
            <button key={p} className={`chip ${p === period ? 'active' : ''}`} onClick={() => setPeriod(p)}>
              {p}
            </button>
          ))}
        </div>
      </div>

      <PriceChart series={series} />

      <div className="table-scroll">
        <table className="compare-table">
          <thead>
            <tr>
              <th>Metric</th>
              {selectedRows.map((row, i) => (
                <th key={row.ticker}>
                  <span className="legend-swatch" style={{ background: SERIES_COLORS[i % SERIES_COLORS.length] }} />
                  {row.ticker}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {METRIC_ROWS.map((metric) => {
              const values = selectedRows.map((r) => r[metric.key] as number | null)
              const comparable = values.filter((v): v is number => v !== null)
              const best = comparable.length
                ? metric.higherIsBetter
                  ? Math.max(...comparable)
                  : Math.min(...comparable)
                : null
              return (
                <tr key={metric.key}>
                  <td>{metric.label}</td>
                  {values.map((v, i) => {
                    const formatted = metric.format(v)
                    const isBest = best !== null && v === best && comparable.length > 1
                    return (
                      <td key={selectedRows[i].ticker} className={isBest ? 'best-value' : ''}>
                        {formatted === null ? <span className="muted">—</span> : formatted}
                      </td>
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <div className="footnote">Market data may be delayed. Not investment advice.</div>
    </div>
  )
}
