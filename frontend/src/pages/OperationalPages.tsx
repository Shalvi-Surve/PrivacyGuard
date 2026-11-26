import { useEffect, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { demoAudit, demoQueries, demoUsers, seededRoles } from '../data/demo'
import { DataTable } from '../components/common/DataTable'
import type { TableColumn } from '../components/common/DataTable'
import { Icon } from '../components/Icon'
import { DecisionPill, PanelHeader, RiskPill } from './OverviewPage'
import { getQueryHistoryDetail, listBudgets, listAuditLogs, listQueryHistory, type AuditItem, type BudgetPage, type QueryHistoryItem } from '../services/operations.service'
import { ApiError } from '../services/api'
import { listDatasets } from '../services/dataset.service'
import { listManagedUsers, resetManagedUserPassword, type ManagedUser } from '../services/users.service'
import type { ApiStatus, AppMode, DatasetRecord, UserProfile } from '../types/app'

function PageHeading({ eyebrow, title, description }: { eyebrow: string; title: string; description: string }) {
  return <div className="page-heading"><div><div className="section-eyebrow">{eyebrow}</div><h1>{title}</h1><p>{description}</p></div></div>
}

export function QueryHistoryPage({ mode, token, apiStatus, profile }: { mode: AppMode; token: string | null; apiStatus: ApiStatus; profile: UserProfile | null }) {
  const [page, setPage] = useState(1); const [search, setSearch] = useState(''); const [type, setType] = useState(''); const [decision, setDecision] = useState(''); const [datasetId, setDatasetId] = useState(''); const [userId, setUserId] = useState('')
  const [from, setFrom] = useState(''); const [to, setTo] = useState(''); const [rows, setRows] = useState<QueryHistoryItem[]>([]); const [total, setTotal] = useState(0); const [datasets, setDatasets] = useState<DatasetRecord[]>([]); const [selected, setSelected] = useState<QueryHistoryItem | null>(null); const [selectedDetail, setSelectedDetail] = useState<(QueryHistoryItem & { detail?: string }) | null>(null); const [loading, setLoading] = useState(false); const [error, setError] = useState('')
  const pageSize = 20
  const isAdmin = profile?.roles.includes('administrator') === true
  useEffect(() => { if (!token || mode !== 'authenticated' || apiStatus !== 'online') return; listDatasets(token).then(result => setDatasets(result.items)).catch(() => setDatasets([])) }, [mode, token, apiStatus])
  useEffect(() => {
    if (!token || mode !== 'authenticated' || apiStatus !== 'online') return
    let active = true; setLoading(true); setError('')
    const dateFrom = from ? new Date(from).toISOString() : undefined; const dateTo = to ? new Date(to).toISOString() : undefined
    const exactRecordRef = search.trim().match(/^[PA]-\d+$/i)?.[0].toUpperCase()
    const request = exactRecordRef
      ? getQueryHistoryDetail(exactRecordRef, token).then(item => {
          const matches = matchesHistoryFilters(item, { datasetId, userId: isAdmin ? userId : '', queryType: type, decision, dateFrom, dateTo })
          return { items: matches ? [item] : [], total: matches ? 1 : 0, page: 1, page_size: pageSize }
        })
      : listQueryHistory(token, { page, page_size: pageSize, search, query_type: type || undefined, decision: decision || undefined, dataset_id: datasetId ? Number(datasetId) : undefined, user_id: isAdmin && userId ? Number(userId) : undefined, date_from: dateFrom, date_to: dateTo })
    request
      .then(result => { if (active) { setRows(result.items); setTotal(result.total) } })
      .catch(reason => {
        if (!active) return
        if (exactRecordRef && reason instanceof ApiError && reason.status === 404) { setRows([]); setTotal(0); return }
        setError(reason instanceof Error ? reason.message : 'Could not load query history.')
      })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [mode, token, apiStatus, page, search, type, decision, datasetId, userId, from, to, isAdmin])
  const maxPage = Math.max(1, Math.ceil(total / pageSize))
  async function openDetail(row: QueryHistoryItem) {
    setSelected(row); setSelectedDetail(null)
    if (!token) return
    try { setSelectedDetail(await getQueryHistoryDetail(row.id, token)) } catch { setSelectedDetail({ ...row }) }
  }
  return <div className="module-view"><PageHeading eyebrow="WORKSPACE · PERSISTED REQUESTS" title="Query History" description="Search analysis-only requests and protected release metadata. Raw SQL and aggregate results are not stored in this view." />
    {mode !== 'authenticated' && <div className="accounting-callout"><Icon name="info" size={17} /><div><b>Sign in to view persisted records</b><span>No illustrative query history is substituted.</span></div></div>}
    {mode === 'authenticated' && apiStatus !== 'online' && <div className="accounting-callout"><Icon name="info" size={17} /><div><b>Backend unavailable</b><span>History filters remain available when the API reconnects.</span></div></div>}
    {error && <div className="inline-alert error" role="alert">{error}</div>}
    <section className="panel explorer-panel operational-panel">
      <div className="filter-card" aria-label="Query history filters">
        <div className="filter-card-heading"><div><b>Filter query history</b><small>Results update as you change filters</small></div></div>
        <div className="filter-row filter-row-search"><label className="filter-field"><span>Search</span><input value={search} onChange={event => { setPage(1); setSearch(event.target.value) }} placeholder="Search query ID, user, dataset or fingerprint" /></label></div>
        <div className="filter-row filter-row-three">
          <label className="filter-field"><span>Dataset</span><select value={datasetId} onChange={event => { setPage(1); setDatasetId(event.target.value) }}><option value="">All accessible datasets</option>{datasets.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          {isAdmin && <label className="filter-field"><span>User ID</span><input type="number" min="1" value={userId} onChange={event => { setPage(1); setUserId(event.target.value) }} placeholder="All users" /></label>}
          <label className="filter-field"><span>Query Type</span><select value={type} onChange={event => { setPage(1); setType(event.target.value) }}><option value="">All types</option><option value="count">COUNT</option><option value="sum">SUM</option></select></label>
        </div>
        <div className="filter-row filter-row-three">
          <label className="filter-field"><span>Decision</span><select value={decision} onChange={event => { setPage(1); setDecision(event.target.value) }}><option value="">All decisions</option><option value="analysis_only">Analysis only</option><option value="released">Released</option><option value="cached">Cached</option><option value="budget_rejected">Budget rejected</option><option value="rejected">Rejected</option><option value="execution_failed">Execution failed</option></select></label>
          <label className="filter-field"><span>From Date</span><input type="datetime-local" value={from} onChange={event => { setPage(1); setFrom(event.target.value) }} /></label>
          <label className="filter-field"><span>To Date</span><input type="datetime-local" value={to} onChange={event => { setPage(1); setTo(event.target.value) }} /></label>
        </div>
      </div>
      {loading ? <div className="dataset-empty"><span className="spinner dataset-spinner" />Loading persisted history…</div> : rows.length === 0 ? <div className="dataset-empty"><Icon name="clock" size={20} /><b>{mode === 'authenticated' && apiStatus === 'online' ? 'No matching history records' : 'History unavailable'}</b><span>Analysis and protected-release requests appear here after they are submitted.</span></div> : <div className="table-wrap data-table-wrap operational-table-wrap history-table-wrap"><table><thead><tr><th>QUERY ID</th><th>USER</th><th>DATASET</th><th>TYPE</th><th>KIND</th><th>FINGERPRINT</th><th>EPSILON</th><th>RISK</th><th>DECISION</th><th>TIME</th></tr></thead><tbody>{rows.map(row => <tr key={row.id} className="clickable-row" tabIndex={0} onClick={() => openDetail(row)} onKeyDown={event => { if (event.key === 'Enter') openDetail(row) }}><td><b className="mono-id">{row.id}</b></td><td>{row.username}</td><td>{row.dataset_name || 'Unscoped analysis'}</td><td>{row.query_type.toUpperCase()}</td><td><span className={`source-chip ${row.request_kind === 'analysis' ? 'demo' : 'live'}`}>{row.request_kind === 'analysis' ? 'ANALYSIS ONLY' : 'PROTECTED'}</span></td><td><code className="short-fingerprint" title={row.fingerprint || undefined} aria-label={row.fingerprint ? `Fingerprint ${row.fingerprint}` : undefined}>{row.fingerprint || '—'}</code></td><td>{row.epsilon == null ? 'N/A' : `${row.epsilon.toFixed(3)} ε`}</td><td>{row.risk_score == null ? '—' : <RiskPill value={row.risk_score} />}</td><td><DecisionPill decision={row.decision.replaceAll('_', ' ')} /></td><td>{new Date(row.created_at).toLocaleString()}</td></tr>)}</tbody></table></div>}
      <div className="table-pagination operational-pagination"><span>{total} records · Page {Math.min(page, maxPage)} of {maxPage}</span><div><button onClick={() => setPage(value => Math.max(1, value - 1))} disabled={page <= 1 || loading}>Previous</button><button onClick={() => setPage(value => Math.min(maxPage, value + 1))} disabled={page >= maxPage || loading}>Next</button></div></div>
    </section>
    {selected && <DetailDrawer title={`History ${selected.id}`} subtitle={`${selected.username} · ${selected.dataset_name || 'unscoped analysis'}`} onClose={() => { setSelected(null); setSelectedDetail(null) }}><div className="drawer-badges"><DecisionPill decision={selected.decision.replaceAll('_', ' ')} /><span className="type-chip">{selected.request_kind === 'analysis' ? 'Analysis only' : 'Protected release'}</span></div><Detail label="Query fingerprint" value={selectedDetail?.fingerprint || 'Not generated for rejected request'} code /><Detail label="Aggregate type" value={selectedDetail?.query_type.toUpperCase() || selected.query_type.toUpperCase()} /><Detail label="Referenced attributes" value={selectedDetail?.attributes.join(', ') || selected.attributes.join(', ') || 'None'} /><Detail label="Epsilon expenditure" value={selected.epsilon == null ? 'N/A' : `${selected.epsilon.toFixed(4)} ε${selected.request_kind === 'analysis' ? ' · analysis only' : ''}`} /><Detail label="Risk score" value={selected.risk_score == null ? 'Not calculated' : `${selected.risk_score.toFixed(3)} · heuristic`} /><Detail label="Timestamp" value={new Date(selected.created_at).toLocaleString()} />{selectedDetail?.detail && <div className="drawer-note">{selectedDetail.detail}</div>}</DetailDrawer>}
  </div>
}

function matchesHistoryFilters(item: QueryHistoryItem, filters: { datasetId: string; userId: string; queryType: string; decision: string; dateFrom?: string; dateTo?: string }) {
  if (filters.datasetId && item.dataset_id !== Number(filters.datasetId)) return false
  if (filters.userId && item.user_id !== Number(filters.userId)) return false
  if (filters.queryType && item.query_type.toLowerCase() !== filters.queryType.toLowerCase()) return false
  if (filters.decision && item.decision.toLowerCase() !== filters.decision.toLowerCase()) return false
  const createdAt = new Date(item.created_at).getTime()
  if (filters.dateFrom && createdAt < new Date(filters.dateFrom).getTime()) return false
  if (filters.dateTo && createdAt > new Date(filters.dateTo).getTime()) return false
  return true
}

export function PrivacyBudgetsPage({ mode, token, apiStatus }: { mode: AppMode; token: string | null; apiStatus: ApiStatus }) {
  const [data, setData] = useState<BudgetPage | null>(null); const [loading, setLoading] = useState(false); const [error, setError] = useState('')
  useEffect(() => { if (!token || mode !== 'authenticated' || apiStatus !== 'online') return; let active = true; setLoading(true); setError(''); listBudgets(token, 1, 100).then(result => { if (active) setData(result) }).catch(reason => { if (active) setError(reason instanceof Error ? reason.message : 'Could not load privacy budgets.') }).finally(() => { if (active) setLoading(false) }); return () => { active = false } }, [mode, token, apiStatus])
  const budgets = data?.items || []; const totalInitial = budgets.reduce((sum, item) => sum + item.initial_epsilon, 0); const spent = budgets.reduce((sum, item) => sum + item.spent_epsilon, 0); const remaining = budgets.reduce((sum, item) => sum + item.remaining_epsilon, 0); const utilization = totalInitial ? Math.min(100, spent / totalInitial * 100) : 0
  const ledger = [...(data?.ledger || [])].reverse(); const running = ledger.reduce<{ id: number; value: number }[]>((acc, item) => { acc.push({ id: item.id, value: (acc.at(-1)?.value || 0) + item.epsilon }); return acc }, [])
  const chartMax = Math.max(1, ...running.map(item => item.value))
  return <div className="module-view"><PageHeading eyebrow="PRIVACY CONTROLS · PERSISTED ACCOUNTING" title="Privacy Budgets" description="Shared dataset epsilon is authoritative; ledger entries show only newly charged releases." />{data?.accounting_status === 'nominal_uncertified' && <div className="accounting-callout"><Icon name="info" size={17} /><div><b>Nominal epsilon accounting</b><span>Totals sum configured epsilon for unique releases. The production finite-precision sampler has no established formal DP guarantee, so these are not certified privacy expenditures.</span></div></div>}
    {mode !== 'authenticated' && <div className="accounting-callout"><Icon name="info" size={17} /><div><b>Sign in to inspect budgets</b><span>No sample expenditure is shown as live accounting.</span></div></div>}{mode === 'authenticated' && apiStatus !== 'online' && <div className="accounting-callout"><Icon name="info" size={17} /><div><b>Budget service unavailable</b><span>Dataset budget values will load after the backend reconnects.</span></div></div>}{error && <div className="inline-alert error" role="alert">{error}</div>}
    {loading ? <div className="dataset-empty"><span className="spinner dataset-spinner" />Loading budget ledger…</div> : <><section className="budget-metric-grid"><Metric label="Initial dataset budgets" value={`${totalInitial.toFixed(3)} ε`} meta={`${budgets.length} accessible dataset(s)`} icon="database" /><Metric label="Nominal expenditure" value={`${spent.toFixed(3)} ε`} meta="Sum of persisted dataset budgets" icon="plus" /><Metric label="Remaining budget" value={`${remaining.toFixed(3)} ε`} meta="Initial budget less committed releases" icon="wallet" /><article className="panel budget-state-card"><span className="metric-label">OVERALL UTILIZATION</span><b className={`state-pill ${budgets.some(item => item.state === 'EXHAUSTED' || item.state === 'CRITICAL') ? 'critical' : 'normal'}`}>{utilization.toFixed(1)}%</b><small>Across currently accessible datasets</small></article></section>
      <section className="dashboard-grid budget-layout"><article className="panel budget-chart-panel"><PanelHeader title="Dataset budget composition" subtitle="Live values from the shared privacy budget rows" />{budgets.length ? budgets.map(item => <div className="budget-dataset-row" key={item.dataset_id}><div className="budget-dataset-heading"><b>{item.dataset_name}</b><span className={`state-pill ${item.state === 'NORMAL' ? 'normal' : 'critical'}`}>{item.state}</span></div><div className="progress-track"><i style={{ width: `${Math.min(100, item.utilization * 100)}%` }} /></div><small>{item.spent_epsilon.toFixed(3)} / {item.initial_epsilon.toFixed(3)} ε used · {item.remaining_epsilon.toFixed(3)} ε remaining · {item.release_count} charged release(s)</small></div>) : <div className="dataset-empty"><b>No accessible budgets</b><span>Create or receive access to a dataset to see accounting.</span></div>}</article><article className="panel composition-panel"><PanelHeader title="Expenditure over time" subtitle="Cumulative charged ledger entries" />{running.length ? <div className="epsilon-chart" role="img" aria-label="Cumulative epsilon expenditure by release">{running.map((point, index) => <div key={point.id} title={`${point.value.toFixed(3)} epsilon`}><i style={{ height: `${Math.max(5, point.value / chartMax * 100)}%` }} /><small>{index + 1}</small></div>)}</div> : <div className="dataset-empty"><Icon name="wallet" size={19} /><b>No charged releases yet</b><span>The chart will reflect saved ledger activity.</span></div>}<p>Basic sequential composition adds epsilon across distinct releases. Cached exact repeats do not add a new ledger charge.</p></article></section>
      <section className="panel explorer-panel"><div className="embedded-table-heading"><div><h2>Release ledger</h2><p>User is shown for attribution; budget is shared across permitted roles.</p></div><span className="source-chip live">LIVE ACCOUNTING</span></div>{data?.ledger.length ? <div className="data-table-wrap"><table><thead><tr><th>LEDGER ID</th><th>QUERY</th><th>DATASET</th><th>USER ATTRIBUTION</th><th>EPSILON</th><th>EVENT</th><th>TIMESTAMP</th></tr></thead><tbody>{data.ledger.map(item => <tr key={item.id}><td><b className="mono-id">{item.id}</b></td><td>{item.query_id ? `P-${item.query_id}` : '—'}</td><td>{item.dataset_name}</td><td>{item.user || '—'}</td><td>{item.epsilon.toFixed(4)} ε</td><td>{item.event_type}</td><td>{new Date(item.created_at).toLocaleString()}</td></tr>)}</tbody></table></div> : <div className="dataset-empty"><b>No ledger entries</b><span>No privacy budget has been charged for accessible datasets.</span></div>}</section></>}
  </div>
}

export function RiskAnalysisPage() {
  const inputs = [
    { key: 'Query sensitivity', value: .5, weight: .20, color: 'navy' },
    { key: 'Data sensitivity', value: .8, weight: .25, color: 'teal' },
    { key: 'History overlap', value: .6, weight: .25, color: 'amber' },
    { key: 'Predicate refinement proxy', value: .4, weight: .20, color: 'violet' },
    { key: 'Query-type risk', value: .8, weight: .10, color: 'blue' },
  ]
  const score = inputs.reduce((sum, item) => sum + item.value * item.weight, 0)
  const columns: TableColumn<(typeof demoQueries)[number]>[] = [
    { id: 'id', label: 'QUERY', value: row => row.id, render: row => <b className="mono-id">{row.id}</b> },
    { id: 'user', label: 'USER', value: row => row.user },
    { id: 'sql', label: 'STRUCTURE', value: row => row.sql, render: row => <code className="query-snippet">{row.sql}</code> },
    { id: 'risk', label: 'DEMO SCORE', value: row => row.risk, render: row => <RiskPill value={row.risk} /> },
    { id: 'decision', label: 'SCENARIO LABEL', value: row => row.decision, render: row => <DecisionPill decision={row.decision} /> },
  ]
  const definitions = [
    'Configured sensitivity normalization for the selected aggregate; not an attack-risk probability.',
    'Fixed policy classification of referenced attributes; distinct from mathematical sensitivity.',
    'Maximum Jaccard overlap with recent dataset-wide query history across authorized users.',
    'Half normalized predicate count plus half normalized repeats of the same structural fingerprint.',
    'Configured category for aggregate type; a heuristic policy input.',
  ]
  return <div className="module-view"><PageHeading eyebrow="PRIVACY CONTROLS · POLICY EXPLAINABILITY" title="Risk Analysis" description="Separate mathematical sensitivity and policy classifications from heuristic risk scoring." /><div className="accounting-callout risk-callout"><Icon name="info" size={17} /><div><b>Illustrative calculation only</b><span>Component values below are examples. The backend computes bounded signals from persisted dataset-wide history, but this page is not a live policy view. The score is a heuristic, not a formal DP guarantee.</span></div></div><section className="dashboard-grid risk-model-grid"><article className="panel risk-model-panel"><PanelHeader title="Weighted risk model" subtitle="Configured defaults in backend/app/privacy/policy.py" /><div className="risk-equation">R<sub>q</sub> = w<sub>s</sub>S<sub>q</sub> + w<sub>d</sub>D<sub>q</sub> + w<sub>h</sub>H<sub>q</sub> + w<sub>n</sub>N<sub>q</sub> + w<sub>t</sub>T<sub>q</sub></div><div className="component-bars">{inputs.map(item => <div className="component-bar-row" key={item.key}><div><span>{item.key}</span><b>{(item.value * item.weight).toFixed(3)} contribution</b></div><div className="component-bar-track"><i className={item.color} style={{ width: `${item.value * 100}%` }} /></div><small>score {item.value.toFixed(2)} · weight {item.weight.toFixed(2)}</small></div>)}</div><div className="score-summary"><span>Illustrative weighted score</span><b>{score.toFixed(3)}</b><RiskPill value={score} /></div></article><article className="panel risk-definitions"><PanelHeader title="What each signal means" subtitle="Keep the concepts distinct" />{inputs.map((item, index) => <div className="definition-row" key={item.key}><span className="definition-number">0{index + 1}</span><div><b>{item.key}</b><small>{definitions[index]}</small></div></div>)}</article></section><section className="panel explorer-panel"><div className="embedded-table-heading"><div><h2>Illustrative query risk list</h2><p>Records and scores are sample UI data, not detector output.</p></div><span className="source-chip demo">DEMO ONLY</span></div><DataTable rows={demoQueries} columns={columns} searchText={row => `${row.id} ${row.user} ${row.sql} ${row.decision}`} searchPlaceholder="Search the illustrative query set…" /></section></div>
}
export function AuditLogsPage({ mode, token, apiStatus, profile }: { mode: AppMode; token: string | null; apiStatus: ApiStatus; profile: UserProfile | null }) {
  const [page, setPage] = useState(1); const [search, setSearch] = useState(''); const [eventType, setEventType] = useState(''); const [status, setStatus] = useState(''); const [from, setFrom] = useState(''); const [to, setTo] = useState('')
  const [rows, setRows] = useState<AuditItem[]>([]); const [total, setTotal] = useState(0); const [loading, setLoading] = useState(false); const [error, setError] = useState(''); const [selected, setSelected] = useState<AuditItem | null>(null)
  const isAdmin = profile?.roles.includes('administrator') === true; const pageSize = 25
  useEffect(() => {
    if (!token || mode !== 'authenticated' || apiStatus !== 'online') return
    let active = true; setLoading(true); setError('')
    listAuditLogs(token, { page, page_size: pageSize, search, event_type: eventType || undefined, status: status || undefined, date_from: from ? new Date(from).toISOString() : undefined, date_to: to ? new Date(to).toISOString() : undefined })
      .then(result => { if (active) { setRows(result.items); setTotal(result.total) } })
      .catch(reason => { if (active) setError(reason instanceof Error ? reason.message : 'Could not load audit logs.') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [mode, token, apiStatus, page, search, eventType, status, from, to])
  const maxPage = Math.max(1, Math.ceil(total / pageSize))
  return <div className="module-view"><PageHeading eyebrow="SECURITY · PERSISTED AUDIT TRAIL" title="Audit Logs" description="Search safe event metadata for authentication, datasets, SQL analysis and protected releases." />
    {mode !== 'authenticated' && <div className="accounting-callout"><Icon name="lock" size={17} /><div><b>Administrator sign-in required</b><span>The audit view does not substitute sample events for persisted records.</span></div></div>}{mode === 'authenticated' && apiStatus !== 'online' && <div className="accounting-callout"><Icon name="info" size={17} /><div><b>Audit service unavailable</b><span>Reconnect to load persisted events.</span></div></div>}{error && <div className="inline-alert error" role="alert">{error}</div>}
    <section className="panel explorer-panel operational-panel">
      <div className="filter-card" aria-label="Audit log filters">
        <div className="filter-card-heading"><div><b>Filter audit events</b><small>Search and narrow permitted event records</small></div>{isAdmin && <span className="source-chip live admin-access">ADMIN ACCESS</span>}</div>
        <div className="filter-row filter-row-search"><label className="filter-field"><span>Search</span><input value={search} onChange={event => { setPage(1); setSearch(event.target.value) }} placeholder="Search by event, user, status or safe metadata" /></label></div>
        <div className="filter-row filter-row-two">
          <label className="filter-field"><span>Event Type</span><select value={eventType} onChange={event => { setPage(1); setEventType(event.target.value) }}><option value="">All event types</option><option value="login_succeeded">Login succeeded</option><option value="login_failed">Login failed</option><option value="dataset_created">Dataset created</option><option value="dataset_deleted">Dataset deleted</option><option value="query_analyzed">Query analyzed</option><option value="query_analysis_rejected">Query analysis rejected</option><option value="query_rejected">Query rejected</option><option value="protected_query_rejected">Protected query rejected</option><option value="protected_query_released">Protected query released</option><option value="protected_query_cached">Protected query cached</option><option value="privacy_budget_rejected">Privacy budget rejected</option><option value="protected_query_failed">Protected query failed</option></select></label>
          <label className="filter-field"><span>Status</span><select value={status} onChange={event => { setPage(1); setStatus(event.target.value) }}><option value="">All statuses</option><option value="success">Success</option><option value="rejected">Rejected</option><option value="error">Error</option></select></label>
        </div>
        <div className="filter-row filter-row-two">
          <label className="filter-field"><span>From Date</span><input type="datetime-local" value={from} onChange={event => { setPage(1); setFrom(event.target.value) }} /></label>
          <label className="filter-field"><span>To Date</span><input type="datetime-local" value={to} onChange={event => { setPage(1); setTo(event.target.value) }} /></label>
        </div>
      </div>
      {loading ? <div className="dataset-empty"><span className="spinner dataset-spinner" />Loading audit events…</div> : rows.length ? <div className="table-wrap data-table-wrap operational-table-wrap audit-table-wrap"><table><thead><tr><th>EVENT ID</th><th>TIMESTAMP</th><th>USER</th><th>EVENT TYPE</th><th>STATUS</th><th>SAFE METADATA</th></tr></thead><tbody>{rows.map(row => { const metadataText = Object.keys(row.metadata).length ? Object.entries(row.metadata).map(([key, value]) => `${key}: ${String(value)}`).join(' · ') : '—'; return <tr key={row.id} className="clickable-row" tabIndex={0} onClick={() => setSelected(row)} onKeyDown={event => { if (event.key === 'Enter') setSelected(row) }}><td><b className="mono-id">A-{row.id}</b></td><td><time dateTime={row.created_at}>{new Date(row.created_at).toLocaleString()}</time></td><td>{row.username || 'system'}</td><td><code>{row.event_type}</code></td><td><DecisionPill decision={row.status} /></td><td><span className="table-truncate" title={metadataText}>{metadataText}</span></td></tr> })}</tbody></table></div> : <div className="dataset-empty"><Icon name="file" size={20} /><b>{mode === 'authenticated' && apiStatus === 'online' ? 'No matching audit events' : 'Audit records unavailable'}</b><span>Successful login, query, dataset and budget events will appear here.</span></div>}
      <div className="table-pagination operational-pagination"><span>{total} events · Page {Math.min(page, maxPage)} of {maxPage}</span><div><button onClick={() => setPage(value => Math.max(1, value - 1))} disabled={page <= 1 || loading}>Previous</button><button onClick={() => setPage(value => Math.min(maxPage, value + 1))} disabled={page >= maxPage || loading}>Next</button></div></div>
    </section>
    {selected && <DetailDrawer title={`Audit event A-${selected.id}`} subtitle={`${selected.event_type} · ${new Date(selected.created_at).toLocaleString()}`} onClose={() => setSelected(null)}><Detail label="User" value={selected.username || 'system'} /><Detail label="Status" value={selected.status} /><div className="detail-field"><span>Safe metadata</span><pre className="audit-metadata">{JSON.stringify(selected.metadata, null, 2)}</pre></div><div className="drawer-note">Passwords, bearer tokens, credentials and aggregate values are not part of audit metadata.</div></DetailDrawer>}
  </div>
}

type UserDisplayRow = { username: string; name: string; role: string; state: string; id?: number }

export function PasswordResetForm({ username, token, onReset }: { username: string; token: string; onReset?: () => void }) {
  const [newPassword, setNewPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const matches = newPassword.length >= 12 && newPassword === confirmation

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(''); setMessage('')
    if (newPassword.length < 12) { setError('Use at least 12 characters.'); return }
    if (newPassword !== confirmation) { setError('The passwords do not match.'); return }
    setLoading(true)
    try {
      await resetManagedUserPassword(token, username, newPassword)
      setMessage(`Password reset for ${username}. The new password is not displayed or retained in this page.`)
      onReset?.()
    } catch (resetError) {
      setError(resetError instanceof Error ? resetError.message : 'Password reset failed. Try again.')
    } finally { setLoading(false); setNewPassword(''); setConfirmation('') }
  }

  return <form className="password-reset-form" onSubmit={submit} aria-label={`Reset password for ${username}`}>
    <div className="password-reset-heading"><b>Reset password</b><span>For <strong>{username}</strong>. This will not change the account role or status.</span></div>
    <label htmlFor="user-new-password">New password</label>
    <input id="user-new-password" name="new-password" type="password" autoComplete="new-password" minLength={12} maxLength={1024} required value={newPassword} onChange={event => { setNewPassword(event.target.value); setError(''); setMessage('') }} />
    <small>At least 12 characters, matching the existing seeded-account password requirement.</small>
    <label htmlFor="user-confirm-password">Confirm new password</label>
    <input id="user-confirm-password" name="confirm-new-password" type="password" autoComplete="new-password" minLength={12} maxLength={1024} required value={confirmation} onChange={event => { setConfirmation(event.target.value); setError(''); setMessage('') }} />
    {error && <p className="password-reset-message error" role="alert">{error}</p>}
    {message && <p className="password-reset-message success" role="status">{message}</p>}
    <button className="primary-button password-reset-submit" type="submit" disabled={!matches || loading}>{loading ? 'Resetting…' : 'Reset user password'}</button>
  </form>
}

type UserListLoadState = 'idle' | 'loading' | 'success' | 'error'

export function UserManagementResults({ state, error, users, columns, onSelect }: {
  state: UserListLoadState
  error: string
  users: UserDisplayRow[]
  columns: TableColumn<UserDisplayRow>[]
  onSelect: (row: UserDisplayRow) => void
}) {
  if (state === 'idle' || state === 'loading') return <div className="loading-state" role="status">Loading current user accounts…</div>
  if (state === 'error') return <div className="data-error" role="alert"><b>Could not load user accounts</b><span>{error || 'The user-management request failed. Check the backend connection and your users:manage authorization, then try again.'}</span></div>
  return <DataTable rows={users} columns={columns} searchText={row => `${row.username} ${row.name} ${row.role} ${row.state}`} searchPlaceholder="Search users…" onSelect={onSelect} />
}

export function UserRolesPage({ mode = 'preview', token = null, apiStatus = 'offline', profile = null }: { mode?: AppMode; token?: string | null; apiStatus?: ApiStatus; profile?: UserProfile | null } = {}) {
  const isAdmin = mode === 'authenticated' && profile?.roles.includes('administrator') === true
  const [selected, setSelected] = useState<UserDisplayRow | null>(null)
  const [users, setUsers] = useState<UserDisplayRow[]>(() => mode === 'preview' ? demoUsers.map(user => ({ ...user })) : [])
  const [loadState, setLoadState] = useState<UserListLoadState>('idle')
  const [error, setError] = useState('')
  useEffect(() => {
    if (mode === 'preview') {
      setUsers(demoUsers.map(user => ({ ...user })))
      setError('')
      setLoadState('success')
      return
    }
    setUsers([])
    setError('')
    if (!isAdmin || !token || apiStatus !== 'online') { setLoadState('idle'); return }
    let active = true
    setLoadState('loading')
    listManagedUsers(token).then(result => {
      if (active) setUsers(result.items.map((user: ManagedUser) => ({
        id: user.id, username: user.username, name: user.full_name,
        role: user.roles.length ? user.roles.join(', ') : 'No assigned role',
        state: user.is_active ? 'Active' : 'Inactive',
      })))
    }).catch(loadError => {
      if (active) {
        setError(loadError instanceof Error ? loadError.message : 'The user-management request failed. Check the backend connection and your users:manage authorization.')
        setLoadState('error')
      }
    }).then(() => { if (active) setLoadState(current => current === 'loading' ? 'success' : current) })
    return () => { active = false }
  }, [mode, token, apiStatus, isAdmin])

  const userColumns: TableColumn<UserDisplayRow>[] = [
    { id: 'name', label: 'USER', value: row => row.name, render: row => <span className="user-cell"><span className="table-avatar">{row.name[0]}</span><span><b>{row.name}</b><small className="cell-sub">{row.username}</small></span></span> },
    { id: 'role', label: mode === 'preview' ? 'SEEDED ROLE' : 'ROLE', value: row => row.role, render: row => <span className="type-chip">{row.role}</span> },
    { id: 'state', label: 'ACCOUNT', value: row => row.state, render: row => <span className="account-state"><i />{row.state}</span> },
  ]
  if (isAdmin) userColumns.push({
    id: 'action', label: 'ACTION', value: row => row.username,
    render: row => <button type="button" className="user-manage-action" aria-label={`Manage ${row.username}`} onClick={event => { event.stopPropagation(); setSelected(row) }}>Manage</button>,
  })
  const isPreview = mode === 'preview'
  return <div className="module-view"><PageHeading eyebrow={isAdmin ? 'SECURITY · ADMIN ACCESS' : isPreview ? 'SECURITY · DEMO PREVIEW' : 'SECURITY · USER MANAGEMENT'} title="User & Role Management" description={isAdmin ? 'Review existing accounts and reset passwords without changing role assignments or account status.' : 'Inspect account roles and permission assignments.'} />
    {isPreview && <div className="accounting-callout"><Icon name="lock" size={17} /><div><b>Read-only preview</b><span>Illustrative seeded accounts only. Sign in as an administrator to manage real accounts.</span></div></div>}
    {!isPreview && !isAdmin && <div className="accounting-callout"><Icon name="lock" size={17} /><div><b>Administrator access required</b><span>This page requires the existing users:manage permission. No account information is loaded for this role.</span></div></div>}
    {isAdmin && apiStatus !== 'online' && <div className="accounting-callout"><Icon name="lock" size={17} /><div><b>API unavailable</b><span>Connect to the backend to load current user records and manage passwords.</span></div></div>}
    <div className="admin-grid"><section className="panel explorer-panel"><div className="embedded-table-heading"><div><h2>{isPreview ? 'Illustrative demo users' : 'Existing user accounts'}</h2><p>{isPreview ? 'Preview data only; it is not connected to account records.' : 'Loaded from the authenticated user-management API.'}</p></div><span className={`source-chip ${isPreview ? 'demo' : 'live'}`}>{isPreview ? 'DEMO ACCOUNTS' : 'LIVE ACCOUNTS'}</span></div>
      {isAdmin && apiStatus !== 'online' ? <div className="empty-state">User records are unavailable until the backend reconnects.</div> : isAdmin ? <UserManagementResults state={loadState} error={error} users={users} columns={userColumns} onSelect={setSelected} /> : isPreview ? <DataTable rows={users} columns={userColumns} searchText={row => `${row.username} ${row.name} ${row.role} ${row.state}`} searchPlaceholder="Search users…" onSelect={setSelected} /> : <div className="empty-state">Sign in with an administrator account to view user records.</div>}
    </section><section className="panel role-panel"><PanelHeader title="Seeded roles & permissions" subtitle="Configured role policy; current account roles are shown in the user list" />{seededRoles.map(role => <div className="role-entry" key={role.role}><div><b>{role.role}</b><small>{role.permissions.length} permission keys</small></div><div className="permission-tags">{role.permissions.map(permission => <code key={permission}>{permission}</code>)}</div></div>)}</section></div>
    {selected && <DetailDrawer title={selected.name} subtitle={selected.username} onClose={() => setSelected(null)}><Detail label="Role assignment" value={selected.role} /><Detail label="Account status" value={selected.state} />{isPreview ? <div className="drawer-note">Preview accounts are illustrative; no password action is available in preview mode.</div> : isAdmin && token && selected.username !== profile?.username ? <PasswordResetForm key={selected.username} username={selected.username} token={token} /> : isAdmin ? <div className="drawer-note">Password resets are available for other users. Use the account recovery process for your own account.</div> : null}</DetailDrawer>}
  </div>
}

export function DetailDrawer({ title, subtitle, onClose, children }: { title: string; subtitle?: string; onClose: () => void; children: ReactNode }) {
  return <div className="drawer-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}><aside className="detail-drawer" role="dialog" aria-modal="true" aria-label={title}><div className="drawer-header"><div><h2>{title}</h2>{subtitle && <small>{subtitle}</small>}</div><button className="icon-action" onClick={onClose} aria-label="Close details"><Icon name="close" size={17} /></button></div><div className="drawer-content">{children}</div></aside></div>
}

export function Detail({ label, value, code = false }: { label: string; value: string; code?: boolean }) {
  return <div className="detail-field"><span>{label}</span>{code ? <code>{value}</code> : <b>{value}</b>}</div>
}

function Metric({ label, value, meta, icon }: { label: string; value: string; meta: string; icon: string }) {
  return <article className="panel metric-card"><span className="metric-icon"><Icon name={icon} size={16} /></span><span className="metric-label">{label}</span><b className="metric-value">{value}</b><small>{meta}</small></article>
}
