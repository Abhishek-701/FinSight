import type { InsightState } from '../hooks/useInsight'
import NewsPanel from './NewsPanel'
import PriceChart from './PriceChart'
import ResultCard from './ResultCard'
import { money, num, pct } from '../lib/format'

const RANK_LABELS: Record<string, string> = {
  operating_margin: 'Operating Margin',
  net_margin: 'Net Margin',
  revenue_growth_yoy: 'Revenue Growth',
  roe: 'ROE',
}

function QuoteStrip({ state }: { state: InsightState }) {
  const { card } = state
  if (!card) return null
  const quote = card.quote
  const changePct = quote?.change_percent ?? null
  const positive = (changePct ?? 0) >= 0
  return (
    <div className="market-strip">
      {quote ? (
        <>
          <span>
            <span className="strip-label">Price</span> <strong>{money(quote.price)}</strong>
          </span>
          {changePct !== null && (
            <span className={positive ? 'quote-up' : 'quote-down'}>
              {positive ? '+' : ''}
              {changePct.toFixed(2)}%
            </span>
          )}
          <span>
            <span className="strip-label">Mkt Cap</span> <strong>{money(quote.market_cap)}</strong>
          </span>
        </>
      ) : (
        <span className="muted">Live quote unavailable — showing filing fundamentals only.</span>
      )}
      {quote?.as_of && <span className="strip-as-of">as of {quote.as_of.slice(0, 10)}</span>}
    </div>
  )
}

function ValuationGrid({ state }: { state: InsightState }) {
  const valuation = state.card?.valuation
  if (!valuation || (!valuation.pe_ratio && !valuation.ps_ratio && !valuation.price_change)) return null
  return (
    <div className="valuation-grid">
      {valuation.pe_ratio && (
        <div className="valuation-tile" title={valuation.pe_ratio.formula}>
          <span className="strip-label">P/E</span>
          <strong>{num(valuation.pe_ratio.value, 1)}x</strong>
        </div>
      )}
      {valuation.ps_ratio && (
        <div className="valuation-tile" title={valuation.ps_ratio.formula}>
          <span className="strip-label">P/S</span>
          <strong>{num(valuation.ps_ratio.value, 1)}x</strong>
        </div>
      )}
      {valuation.price_change && (
        <div className="valuation-tile" title={valuation.price_change.formula}>
          <span className="strip-label">Price Change</span>
          <strong className={valuation.price_change.value >= 0 ? 'quote-up' : 'quote-down'}>
            {valuation.price_change.value >= 0 ? '+' : ''}
            {num(valuation.price_change.value, 1)}%
          </strong>
        </div>
      )}
    </div>
  )
}

function FundamentalsRow({ state }: { state: InsightState }) {
  const f = state.card?.fundamentals
  const ranks = state.card?.ranks
  if (!f) return null
  const tiles: { label: string; value: string | null; rankKey?: string }[] = [
    { label: 'Revenue', value: money(f.revenue) },
    { label: 'Op Margin', value: pct(f.operating_margin), rankKey: 'operating_margin' },
    { label: 'Net Margin', value: pct(f.net_margin), rankKey: 'net_margin' },
    { label: 'Rev Growth', value: pct(f.revenue_growth_yoy), rankKey: 'revenue_growth_yoy' },
    { label: 'ROE', value: pct(f.roe), rankKey: 'roe' },
  ]
  return (
    <div className="valuation-grid">
      {tiles.map((t) => {
        const rank = t.rankKey ? ranks?.[t.rankKey] : undefined
        return (
          <div className="valuation-tile" key={t.label}>
            <span className="strip-label">{t.label}</span>
            <strong>{t.value ?? '—'}</strong>
            {rank && (
              <span className="rank-badge" title={RANK_LABELS[t.rankKey!]}>
                #{rank.rank} of {rank.of}
              </span>
            )}
          </div>
        )
      })}
    </div>
  )
}

export default function InsightCard({ state }: { state: InsightState }) {
  if (!state.card && state.streaming) {
    return <p className="muted">Loading insight brief...</p>
  }
  if (state.error) {
    return <p className="muted">Insight brief unavailable: {state.error}</p>
  }
  if (!state.card) {
    return <p className="muted">Select a company to see its insight brief.</p>
  }

  const rows = state.card.history?.rows ?? []

  return (
    <article className="answer-card insight-card">
      <div className="agent-head">
        <div className="agent-avatar">{state.card.ticker[0]}</div>
        <div>
          <b>
            {state.card.company} ({state.card.ticker})
          </b>
          <span>{state.streaming ? 'Assembling brief...' : 'Insight Brief'}</span>
        </div>
      </div>
      <QuoteStrip state={state} />
      {rows.length >= 2 && (
        <PriceChart
          series={[{ ticker: state.card.ticker, color: '#0ca678', rows }]}
          height={180}
          mode="price"
          variant="embedded"
        />
      )}
      <ValuationGrid state={state} />
      <FundamentalsRow state={state} />
      <NewsPanel items={state.card.news} />
      <ResultCard
        answer={state.narrative}
        citationDetails={state.citationDetails}
        streaming={state.streaming}
        showChart={false}
      />
      {state.card.disclaimer && <div className="footnote">{state.card.disclaimer}</div>}
    </article>
  )
}
