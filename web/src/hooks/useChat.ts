import { useCallback, useEffect, useRef, useState } from 'react'
import { getSession, streamChat } from '../lib/api'
import { titleFromQuestion } from '../lib/format'
import type { CitationDetail, PlanSummary, ToolCallSummary } from '../lib/types'

export interface ChatTurn {
  question: string
  answer: string
  citationDetails: CitationDetail[]
  streaming: boolean
  refused?: boolean
  toolCalls?: ToolCallSummary[]
  plan?: PlanSummary
}

export interface ChatWindow {
  id: string
  title: string
  updated_at: string
}

const SESSION_KEY = 'finsight_session_id'
const WINDOWS_KEY = 'finsight_chat_windows'
const RECENT_KEY = 'finsight_recent_searches'
const TURNS_KEY = 'finsight_local_turns'

const DEFAULT_PROMPTS = [
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

export function useChat() {
  const [sessionId, setSessionId] = useState<string | null>(() => localStorage.getItem(SESSION_KEY))
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [isBusy, setIsBusy] = useState(false)
  const [chatWindows, setChatWindows] = useState<ChatWindow[]>(() => loadJson(WINDOWS_KEY, []))
  const [recentSearches, setRecentSearches] = useState<string[]>(() =>
    loadJson(RECENT_KEY, DEFAULT_PROMPTS.slice(0, 3))
  )
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
    setRecentSearches((prev) => {
      const next = [question, ...prev.filter((q) => q !== question)].slice(0, 8)
      localStorage.setItem(RECENT_KEY, JSON.stringify(next))
      return next
    })
  }, [])

  const ask = useCallback(
    async (question: string) => {
      if (isBusy) return
      setIsBusy(true)
      updateRecent(question)
      setTurns((prev) => [...prev, { question, answer: '', citationDetails: [], streaming: true }])

      let sid = sessionId
      try {
        for await (const evt of streamChat(question, sid)) {
          if (evt.event === 'session') {
            sid = evt.data.session_id as string
            setSessionId(sid)
            localStorage.setItem(SESSION_KEY, sid)
            upsertWindow(sid, question)
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
            setTurns((prev) => {
              const next = [...prev]
              const last = next[next.length - 1]
              const finished = { ...last, citationDetails, refused, toolCalls, plan, streaming: false }
              next[next.length - 1] = finished
              if (sid) {
                localTurnsRef.current[sid] = [...(localTurnsRef.current[sid] || []), finished].slice(-20)
                persistTurns()
              }
              return next
            })
          }
        }
      } catch {
        setTurns((prev) => {
          const next = [...prev]
          const last = next[next.length - 1]
          next[next.length - 1] = {
            ...last,
            answer: last.answer || 'Request failed. Please try again.',
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
        const data = await getSession(id)
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

  return { sessionId, turns, isBusy, chatWindows, recentSearches, ask, newChat, switchChat }
}
