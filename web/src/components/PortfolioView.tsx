import { useState } from 'react'
import { usePortfolio } from '../hooks/usePortfolio'
import { useQuotes } from '../hooks/useQuotes'
import ConcentrationCard from './ConcentrationCard'
import PortfolioWhatif from './PortfolioWhatif'
import PortfolioBenchmark from './PortfolioBenchmark'
import { money, num, pct } from '../lib/format'

interface Props {
  onExplain: () => void
}

function changeClass(value: number | null): string {
  if (value === null) return ''
  return value >= 0 ? 'quote-up' : 'quote-down'
}

export default function PortfolioView({ onExplain }: Props) {
  const { holdings, totalValue, totalDayChange, totalUnrealizedPl, concentration, loading, set, remove } = usePortfolio()
  const [ticker, setTicker] = useState('')
  const [mode, setMode] = useState<'shares' | 'dollars'>('shares')
  const [amount, setAmount] = useState('')
  const [costBasis, setCostBasis] = useState('')
  const quotes = useQuotes(ticker ? [ticker.toUpperCase()] : [])

  const livePrice = ticker ? (quotes[ticker.toUpperCase()]?.data?.price ?? null) : null
  const parsedAmount = parseFloat(amount)
  const previewShares =
    mode === 'dollars' && livePrice && parsedAmount > 0 ? parsedAmount / livePrice : mode === 'shares' ? parsedAmount : null

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!ticker || !previewShares || previewShares <= 0) return
    const parsedCostBasis = parseFloat(costBasis)
    await set(ticker.toUpperCase(), previewShares, parsedCostBasis > 0 ? parsedCostBasis : null)
    setAmount('')
    setCostBasis('')
  }

  return (
    <div className="portfolio-view">
      <div className="view-header">
        <h2>Portfolio</h2>
        <button className="chip" disabled={loading || holdings.length === 0} onClick={onExplain}>
          Explain my portfolio
        </button>
      </div>

      <div className="portfolio-totals">
        <div className="valuation-tile">
          <span className="strip-label">Total Value</span>
          <strong>{money(totalValue) ?? '$0'}</strong>
        </div>
        <div className="valuation-tile">
          <span className="strip-label">Day Change</span>
          <strong className={changeClass(totalDayChange)}>
            {totalDayChange !== null ? money(totalDayChange) : <span className="muted">—</span>}
          </strong>
        </div>
        <div className="valuation-tile">
          <span className="strip-label">Unrealized P&amp;L</span>
          <strong className={changeClass(totalUnrealizedPl)}>
            {totalUnrealizedPl !== null ? money(totalUnrealizedPl) : <span className="muted">no cost basis</span>}
          </strong>
        </div>
      </div>

      <form className="portfolio-form" onSubmit={submit}>
        <input
          type="text"
          placeholder="Ticker (any symbol)"
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          required
        />
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
        <input
          type="number"
          step="any"
          min="0"
          placeholder="Cost basis / share (optional)"
          value={costBasis}
          onChange={(e) => setCostBasis(e.target.value)}
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
              <th>Cost Basis</th>
              <th>Price</th>
              <th>Value</th>
              <th>Weight</th>
              <th>Day Change</th>
              <th>Unrealized P&amp;L</th>
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
                <td>{h.cost_basis !== null ? '$' + num(h.cost_basis, 2) : <span className="muted">—</span>}</td>
                <td>{h.price !== null ? '$' + num(h.price, 2) : <span className="muted">—</span>}</td>
                <td>{h.value !== null ? money(h.value) : <span className="muted">—</span>}</td>
                <td>{pct(h.weight) ?? <span className="muted">—</span>}</td>
                <td className={changeClass(h.day_change_pct)}>
                  {h.day_change_pct !== null ? `${h.day_change_pct >= 0 ? '+' : ''}${pct(h.day_change_pct)}` : '—'}
                </td>
                <td className={changeClass(h.unrealized_pl)}>
                  {h.unrealized_pl !== null ? (
                    `${money(h.unrealized_pl)} (${h.unrealized_pl_pct !== null && h.unrealized_pl_pct >= 0 ? '+' : ''}${pct(h.unrealized_pl_pct)})`
                  ) : (
                    <span className="muted">no cost basis</span>
                  )}
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
                <td colSpan={9} className="muted">
                  No holdings yet. Add one above.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <ConcentrationCard concentration={concentration} />

      <PortfolioBenchmark hasHoldings={holdings.length > 0} />
      <PortfolioWhatif holdings={holdings} />

      <div className="footnote">Market data may be delayed. Not investment advice.</div>
    </div>
  )
}
