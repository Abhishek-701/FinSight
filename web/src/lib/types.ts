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

export type View = 'chat' | 'screener' | 'compare' | 'portfolio'

export interface ScreenerRow {
  ticker: string
  company: string
  fiscal_period_end: string | null
  revenue: number | null
  operating_income: number | null
  net_income: number | null
  equity: number | null
  operating_margin: number | null
  net_margin: number | null
  revenue_growth_yoy: number | null
  roe: number | null
  price: number | null
  market_cap: number | null
  ps_ratio: number | null
  market_status: 'ok' | 'unavailable' | 'skipped'
  sources: Record<string, string>
}

export interface ScreenerResponse {
  as_of: string
  rows: ScreenerRow[]
  disclaimer: string | null
}

export interface HistoryRow {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface HistoryResult {
  status: 'ok' | 'error'
  cached?: boolean
  data?: {
    ticker: string
    company: string
    period: string
    rows: HistoryRow[]
    source: string
    as_of: string
    disclaimer: string
  }
  error?: string
}

export type HistoryPeriod = '1mo' | '3mo' | '6mo' | '1y'

export interface PortfolioHolding {
  ticker: string
  company: string
  shares: number
  updated_at: string
  price: number | null
  value: number | null
  weight: number | null
  change_percent: number | null
  market_status: 'ok' | 'unavailable'
}

export interface PortfolioResponse {
  client_id: string
  as_of: string
  total_value: number
  holdings: PortfolioHolding[]
  disclaimer: string
}
