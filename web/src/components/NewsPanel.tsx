import type { NewsItem } from '../lib/types'

function relativeDate(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const days = Math.floor((Date.now() - d.getTime()) / 86_400_000)
  if (days <= 0) return 'today'
  if (days === 1) return '1 day ago'
  if (days < 7) return `${days} days ago`
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export default function NewsPanel({ items }: { items: NewsItem[] }) {
  if (!items.length) return null
  return (
    <div className="news-panel">
      <div className="section-title">Recent Headlines</div>
      <div className="news-list">
        {items.map((item, i) => (
          <a
            className="news-row"
            href={item.url || undefined}
            target="_blank"
            rel="noreferrer"
            key={`${item.title}-${i}`}
          >
            <div className="news-row-title">{item.title}</div>
            <div className="news-row-meta muted">
              {item.publisher}
              {item.published_at && ` · ${relativeDate(item.published_at)}`}
            </div>
          </a>
        ))}
      </div>
      <div className="footnote">Third-party reports, shown as context — not verified causes of any price move.</div>
    </div>
  )
}
