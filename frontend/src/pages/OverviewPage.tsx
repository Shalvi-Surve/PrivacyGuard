import { useCallback, useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import { demoQueries, demoSnapshot } from '../data/demo'
import { Icon } from '../components/Icon'
import type { ApiStatus, AppMode, PageId } from '../types/app'
import { getDashboardSummary, type DashboardOverview } from '../services/operations.service'

type Props = { onNavigate: (page: PageId) => void; mode?: AppMode; token?: string | null; apiStatus?: ApiStatus; onRetry?: () => void }

export function OverviewPage({ onNavigate, mode, token, apiStatus, onRetry }: Props) {
  const [summary, setSummary] = useState<DashboardOverview | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [refreshKey, setRefreshKey] = useState(0)
  const refresh = useCallback(() => setRefreshKey(value => value + 1), [])

  useEffect(() => {
    if (mode !== 'authenticated' || !token || apiStatus !== 'online') return
    let active = true
    setLoading(true)
    setError('')
    getDashboardSummary(token).then(value => { if (active) setSummary(value) })
      .catch(reason => { if (active) setError(reason instanceof Error ? reason.message : 'Dashboard overview is unavailable.') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [mode, token, apiStatus, refreshKey])

  return <>
    <div className="page-heading">
      <div><div className="section-eyebrow">WORKSPACE OVERVIEW</div><h1>Privacy operations</h1><p>Persisted query activity, shared-budget health and service status.</p></div>
      <div className="overview-actions">
        {mode === 'authenticated' && <button className="secondary-button" onClick={apiStatus === 'online' ? refresh : onRetry} disabled={loading} aria-label={apiStatus === 'online' ? 'Refresh overview' : 'Retry API connection'}><Icon name="refresh" size={14} /> {loading ? 'Refreshing…' : apiStatus === 'online' ? 'Refresh' : 'Retry connection'}</button>}
        <button className="primary-button new-query" onClick={() => onNavigate('query')}><Icon name="plus" size={15} /> New query</button>
      </div>
    </div>
    {mode === 'preview' || mode === undefined
      ? <PreviewOverview onNavigate={onNavigate} />
      : <LiveOverview summary={summary} loading={loading} error={error} apiStatus={apiStatus ?? 'checking'} onRetry={apiStatus === 'online' ? refresh : onRetry} onNavigate={onNavigate} />}
  </>
}

export function LiveOverview({ summary, loading, error, apiStatus, onRetry, onNavigate }: { summary: DashboardOverview | null; loading: boolean; error: string; apiStatus: ApiStatus; onRetry?: () => void; onNavigate: (page: PageId) => void }) {
  if (loading && !summary) return <div className="overview-loading" role="status" aria-label="Loading dashboard overview"><div className="kpi-grid overview-kpis">{Array.from({ length: 8 }, (_, i) => <div className="kpi-card skeleton-card" key={i} />)}</div><div className="dashboard-grid overview-grid"><div className="panel skeleton-panel" /><div className="panel skeleton-panel" /></div></div>
  if (error && !summary) return <section className="panel overview-error" role="alert"><Icon name="warning" size={20} /><div><b>Live overview could not be loaded</b><p>{error}</p><button className="secondary-button" onClick={onRetry}>Retry</button></div></section>
  if (apiStatus === 'checking' && !summary) return <section className="panel overview-error" role="status"><span className="spinner" /><div><b>Checking backend connection</b><p>Overview metrics will load when the API health check completes.</p></div></section>
  if (apiStatus !== 'online' && !summary) return <section className="panel overview-error" role="status"><Icon name="info" size={20} /><div><b>{apiStatus === 'degraded' ? 'Database unavailable' : 'Backend connection unavailable'}</b><p>Live metrics are not replaced with illustrative values. Retry the connection when the API is available.</p><button className="secondary-button" onClick={onRetry}>Retry connection</button></div></section>
  if (!summary) return <div className="dataset-empty"><b>No overview data loaded</b><span>Refresh to request persisted dashboard metrics.</span></div>

  const metrics = summary.metrics
  const percent = summary.budget_health.utilization === null ? null : Math.min(100, Math.max(0, summary.budget_health.utilization * 100))
  const distributionTotal = Object.values(summary.decision_distribution).reduce((sum, value) => sum + value, 0)
  const donutStyle = decisionGradient(summary.decision_distribution, distributionTotal)
  const budgetStyle = { '--budget-utilization': `${percent ?? 0}%` } as CSSProperties
  const cards = [
    ['Requests recorded', metrics.total_requests.toLocaleString(), 'Submitted analysis and protected requests'],
    ['Unique protected releases', metrics.protected_releases.toLocaleString(), 'Stored DP outputs · cached requests excluded'],
    ['Approved requests', metrics.approved_requests.toLocaleString(), 'Valid analysis, release, or cached reuse'],
    ['Rejected requests', metrics.rejected_requests.toLocaleString(), 'Validation and budget rejections'],
    ['High-risk requests', metrics.high_risk_requests.toLocaleString(), `${(metrics.risk_scored_requests ?? 0).toLocaleString()} scored · ${metrics.high_risk_percentage_of_scored == null ? 'N/A' : metrics.high_risk_percentage_of_scored.toFixed(1) + '%'} above ${metrics.high_risk_threshold == null ? 'N/A' : metrics.high_risk_threshold.toFixed(2)}`],
    ['Privacy spent', epsilon(metrics.privacy_spent), 'Across visible shared dataset budgets'],
    ['Budget remaining', epsilon(metrics.remaining_budget), 'Null when accounting is unavailable'],
    ['Accessible datasets', metrics.accessible_datasets.toLocaleString(), 'Role-granted datasets'],
  ]
  return <>
    {apiStatus !== 'online' && summary && <div className="scenario-note" role="status"><Icon name="info" size={14} /><span>Showing the last successfully loaded persisted snapshot. The backend is currently {apiStatus === 'degraded' ? 'database-degraded' : 'offline'}.</span></div>}
    {error && <div className="inline-alert error overview-stale" role="alert">Refresh failed: {error} <button className="text-button" onClick={onRetry}>Retry</button></div>}
    <section className="kpi-grid overview-kpis" aria-label="Persisted overview metrics">{cards.map(([label, value, note]) => <article className="kpi-card" key={label}><div className="kpi-top"><span>{label}</span></div><div className="kpi-value">{value}</div><div className="kpi-foot"><span>{note}</span></div></article>)}</section>
    <div className="scenario-note" role="note"><Icon name="info" size={14} /><span>High-risk is a heuristic classification. {metrics.risk_unscored_or_rejected_requests?.toLocaleString() ?? '—'} requests are unscored or rejected; missing risk values are not treated as zero. This is not a formal Differential Privacy guarantee or proof that inference attacks were prevented.</span></div>
    <section className="dashboard-grid overview-grid">
      <article className="panel activity-panel"><PanelHeader title="Query activity" subtitle={`Persisted request decisions · last ${summary.window_days} days`} action="View history" onAction={() => onNavigate('history')} /><div className="chart-legend"><Legend color="navy" label="Approved" /><Legend color="red" label="Rejected" /><Legend color="amber" label="Other" /></div>{summary.daily_activity.some(day => day.total > 0) ? <ActivityChart data={summary.daily_activity} /> : <EmptyChart label="No persisted query activity in this period" />}</article>
      <article className="panel distribution-panel"><PanelHeader title="Decision distribution" subtitle="Persisted request events" action="Query history" onAction={() => onNavigate('history')} />{distributionTotal ? <div className="distribution-body"><div className="decision-donut" style={{ background: donutStyle }}><div><b>{distributionTotal.toLocaleString()}</b><span>requests</span></div></div><div className="distribution-legend">{Object.entries(summary.decision_distribution).sort(([a], [b]) => a.localeCompare(b)).map(([decision, count], i) => <LegendRow key={decision} color={['green', 'red', 'amber', 'blue'][i % 4]} label={decision.replaceAll('_', ' ')} value={count} />)}</div></div> : <div className="dataset-empty"><b>No recorded decisions yet</b><span>Decision counts appear after a request is persisted.</span></div>}</article>
    </section>
    <section className="dashboard-grid lower-grid overview-lower">
      <article className="panel table-panel"><PanelHeader title="Recent query activity" subtitle="Persisted request metadata · no aggregate values" action="Open history" onAction={() => onNavigate('history')} />{summary.recent_activity.length ? <div className="table-wrap"><table><thead><tr><th>QUERY</th><th>USER</th><th>DATASET</th><th>TYPE</th><th>EPSILON</th><th>RISK</th><th>DECISION</th><th>TIME</th></tr></thead><tbody>{summary.recent_activity.map(row => <tr key={row.id}><td><b className="mono-id">{row.id}</b></td><td>{row.user}</td><td>{row.dataset_name ?? '—'}</td><td>{row.query_type.toUpperCase()}</td><td>{epsilon(row.epsilon)}</td><td>{row.risk_score === null ? '—' : <RiskPill value={row.risk_score} />}</td><td><DecisionPill decision={row.decision.replaceAll('_', ' ')} /></td><td><time dateTime={row.created_at}>{formatDate(row.created_at)}</time></td></tr>)}</tbody></table></div> : <div className="dataset-empty"><b>No query activity yet</b><span>Submit a SQL analysis or protected query to populate this table.</span></div>}</article>
      <article className="panel risk-panel"><PanelHeader title="Privacy budget health" subtitle={summary.budget_health.available ? 'Shared dataset accounting' : 'Accounting unavailable for one or more datasets'} action="View budgets" onAction={() => onNavigate('budgets')} />{summary.budget_health.available && percent !== null ? <div className="budget-summary"><div className="budget-ring" style={budgetStyle}><div><b>{percent.toFixed(0)}%</b><span>consumed</span></div></div><div className="budget-summary-copy"><b>{epsilon(summary.budget_health.remaining_budget)} <small>remaining</small></b><span>{epsilon(summary.budget_health.spent_budget)} of {epsilon(summary.budget_health.initial_budget)} used</span><div className="progress-track"><i style={{ width: `${percent}%` }} /></div><small>Scope: shared dataset budget</small></div></div> : <div className="dataset-empty"><b>Budget totals unavailable</b><span>Missing or inaccessible budget records are shown as unavailable.</span></div>}{summary.budget_health.datasets.length > 0 && <div className="overview-budget-list">{summary.budget_health.datasets.map(item => <div key={item.dataset_id}><b>{item.dataset_name}</b><span>{item.available ? `${epsilon(item.spent_budget)} spent · ${epsilon(item.remaining_budget)} remaining` : 'Budget unavailable'}</span></div>)}</div>}</article>
    </section>
    <section className="dashboard-grid lower-grid extra-grid">
      <article className="panel table-panel"><PanelHeader title="Recent system events" subtitle="Permission-scoped safe audit descriptions" action="Open audit logs" onAction={() => onNavigate('audit')} />{summary.recent_audit_activity.length ? summary.recent_audit_activity.map(event => <div className="feed-item" key={event.id}><span className={`feed-icon ${event.status.toLowerCase()}`}><Icon name={event.status === 'success' ? 'check' : 'info'} size={14} /></span><span><b>{event.description}</b><small>{event.event_type.replaceAll('_', ' ')} · {event.actor} · {event.status}</small></span><time dateTime={event.timestamp}>{formatTime(event.timestamp)}</time></div>) : <div className="dataset-empty"><b>No permitted audit events</b><span>Events will appear here when available to your role.</span></div>}</article>
      <article className="panel system-panel"><PanelHeader title="Operational signals" subtitle="Current service capability" />{Object.entries(summary.operational_signals).map(([key, value]) => <StatusRow key={key} label={signalLabel(key)} value={signalValue(value)} state={value === 'available' ? 'live' : 'planned'} />)}</article>
    </section>
  </>
}

function PreviewOverview({ onNavigate }: { onNavigate: (page: PageId) => void }) {
  const demoCards = [['Illustrative requests', demoSnapshot.queriesAnalyzed.toLocaleString()], ['Illustrative approvals', demoSnapshot.approvedQueries.toLocaleString()], ['Illustrative rejections', demoSnapshot.rejectedQueries.toLocaleString()], ['Illustrative budget remaining', `${(demoSnapshot.privacyBudgetInitial - demoSnapshot.privacyBudgetConsumed).toFixed(1)} ε`]]
  return <><div className="scenario-note"><Icon name="info" size={14} /><span>{demoSnapshot.generatedLabel}. These preview values are not persisted backend data, production metrics, or experimental results.</span></div><section className="kpi-grid overview-kpis" aria-label="Illustrative overview metrics">{demoCards.map(([label, value]) => <article className="kpi-card" key={label}><div className="kpi-top"><span>{label}</span></div><div className="kpi-value">{value}</div><div className="kpi-foot"><span>Illustrative preview</span></div></article>)}</section><section className="dashboard-grid overview-grid"><article className="panel activity-panel"><PanelHeader title="Query activity" subtitle="Illustrative workload" action="Query Console" onAction={() => onNavigate('query')} /><ActivityChart data={demoSnapshot.dailyActivity.map((total, i) => ({ date: `2026-11-${String(i + 15).padStart(2, '0')}`, approved: total, rejected: 0, other: 0, total }))} /></article><article className="panel table-panel"><PanelHeader title="Preview records" subtitle="Illustrative only" />{demoQueries.slice(0, 4).map(row => <div className="feed-item" key={row.id}><span><b>{row.id} · {row.type}</b><small>{row.user} · sample record</small></span><RiskPill value={row.risk} /></div>)}</article></section></>
}

function epsilon(value: number | null) { return value === null ? 'Unavailable' : `${value.toFixed(3)} ε` }
function formatDate(value: string) { return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) }
function formatTime(value: string) { return new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(new Date(value)) }
function signalLabel(key: string) { return ({ api_health: 'API health', database: 'Database', sql_analysis: 'SQL analysis', protected_releases: 'Protected releases', experiments: 'Experiments' } as Record<string, string>)[key] ?? key }
function signalValue(value: string) { return value.replaceAll('_', ' ') }
function Legend({ color, label }: { color: string; label: string }) { return <span><i className={`legend-dot ${color}`} /> {label}</span> }
function LegendRow({ color, label, value }: { color: string; label: string; value: number }) { return <div className="dist-legend-row"><span className={`dist-swatch ${color}`} /><span>{label}</span><b>{value.toLocaleString()}</b></div> }
function StatusRow({ label, value, state }: { label: string; value: string; state: 'live' | 'planned' }) { return <div className="status-row"><span className={`status-light ${state}`} /><span>{label}</span><b>{value}</b><span className={`status-label ${state}`}>{state === 'live' ? 'AVAILABLE' : 'LIMITED'}</span></div> }
function EmptyChart({ label }: { label: string }) { return <div className="dataset-empty"><b>{label}</b><span>No observations are invented to fill the chart.</span></div> }
function decisionGradient(values: Record<string, number>, total: number) {
  if (!total) return '#e6eef0'
  const colors = ['#2d967e', '#c65e54', '#d1a04b', '#426a88', '#748a98']
  let cursor = 0
  const stops = Object.entries(values).sort(([a], [b]) => a.localeCompare(b)).map(([, value], index) => {
    const start = cursor / total * 100; cursor += value
    return `${colors[index % colors.length]} ${start}% ${cursor / total * 100}%`
  })
  return `conic-gradient(${stops.join(', ')})`
}
function ActivityChart({ data }: { data: { date: string; approved: number; rejected: number; other: number; total: number }[] }) {
  const max = Math.max(1, ...data.flatMap(day => [day.approved, day.rejected, day.other]))
  const series = [{ key: 'approved', className: 'requests', title: 'Approved' }, { key: 'rejected', className: 'rejected', title: 'Rejected' }, { key: 'other', className: 'protected', title: 'Other' }] as const
  const x = (index: number) => data.length <= 1 ? 250 : 44 + index * 424 / (data.length - 1)
  const y = (value: number) => 139 - value / max * 105
  return <div className="chart-wrap"><svg className="activity-chart" viewBox="0 0 500 170" role="img" aria-label="Persisted approved, rejected and other request counts by date"><title>Query activity by decision category</title>{[34, 86, 139].map(yy => <line key={yy} x1="35" y1={yy} x2="468" y2={yy} className="chart-gridline" />)}{series.map(item => <g key={item.key}><polyline className={`chart-line ${item.className}`} points={data.map((day, index) => `${x(index)},${y(day[item.key])}`).join(' ')} />{data.map((day, index) => <circle key={day.date} className="chart-point" cx={x(index)} cy={y(day[item.key])} r="3"><title>{`${day.date}: ${item.title} ${day[item.key]} requests`}</title></circle>)}</g>)}{data.map((day, index) => <text key={day.date} x={x(index)} y="162" textAnchor="middle" className="chart-day">{new Intl.DateTimeFormat(undefined, { month: 'numeric', day: 'numeric' }).format(new Date(`${day.date}T00:00:00`))}</text>)}</svg><div className="chart-y-labels"><span>{max}</span><span>{Math.round(max / 2)}</span><span>0 requests</span></div></div>
}

export function PanelHeader({ title, subtitle, action, onAction }: { title: string; subtitle?: string; action?: string; onAction?: () => void }) {
  return <div className="panel-header"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{action && onAction && <button className="text-button" onClick={onAction}>{action} <span>→</span></button>}</div>
}

export function DecisionPill({ decision }: { decision: string }) {
  return <span className={`decision-pill ${decision.toLowerCase()}`}><i />{decision}</span>
}

export function RiskPill({ value }: { value: number }) {
  const tone = value >= .67 ? 'high' : value >= .34 ? 'medium' : 'low'
  return <span className={`risk-pill ${tone}`}>{value.toFixed(2)}</span>
}
