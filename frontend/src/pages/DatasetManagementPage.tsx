import { useEffect, useState, type FormEvent } from 'react'
import { deleteDataset, generateEmployeeDataset, listDatasets } from '../services/dataset.service'
import type { ApiStatus, AppMode, DatasetRecord, UserProfile } from '../types/app'
import { Icon } from '../components/Icon'

export function DatasetManagementPage({ mode, token, apiStatus, profile, onNavigate }: {
  mode: AppMode
  token: string | null
  apiStatus: ApiStatus
  profile: UserProfile | null
  onNavigate: (page: 'query') => void
}) {
  const [datasets, setDatasets] = useState<DatasetRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [name, setName] = useState('Synthetic Employees')
  const [size, setSize] = useState(5_000)
  const [seed, setSeed] = useState(2026)
  const canManage = profile?.roles?.includes('administrator') === true

  useEffect(() => {
    if (mode !== 'authenticated' || !token || apiStatus !== 'online') return
    let active = true
    setLoading(true)
    listDatasets(token).then(result => { if (active) setDatasets(result.items) })
      .catch(reason => { if (active) setError(reason instanceof Error ? reason.message : 'Could not load datasets.') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [mode, token, apiStatus])

  async function generate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!token || mode !== 'authenticated') return
    setGenerating(true); setError(''); setNotice('')
    try {
      const created = await generateEmployeeDataset(token, { name: name.trim(), size, seed, initial_epsilon: 10 })
      setDatasets(current => [...current, created])
      setNotice(`Created ${created.name} with ${created.record_count.toLocaleString()} synthetic rows. The records were generated from seed ${seed}.`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Dataset generation failed.')
    } finally { setGenerating(false) }
  }

  async function removeDataset(dataset: DatasetRecord) {
    if (!token || !window.confirm(`Delete “${dataset.name}” and its associated query history, budget and releases? This action cannot be undone.`)) return
    setError(''); setNotice('')
    try { await deleteDataset(token, dataset.id); setDatasets(current => current.filter(item => item.id !== dataset.id)); setNotice(`${dataset.name} was deleted.`) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Dataset deletion failed.') }
  }

  return <div className="module-view">
    <div className="page-heading"><div><div className="section-eyebrow">DATA · REGISTERED SOURCES</div><h1>Dataset Management</h1><p>Manage synthetic research datasets available to your assigned roles.</p></div><button className="primary-button" onClick={() => onNavigate('query')}><Icon name="terminal" size={15} /> Open Query Console</button></div>
    {mode === 'preview' && <div className="accounting-callout"><Icon name="info" size={17} /><div><b>Preview only</b><span>This screen does not create datasets or call protected API operations.</span></div></div>}
    {mode === 'authenticated' && apiStatus !== 'online' && <div className="accounting-callout"><Icon name="info" size={17} /><div><b>{apiStatus === 'degraded' ? 'Database unavailable' : apiStatus === 'checking' ? 'Checking connection' : 'Backend unavailable'}</b><span>Dataset operations require the connected API and database.</span></div></div>}
    {error && <div className="inline-alert error" role="alert">{error}</div>}
    {notice && <div className="dataset-success" role="status"><Icon name="check" size={16} />{notice}</div>}
    <section className="panel dataset-generator">
      <div className="panel-header"><div><h2>Generate Demo Dataset</h2><p>Creates deterministic, synthetic employee records in local application storage.</p></div><span className="source-chip demo">SYNTHETIC DATA</span></div>
      {canManage ? <form className="dataset-generator-form" onSubmit={generate}>
        <label>Dataset name<input value={name} onChange={event => setName(event.target.value)} minLength={3} maxLength={100} required /></label>
        <label>Record count<select value={size} onChange={event => setSize(Number(event.target.value))}><option value={5000}>5,000</option><option value={25000}>25,000</option><option value={100000}>100,000</option><option value={500000}>500,000</option></select></label>
        <label>Reproducibility seed<input type="number" min="0" max="4294967295" value={seed} onChange={event => setSeed(Number(event.target.value))} required /></label>
        <div className="dataset-generator-actions"><span>Shared dataset budget starts at 10 ε. Generate explicitly; no data is created at startup.</span><button className="primary-button" disabled={generating || mode !== 'authenticated' || apiStatus !== 'online'}>{generating ? <><span className="spinner" /> Generating…</> : <><Icon name="plus" size={15} /> Generate dataset</>}</button></div>
      </form> : <div className="dataset-readonly"><Icon name="lock" size={16} /><span>{mode === 'authenticated' ? 'Dataset generation is restricted to administrators.' : 'Sign in as an authorized administrator to generate a dataset.'}</span></div>}
    </section>
    <section className="panel dataset-list-panel"><div className="panel-header"><div><h2>Available datasets</h2><p>Only datasets granted to one of your roles are listed.</p></div><span className="source-chip live">{mode === 'authenticated' ? 'LIVE API' : 'PREVIEW'}</span></div>
      {loading ? <div className="dataset-empty"><span className="spinner dataset-spinner" />Loading registered datasets…</div> : datasets.length === 0 ? <div className="dataset-empty"><Icon name="database" size={20} /><b>{mode === 'preview' ? 'Sign in to load datasets' : apiStatus === 'online' ? 'No accessible datasets yet' : 'Dataset list unavailable'}</b><span>{mode === 'preview' ? 'Preview mode does not show fabricated dataset records.' : apiStatus === 'online' ? 'An administrator can generate or import an employee dataset above.' : 'Reconnect to the backend to load accessible datasets.'}</span></div> : <div className="data-table-wrap"><table><thead><tr><th>DATASET</th><th>SOURCE</th><th>TABLE</th><th>RECORDS</th><th>COLUMNS</th><th>OWNER</th><th>ACCESS ROLES</th><th>CREATED</th>{canManage && <th>ACTION</th>}</tr></thead><tbody>{datasets.map(dataset => <tr key={dataset.id}><td><b>{dataset.name}</b><small className="cell-sub">{dataset.description}</small></td><td><span className="source-chip demo">{dataset.source_type.toUpperCase()}</span></td><td><code>{dataset.table_name}</code></td><td>{dataset.record_count.toLocaleString()}</td><td>{dataset.columns?.length ?? 0}</td><td>{dataset.owner || '—'}</td><td>{dataset.access_roles?.join(', ') || '—'}</td><td>{new Date(dataset.created_at).toLocaleString()}</td>{canManage && <td><button className="secondary-button dataset-delete" onClick={() => removeDataset(dataset)}>Delete</button></td>}</tr>)}</tbody></table></div>}
    </section>
    <div className="accounting-callout dataset-limit"><Icon name="info" size={16} /><div><b>Current boundary</b><span>Synthetic Employees generation and role-scoped listing are implemented. CSV import, PostgreSQL connection management, schema browsing, other synthetic datasets, and deletion remain pending.</span></div></div>
  </div>
}
