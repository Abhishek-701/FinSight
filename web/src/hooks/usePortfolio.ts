import { useCallback, useEffect, useState } from 'react'
import { getPortfolio, removeHolding, setHolding } from '../lib/api'
import { getClientId } from '../lib/clientId'
import type { PortfolioHolding } from '../lib/types'

const POLL_MS = 60_000

export function usePortfolio() {
  const [holdings, setHoldings] = useState<PortfolioHolding[]>([])
  const [totalValue, setTotalValue] = useState(0)
  const [loading, setLoading] = useState(true)
  const clientId = getClientId()

  const refresh = useCallback(async () => {
    try {
      const res = await getPortfolio(clientId)
      setHoldings(res.holdings)
      setTotalValue(res.total_value)
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
    async (ticker: string, shares: number) => {
      const res = await setHolding(clientId, ticker, shares)
      setHoldings(res.holdings)
      setTotalValue(res.total_value)
    },
    [clientId]
  )

  const remove = useCallback(
    async (ticker: string) => {
      const res = await removeHolding(clientId, ticker)
      setHoldings(res.holdings)
      setTotalValue(res.total_value)
    },
    [clientId]
  )

  return { holdings, totalValue, loading, set, remove, refresh }
}
