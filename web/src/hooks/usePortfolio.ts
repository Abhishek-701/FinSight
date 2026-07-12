import { useCallback, useEffect, useState } from 'react'
import { getPortfolioAnalysis, removeHolding, setHolding } from '../lib/api'
import { getClientId } from '../lib/clientId'
import type { PortfolioAnalysis } from '../lib/types'

const POLL_MS = 60_000

const EMPTY: PortfolioAnalysis = {
  client_id: '', as_of: '', holdings: [], total_value: 0,
  total_day_change: null, total_unrealized_pl: null, concentration: null, disclaimer: '',
}

export function usePortfolio() {
  const [analysis, setAnalysis] = useState<PortfolioAnalysis>(EMPTY)
  const [loading, setLoading] = useState(true)
  const clientId = getClientId()

  const refresh = useCallback(async () => {
    try {
      const res = await getPortfolioAnalysis(clientId)
      setAnalysis(res)
    } catch {
      /* keep last-known holdings on transient failure */
    } finally {
      setLoading(false)
    }
  }, [clientId])

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
  }, [refresh])

  const set = useCallback(
    async (ticker: string, shares: number, costBasis?: number | null) => {
      await setHolding(clientId, ticker, shares, costBasis)
      await refresh()
    },
    [clientId, refresh]
  )

  const remove = useCallback(
    async (ticker: string) => {
      await removeHolding(clientId, ticker)
      await refresh()
    },
    [clientId, refresh]
  )

  return {
    holdings: analysis.holdings,
    totalValue: analysis.total_value,
    totalDayChange: analysis.total_day_change,
    totalUnrealizedPl: analysis.total_unrealized_pl,
    concentration: analysis.concentration,
    loading,
    set,
    remove,
    refresh,
  }
}
