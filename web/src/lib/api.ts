import type {
  BenchmarkResult,
  ChatResponse,
  HistoryPeriod,
  HistoryResult,
  InsightBrief,
  IngestJob,
  MeResponse,
  PortfolioAnalysis,
  PortfolioItem,
  QuoteResult,
  ScreenerResponse,
  SessionMessage,
  UniverseResolveResult,
  UniverseSearchResult,
  WatchlistItem,
  WhatifResult,
  WhatifTrade,
} from './types'

async function jsonFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}))
    throw new Error(detail.detail || `${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<T>
}

export function chat(message: string, sessionId: string | null, clientId?: string | null): Promise<ChatResponse> {
  return jsonFetch<ChatResponse>('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId, stream: false, client_id: clientId }),
  })
}

export interface SseEvent {
  event: string
  data: Record<string, unknown>
}

/** Shared SSE body parser: both /api/chat (stream:true) and /api/insight/{ticker}/stream use this wire format. */
async function* parseSse(res: Response): AsyncGenerator<SseEvent> {
  if (!res.ok || !res.body) throw new Error(`${res.status} ${res.statusText}`)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let sep: number
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const raw = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      const eventLine = raw.split('\n').find((l) => l.startsWith('event: '))
      const dataLine = raw.split('\n').find((l) => l.startsWith('data: '))
      if (!eventLine || !dataLine) continue
      yield { event: eventLine.slice(7), data: JSON.parse(dataLine.slice(6)) }
    }
  }
}

export async function* streamChat(
  message: string, sessionId: string | null, clientId?: string | null
): AsyncGenerator<SseEvent> {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId, stream: true, client_id: clientId }),
  })
  yield* parseSse(res)
}

export async function* streamInsight(ticker: string): AsyncGenerator<SseEvent> {
  const res = await fetch(`/api/insight/${encodeURIComponent(ticker)}/stream`)
  yield* parseSse(res)
}

export function getInsight(ticker: string): Promise<InsightBrief> {
  return jsonFetch(`/api/insight/${encodeURIComponent(ticker)}`)
}

export function getSession(
  sessionId: string, clientId?: string | null
): Promise<{ session_id: string; messages: SessionMessage[] }> {
  const qs = clientId ? `?client_id=${encodeURIComponent(clientId)}` : ''
  return jsonFetch(`/api/sessions/${encodeURIComponent(sessionId)}${qs}`)
}

export function getMe(): Promise<MeResponse> {
  return jsonFetch('/api/auth/me')
}

export function logout(): Promise<{ ok: boolean }> {
  return jsonFetch('/api/auth/logout', { method: 'POST' })
}

export function claimClientId(clientId: string): Promise<{ user: MeResponse['user'] }> {
  return jsonFetch('/api/auth/claim', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ client_id: clientId }),
  })
}

export function getCompanies(): Promise<{ companies: Record<string, string> }> {
  return jsonFetch('/api/companies')
}

export function searchCompanies(q: string): Promise<{ results: UniverseSearchResult[] }> {
  return jsonFetch(`/api/universe/search?q=${encodeURIComponent(q)}`)
}

export function resolveTicker(q: string): Promise<UniverseResolveResult> {
  return jsonFetch(`/api/universe/resolve?q=${encodeURIComponent(q)}`)
}

export function startIngest(ticker: string): Promise<{ status: string; job: IngestJob | null }> {
  return jsonFetch(`/api/companies/${encodeURIComponent(ticker)}/ingest`, { method: 'POST' })
}

export function getIngestStatus(ticker: string): Promise<{ status: string; job: IngestJob | null }> {
  return jsonFetch(`/api/companies/${encodeURIComponent(ticker)}/ingest/status`)
}

export async function* streamIngest(ticker: string): AsyncGenerator<SseEvent> {
  const res = await fetch(`/api/companies/${encodeURIComponent(ticker)}/ingest/stream`)
  yield* parseSse(res)
}

export function getWatchlist(clientId: string): Promise<{ client_id: string; items: WatchlistItem[] }> {
  return jsonFetch(`/api/watchlist?client_id=${encodeURIComponent(clientId)}`)
}

export function addWatchlist(clientId: string, ticker: string): Promise<{ ok: boolean; items: WatchlistItem[] }> {
  return jsonFetch('/api/watchlist', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ client_id: clientId, ticker }),
  })
}

export function removeWatchlist(clientId: string, ticker: string): Promise<{ ok: boolean; items: WatchlistItem[] }> {
  return jsonFetch(`/api/watchlist/${encodeURIComponent(ticker)}?client_id=${encodeURIComponent(clientId)}`, {
    method: 'DELETE',
  })
}

export function getQuotes(tickers: string[]): Promise<{ quotes: QuoteResult[] }> {
  if (!tickers.length) return Promise.resolve({ quotes: [] })
  return jsonFetch(`/api/quotes?tickers=${encodeURIComponent(tickers.join(','))}`)
}

export function getHistory(tickers: string[], period: HistoryPeriod): Promise<{ histories: HistoryResult[] }> {
  if (!tickers.length) return Promise.resolve({ histories: [] })
  return jsonFetch(`/api/history?tickers=${encodeURIComponent(tickers.join(','))}&period=${period}`)
}

export function getScreener(): Promise<ScreenerResponse> {
  return jsonFetch('/api/screener?live=1')
}

export function getPortfolio(clientId: string): Promise<{ client_id: string; items: PortfolioItem[] }> {
  return jsonFetch(`/api/portfolio?client_id=${encodeURIComponent(clientId)}`)
}

export function getPortfolioAnalysis(clientId: string): Promise<PortfolioAnalysis> {
  return jsonFetch(`/api/portfolio/analysis?client_id=${encodeURIComponent(clientId)}`)
}

export function setHolding(
  clientId: string, ticker: string, shares: number, costBasis?: number | null
): Promise<{ client_id: string; items: PortfolioItem[] }> {
  return jsonFetch('/api/portfolio', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ client_id: clientId, ticker, shares, cost_basis: costBasis ?? null }),
  })
}

export function removeHolding(clientId: string, ticker: string): Promise<{ client_id: string; items: PortfolioItem[] }> {
  return jsonFetch(`/api/portfolio/${encodeURIComponent(ticker)}?client_id=${encodeURIComponent(clientId)}`, {
    method: 'DELETE',
  })
}

export function postWhatif(clientId: string, trades: WhatifTrade[]): Promise<WhatifResult> {
  return jsonFetch('/api/portfolio/whatif', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ client_id: clientId, trades }),
  })
}

export function getBenchmark(clientId: string, period: HistoryPeriod): Promise<BenchmarkResult> {
  return jsonFetch(`/api/portfolio/benchmark?client_id=${encodeURIComponent(clientId)}&period=${period}`)
}
