import type { TickerIngestState } from '../hooks/useTickerIngest'

const STAGE_LABELS: Record<string, string> = {
  resolving: 'Looking up filing...',
  downloading: 'Downloading 10-K...',
  parsing: 'Parsing filing...',
  chunking: 'Indexing sections...',
  extracting_facts: 'Extracting financial facts...',
  embedding: 'Embedding for search...',
  saving: 'Saving...',
  done: 'Done',
}

export default function IngestProgress({ state }: { state: TickerIngestState }) {
  if (state.status === 'idle') return null
  if (state.status === 'error') {
    return <div className="ingest-progress ingest-error">{state.error}</div>
  }
  if (state.status === 'done') {
    return <div className="ingest-progress ingest-done">Added {state.ticker}</div>
  }
  const label = (state.stage && STAGE_LABELS[state.stage]) || 'Starting...'
  return (
    <div className="ingest-progress">
      <div className="ingest-bar">
        <div className="ingest-bar-fill" style={{ width: `${Math.round(state.pct * 100)}%` }} />
      </div>
      <span className="muted">{label}</span>
    </div>
  )
}
