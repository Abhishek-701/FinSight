import { useEffect, useRef } from 'react'
import DemoStage from './DemoStage'
import MessageBubble from './MessageBubble'
import type { ChatTurn } from '../hooks/useChat'

export default function ChatView({ turns, onAsk }: { turns: ChatTurn[]; onAsk: (q: string) => void }) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [turns.length, turns[turns.length - 1]?.answer])

  if (!turns.length) {
    return (
      <div className="thread">
        <DemoStage onAsk={onAsk} />
      </div>
    )
  }

  return (
    <div className="thread">
      {turns.map((turn, i) => (
        <MessageBubble turn={turn} onAsk={onAsk} key={i} />
      ))}
      <div ref={bottomRef} />
    </div>
  )
}
