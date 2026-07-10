import { useEffect, useRef, useState } from 'react'
import { searchCompanies } from '../lib/api'
import { useTickerIngest } from '../hooks/useTickerIngest'
import IngestProgress from './IngestProgress'
import type { UniverseSearchResult } from '../lib/types'

const DEBOUNCE_MS = 250

export default function TickerSearch({ onAdded }: { onAdded: (ticker: string) => void }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<UniverseSearchResult[]>([])
  const [open, setOpen] = useState(false)
  const [searching, setSearching] = useState(false)
  const { state: ingestState, start: startIngest, reset: resetIngest } = useTickerIngest()
  const debounceRef = useRef<number | undefined>(undefined)
  const boxRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    window.clearTimeout(debounceRef.current)
    const q = query.trim()
    if (q.length < 1) {
      setResults([])
      setSearching(false)
      return
    }
    setSearching(true)
    debounceRef.current = window.setTimeout(async () => {
      try {
        const res = await searchCompanies(q)
        setResults(res.results)
      } catch {
        setResults([])
      } finally {
        setSearching(false)
      }
    }, DEBOUNCE_MS)
    return () => window.clearTimeout(debounceRef.current)
  }, [query])

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [])

  function handleAdd(ticker: string) {
    startIngest(ticker, () => {
      onAdded(ticker)
      searchCompanies(query.trim())
        .then((res) => setResults(res.results))
        .catch(() => undefined)
    })
  }

  const busy = ingestState.status === 'running'

  return (
    <div className="ticker-search" ref={boxRef}>
      <div className="section-title">Add a Company</div>
      <input
        type="text"
        placeholder="Search ticker or company..."
        value={query}
        disabled={busy}
        onFocus={() => setOpen(true)}
        onChange={(e) => {
          setQuery(e.target.value)
          setOpen(true)
          resetIngest()
        }}
      />
      {open && query.trim().length > 0 && (
        <div className="ticker-search-results">
          {searching && <div className="ticker-search-empty muted">Searching...</div>}
          {!searching && results.length === 0 && (
            <div className="ticker-search-empty muted">No matching companies</div>
          )}
          {!searching &&
            results.map((r) => (
              <div key={r.ticker} className="ticker-search-row">
                <div className="ticker-search-row-name">
                  <b>{r.ticker}</b>
                  <span className="muted">{r.name}</span>
                </div>
                {r.ingested ? (
                  <span className="ticker-search-tag">Loaded</span>
                ) : ingestState.ticker === r.ticker && ingestState.status !== 'idle' ? null : (
                  <button className="chip" disabled={busy} onClick={() => handleAdd(r.ticker)}>
                    Add
                  </button>
                )}
              </div>
            ))}
        </div>
      )}
      {ingestState.status !== 'idle' && <IngestProgress state={ingestState} />}
    </div>
  )
}
