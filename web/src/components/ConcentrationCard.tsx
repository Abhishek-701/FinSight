import { pct } from '../lib/format'
import type { PortfolioConcentration } from '../lib/types'

const BAND_LABEL: Record<PortfolioConcentration['band'], string> = {
  diversified: 'Diversified',
  'moderately concentrated': 'Moderately Concentrated',
  concentrated: 'Concentrated',
}

export default function ConcentrationCard({ concentration }: { concentration: PortfolioConcentration | null }) {
  if (!concentration) return null
  return (
    <div className="concentration-card">
      <div className="section-title">Concentration</div>
      <div className="valuation-grid">
        <div className="valuation-tile">
          <span className="strip-label">Top Holding</span>
          <strong>{concentration.top_ticker}</strong>
          <span className="muted">{pct(concentration.top_weight)} of portfolio</span>
        </div>
        <div className="valuation-tile">
          <span className="strip-label">Top 3 Holdings</span>
          <strong>{pct(concentration.top3_weight)}</strong>
        </div>
        <div className="valuation-tile">
          <span className="strip-label">HHI</span>
          <strong>{concentration.hhi.toLocaleString()}</strong>
          <span className={`concentration-band band-${concentration.band.replace(/\s+/g, '-')}`}>
            {BAND_LABEL[concentration.band]}
          </span>
        </div>
      </div>
    </div>
  )
}
