import { useCallback, useEffect, useRef, useState } from 'react'
import { putPreferences } from '../lib/api'
import type { AuthUser, UserPreferences } from '../lib/types'

const PREFS_KEY = 'finsight_prefs'
const RECENT_KEY = 'finsight_recent_searches'
const DEBOUNCE_MS = 500

function loadJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : fallback
  } catch {
    return fallback
  }
}

function loadLocal(): UserPreferences {
  const stored = loadJson<UserPreferences>(PREFS_KEY, {})
  if (!stored.recent_searches) {
    const legacy = loadJson<string[] | null>(RECENT_KEY, null)
    if (legacy?.length) stored.recent_searches = legacy
  }
  return stored
}

function isEmpty(prefs: UserPreferences | null | undefined): boolean {
  return !prefs || Object.keys(prefs).length === 0
}

export function usePreferences(user: AuthUser | null, authLoading: boolean) {
  const [prefs, setPrefs] = useState<UserPreferences>(loadLocal)
  const [ready, setReady] = useState(false)
  const skipPut = useRef(true)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const prefsRef = useRef(prefs)
  prefsRef.current = prefs

  useEffect(() => {
    if (authLoading) return
    skipPut.current = true
    if (user) {
      if (isEmpty(user.preferences)) {
        const local = loadLocal()
        if (!isEmpty(local)) {
          setPrefs(local)
          putPreferences(local).catch(() => {})
        } else {
          setPrefs({})
        }
      } else {
        setPrefs(user.preferences)
      }
    } else {
      setPrefs(loadLocal())
    }
    setReady(true)
    const id = setTimeout(() => {
      skipPut.current = false
    }, 0)
    return () => clearTimeout(id)
  }, [authLoading, user])

  useEffect(() => {
    localStorage.setItem(PREFS_KEY, JSON.stringify(prefs))
    if (prefs.recent_searches) {
      localStorage.setItem(RECENT_KEY, JSON.stringify(prefs.recent_searches))
    }
    if (!user || skipPut.current) return
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => {
      putPreferences(prefsRef.current).catch(() => {})
    }, DEBOUNCE_MS)
    return () => {
      if (timer.current) clearTimeout(timer.current)
    }
  }, [prefs, user])

  const update = useCallback((patch: Partial<UserPreferences>) => {
    setPrefs((prev) => ({ ...prev, ...patch }))
  }, [])

  return { prefs, ready, update }
}
