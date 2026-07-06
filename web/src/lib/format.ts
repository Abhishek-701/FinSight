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
