import { money } from './format'
import type { CitationDetail, HistoryRow } from './types'

export interface Headline {
  value: number
  display: string
  period: string | null
  label: string
  chunkId: string
}

const CONCEPT_LABELS: Record<string, string> = {
  RevenueFromContractWithCustomerExcludingAssessedTax: 'Revenue',
  Revenues: 'Revenue',
  SalesRevenueNet: 'Revenue',
  OperatingIncomeLoss: 'Operating Income',
  NetIncomeLoss: 'Net Income',
  EarningsPerShareDiluted: 'Diluted EPS',
  Assets: 'Assets',
  StockholdersEquity: 'Equity',
}

interface XbrlFact {
  concept?: string
  period_end?: string
  value_scaled?: number
  value_display?: string
  scale?: number
}

function shortConcept(concept: string): string {
  const raw = concept.split(':').pop() || concept
  if (CONCEPT_LABELS[raw]) return CONCEPT_LABELS[raw]
  if (/revenue/i.test(raw)) return 'Revenue'
  return raw.replace(/([a-z])([A-Z])/g, '$1 $2') || 'Filed figure'
}

function asFact(raw: unknown): XbrlFact | null {
  if (!raw || typeof raw !== 'object') return null
  return raw as XbrlFact
}

function isXbrl(detail: CitationDetail): boolean {
  return detail.kind === 'xbrl' || detail.chunk_id.includes('XBRL')
}

function isMarket(detail: CitationDetail): boolean {
  return detail.kind === 'market' || detail.chunk_id.includes('-MKT-')
}

function xbrlHeadline(detail: CitationDetail): Headline | null {
  const facts = Array.isArray(detail.facts) ? detail.facts : []
  for (const raw of facts) {
    const fact = asFact(raw)
    if (!fact) continue
    let value = typeof fact.value_scaled === 'number' ? fact.value_scaled : null
    if (value === null && fact.value_display) {
      const parsed = Number(String(fact.value_display).replace(/,/g, ''))
      if (!Number.isNaN(parsed)) value = parsed * 10 ** (fact.scale ?? 0)
    }
    if (value === null) continue
    return {
      value,
      display: money(value) ?? String(value),
      period: fact.period_end ?? null,
      label: shortConcept(fact.concept || ''),
      chunkId: detail.chunk_id,
    }
  }
  return null
}

function marketHeadline(detail: CitationDetail): Headline | null {
  const price = detail.data?.price
  if (typeof price !== 'number') return null
  const asOf = typeof detail.data?.as_of === 'string' ? String(detail.data.as_of).slice(0, 10) : null
  return {
    value: price,
    display: money(price) ?? String(price),
    period: asOf,
    label: 'Price',
    chunkId: detail.chunk_id,
  }
}

export function headlineFromCitations(details: CitationDetail[]): Headline | null {
  for (const detail of details) {
    if (!isXbrl(detail)) continue
    const hit = xbrlHeadline(detail)
    if (hit) return hit
  }
  for (const detail of details) {
    if (!isMarket(detail)) continue
    const hit = marketHeadline(detail)
    if (hit) return hit
  }
  return null
}

export function historyFromCitations(details: CitationDetail[]): HistoryRow[] {
  for (const detail of details) {
    const rows = detail.data?.rows
    if (!Array.isArray(rows) || rows.length < 2) continue
    const first = rows[0] as { close?: unknown }
    if (typeof first?.close === 'number') return rows as HistoryRow[]
  }
  return []
}

export function historyTickerFromCitations(details: CitationDetail[]): string {
  for (const detail of details) {
    if (typeof detail.data?.ticker === 'string' && Array.isArray(detail.data.rows)) return detail.data.ticker
  }
  return 'Price'
}

export function quoteFromCitations(details: CitationDetail[]): {
  price: number | null
  marketCap: number | null
  asOf: string | null
} | null {
  for (const detail of details) {
    if (!isMarket(detail) || !detail.data) continue
    const price = typeof detail.data.price === 'number' ? detail.data.price : null
    const marketCap = typeof detail.data.market_cap === 'number' ? detail.data.market_cap : null
    if (price === null && marketCap === null) continue
    const asOf = typeof detail.data.as_of === 'string' ? String(detail.data.as_of).slice(0, 10) : null
    return { price, marketCap, asOf }
  }
  return null
}

function formFromFacts(detail: CitationDetail): string | null {
  const facts = Array.isArray(detail.facts) ? detail.facts : []
  for (const raw of facts) {
    if (raw && typeof raw === 'object' && 'form' in raw) {
      const form = (raw as { form?: string }).form
      if (form) return form
    }
  }
  return null
}

export function citeForm(source: CitationDetail | string): string {
  if (typeof source !== 'string') {
    if (source.form) return source.form
    const fromFact = formFromFacts(source)
    if (fromFact) return fromFact
    return citeForm(source.chunk_id)
  }
  const chunkId = source
  if (chunkId.includes('NEWS')) return 'News'
  if (chunkId.includes('-MKT-')) return 'Market'
  if (chunkId.includes('-CALC-')) return 'Calc'
  if (chunkId.includes('10Q') || chunkId.includes('10-Q')) return '10-Q'
  if (chunkId.includes('XBRL') || chunkId.includes('10K') || chunkId.includes('10-K')) return '10-K'
  if (/^[A-Z]{1,5}-\d{4}$/.test(chunkId)) return '10-K'
  return 'Filing'
}

export function citeChipLabel(detail: CitationDetail): string {
  const form = citeForm(detail)
  if (isXbrl(detail)) {
    const hit = xbrlHeadline(detail)
    return hit ? `${form} · ${hit.label}` : form
  }
  if (detail.kind === 'news' || detail.chunk_id.includes('NEWS')) return 'News'
  if (isMarket(detail)) {
    return detail.section === 'Price History' ? 'Market · History' : 'Market · Quote'
  }
  return detail.section || form
}

export const HEADLINE_VECTORS = {
  aaplQuarterlyRevenue: {
    chunk_id: 'AAPL-10Q-XBRL-RevenueFromContractWithCustomerExcludingAssessedTax',
    company: 'Apple Inc.',
    section: 'Financial Statements (XBRL)',
    text: '',
    kind: 'xbrl',
    facts: [
      {
        concept: 'us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax',
        period_end: '2026-06-27',
        value_display: '109,417',
        value_scaled: 109417000000,
        scale: 6,
        form: '10-Q',
      },
    ],
  } satisfies CitationDetail,
} as const
