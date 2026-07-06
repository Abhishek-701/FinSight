import { useEffect, useState } from 'react'
import { getQuotes } from '../lib/api'
import type { QuoteResult } from '../lib/types'

const POLL_MS = 60_000

export function useQuotes(tickers: string[]) {
  const [quotes, setQuotes] = useState<Record<string, QuoteResult>> ({})
  const key = tickers.slice().sort().join(',')

  useEffect(() => {
    if (!tickers.length) {
      setQuotes({})
      return
    }
    let cancelled = false
    async function poll() {
      try {
        const res = await getQuotes(tickers)
        if (cancelled) return
        const byTicker: Record<string, QuoteResult> = {}
        res.quotes.forEach((q, i) => {
          byTicker[tickers[i]] = q
        })
        setQuotes(byTicker)
      } catch {
        /* keep last-known quotes on transient failure */
      }
    }
    poll()
    const id = setInterval(poll, POLL_MS)
    return () => {
      cancelled = true
      clearInterval(id)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  return quotes
}
