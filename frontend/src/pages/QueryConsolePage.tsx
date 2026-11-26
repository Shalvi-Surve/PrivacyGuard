import { useEffect, useState } from 'react'
import { analyzeQuery, executeProtectedQuery } from '../services/query.service'
import { listDatasets } from '../services/dataset.service'
import type { ApiStatus, AppMode, DatasetRecord, ProtectedQueryResult, QueryAnalysis } from '../types/app'
import { Icon } from '../components/Icon'

const examples = [
  { label: 'Count employees', supported: true, sql: 'SELECT COUNT(*)\nFROM employees;' },
  { label: 'Count by department', supported: true, sql: "SELECT COUNT(*)\nFROM employees\nWHERE department = 'Engineering';" },
  { label: 'Sum bounded salary', supported: true, sql: "SELECT SUM(salary)\nFROM employees\nWHERE department = 'Finance';" },
  { label: 'Average (unsupported)', supported: false, sql: "SELECT AVG(performance_score)\nFROM employees;" },
]

type ConsoleTab = 'analysis' | 'pipeline' | 'privacy'

export function QueryConsolePage({ mode, apiStatus, token }: { mode: AppMode; apiStatus: ApiStatus; token: string | null }) {
  const [sql, setSql] = useState(examples[0].sql)
  const [datasetId, setDatasetId] = useState('')
  const [datasets, setDatasets] = useState<DatasetRecord[]>([])
  const [analysis, setAnalysis] = useState<QueryAnalysis | null>(null)
  const [release, setRelease] = useState<ProtectedQueryResult | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [tab, setTab] = useState<ConsoleTab>('analysis')

  useEffect(() => {
    if (mode !== 'authenticated' || !token || apiStatus !== 'online') return
    let active = true
    listDatasets(token).then(response => {
      if (!active) return
      setDatasets(response.items)
      setDatasetId(current => current || String(response.items[0]?.id ?? ''))
    }).catch(reason => { if (active) setError(reason instanceof Error ? reason.message : 'Could not load datasets.') })
    return () => { active = false }
  }, [mode, token, apiStatus])

  async function analyze() {
    if (mode !== 'authenticated' || !token) { setError('Sign in to call the SQL structure analyzer. Preview mode does not make API requests.'); return }
    setError(''); setAnalysis(null); setRelease(null); setLoading(true); setTab('analysis')
    try { setAnalysis(await analyzeQuery(sql, token, datasetId ? Number(datasetId) : undefined)) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Query analysis failed.') }
    finally { setLoading(false) }
  }

  async function execute() {
    if (mode !== 'authenticated' || !token) { setError('Sign in with a seeded account authorized for protected queries.'); return }
    if (!datasetId) { setError('Select an accessible dataset before executing a protected query.'); return }
    setError(''); setAnalysis(null); setRelease(null); setLoading(true); setTab('analysis')
    try { setRelease(await executeProtectedQuery(sql, Number(datasetId), token)) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Protected query failed.') }
    finally { setLoading(false) }
  }

  return <div className="module-view query-workspace">
    <div className="page-heading"><div><div className="section-eyebrow">WORKSPACE · PROTECTED AGGREGATES</div><h1>Query Console</h1><p>Analyze a restricted SQL shape or request an authorized, budgeted protected aggregate.</p></div><span className="api-capability-pill"><i /> {apiStatus === 'online' ? 'API available' : apiStatus === 'degraded' ? 'Database unavailable' : apiStatus === 'checking' ? 'Checking API' : 'API offline'}</span></div>
    <div className="console-grid">
      <section className="panel editor-panel">
        <div className="editor-toolbar"><div><span className="editor-live-dot" /> SQL workspace <small>Restricted COUNT/SUM subset</small></div></div>
        <div className="template-bar"><label htmlFor="query-template">Examples</label><select id="query-template" value={examples.find(example => example.sql === sql)?.label || ''} onChange={event => { const selected = examples.find(example => example.label === event.target.value); if (selected) { setSql(selected.sql); setAnalysis(null); setRelease(null); setError('') } }}><option value="" disabled>Select an example</option>{examples.map(example => <option value={example.label} key={example.label} disabled={!example.supported}>{example.supported ? 'Supported · ' : 'Unsupported · '}{example.label}</option>)}</select></div>
        <div className="editor-wrap"><div className="line-numbers">{sql.split('\n').map((_, index) => <span key={index}>{index + 1}</span>)}</div><textarea aria-label="SQL query editor" spellCheck={false} autoCapitalize="off" autoCorrect="off" value={sql} onChange={event => { setSql(event.target.value); setAnalysis(null); setRelease(null) }} /></div>
        <div className="dataset-selector-row"><label htmlFor="query-dataset">Dataset</label><select id="query-dataset" value={datasetId} onChange={event => { setDatasetId(event.target.value); setRelease(null) }} disabled={mode !== 'authenticated' || apiStatus !== 'online' || datasets.length === 0}><option value="">{datasets.length ? 'Select accessible dataset' : 'No accessible datasets'}</option>{datasets.map(item => <option key={item.id} value={item.id}>{item.name} · {item.record_count.toLocaleString()} rows</option>)}</select></div>
        <div className="editor-footer"><span>Analysis validates SQL only. Protected execution runs the approved aggregate internally and returns a DP release.</span><div className="query-actions"><button className="secondary-button" onClick={analyze} disabled={loading || mode !== 'authenticated' || apiStatus !== 'online'}>{loading ? <><span className="spinner" /> Working…</> : 'Analyze SQL'}</button><button className="primary-button" onClick={execute} disabled={loading || mode !== 'authenticated' || apiStatus !== 'online' || !datasetId}>{loading ? <><span className="spinner" /> Running…</> : <><Icon name="pulse" size={15} /> Execute protected query</>}</button></div></div>
        {mode === 'preview' && <div className="inline-alert query-preview-alert" role="note"><Icon name="info" size={14} /> Preview is read-only. Sign in to use the analyzer or protected execution endpoint.</div>}
        {error && <div className="inline-alert error query-error" role="alert">{error}</div>}
        {mode === 'authenticated' && apiStatus !== 'online' && <div className="inline-alert query-preview-alert" role="status"><span className="alert-dot" /> {apiStatus === 'degraded' ? 'The API is reachable, but database access is unavailable.' : apiStatus === 'checking' ? 'Checking the backend. The editor remains available.' : 'Backend is offline. The editor remains available and no request is pending.'}</div>}
      </section>
      <aside className="panel schema-panel"><div className="panel-header"><div><h2>Execution allowlist</h2><p>Static policy · not database introspection</p></div><Icon name="database" size={17} /></div><div className="schema-table"><Icon name="database" size={15} /><b>employees</b><span>Approved table</span></div><div className="schema-columns">{['employee_id', 'department', 'designation', 'age', 'gender', 'salary', 'performance_score', 'location'].map(column => <div key={column}><span>{column}</span><small>{column === 'salary' || column === 'performance_score' ? 'bounded SUM' : 'predicate or COUNT'}</small></div>)}</div><div className="schema-note"><Icon name="info" size={14} /><span>Only approved SQL is compiled to a dataset-scoped aggregate. No raw aggregate is returned. COUNT and bounded SUM are supported; other aggregates remain unsupported.</span></div></aside>
    </div>
    <section className="panel analysis-panel"><div className="analysis-tabs" role="tablist" aria-label="Query response views"><button role="tab" aria-selected={tab === 'analysis'} className={tab === 'analysis' ? 'selected' : ''} onClick={() => setTab('analysis')}>Response</button><button role="tab" aria-selected={tab === 'pipeline'} className={tab === 'pipeline' ? 'selected' : ''} onClick={() => setTab('pipeline')}>Processing pipeline</button><button role="tab" aria-selected={tab === 'privacy'} className={tab === 'privacy' ? 'selected' : ''} onClick={() => setTab('privacy')}>Privacy context</button></div>
      {tab === 'analysis' && <div className="analysis-content">{release ? <div className="protected-result-panel"><div className="analysis-result-heading"><span className="validation-mark"><Icon name="check" size={16} /></span><div><b>Protected aggregate {release.cache_hit ? 'reused' : 'released'}</b><small>{release.dataset_name} · {release.decision} · {release.processing_ms.toFixed(1)} ms</small></div><span className="result-tag">{release.cache_hit ? 'CACHED' : 'PROTECTED RELEASE'}</span></div><div className="protected-result-value"><span>PROTECTED {release.query_type.toUpperCase()} · ILLUSTRATIVE OUTPUT</span><b>{Number(release.protected_result.toFixed(2)).toLocaleString()}</b></div><div className="protected-result-metrics"><Metric label="Nominal epsilon charged" value={`${release.epsilon_charged.toFixed(3)} ε`} /><Metric label="Release calibration ε" value={`${release.epsilon.toFixed(3)} ε${release.cache_hit ? ' · stored draw' : ''}`} /><Metric label="Remaining budget" value={`${release.remaining_budget.toFixed(3)} ε`} /><Metric label="Risk heuristic" value={`${(release.risk_score * 100).toFixed(0)}% · ${release.risk_level}`} /></div><p className="protected-explanation">{release.explanation} The recorded epsilon is nominal expenditure; this finite-precision sampler has no established formal DP guarantee. This output is not a research experiment finding.</p></div> : analysis ? <><div className="analysis-result-heading"><span className="validation-mark"><Icon name="check" size={16} /></span><div><b>SQL structure accepted</b><small>Analysis only · no database execution, noise, or budget charge</small></div><span className="result-tag">ANALYZED</span></div><div className="analysis-facts"><Fact label="Aggregate" value={analysis.query_type.toUpperCase()} /><Fact label="Table" value={analysis.table} /><Fact label="Aggregate column" value={analysis.aggregate_column || 'All rows'} /><Fact label="Referenced columns" value={analysis.referenced_columns.join(', ') || 'None'} /></div><div className="canonical-block"><div><span>CANONICAL SQL</span></div><code>{analysis.canonical_sql}</code></div><div className="fingerprint-block"><span>STRUCTURAL FINGERPRINT</span><code>{analysis.fingerprint}</code></div></> : <div className="analysis-empty"><span className="empty-icon"><Icon name="terminal" size={17} /></span><b>Response will appear here</b><p>Run analysis to inspect the SQL structure, or execute an authorized protected query against an accessible dataset.</p></div>}</div>}
      {tab === 'pipeline' && <div className="pipeline-grid">{[['SQL validation', 'Implemented', 'Restricted SQL parser validates COUNT/SUM query structure.'], ['Dataset authorization', 'Implemented', 'Role grants scope the selected dataset.'], ['Budget reservation', 'Implemented', 'A shared dataset epsilon budget is atomically reserved.'], ['Aggregate + Laplace', 'Implemented', 'Approved SQLite employee aggregates are bounded where required and noised.'], ['History + audit', 'Implemented', 'Release metadata, query history, budget ledger and audit events are persisted.'], ['PostgreSQL / CSV', 'Pending', 'Additional data sources and import workflows are not connected yet.']].map(([label, state, detail]) => <div className="pipeline-step complete" key={label}><span className="pipeline-number"><Icon name="check" size={13} /></span><div><b>{label}</b><small>{detail}</small></div><span className="pipeline-status">{state.toUpperCase()}</span></div>)}</div>}
      {tab === 'privacy' && <div className="privacy-context-grid"><PrivacyFact title="Mechanism" value={release?.mechanism ?? 'Laplace'} note={`Adjacency: ${release?.adjacency_model ?? 'add_remove_one_record'}. COUNT sensitivity 1; bounded SUM sensitivity uses full contribution bounds.`} /><PrivacyFact title="Release configuration" value={release ? `Policy ${release.policy_version} · dataset v${release.dataset_version}` : 'Current policy'} note={release?.clipping_bounds ? `SUM clipping: ${release.clipping_bounds.lower} to ${release.clipping_bounds.upper}.` : 'Repeated identical dataset/query configuration reuses the stored output and original epsilon without recharging.'} /><PrivacyFact title="Risk score" value="Heuristic" note="Uses query structure/history proxies; not a calibrated attack-risk estimate." /><PrivacyFact title="Research evaluation" value="Not claimed" note="This protected query path is not an experimental DP mitigation result." /></div>}
    </section>
  </div>
}

function Fact({ label, value }: { label: string; value: string }) { return <div className="analysis-fact"><span>{label}</span><b>{value}</b></div> }
function Metric({ label, value }: { label: string; value: string }) { return <div className="result-metric"><span>{label}</span><b>{value}</b></div> }
function PrivacyFact({ title, value, note }: { title: string; value: string; note: string }) { return <div className="privacy-fact"><span>{title}</span><b>{value}</b><small>{note}</small></div> }
