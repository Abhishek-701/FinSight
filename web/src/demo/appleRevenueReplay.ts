import type { ChatTurn } from '../hooks/useChat'
import { HEADLINE_VECTORS } from '../lib/headline'
import type { CitationDetail, HistoryRow } from '../lib/types'

// Gold figures from eval case aapl-revenue-last-quarter. Update when the next 10-Q lands.
export const REPLAY_QUESTION = "What was Apple's revenue last quarter?"
export const REPLAY_CITE_ID = HEADLINE_VECTORS.aaplQuarterlyRevenue.chunk_id
export const REPLAY_ANSWER =
  "Apple's revenue for the fiscal quarter ending **June 27, 2026** was **$109,417 million** [AAPL-10Q-XBRL-RevenueFromContractWithCustomerExcludingAssessedTax]."

export const REPLAY_HANDOFF = [
  { q: "Compare NVIDIA and Caterpillar's operating margins.", label: 'Compare NVDA vs CAT' },
  { q: 'Is NVIDIA expensive right now?', label: 'Is NVDA expensive?' },
  { q: "What was Tesla's revenue last year?", label: 'Add Tesla' },
]

function syntheticHistory(): HistoryRow[] {
  const rows: HistoryRow[] = []
  const start = new Date('2026-03-30T00:00:00Z')
  const end = new Date('2026-06-26T00:00:00Z')
  let close = 198.4
  let i = 0
  for (let d = new Date(start); d <= end; d.setUTCDate(d.getUTCDate() + 1)) {
    const day = d.getUTCDay()
    if (day === 0 || day === 6) continue
    close = close + Math.sin(i / 6) * 1.6 + 0.12
    const c = Math.round(close * 100) / 100
    rows.push({
      date: d.toISOString().slice(0, 10),
      open: c,
      high: c,
      low: c,
      close: c,
      volume: 0,
    })
    i += 1
  }
  return rows
}

const HISTORY_ROWS = syntheticHistory()

const XBRL_CITATION: CitationDetail = {
  ...HEADLINE_VECTORS.aaplQuarterlyRevenue,
  text:
    '[Apple Inc.] 10-Q Financial Statements — XBRL-tagged consolidated figures ' +
    '(quarter_recent, period ending 2026-06-27, filed 2026-08-01, in millions unless noted)\n' +
    'Consolidated | RevenueFromContractWithCustomerExcludingAssessedTax | 2026-06-27 = 109,417',
}

const HISTORY_CITATION: CitationDetail = {
  chunk_id: 'AAPL-MKT-REPLAY-HISTORY',
  company: 'Apple Inc.',
  section: 'Price History',
  kind: 'market',
  text: '[Apple Inc.] Market history (replay fixture) as of 2026-06-26. Period: 3mo. This data may be delayed.',
  data: {
    ticker: 'AAPL',
    period: '3mo',
    rows: HISTORY_ROWS,
    as_of: '2026-06-26',
  },
}

export function emptyReplayTurn(): ChatTurn {
  return {
    question: '',
    answer: '',
    citationDetails: [],
    streaming: false,
  }
}

export function finalReplayTurn(): ChatTurn {
  return {
    question: REPLAY_QUESTION,
    answer: REPLAY_ANSWER,
    citationDetails: [XBRL_CITATION, HISTORY_CITATION],
    streaming: false,
    plan: { strategy: 'lookup', intent: 'facts', steps: ['facts_lookup'] },
    liveTools: [{ tool: 'facts_lookup', status: 'ok', elapsed_ms: 48 }],
    toolCalls: [{ tool: 'facts_lookup', status: 'ok', elapsed_ms: 48 }],
    suggestions: REPLAY_HANDOFF.map((c) => c.q),
  }
}

export const REPLAY_ANSWER_TOKENS = REPLAY_ANSWER.split(/(\s+)/)
