import { useState } from 'react'
import { postWhatif } from '../lib/api'
import { getClientId } from '../lib/clientId'
import { money, pct } from '../lib/format'
import type { PortfolioItem, WhatifResult } from '../lib/types'

interface Props {
  holdings: PortfolioItem[]
}

export default function PortfolioWhatif({ holdings }: Props) {
  const [ticker, setTicker] = useState('')
  const [delta, setDelta] = useState('')
  const [result, setResult] = useState<WhatifResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    const deltaShares = parseFloat(delta)
    if (!ticker || !deltaShares) return
    setLoading(true)
    setError(null)
    try {
      const res = await postWhatif(getClientId(), [{ ticker: ticker.toUpperCase(), delta_shares: deltaShares }])
      setResult(res)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to simulate trade')
    } finally {
      setLoading(false)
    }
  }

  if (!holdings.length) return null

  return (
    <div className="whatif-panel">
      <div className="section-title">What If</div>
      <form className="whatif-form" onSubmit={submit}>
        <select value={ticker} onChange={(e) => setTicker(e.target.value)} required>
          <option value="">Ticker...</option>
          {holdings.map((h) => (
            <option key={h.ticker} value={h.ticker}>
              {h.ticker}
            </option>
          ))}
        </select>
        <input
          type="number"
          step="any"
          placeholder="+/- shares (e.g. 10 or -5)"
          value={delta}
          onChange={(e) => setDelta(e.target.value)}
        />
        <button type="submit" className="ask" disabled={loading || !ticker || !delta}>
          {loading ? 'Simulating…' : 'Simulate'}
        </button>
      </form>
      {error && <div className="ingest-error">{error}</div>}
      {result && (
        <div className="whatif-result">
          <div className="valuation-grid">
            <div className="valuation-tile">
              <span className="strip-label">Total Value</span>
              <strong>
                {money(result.before.total_value)} → {money(result.after.total_value)}
              </strong>
            </div>
            {result.before.concentration && result.after.concentration && (
              <div className="valuation-tile">
                <span className="strip-label">HHI</span>
                <strong>
                  {result.before.concentration.hhi.toLocaleString()} → {result.after.concentration.hhi.toLocaleString()}
                </strong>
                <span className="muted">
                  {result.before.concentration.band} → {result.after.concentration.band}
                </span>
              </div>
            )}
          </div>
          <div className="whatif-holdings">
            {result.after.holdings.map((h) => (
              <div key={h.ticker} className="whatif-holding-row">
                <b>{h.ticker}</b>
                <span>{pct(h.weight) ?? '—'} of portfolio after</span>
              </div>
            ))}
          </div>
          <div className="footnote">Simulation only — nothing was bought or sold.</div>
        </div>
      )}
    </div>
  )
}
