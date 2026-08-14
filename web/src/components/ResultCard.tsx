import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'
import { formatPeriod, markCitations, money } from '../lib/format'
import {
  citeChipLabel,
  headlineFromCitations,
  historyFromCitations,
  historyTickerFromCitations,
  quoteFromCitations,
} from '../lib/headline'
import type { CitationDetail } from '../lib/types'
import PriceChart from './PriceChart'
import SourceInspector from './SourceInspector'

interface Props {
  answer: string
  citationDetails: CitationDetail[]
  streaming?: boolean
  autoOpenChunkId?: string | null
  showChart?: boolean
}

export default function ResultCard({
  answer,
  citationDetails,
  streaming = false,
  autoOpenChunkId = null,
  showChart = true,
}: Props) {
  const headline = !streaming ? headlineFromCitations(citationDetails) : null
  const history = !streaming ? historyFromCitations(citationDetails) : []
  const quote = !streaming ? quoteFromCitations(citationDetails) : null
  const [openId, setOpenId] = useState<string | null>(null)

  useEffect(() => {
    if (!streaming && autoOpenChunkId) setOpenId(autoOpenChunkId)
  }, [streaming, autoOpenChunkId])

  const openDetail = citationDetails.find((d) => d.chunk_id === openId) ?? null
  const showQuoteStrip =
    quote && (headline?.label !== 'Price' || quote.marketCap !== null || quote.asOf)
  const priceStr = quote ? money(quote.price) : null
  const capStr = quote ? money(quote.marketCap) : null

  function openCite(chunkId: string) {
    if (citationDetails.some((d) => d.chunk_id === chunkId)) setOpenId(chunkId)
  }

  return (
    <div className={`result-card ${openDetail ? 'result-card-split' : ''}`}>
      <div className="result-main">
        {headline && (
          <div className="result-hero">
            <span className="strip-label">{headline.label}</span>
            <strong className="result-hero-value">{headline.display}</strong>
            {headline.period && (
              <span className="result-hero-period">{formatPeriod(headline.period)}</span>
            )}
            <div className="cite-chips">
              {citationDetails.map((detail) => (
                <button
                  key={detail.chunk_id}
                  type="button"
                  className={`chip cite-chip ${detail.chunk_id === openId ? 'active' : ''}`}
                  onClick={() => setOpenId(detail.chunk_id === openId ? null : detail.chunk_id)}
                >
                  {citeChipLabel(detail)}
                </button>
              ))}
            </div>
          </div>
        )}
        {showQuoteStrip && headline?.label !== 'Price' && (
          <div className="market-strip">
            {priceStr && (
              <span>
                <span className="strip-label">Price</span> <strong>{priceStr}</strong>
              </span>
            )}
            {capStr && (
              <span>
                <span className="strip-label">Mkt Cap</span> <strong>{capStr}</strong>
              </span>
            )}
            {quote?.asOf && <span className="strip-as-of">as of {quote.asOf}</span>}
          </div>
        )}
        {answer && (
          <div className="narrative">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              rehypePlugins={[rehypeRaw]}
              components={{
                cite: ({ children }) => {
                  const id = String(children).replace(/,/g, '').trim()
                  const detail = citationDetails.find((d) => d.chunk_id === id)
                  return (
                    <button
                      type="button"
                      className="citation-badge citation-badge-btn"
                      onClick={() => openCite(id)}
                    >
                      {detail ? citeChipLabel(detail) : id}
                    </button>
                  )
                },
              }}
            >
              {markCitations(answer)}
            </ReactMarkdown>
          </div>
        )}
        {showChart && history.length >= 2 && (
          <PriceChart
            series={[{ ticker: historyTickerFromCitations(citationDetails), color: '#0ca678', rows: history }]}
            height={180}
            mode="price"
            variant="embedded"
          />
        )}
        {!headline && !streaming && citationDetails.length > 0 && (
          <div className="cite-chips">
            {citationDetails.map((detail) => (
              <button
                key={detail.chunk_id}
                type="button"
                className={`chip cite-chip ${detail.chunk_id === openId ? 'active' : ''}`}
                onClick={() => setOpenId(detail.chunk_id === openId ? null : detail.chunk_id)}
              >
                {citeChipLabel(detail)}
              </button>
            ))}
          </div>
        )}
      </div>
      {openDetail && <SourceInspector detail={openDetail} onClose={() => setOpenId(null)} />}
    </div>
  )
}
