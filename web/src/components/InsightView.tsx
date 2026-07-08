import { useEffect, useState } from 'react'
import { useInsight } from '../hooks/useInsight'
import InsightCard from './InsightCard'

interface Props {
  companies: Record<string, string>
  initialTicker: string | null
}

export default function InsightView({ companies, initialTicker }: Props) {
  const [ticker, setTicker] = useState<string | null>(initialTicker)
  const state = useInsight(ticker)

  useEffect(() => {
    if (initialTicker) setTicker(initialTicker)
  }, [initialTicker])

  return (
    <div className="insight-view">
      <div className="view-header">
        <h2>Insight Brief</h2>
      </div>
      <div className="company-picker company-picker-row">
        {Object.entries(companies).map(([t, name]) => (
          <button
            key={t}
            className={`chip ${t === ticker ? 'active' : ''}`}
            onClick={() => setTicker(t)}
          >
            {t} <span className="muted">{name}</span>
          </button>
        ))}
      </div>
      <InsightCard state={state} />
    </div>
  )
}
