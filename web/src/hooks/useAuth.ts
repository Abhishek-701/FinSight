import { useCallback, useEffect, useState } from 'react'
import { claimClientId, getMe, logout as apiLogout } from '../lib/api'
import { getClientId } from '../lib/clientId'
import type { AuthUser } from '../lib/types'

const CLAIM_ATTEMPTED_KEY = 'finsight_claim_attempted'

export function useAuth() {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [isAdmin, setIsAdmin] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    getMe()
      .then(async (me) => {
        if (cancelled) return
        setUser(me.user)
        setIsAdmin(me.is_admin)
        // Anonymous localStorage data (portfolio/watchlist/chat history) follows the user into
        // their account exactly once, right after their first login — guarded both here (only
        // try once per browser) and server-side (users.claimed_client_id, 409 on repeat).
        if (me.user && !me.user.claimed && !localStorage.getItem(CLAIM_ATTEMPTED_KEY)) {
          localStorage.setItem(CLAIM_ATTEMPTED_KEY, '1')
          try {
            await claimClientId(getClientId())
            window.location.reload()
          } catch {
            // Nothing to claim, or the claim failed — anonymous data (if any) just stays
            // anonymous; the user isn't blocked from using the app either way.
          }
        }
      })
      .catch(() => {
        if (!cancelled) {
          setUser(null)
          setIsAdmin(false)
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(() => {
    window.location.href = '/api/auth/google/login'
  }, [])

  const logout = useCallback(async () => {
    await apiLogout()
    localStorage.removeItem(CLAIM_ATTEMPTED_KEY)
    setUser(null)
    setIsAdmin(false)
  }, [])

  return { user, isAdmin, loading, login, logout }
}
