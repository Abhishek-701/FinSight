import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, getSession, listSessions, streamChat } from '../lib/api'
import { getClientId } from '../lib/clientId'
import { titleFromQuestion } from '../lib/format'
import type { CitationDetail, LiveToolCall, PlanSummary, ToolCallSummary } from '../lib/types'

export interface ChatTurn {
  question: string
  answer: string
  citationDetails: CitationDetail[]
  streaming: boolean
  refused?: boolean
  toolCalls?: ToolCallSummary[]
  plan?: PlanSummary
  liveTools?: LiveToolCall[]
  suggestions?: string[]
  needsIngestTicker?: string | null
}

export interface ChatWindow {
  id: string
  title: string
  updated_at: string
}

const SESSION_KEY = 'finsight_session_id'
const WINDOWS_KEY = 'finsight_chat_windows'
const TURNS_KEY = 'finsight_local_turns'

function failMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 429) return 'Too many requests. Wait a moment and try again.'
    if (err.status >= 500) return 'Server error. Please try again.'
    if (err.detail && err.detail !== `${err.status}`) return err.detail
  }
  if (err instanceof TypeError) return 'Could not reach the server. If the demo was asleep, wait and retry.'
  return 'Request failed. Please try again.'
}

export const DEFAULT_PROMPTS = [
  "What is NVIDIA's current stock price and latest reported revenue?",
  "Compare Apple's current market cap to its latest reported revenue.",
  'What cybersecurity risks did Walmart disclose?',
  "Compare JPMorgan's revenue to its current market cap.",
]

function loadJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : fallback
  } catch {
    return fallback
  }
}

export function useChat({
  signedIn,
  recentSearches,
  onRecentSearches,
}: {
  signedIn: boolean
  recentSearches: string[]
  onRecentSearches: (next: string[]) => void
}) {
  const [sessionId, setSessionId] = useState<string | null>(() => localStorage.getItem(SESSION_KEY))
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [isBusy, setIsBusy] = useState(false)
  const [chatWindows, setChatWindows] = useState<ChatWindow[]>(() => loadJson(WINDOWS_KEY, []))
  const localTurnsRef = useRef<Record<string, ChatTurn[]>>(loadJson(TURNS_KEY, {}))

  const persistWindows = useCallback((windows: ChatWindow[]) => {
    localStorage.setItem(WINDOWS_KEY, JSON.stringify(windows))
  }, [])

  const persistTurns = useCallback(() => {
    localStorage.setItem(TURNS_KEY, JSON.stringify(localTurnsRef.current))
  }, [])

  const upsertWindow = useCallback(
    (id: string, question: string) => {
      setChatWindows((prev) => {
        const now = new Date().toISOString()
        const existing = prev.find((w) => w.id === id)
        let next: ChatWindow[]
        if (existing) {
          next = prev.map((w) => (w.id === id ? { ...w, updated_at: now } : w))
        } else {
          next = [{ id, title: titleFromQuestion(question), updated_at: now }, ...prev]
        }
        next = next.sort((a, b) => b.updated_at.localeCompare(a.updated_at)).slice(0, 12)
        persistWindows(next)
        return next
      })
    },
    [persistWindows]
  )

  const updateRecent = useCallback((question: string) => {
    const next = [question, ...recentSearches.filter((q) => q !== question)].slice(0, 8)
    onRecentSearches(next)
  }, [recentSearches, onRecentSearches])

  const ask = useCallback(
    async (question: string) => {
      if (isBusy) return
      setIsBusy(true)
      updateRecent(question)
      setTurns((prev) => [...prev, { question, answer: '', citationDetails: [], streaming: true }])

      let sid = sessionId
      try {
        for (let attempt = 0; attempt < 2; attempt++) {
          try {
            for await (const evt of streamChat(question, sid, getClientId())) {
          if (evt.event === 'session') {
            sid = evt.data.session_id as string
            setSessionId(sid)
            localStorage.setItem(SESSION_KEY, sid)
            upsertWindow(sid, question)
          } else if (evt.event === 'plan') {
            const plan = evt.data as PlanSummary
            setTurns((prev) => {
              const next = [...prev]
              const last = next[next.length - 1]
              next[next.length - 1] = { ...last, plan }
              return next
            })
          } else if (evt.event === 'tool_start') {
            const tool = evt.data.tool as string
            setTurns((prev) => {
              const next = [...prev]
              const last = next[next.length - 1]
              const liveTools = [...(last.liveTools || []), { tool, status: 'running' as const }]
              next[next.length - 1] = { ...last, liveTools }
              return next
            })
          } else if (evt.event === 'tool_result') {
            const status = evt.data.status === 'error' ? 'error' : 'ok'
            const elapsed_ms = evt.data.elapsed_ms as number | undefined
            setTurns((prev) => {
              const next = [...prev]
              const last = next[next.length - 1]
              const liveTools = [...(last.liveTools || [])]
              if (liveTools.length) {
                liveTools[liveTools.length - 1] = { ...liveTools[liveTools.length - 1], status, elapsed_ms }
              }
              next[next.length - 1] = { ...last, liveTools }
              return next
            })
          } else if (evt.event === 'token') {
            const text = evt.data.text as string
            setTurns((prev) => {
              const next = [...prev]
              const last = next[next.length - 1]
              next[next.length - 1] = { ...last, answer: last.answer + text }
              return next
            })
          } else if (evt.event === 'done') {
            const citationDetails = (evt.data.citations as CitationDetail[]) || []
            const refused = Boolean(evt.data.refused)
            const toolCalls = (evt.data.tool_calls as ToolCallSummary[]) || []
            const plan = (evt.data.plan as PlanSummary) || undefined
            const suggestions = (evt.data.suggestions as string[]) || []
            const needsIngestTicker =
              evt.data.action === 'offer_ingest' ? (evt.data.ticker as string) : null
            setTurns((prev) => {
              const next = [...prev]
              const last = next[next.length - 1]
              const finished = {
                ...last,
                citationDetails,
                refused,
                toolCalls,
                plan,
                suggestions,
                needsIngestTicker,
                streaming: false,
              }
              next[next.length - 1] = finished
              if (sid) {
                localTurnsRef.current[sid] = [...(localTurnsRef.current[sid] || []), finished].slice(-20)
                persistTurns()
              }
              return next
            })
          }
            }
            break
          } catch (err) {
            const staleSession =
              err instanceof ApiError && err.status === 404 && err.detail === 'session_not_found'
            if (staleSession && sid && attempt === 0) {
              sid = null
              setSessionId(null)
              localStorage.removeItem(SESSION_KEY)
              continue
            }
            throw err
          }
        }
      } catch (err) {
        setTurns((prev) => {
          const next = [...prev]
          const last = next[next.length - 1]
          next[next.length - 1] = {
            ...last,
            answer: last.answer || failMessage(err),
            streaming: false,
          }
          return next
        })
      } finally {
        setIsBusy(false)
      }
    },
    [isBusy, sessionId, updateRecent, upsertWindow, persistTurns]
  )

  const newChat = useCallback(() => {
    if (isBusy) return
    setSessionId(null)
    localStorage.removeItem(SESSION_KEY)
    setTurns([])
  }, [isBusy])

  const switchChat = useCallback(
    async (id: string) => {
      if (isBusy || id === sessionId) return
      setSessionId(id)
      localStorage.setItem(SESSION_KEY, id)
      if (localTurnsRef.current[id]?.length) {
        setTurns(localTurnsRef.current[id])
        return
      }
      setTurns([])
      try {
        const data = await getSession(id, getClientId())
        const restored: ChatTurn[] = []
        for (const msg of data.messages) {
          if (msg.role === 'user') {
            restored.push({ question: msg.content, answer: '', citationDetails: [], streaming: false })
          } else if (restored.length) {
            restored[restored.length - 1].answer = msg.content
          }
        }
        setTurns(restored)
      } catch {
        setTurns([])
      }
    },
    [isBusy, sessionId]
  )

  useEffect(() => {
    persistWindows(chatWindows)
  }, [chatWindows, persistWindows])

  useEffect(() => {
    if (!signedIn) return
    let cancelled = false
    listSessions(getClientId())
      .then((res) => {
        if (cancelled) return
        setChatWindows(
          res.sessions.map((s) => ({
            id: s.session_id,
            title: titleFromQuestion(s.title),
            updated_at: s.updated_at,
          }))
        )
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [signedIn])

  return { sessionId, turns, isBusy, chatWindows, recentSearches, ask, newChat, switchChat }
}
