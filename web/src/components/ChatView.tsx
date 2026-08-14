import { useEffect, useRef } from 'react'
import DemoStage from './DemoStage'
import MessageBubble from './MessageBubble'
import type { ChatTurn } from '../hooks/useChat'

const STICK_PX = 96

export default function ChatView({ turns, onAsk }: { turns: ChatTurn[]; onAsk: (q: string) => void }) {
  const rootRef = useRef<HTMLDivElement>(null)
  const stickRef = useRef(true)
  const prevLen = useRef(0)

  useEffect(() => {
    const workspace = rootRef.current?.closest('.workspace') as HTMLElement | null
    if (!workspace) return
    const onScroll = () => {
      stickRef.current = workspace.scrollHeight - workspace.scrollTop - workspace.clientHeight < STICK_PX
    }
    workspace.addEventListener('scroll', onScroll, { passive: true })
    return () => workspace.removeEventListener('scroll', onScroll)
  }, [])

  useEffect(() => {
    const workspace = rootRef.current?.closest('.workspace') as HTMLElement | null
    if (!workspace) return
    if (turns.length > prevLen.current) stickRef.current = true
    prevLen.current = turns.length
    if (!stickRef.current) return
    workspace.scrollTop = workspace.scrollHeight
  }, [turns.length, turns[turns.length - 1]?.answer, turns[turns.length - 1]?.liveTools])

  const asked = turns.map((t) => t.question).filter(Boolean)

  if (!turns.length) {
    return (
      <div className="thread" ref={rootRef}>
        <DemoStage onAsk={onAsk} />
      </div>
    )
  }

  return (
    <div className="thread" ref={rootRef}>
      {turns.map((turn, i) => (
        <MessageBubble
          turn={turn}
          onAsk={onAsk}
          key={i}
          showSuggestions={i === turns.length - 1}
          asked={asked}
        />
      ))}
    </div>
  )
}
