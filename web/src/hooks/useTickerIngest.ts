import { useCallback, useState } from 'react'
import { streamIngest } from '../lib/api'

export interface TickerIngestState {
  ticker: string | null
  status: 'idle' | 'running' | 'done' | 'error'
  stage: string | null
  pct: number
  error: string | null
}

const IDLE: TickerIngestState = { ticker: null, status: 'idle', stage: null, pct: 0, error: null }

/** Starts an on-demand ingest for `ticker` and streams its progress (POST + SSE stream share
 * the wire format used by useInsight). Manually triggered (unlike useInsight's auto-load on
 * ticker change) since ingest is an explicit user action, not a view-driven fetch. */
export function useTickerIngest() {
  const [state, setState] = useState<TickerIngestState>(IDLE)

  const start = useCallback(async (ticker: string, onDone?: () => void) => {
    setState({ ticker, status: 'running', stage: null, pct: 0, error: null })
    try {
      for await (const evt of streamIngest(ticker)) {
        if (evt.event === 'progress') {
          const stage = (evt.data.stage as string | null) ?? null
          const pct = typeof evt.data.pct === 'number' ? evt.data.pct : 0
          setState((prev) => ({ ...prev, stage, pct }))
        } else if (evt.event === 'done') {
          const status = evt.data.status as string
          if (status === 'error') {
            const err = evt.data.error as { message?: string } | undefined
            setState((prev) => ({ ...prev, status: 'error', error: err?.message || 'Could not add this company.' }))
          } else {
            setState((prev) => ({ ...prev, status: 'done', pct: 1 }))
            onDone?.()
          }
        }
      }
    } catch (err) {
      setState((prev) => ({
        ...prev,
        status: 'error',
        error: err instanceof Error ? err.message : 'Could not add this company.',
      }))
    }
  }, [])

  const reset = useCallback(() => setState(IDLE), [])

  return { state, start, reset }
}
