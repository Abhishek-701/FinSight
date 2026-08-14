import { citeChipLabel, citeForm, headlineFromCitations } from '../lib/headline'
import { formatPeriod } from '../lib/format'
import type { CitationDetail, NewsItem } from '../lib/types'

interface Props {
  detail: CitationDetail
  onClose: () => void
}

function factPeriod(detail: CitationDetail): string | null {
  const facts = Array.isArray(detail.facts) ? detail.facts : []
  for (const raw of facts) {
    if (raw && typeof raw === 'object' && 'period_end' in raw) {
      const period = (raw as { period_end?: string }).period_end
      if (period) return period
    }
  }
  const asOf = detail.data?.as_of
  return typeof asOf === 'string' ? asOf.slice(0, 10) : null
}

function factForm(detail: CitationDetail): string {
  return citeForm(detail)
}

export default function SourceInspector({ detail, onClose }: Props) {
  const headline = headlineFromCitations([detail])
  const period = formatPeriod(factPeriod(detail))
  const newsItems = ((detail.data?.items as NewsItem[] | undefined) ?? []).filter((item) => item.title)
  const isNews = detail.kind === 'news' || detail.chunk_id.includes('NEWS')

  return (
    <aside className="source-inspector" aria-label="Source inspector">
      <div className="source-inspector-head">
        <div>
          <b>{citeChipLabel(detail)}</b>
          <span>{detail.company}</span>
        </div>
        <button type="button" className="source-inspector-close" onClick={onClose} aria-label="Close source">
          Close
        </button>
      </div>
      <dl className="source-inspector-meta">
        <div>
          <dt>Form</dt>
          <dd>{factForm(detail)}</dd>
        </div>
        {period && (
          <div>
            <dt>Period</dt>
            <dd>{period}</dd>
          </div>
        )}
        {headline && (
          <div>
            <dt>{headline.label}</dt>
            <dd>{headline.display}</dd>
          </div>
        )}
      </dl>
      {detail.section && <div className="source-inspector-section">{detail.section}</div>}
      {isNews ? (
        <div className="news-source-links">
          {newsItems.map((item, i) => (
            <a href={item.url || undefined} target="_blank" rel="noreferrer" key={`${item.title}-${i}`}>
              {item.title} <span className="muted">— {item.publisher}</span>
            </a>
          ))}
        </div>
      ) : (
        <pre className="source-inspector-excerpt">{detail.text}</pre>
      )}
      <div className="source-inspector-id">{detail.chunk_id}</div>
    </aside>
  )
}
