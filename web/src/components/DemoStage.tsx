import MessageBubble from './MessageBubble'
import { REPLAY_HANDOFF } from '../demo/appleRevenueReplay'
import { useReplay } from '../demo/useReplay'

export default function DemoStage({
  onAsk,
  onOpenFeatures,
}: {
  onAsk: (q: string) => void
  onOpenFeatures: () => void
}) {
  const { turn, phase, skip, autoOpenChunkId } = useReplay()

  function askYourself() {
    if (phase === 'playing') skip()
    window.setTimeout(() => {
      const input = document.getElementById('composer-input')
      if (!(input instanceof HTMLInputElement)) return
      input.focus()
      input.scrollIntoView({ block: 'nearest' })
    }, 0)
  }

  return (
    <div className="demo-stage">
      <div className="demo-banner">
        <div>
          <span className="example-badge">Example</span>
          <b>This is a recorded answer, not live data.</b>
          <span className="muted">Ask your own question below to search filings, prices, and your portfolio.</span>
        </div>
        <div className="demo-banner-actions">
          {phase === 'playing' && (
            <button type="button" className="chip" onClick={skip}>
              Skip
            </button>
          )}
          <button type="button" className="demo-cta" onClick={askYourself}>
            Ask your own question
          </button>
          <button type="button" className="chip" onClick={onOpenFeatures}>
            See all features
          </button>
        </div>
      </div>
      {turn.question && (
        <MessageBubble turn={turn} onAsk={onAsk} autoOpenChunkId={autoOpenChunkId} example />
      )}
      {phase === 'done' && (
        <div className="demo-handoff">
          <div className="section-title">Or try one of these</div>
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
