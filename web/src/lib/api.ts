import type { ChatResponse, QuoteResult, SessionMessage, WatchlistItem } from './types'

async function jsonFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}))
    throw new Error(detail.detail || `${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<T>
}

export function chat(message: string, sessionId: string | null): Promise<ChatResponse> {
  return jsonFetch<ChatResponse>('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId, stream: false }),
  })
}

export interface SseEvent {
  event: string
  data: Record<string, unknown>
}

export async function* streamChat(message: string, sessionId: string | null): AsyncGenerator<SseEvent> {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId, stream: true }),
  })
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

export function getSession(sessionId: string): Promise<{ session_id: string; messages: SessionMessage[] }> {
  return jsonFetch(`/api/sessions/${encodeURIComponent(sessionId)}`)
}

export function getCompanies(): Promise<{ companies: Record<string, string> }> {
  return jsonFetch('/api/companies')
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
