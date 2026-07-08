import { useWatchlist } from '../hooks/useWatchlist'
import { useQuotes } from '../hooks/useQuotes'
import { useHistories } from '../hooks/useHistories'
import Sparkline from './Sparkline'
import { money } from '../lib/format'

interface Props {
  companies: Record<string, string>
  onInsight: (ticker: string) => void
}

export default function WatchlistPanel({ companies, onInsight }: Props) {
  const { items, add, remove } = useWatchlist()
  const tickers = items.map((i) => i.ticker)
  const quotes = useQuotes(tickers)
  const { histories } = useHistories(tickers, '1mo')
  const watched = new Set(tickers)

  return (
    <aside className="market-panel">
      <div className="section-title">Watchlist</div>
      <div className="watchlist-rows">
        {items.length === 0 && <p className="muted">Star a company below to track its price here.</p>}
        {items.map((item) => {
          const quote = quotes[item.ticker]
          const data = quote?.data
          const changePct = data?.change_percent
          const positive = (changePct ?? 0) >= 0
          return (
            <div className="watchlist-row" key={item.ticker}>
              <button className="star-btn" onClick={() => remove(item.ticker)} title="Remove from watchlist">
                ★
              </button>
              <button className="watchlist-info watchlist-info-btn" onClick={() => onInsight(item.ticker)}>
                <b>{item.ticker}</b>
                <span>{item.company}</span>
              </button>
              <Sparkline rows={histories[item.ticker] || []} />
              <div className="watchlist-quote">
                {quote?.status === 'ok' && data ? (
                  <>
                    <span>{money(data.price)}</span>
                    {changePct !== null && changePct !== undefined && (
                      <span className={positive ? 'quote-up' : 'quote-down'}>
                        {positive ? '+' : ''}
                        {changePct.toFixed(2)}%
                      </span>
                    )}
                  </>
                ) : (
                  <span className="muted">quote unavailable</span>
                )}
              </div>
            </div>
          )
        })}
      </div>

      <div className="section-title">Companies</div>
      <div className="company-picker">
        {Object.entries(companies).map(([ticker, name]) => (
          <button
            key={ticker}
            className={`company-chip ${watched.has(ticker) ? 'active' : ''}`}
            onClick={() => (watched.has(ticker) ? remove(ticker) : add(ticker))}
          >
            {watched.has(ticker) ? '★' : '☆'} {ticker} <span>{name}</span>
          </button>
        ))}
      </div>
      <div className="footnote">Market data may be delayed. Not investment advice.</div>
    </aside>
  )
}
