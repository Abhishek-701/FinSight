import { useState } from 'react'
import { useScreener } from '../hooks/useScreener'
import { money, num, pct } from '../lib/format'
import type { ScreenerRow } from '../lib/types'

type SortKey = keyof Pick<
  ScreenerRow,
  'revenue' | 'operating_margin' | 'net_margin' | 'revenue_growth_yoy' | 'roe' | 'market_cap' | 'ps_ratio' | 'price'
>

const COLUMNS: { key: SortKey; label: string; format: (v: number | null) => string | null }[] = [
  { key: 'revenue', label: 'Revenue', format: money },
  { key: 'operating_margin', label: 'Op Margin', format: (v) => pct(v) },
  { key: 'net_margin', label: 'Net Margin', format: (v) => pct(v) },
  { key: 'revenue_growth_yoy', label: 'Rev Growth YoY', format: (v) => pct(v) },
  { key: 'roe', label: 'ROE', format: (v) => pct(v) },
  { key: 'market_cap', label: 'Mkt Cap', format: money },
  { key: 'ps_ratio', label: 'P/S', format: (v) => num(v, 1) },
  { key: 'price', label: 'Price', format: (v) => (v === null ? null : '$' + num(v, 2)) },
]

function nullNote(ticker: string, key: SortKey): string {
  if (ticker === 'JPM' && key === 'operating_margin') {
    return 'Not comparable — JPMorgan reports net revenue after interest expense, no comparable operating income line.'
  }
  return 'Not available in this filing.'
}

interface Props {
  onCompare: (tickers: string[]) => void
}

export default function ScreenerView({ onCompare }: Props) {
  const { rows, asOf, loading, error } = useScreener()
  const [sortKey, setSortKey] = useState<SortKey>('market_cap')
  const [sortDesc, setSortDesc] = useState(true)
  const [selected, setSelected] = useState<string[]>([])

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDesc((d) => !d)
    } else {
      setSortKey(key)
      setSortDesc(true)
    }
  }

  function toggleSelect(ticker: string) {
    setSelected((prev) => {
      if (prev.includes(ticker)) return prev.filter((t) => t !== ticker)
      if (prev.length >= 3) return prev
      return [...prev, ticker]
    })
  }

  const sorted = [...rows].sort((a, b) => {
    const av = a[sortKey]
    const bv = b[sortKey]
    if (av === null && bv === null) return 0
    if (av === null) return 1
    if (bv === null) return -1
    return sortDesc ? bv - av : av - bv
  })

  return (
    <div className="screener-view">
      <div className="view-header">
        <h2>Screener</h2>
        {asOf && <span className="muted">As of {new Date(asOf).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>}
      </div>
      {error && <p className="muted">Screener data unavailable: {error}</p>}
      {loading && !rows.length ? (
        <p className="muted">Loading screener...</p>
      ) : (
        <div className="table-scroll">
          <table className="screener-table">
            <thead>
              <tr>
                <th></th>
                <th>Ticker</th>
                {COLUMNS.map((col) => (
                  <th key={col.key} onClick={() => toggleSort(col.key)} className="sortable">
                    {col.label}
                    {sortKey === col.key ? (sortDesc ? ' ▼' : ' ▲') : ''}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((row) => (
                <tr key={row.ticker}>
                  <td>
                    <input
                      type="checkbox"
                      checked={selected.includes(row.ticker)}
                      onChange={() => toggleSelect(row.ticker)}
                      disabled={!selected.includes(row.ticker) && selected.length >= 3}
                      aria-label={`Select ${row.ticker} for comparison`}
                    />
                  </td>
                  <td>
                    <b>{row.ticker}</b>
                    <span className="muted"> {row.company}</span>
                  </td>
                  {COLUMNS.map((col) => {
                    const raw = row[col.key]
                    const formatted = col.format(raw)
                    return (
                      <td key={col.key}>
                        {formatted === null ? (
                          <span className="muted" title={nullNote(row.ticker, col.key)}>
                            —
                          </span>
                        ) : (
                          formatted
                        )}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="screener-actions">
        <button
          className="chip"
          disabled={selected.length < 2}
          onClick={() => onCompare(selected)}
        >
          Compare selected ({selected.length})
        </button>
      </div>
      <div className="footnote">Market data may be delayed. Not investment advice.</div>
    </div>
  )
}
