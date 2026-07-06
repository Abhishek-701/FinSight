export interface CitationDetail {
  chunk_id: string
  company: string
  section: string
  text: string
  kind?: string
  data?: Record<string, unknown>
  facts?: unknown[]
}

export interface ChatResponse {
  answer: string
  session_id?: string
  citation_details?: CitationDetail[]
  citations?: CitationDetail[]
  gaps?: string[]
  refused?: boolean
  refusal_reason?: string
}

export interface SessionMessage {
  role: 'user' | 'assistant'
  content: string
  metadata: Record<string, unknown>
  created_at: string
}

export interface WatchlistItem {
  ticker: string
  company: string
  added_at: string
}

export interface QuoteData {
  ticker: string
  company: string
  price: number | null
  previous_close: number | null
  change: number | null
  change_percent: number | null
  market_cap: number | null
  currency: string | null
  source: string
  as_of: string
  disclaimer: string
}

export interface QuoteResult {
  status: 'ok' | 'error'
  cached?: boolean
  data?: QuoteData
  error?: string
}

export interface Turn {
  question: string
  data: ChatResponse
}
