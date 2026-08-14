export function money(value: number | null | undefined): string | null {
  if (value === null || value === undefined || Number.isNaN(value)) return null
  const abs = Math.abs(value)
  if (abs >= 1e12) return '$' + (value / 1e12).toFixed(2) + 'T'
  if (abs >= 1e9) return '$' + (value / 1e9).toFixed(1) + 'B'
  if (abs >= 1e6) return '$' + (value / 1e6).toFixed(1) + 'M'
  return '$' + value.toLocaleString(undefined, { maximumFractionDigits: 2 })
}

export function titleFromQuestion(q: string): string {
  const plain = q
    .replace(/\*\*(.*?)\*\*/g, '$1')
    .replace(/#{1,6}\s*/g, '')
    .trim()
  return plain.slice(0, 64) || 'Untitled chat'
}

/** Wrap [CHUNK_ID] citation markers in literal <cite> HTML so remark-rehype-raw renders them as chips. */
export function markCitations(text: string): string {
  return text.replace(/\[([A-Z][A-Z0-9_\-.]+)\]/g, '<cite class="citation-badge">$1</cite>')
}

export function pct(value: number | null | undefined, dp = 1): string | null {
  if (value === null || value === undefined || Number.isNaN(value)) return null
  return (value * 100).toFixed(dp) + '%'
}

export function num(value: number | null | undefined, dp = 2): string | null {
  if (value === null || value === undefined || Number.isNaN(value)) return null
  return value.toLocaleString(undefined, { maximumFractionDigits: dp })
}

export function formatPeriod(iso: string | null | undefined): string | null {
  if (!iso) return null
  const day = iso.slice(0, 10)
  const date = new Date(`${day}T00:00:00`)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })
}

const TOOL_LABELS: Record<string, string> = {
  facts_lookup: 'Looking up filed financials',
  filing_rag: 'Searching filings',
  multi_company_compare: 'Comparing filings',
  market_quote: 'Fetching live quote',
  market_history: 'Fetching price history',
  news_headlines: 'Checking recent news',
  compute_metric: 'Computing ratios',
  screen_companies: 'Ranking companies',
  company_insight: 'Assembling insight brief',
  portfolio_context: 'Reading your portfolio',
  refuse_or_clarify: 'Checking coverage',
}

export function toolLabel(tool: string): string {
  return TOOL_LABELS[tool] || tool.replace(/_/g, ' ')
}
