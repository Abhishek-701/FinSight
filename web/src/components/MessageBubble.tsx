import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'
import { markCitations, money, toolLabel } from '../lib/format'
import type { ChatTurn } from '../hooks/useChat'
import type { HistoryRow, NewsItem } from '../lib/types'
import Sparkline from './Sparkline'
import { useTickerIngest } from '../hooks/useTickerIngest'
import IngestProgress from './IngestProgress'

function marketDetails(turn: ChatTurn) {
  return turn.citationDetails.filter((c) => c.chunk_id.includes('-MKT-'))
}

function MarketStrip({ turn }: { turn: ChatTurn }) {
  const details = marketDetails(turn)
  const quote = details.find((d) => (d.data as { price?: number } | undefined)?.price !== undefined)
  const history = details.find((d) => Array.isArray((d.data as { rows?: unknown } | undefined)?.rows))
  const data = quote?.data as { price?: number; market_cap?: number; as_of?: string } | undefined
  const price = data?.price ?? null
  const marketCap = data?.market_cap ?? null
  const rows = (history?.data as { rows?: HistoryRow[] } | undefined)?.rows ?? []
  if (price === null && marketCap === null && rows.length < 2) return null
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
      {rows.length >= 2 && <Sparkline rows={rows} width={90} height={26} />}
      {asOf && <span className="strip-as-of">as of {asOf}</span>}
    </div>
  )
}

function ToolTrace({ turn }: { turn: ChatTurn }) {
  const chips = turn.streaming
    ? turn.liveTools || []
    : (turn.toolCalls || [])
        .filter((t) => t.tool !== 'synthesize_report')
        .map((t) => ({ tool: t.tool, status: t.status === 'error' ? 'error' : 'ok', elapsed_ms: t.elapsed_ms }) as const)
  if (!chips.length) return null
  return (
    <div className="tool-trace">
      {turn.plan?.strategy && <span className="strategy-badge">{turn.plan.strategy}</span>}
      {chips.map((c, i) => (
        <span key={`${c.tool}-${i}`} className={`trace-chip trace-chip-${c.status}`}>
          {toolLabel(c.tool)}
          {c.status === 'running' && <span className="trace-spinner" />}
          {typeof c.elapsed_ms === 'number' && <span className="trace-ms"> · {c.elapsed_ms}ms</span>}
        </span>
      ))}
    </div>
  )
}

function SuggestionChips({ turn, onAsk }: { turn: ChatTurn; onAsk: (q: string) => void }) {
  if (turn.streaming || !turn.suggestions?.length) return null
  return (
    <div className="suggestion-chips">
      {turn.suggestions.map((q) => (
        <button key={q} className="chip" onClick={() => onAsk(q)}>
          {q}
        </button>
      ))}
    </div>
  )
}

function IngestOfferChip({ turn, onAsk }: { turn: ChatTurn; onAsk: (q: string) => void }) {
  const ticker = turn.needsIngestTicker
  const { state, start } = useTickerIngest()
  if (!ticker) return null
  if (state.status === 'idle') {
    return (
      <div className="ingest-offer">
        <button className="chip" onClick={() => start(ticker, () => onAsk(turn.question))}>
          + Add {ticker} (~1 min)
        </button>
      </div>
    )
  }
  return (
    <div className="ingest-offer">
      <IngestProgress state={state} />
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
            {d.kind === 'news' && <span className="news-badge">news</span>}
            {d.chunk_id} — {d.company}
            {d.section ? ` — ${d.section}` : ''}
          </summary>
          {d.kind === 'news' ? (
            <div className="news-source-links">
              {((d.data?.items as NewsItem[] | undefined) ?? []).map((item, i) => (
                <a href={item.url || undefined} target="_blank" rel="noreferrer" key={`${item.title}-${i}`}>
                  {item.title} <span className="muted">— {item.publisher}</span>
                </a>
              ))}
            </div>
          ) : (
            <pre>{d.text}</pre>
          )}
        </details>
      ))}
    </>
  )
}

function statusLabel(turn: ChatTurn): string {
  if (!turn.streaming) return 'Answer'
  const running = [...(turn.liveTools || [])].reverse().find((t) => t.status === 'running')
  if (running) return `${toolLabel(running.tool)}…`
  if (turn.plan?.steps?.length) return 'Planning next step…'
  return 'Analyzing filings, prices, and calculations...'
}

export default function MessageBubble({ turn, onAsk }: { turn: ChatTurn; onAsk: (q: string) => void }) {
  return (
    <>
      <div className="user-query">{turn.question}</div>
      <article className="answer-card">
        <div className="agent-head">
          <div className="agent-avatar">F</div>
          <div>
            <b>FinSight</b>
            <span>{statusLabel(turn)}</span>
          </div>
        </div>
        {!turn.streaming && <MarketStrip turn={turn} />}
        <div className="narrative">
          <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>
            {markCitations(turn.answer)}
          </ReactMarkdown>
        </div>
        {!turn.streaming && turn.needsIngestTicker && <IngestOfferChip turn={turn} onAsk={onAsk} />}
        <ToolTrace turn={turn} />
        {!turn.streaming && <Sources turn={turn} />}
        <SuggestionChips turn={turn} onAsk={onAsk} />
      </article>
    </>
  )
}
