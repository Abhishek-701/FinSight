import { useCallback, useEffect, useState } from 'react'
import { addWatchlist, getWatchlist, removeWatchlist } from '../lib/api'
import { getClientId } from '../lib/clientId'
import type { WatchlistItem } from '../lib/types'

const MIRROR_KEY = 'finsight_watchlist_mirror'

function loadMirror(): string[] {
  try {
    return JSON.parse(localStorage.getItem(MIRROR_KEY) || '[]')
  } catch {
    return []
  }
}

function saveMirror(tickers: string[]) {
  localStorage.setItem(MIRROR_KEY, JSON.stringify(tickers))
}

export function useWatchlist() {
  const [items, setItems] = useState<WatchlistItem[]>([])
  const [loading, setLoading] = useState(true)
  const clientId = getClientId()

  useEffect(() => {
    let cancelled = false
    async function init() {
      const mirror = loadMirror()
      try {
        const server = await getWatchlist(clientId)
        let current = server.items
        const missing = mirror.filter((t) => !current.some((i) => i.ticker === t))
        for (const ticker of missing) {
          try {
            current = await addWatchlist(clientId, ticker).then((r) => r.items)
          } catch {
            /* ticker may no longer be supported; skip */
          }
        }
        if (!cancelled) {
          setItems(current)
          saveMirror(current.map((i) => i.ticker))
        }
      } catch {
        if (!cancelled) setItems([])
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    init()
    return () => {
      cancelled = true
    }
  }, [clientId])

  const add = useCallback(
    async (ticker: string) => {
      const result = await addWatchlist(clientId, ticker)
      setItems(result.items)
      saveMirror(result.items.map((i) => i.ticker))
    },
    [clientId]
  )

  const remove = useCallback(
    async (ticker: string) => {
      const result = await removeWatchlist(clientId, ticker)
      setItems(result.items)
      saveMirror(result.items.map((i) => i.ticker))
    },
    [clientId]
  )

  return { items, loading, add, remove }
}
