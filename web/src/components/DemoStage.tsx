import MessageBubble from './MessageBubble'
import { REPLAY_HANDOFF } from '../demo/appleRevenueReplay'
import { useReplay } from '../demo/useReplay'

export default function DemoStage({ onAsk }: { onAsk: (q: string) => void }) {
  const { turn, phase, skip, autoOpenChunkId } = useReplay()

  return (
    <div className="demo-stage">
      <div className="demo-stage-bar">
        <div>
          <b>Watch FinSight answer</b>
          <span className="muted">Recorded from the eval suite — not a live quote</span>
        </div>
        {phase === 'playing' && (
          <button type="button" className="chip" onClick={skip}>
            Skip
          </button>
        )}
      </div>
      {turn.question && (
        <MessageBubble turn={turn} onAsk={onAsk} autoOpenChunkId={autoOpenChunkId} example />
      )}
      {phase === 'done' && (
        <div className="demo-handoff">
          <div className="section-title">Your turn</div>
          <div className="chips">
            {REPLAY_HANDOFF.map((chip) => (
              <button key={chip.label} type="button" className="chip" onClick={() => onAsk(chip.q)}>
                {chip.label}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
