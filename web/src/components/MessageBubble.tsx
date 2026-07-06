import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'
import { markCitations, money } from '../lib/format'
import type { ChatTurn } from '../hooks/useChat'

function marketDetail(turn: ChatTurn) {
  return turn.citationDetails.find((c) => c.chunk_id.includes('-MKT-'))
}

function MarketStrip({ turn }: { turn: ChatTurn }) {
  const market = marketDetail(turn)
  const data = market?.data as { price?: number; market_cap?: number; as_of?: string } | undefined
  const price = data?.price ?? null
  const marketCap = data?.market_cap ?? null
  if (price === null && marketCap === null) return null
  const priceStr = money(price)
  const capStr = money(marketCap)
  const asOf = data?.as_of ? String(data.as_of).slice(0, 10) : null
  return (
    <div className="market-strip">
      {priceStr && (
        <span>
          <span className="strip-label">Price</span> <strong>{priceStr}</strong>
        </span>
      )}
      {capStr && (
        <span>
          <span className="strip-label">Mkt Cap</span> <strong>{capStr}</strong>
        </span>
      )}
      {asOf && <span className="strip-as-of">as of {asOf}</span>}
    </div>
  )
}

function Sources({ turn }: { turn: ChatTurn }) {
  if (!turn.citationDetails.length) return null
  return (
    <>
      <div className="sources">Sources: {turn.citationDetails.map((d) => d.chunk_id).join(' | ')}</div>
      {turn.citationDetails.map((d) => (
        <details className="source-detail" key={d.chunk_id}>
          <summary>
            {d.chunk_id} — {d.company}
            {d.section ? ` — ${d.section}` : ''}
          </summary>
          <pre>{d.text}</pre>
        </details>
      ))}
    </>
  )
}

export default function MessageBubble({ turn }: { turn: ChatTurn }) {
  return (
    <>
      <div className="user-query">{turn.question}</div>
      <article className="answer-card">
        <div className="agent-head">
          <div className="agent-avatar">F</div>
          <div>
            <b>FinSight</b>
            <span>{turn.streaming ? 'Analyzing filings, prices, and calculations...' : 'Answer'}</span>
          </div>
        </div>
        {!turn.streaming && <MarketStrip turn={turn} />}
        <div className="narrative">
          <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>
            {markCitations(turn.answer)}
          </ReactMarkdown>
        </div>
        {!turn.streaming && <Sources turn={turn} />}
      </article>
    </>
  )
}
