import { useCallback, useEffect, useRef, useState } from 'react'
import type { ChatTurn } from '../hooks/useChat'
import {
  REPLAY_ANSWER_TOKENS,
  REPLAY_CITE_ID,
  REPLAY_QUESTION,
  emptyReplayTurn,
  finalReplayTurn,
} from './appleRevenueReplay'

export type ReplayPhase = 'playing' | 'done'

export function useReplay() {
  const [turn, setTurn] = useState<ChatTurn>(emptyReplayTurn)
  const [phase, setPhase] = useState<ReplayPhase>('playing')
  const [autoOpenChunkId, setAutoOpenChunkId] = useState<string | null>(null)
  const timers = useRef<number[]>([])

  const clearTimers = useCallback(() => {
    for (const id of timers.current) window.clearTimeout(id)
    timers.current = []
  }, [])

  const later = useCallback(
    (ms: number, fn: () => void) => {
      timers.current.push(window.setTimeout(fn, ms))
    },
    [],
  )

  const skip = useCallback(() => {
    clearTimers()
    setTurn(finalReplayTurn())
    setAutoOpenChunkId(REPLAY_CITE_ID)
    setPhase('done')
  }, [clearTimers])

  useEffect(() => {
    later(0, () => {
      setTurn({
        question: REPLAY_QUESTION,
        answer: '',
        citationDetails: [],
        streaming: true,
      })
    })
    later(350, () => {
      setTurn((prev) => ({
        ...prev,
        plan: { strategy: 'lookup', intent: 'facts', steps: ['facts_lookup'] },
      }))
    })
    later(700, () => {
      setTurn((prev) => ({
        ...prev,
        liveTools: [{ tool: 'facts_lookup', status: 'running' }],
      }))
    })
    later(1600, () => {
      setTurn((prev) => ({
        ...prev,
        liveTools: [{ tool: 'facts_lookup', status: 'ok', elapsed_ms: 48 }],
      }))
    })

    let cursor = 0
    const tokenStart = 1850
    const tokenGap = 22
    for (const token of REPLAY_ANSWER_TOKENS) {
      const captured = token
      later(tokenStart + cursor * tokenGap, () => {
        setTurn((prev) => ({ ...prev, answer: prev.answer + captured }))
      })
      cursor += 1
    }

    later(tokenStart + cursor * tokenGap + 200, () => {
      setTurn(finalReplayTurn())
      setPhase('done')
    })
    later(tokenStart + cursor * tokenGap + 550, () => {
      setAutoOpenChunkId(REPLAY_CITE_ID)
    })

    return clearTimers
  }, [clearTimers, later])

  return { turn, phase, skip, autoOpenChunkId }
}
