import { useEffect, useState } from 'react'
import { getAdminAudit, getAdminSummary } from '../lib/api'
import Sparkline from './Sparkline'
import { money, pct } from '../lib/format'
import type { AdminAuditRow, AdminSummary, HistoryRow } from '../lib/types'

/** Sparkline only reads `.close` — reuse it for any single numeric series without a new chart. */
function toSparklineRows(values: number[]): HistoryRow[] {
  return values.map((v, i) => ({ date: String(i), open: v, high: v, low: v, close: v, volume: 0 }))
}

function ms(value: number | null): string {
  return value === null ? '—' : `${Math.round(value)}ms`
}

export default function AdminView() {
  const [summary, setSummary] = useState<AdminSummary | null>(null)
  const [auditRows, setAuditRows] = useState<AdminAuditRow[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([getAdminSummary(7), getAdminAudit(15)])
      .then(([s, a]) => {
        setSummary(s)
        setAuditRows(a.rows)
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load admin data'))
  }, [])

  if (error) return <p className="muted">{error}</p>
  if (!summary) return <p className="muted">Loading…</p>

  const requestSpark = toSparklineRows(summary.requests.per_day.map((d) => d.count))
  const tokenSpark = toSparklineRows(summary.tokens.per_day.map((d) => d.input + d.output))

  return (
    <div className="admin-view">
      <div className="section-title">Last {summary.window_days} days</div>
      <div className="valuation-grid">
        <div className="valuation-tile">
          <span className="strip-label">Requests</span>
          <strong>{summary.requests.total.toLocaleString()}</strong>
          <Sparkline rows={requestSpark} />
        </div>
        <div className="valuation-tile">
          <span className="strip-label">Error Rate</span>
          <strong>{pct(summary.requests.error_rate) ?? '0%'}</strong>
        </div>
        <div className="valuation-tile">
          <span className="strip-label">Latency p95</span>
          <strong>{ms(summary.latency_ms.overall.p95)}</strong>
          <span className="muted">p50 {ms(summary.latency_ms.overall.p50)}</span>
        </div>
        <div className="valuation-tile">
          <span className="strip-label">Est. Token Spend</span>
          <strong>{money(summary.tokens.est_cost_usd) ?? '$0'}</strong>
          <Sparkline rows={tokenSpark} />
        </div>
        <div className="valuation-tile">
          <span className="strip-label">Refusal Rate</span>
          <strong>{pct(summary.chat.refusal_rate) ?? '0%'}</strong>
          <span className="muted">{summary.chat.turns} chat turns</span>
        </div>
        <div className="valuation-tile">
          <span className="strip-label">Users</span>
          <strong>{summary.users.total}</strong>
          <span className="muted">{summary.users.active_sessions} active sessions</span>
        </div>
      </div>

      <div className="section-title">Slowest routes</div>
      <div className="table-scroll">
        <table className="admin-table">
          <thead>
            <tr>
              <th>Route</th>
              <th>Count</th>
              <th>p50</th>
              <th>p95</th>
            </tr>
          </thead>
          <tbody>
            {summary.latency_ms.by_route.length === 0 && (
              <tr>
                <td colSpan={4} className="muted">No traffic yet.</td>
              </tr>
            )}
            {summary.latency_ms.by_route.map((r) => (
              <tr key={r.route}>
                <td>{r.route}</td>
                <td>{r.count}</td>
                <td>{ms(r.p50)}</td>
                <td>{ms(r.p95)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="section-title">Recent chat turns</div>
      <div className="table-scroll">
        <table className="admin-table">
          <thead>
            <tr>
              <th>Time (UTC)</th>
              <th>Question</th>
              <th>Refused</th>
              <th>Elapsed</th>
            </tr>
          </thead>
          <tbody>
            {auditRows.length === 0 && (
              <tr>
                <td colSpan={4} className="muted">No chat turns yet.</td>
              </tr>
            )}
            {auditRows.map((row, i) => (
              <tr key={row.request_id ?? i}>
                <td>{row.created_at}</td>
                <td>{row.question}</td>
                <td>{row.refused ? 'Yes' : 'No'}</td>
                <td>{row.elapsed_ms !== null ? `${row.elapsed_ms}ms` : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
