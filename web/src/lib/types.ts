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
  action?: string | null
  ticker?: string | null
}

export interface IngestJob {
  ticker: string
  status: 'queued' | 'running' | 'done' | 'error'
  stage: string | null
  pct: number
  error: { reason: string; message: string } | null
  result: {
    ticker: string
    company: string
    cik: string
    accession: string
    filing_date: string
    chunk_count: number
    fact_count: number
  } | null
}

export interface UniverseSearchResult {
  ticker: string
  name: string
  ingested: boolean
}

export interface UniverseResolveResult {
  ticker: string
  name: string
  cik: string | null
  ingested: boolean
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

export type View = 'chat' | 'screener' | 'compare' | 'portfolio' | 'insight'

export interface ToolCallSummary {
  tool: string
  status?: string
  elapsed_ms?: number
}

export interface PlanSummary {
  strategy?: string
  intent?: string
}

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

// Plain editable item — GET/POST/DELETE /api/portfolio (no live pricing).
export interface PortfolioItem {
  ticker: string
  company: string
  shares: number
  cost_basis: number | null
  updated_at: string
}

// Priced + P&L holding — GET /api/portfolio/analysis. All *_pct/weight fields are 0-1
// fractions (use lib/format's pct() to render), matching PortfolioConcentration below.
export interface PricedPortfolioHolding extends PortfolioItem {
  price: number | null
  value: number | null
  weight: number | null
  day_change_pct: number | null
  day_change_value: number | null
  unrealized_pl: number | null
  unrealized_pl_pct: number | null
  market_status: 'ok' | 'unavailable'
}

export interface PortfolioConcentration {
  top_ticker: string
  top_weight: number
  top3_weight: number
  hhi: number
  band: 'diversified' | 'moderately concentrated' | 'concentrated'
}

export interface PortfolioAnalysis {
  client_id: string
  as_of: string
  holdings: PricedPortfolioHolding[]
  total_value: number
  total_day_change: number | null
  total_unrealized_pl: number | null
  concentration: PortfolioConcentration | null
  disclaimer: string
}

export interface ValuationMetric {
  metric: string
  value: number
  formula: string
  inputs: Record<string, unknown>
  source_ids: string[]
}

export interface RankInfo {
  rank: number
  of: number
  value: number
}

export interface NewsItem {
  title: string
  publisher: string
  published_at: string
  url: string
  summary: string
}

export interface InsightCardData {
  ticker: string
  company: string
  as_of: string
  quote: QuoteData | null
  history: HistoryResult['data'] | null
  fundamentals: ScreenerRow
  valuation: {
    pe_ratio?: ValuationMetric
    ps_ratio?: ValuationMetric
    price_change?: ValuationMetric
  }
  ranks: Record<string, RankInfo>
  news: NewsItem[]
  disclaimer: string
  market_status: 'ok' | 'unavailable'
}

export interface InsightBrief extends InsightCardData {
  answer: string
  citations: string[]
  citation_details: CitationDetail[]
  tool_calls: ToolCallSummary[]
  elapsed_ms: number
}
