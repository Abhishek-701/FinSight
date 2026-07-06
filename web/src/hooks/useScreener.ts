import { useEffect, useState } from 'react'
import { getScreener } from '../lib/api'
import type { ScreenerRow } from '../lib/types'

const POLL_MS = 60_000

export function useScreener() {
  const [rows, setRows] = useState<ScreenerRow[]>([])
  const [asOf, setAsOf] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  async function refresh() {
    try {
      const res = await getScreener()
      setRows(res.rows)
      setAsOf(res.as_of)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'failed to load screener')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    let cancelled = false
    async function poll() {
      if (cancelled) return
      await refresh()
    }
    poll()
    const id = setInterval(poll, POLL_MS)
    return () => {
      cancelled = true
      clearInterval(id)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return { rows, asOf, loading, error, refresh }
}
