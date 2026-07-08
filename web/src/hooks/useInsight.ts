import { useCallback, useEffect, useState } from 'react'
import { streamInsight } from '../lib/api'
import type { CitationDetail, InsightCardData, ToolCallSummary } from '../lib/types'

export interface InsightState {
  card: InsightCardData | null
  narrative: string
  citationDetails: CitationDetail[]
  toolCalls: ToolCallSummary[]
  streaming: boolean
  error: string | null
}

const EMPTY: InsightState = {
  card: null,
  narrative: '',
  citationDetails: [],
  toolCalls: [],
  streaming: false,
  error: null,
}

export function useInsight(ticker: string | null) {
  const [state, setState] = useState<InsightState>(EMPTY)

  const load = useCallback(async (t: string) => {
    setState({ ...EMPTY, streaming: true })
    try {
      for await (const evt of streamInsight(t)) {
        if (evt.event === 'card') {
          setState((prev) => ({ ...prev, card: evt.data as unknown as InsightCardData }))
        } else if (evt.event === 'token') {
          const text = evt.data.text as string
          setState((prev) => ({ ...prev, narrative: prev.narrative + text }))
        } else if (evt.event === 'done') {
          const citationDetails = (evt.data.citations as CitationDetail[]) || []
          const toolCalls = (evt.data.tool_calls as ToolCallSummary[]) || []
          setState((prev) => ({ ...prev, citationDetails, toolCalls, streaming: false }))
        }
      }
    } catch (err) {
      setState((prev) => ({
        ...prev,
        streaming: false,
        error: err instanceof Error ? err.message : 'Failed to load insight brief',
      }))
    }
  }, [])

  useEffect(() => {
    if (ticker) load(ticker)
    else setState(EMPTY)
  }, [ticker, load])

  return state
}
