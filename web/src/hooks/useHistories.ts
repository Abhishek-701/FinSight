import { useEffect, useState } from 'react'
import { getHistory } from '../lib/api'
import type { HistoryPeriod, HistoryRow } from '../lib/types'

const POLL_MS = 300_000

export function useHistories(tickers: string[], period: HistoryPeriod) {
  const [histories, setHistories] = useState<Record<string, HistoryRow[]>>({})
  const [loading, setLoading] = useState(true)
  const key = tickers.slice().sort().join(',') + '|' + period

  useEffect(() => {
    if (!tickers.length) {
      setHistories({})
      setLoading(false)
      return
    }
    let cancelled = false
    async function poll() {
      try {
        const res = await getHistory(tickers, period)
        if (cancelled) return
        const byTicker: Record<string, HistoryRow[]> = {}
        res.histories.forEach((h) => {
          if (h.status === 'ok' && h.data) byTicker[h.data.ticker] = h.data.rows
        })
        setHistories(byTicker)
      } catch {
        /* keep last-known histories on transient failure */
      } finally {
        if (!cancelled) setLoading(false)
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

  return { histories, loading }
}
