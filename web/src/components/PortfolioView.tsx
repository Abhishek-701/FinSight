import { useState } from 'react'
import { usePortfolio } from '../hooks/usePortfolio'
import { useQuotes } from '../hooks/useQuotes'
import { money, num, pct } from '../lib/format'

interface Props {
  companies: Record<string, string>
}

export default function PortfolioView({ companies }: Props) {
  const { holdings, totalValue, loading, set, remove } = usePortfolio()
  const [ticker, setTicker] = useState('')
  const [mode, setMode] = useState<'shares' | 'dollars'>('shares');
  const [amount, setAmount] = useState('')
  const quotes = useQuotes(ticker ? [ticker] : [])

  const livePrice = ticker ? quotes[ticker]?.data?.price ?? null : null
  const parsedAmount = parseFloat(amount)
  const previewShares =
    mode === 'dollars' && livePrice && parsedAmount > 0 ? parsedAmount / livePrice : mode === 'shares' ? parsedAmount : null

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!ticker || !previewShares || previewShares <= 0) return
    await set(ticker, previewShares)
    setAmount('')
  }

  const tickerOptions = Object.entries(companies)

  return (
    <div className="portfolio-view">
      <div className="view-header">
        <h2>Portfolio</h2>
        <span className="total-value">{money(totalValue) ?? '$0'}</span>
      </div>

      <form className="portfolio-form" onSubmit={submit}>
        <select value={ticker} onChange={(e) => setTicker(e.target.value)} required>
          <option value="" disabled>
            Select company
          </option>
          {tickerOptions.map(([t, name]) => (
            <option key={t} value={t}>
              {t} — {name}
            </option>
          ))}
        </select>
        <div className="mode-toggle">
          <button type="button" className={mode === 'shares' ? 'active' : ''} onClick={() => setMode('shares')}>
            Shares
          </button>
          <button type="button" className={mode === 'dollars' ? 'active' : ''} onClick={() => setMode('dollars')}>
            Dollars
          </button>
        </div>
        <input
          type="number"
          step="any"
          min="0"
          placeholder={mode === 'shares' ? 'Number of shares' : 'Dollar amount'}
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
        />
        <button type="submit" className="ask" disabled={!ticker || !previewShares || previewShares <= 0}>
          Add
        </button>
        {mode === 'dollars' && ticker && (
          <span className="muted preview-note">
            {!livePrice
              ? 'fetching live price...'
              : previewShares && previewShares > 0
                ? `≈ ${num(previewShares, 4)} shares @ $${num(livePrice, 2)}`
                : `@ $${num(livePrice, 2)} per share`}
          </span>
        )}
      </form>

      {!loading && holdings.length > 0 && (
        <div className="allocation-bar">
          {holdings.map((h, i) => (
            <div
              key={h.ticker}
              className="allocation-segment"
              style={{
                width: `${(h.weight ?? 0) * 100}%`,
                background: `hsl(${(i * 47) % 360}, 55%, 55%)`,
              }}
              title={`${h.ticker}: ${pct(h.weight) ?? '—'}`}
            />
          ))}
        </div>
      )}

      <div className="table-scroll">
        <table className="portfolio-table">
          <thead>
            <tr>
              <th>Ticker</th>
              <th>Shares</th>
              <th>Price</th>
              <th>Value</th>
              <th>Weight</th>
              <th>Change</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {holdings.map((h) => (
              <tr key={h.ticker}>
                <td>
                  <b>{h.ticker}</b>
                  <span className="muted"> {h.company}</span>
                </td>
                <td>{num(h.shares, 4)}</td>
                <td>{h.price !== null ? '$' + num(h.price, 2) : <span className="muted">—</span>}</td>
                <td>{h.value !== null ? money(h.value) : <span className="muted">—</span>}</td>
                <td>{pct(h.weight) ?? <span className="muted">—</span>}</td>
                <td className={h.change_percent !== null && h.change_percent >= 0 ? 'quote-up' : 'quote-down'}>
                  {h.change_percent !== null ? `${h.change_percent >= 0 ? '+' : ''}${h.change_percent.toFixed(2)}%` : '—'}
                </td>
                <td>
                  <button className="clear" type="button" onClick={() => remove(h.ticker)}>
                    Remove
                  </button>
                </td>
              </tr>
            ))}
            {!loading && holdings.length === 0 && (
              <tr>
                <td colSpan={7} className="muted">
                  No holdings yet. Add one above.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="footnote">Market data may be delayed. Not investment advice.</div>
    </div>
  )
}
