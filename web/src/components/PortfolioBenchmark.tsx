import { useEffect, useState } from 'react'
import { getBenchmark } from '../lib/api'
import { getClientId } from '../lib/clientId'
import PriceChart from './PriceChart'
import type { BenchmarkResult, HistoryPeriod } from '../lib/types'

const PERIODS: HistoryPeriod[] = ['1mo', '3mo', '6mo', '1y']

export default function PortfolioBenchmark({ hasHoldings }: { hasHoldings: boolean }) {
  const [period, setPeriod] = useState<HistoryPeriod>('3mo')
  const [data, setData] = useState<BenchmarkResult | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!hasHoldings) return
    let cancelled = false
    setLoading(true)
    getBenchmark(getClientId(), period)
      .then((res) => {
        if (!cancelled) setData(res)
      })
      .catch(() => {
        if (!cancelled) setData(null)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [period, hasHoldings])

  if (!hasHoldings) return null

  const series = [
    { ticker: 'Portfolio', color: '#2a78d6', rows: data?.portfolio ?? [] },
    { ticker: 'SPY', color: '#8a8578', rows: data?.spy ?? [] },
  ]

  return (
    <div className="benchmark-panel">
      <div className="view-header">
        <div className="section-title">vs S&amp;P 500 (SPY)</div>
        <div className="period-pills">
          {PERIODS.map((p) => (
            <button key={p} className={`chip ${p === period ? 'active' : ''}`} onClick={() => setPeriod(p)}>
              {p}
            </button>
          ))}
        </div>
      </div>
      {loading && !data ? (
        <div className="muted">Loading…</div>
      ) : data?.portfolio && data.portfolio.length >= 2 ? (
        <>
          <PriceChart series={series} height={200} />
          <div className="footnote">
            Uses today's holdings/weights applied backward over the period (static, no rebalancing) —
            not a historical-weights-accurate backtest.
          </div>
        </>
      ) : (
        <div className="muted">Not enough price history to compare yet.</div>
      )}
    </div>
  )
}
