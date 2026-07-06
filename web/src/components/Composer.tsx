import { useState } from 'react'
import ExampleChips from './ExampleChips'

interface Props {
  isBusy: boolean
  onAsk: (question: string) => void
  onClear: () => void
}

export default function Composer({ isBusy, onAsk, onClear }: Props) {
  const [value, setValue] = useState('')

  function submit(e: React.FormEvent) {
    e.preventDefault()
    const q = value.trim()
    if (!q) return
    setValue('')
    onAsk(q)
  }

  return (
    <div className="composer">
      <div className="composer-inner">
        <ExampleChips disabled={isBusy} onPick={onAsk} />
        <form onSubmit={submit}>
          <input
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="Ask any financial question..."
            autoComplete="off"
            autoFocus
            disabled={isBusy}
          />
          <button className="ask" type="submit" disabled={isBusy}>
            Ask
          </button>
        </form>
        <button className="clear" type="button" disabled={isBusy} onClick={onClear}>
          Clear session
        </button>
        <div className="footnote">Research support only. Data may be delayed. Not investment advice.</div>
      </div>
    </div>
  )
}
