import { toolLabel } from '../lib/format'
import type { ChatTurn } from '../hooks/useChat'
import { useTickerIngest } from '../hooks/useTickerIngest'
import IngestProgress from './IngestProgress'
import ResultCard from './ResultCard'

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

function statusLabel(turn: ChatTurn): string {
  if (!turn.streaming) return 'Answer'
  const running = [...(turn.liveTools || [])].reverse().find((t) => t.status === 'running')
  if (running) return `${toolLabel(running.tool)}…`
  if (turn.plan?.steps?.length) return 'Planning next step…'
  return 'Analyzing filings, prices, and calculations...'
}

export default function MessageBubble({
  turn,
  onAsk,
  autoOpenChunkId,
  example,
}: {
  turn: ChatTurn
  onAsk: (q: string) => void
  autoOpenChunkId?: string | null
  example?: boolean
}) {
  return (
    <>
      {turn.question && <div className="user-query">{turn.question}</div>}
      <article className="answer-card">
        <div className="agent-head">
          <div className="agent-avatar">F</div>
          <div>
            <b>FinSight</b>
            <span>{statusLabel(turn)}</span>
          </div>
          {example && <span className="example-badge">Example</span>}
        </div>
        <ResultCard
          answer={turn.answer}
          citationDetails={turn.citationDetails}
          streaming={turn.streaming}
          autoOpenChunkId={autoOpenChunkId}
        />
        {!turn.streaming && turn.needsIngestTicker && <IngestOfferChip turn={turn} onAsk={onAsk} />}
        <ToolTrace turn={turn} />
        <SuggestionChips turn={turn} onAsk={onAsk} />
      </article>
    </>
  )
}
