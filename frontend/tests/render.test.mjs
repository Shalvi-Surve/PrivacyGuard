import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

let vite
let App
let Dashboard
let OverviewPage
let LiveOverview
let QueryConsolePage
let DatasetManagementPage
let api
let authService
let queryService
let datasetService
let navigationModule
let operationalPages
let researchPages
let comparativePage
let comparativeDemo
let LoginPage
let operationsService
let researchService
let usersService
let metricState

before(async () => {
  vite = await createServer({ server: { middlewareMode: true }, appType: 'custom' })
  ;({ default: App, Dashboard } = await vite.ssrLoadModule('/src/App.tsx'))
  ;({ OverviewPage } = await vite.ssrLoadModule('/src/pages/OverviewPage.tsx'))
  ;({ LiveOverview } = await vite.ssrLoadModule('/src/pages/OverviewPage.tsx'))
  ;({ QueryConsolePage } = await vite.ssrLoadModule('/src/pages/QueryConsolePage.tsx'))
  ;({ DatasetManagementPage } = await vite.ssrLoadModule('/src/pages/DatasetManagementPage.tsx'))
  ;({ LoginPage } = await vite.ssrLoadModule('/src/pages/LoginPage.tsx'))
  api = await vite.ssrLoadModule('/src/services/api.ts')
  authService = await vite.ssrLoadModule('/src/services/auth.service.ts')
  queryService = await vite.ssrLoadModule('/src/services/query.service.ts')
  datasetService = await vite.ssrLoadModule('/src/services/dataset.service.ts')
  navigationModule = await vite.ssrLoadModule('/src/app/navigation.ts')
  operationalPages = await vite.ssrLoadModule('/src/pages/OperationalPages.tsx')
  researchPages = await vite.ssrLoadModule('/src/pages/ResearchPages.tsx')
  comparativePage = await vite.ssrLoadModule('/src/pages/ComparativeResultsPage.tsx')
  comparativeDemo = await vite.ssrLoadModule('/src/pages/comparativeDemo.ts')
  operationsService = await vite.ssrLoadModule('/src/services/operations.service.ts')
  researchService = await vite.ssrLoadModule('/src/services/research.service.ts')
  usersService = await vite.ssrLoadModule('/src/services/users.service.ts')
  metricState = await vite.ssrLoadModule('/src/utils/metricState.ts')
})

after(async () => {
  await vite?.close()
})

test('root component renders sign-in immediately without depending on API availability', () => {
  const markup = renderToStaticMarkup(React.createElement(App))
  assert.match(markup, /Sign in to your workspace/)
  assert.match(markup, /Use a seeded research account/)
  assert.match(markup, /class="brand-name"/)
  assert.match(markup, /Explore dashboard preview/)
  assert.match(markup, /PrivacyGuard/)
})

test('dashboard shell and offline state render with labelled demo values', () => {
  const markup = renderToStaticMarkup(React.createElement(Dashboard, {
    mode: 'preview', profile: null, apiStatus: 'offline', activePage: 'overview',
    onNavigate() {}, onLogout() {}, children: React.createElement(OverviewPage, { onNavigate() {} }),
  }))
  assert.match(markup, /Query Console/)
  assert.match(markup, /DEMO MODE/)
  assert.match(markup, /Illustrative data only/)
  assert.match(markup, /Illustrative requests/)
  assert.match(markup, /API offline/)
  assert.match(markup, /class="brand-name"/)
  assert.match(markup, /PRIVACY CONTROL PLANE/)
})

test('authenticated overview banner distinguishes persisted metrics from synthetic dataset contents', () => {
  const markup = renderToStaticMarkup(React.createElement(Dashboard, {
    mode: 'authenticated', profile: { id: 1, username: 'admin', full_name: 'Demo Administrator', roles: ['administrator'] },
    apiStatus: 'online', activePage: 'overview', onNavigate() {}, onLogout() {},
    children: React.createElement('div', null, 'Overview content'),
  }))
  assert.match(markup, /LIVE PERSISTED DATA/)
  assert.match(markup, /Dashboard metrics and activity come from persisted backend records/)
  assert.match(markup, /dataset contents may be synthetic/)
  assert.doesNotMatch(markup, /Live endpoint not implemented/)
})

test('comparative results gets its persisted classification without changing demo preview', () => {
  const live = renderToStaticMarkup(React.createElement(Dashboard, {
    mode: 'authenticated', profile: { id: 1, username: 'admin', full_name: 'Demo Administrator', roles: ['administrator'] },
    apiStatus: 'online', activePage: 'comparative-results', onNavigate() {}, onLogout() {}, children: React.createElement('div', null, 'Comparative content'),
  }))
  const preview = renderToStaticMarkup(React.createElement(Dashboard, {
    mode: 'preview', profile: null, apiStatus: 'offline', activePage: 'comparative-results', onNavigate() {}, onLogout() {}, children: React.createElement('div', null, 'Preview content'),
  }))
  assert.match(live, /PERSISTED RESEARCH RESULTS/)
  assert.match(live, /published literature is shown separately/)
  assert.match(preview, /DEMO MODE/)
  assert.doesNotMatch(live, /ILLUSTRATIVE \/ PLANNED/)
})

test('navigation renders the selected page state', () => {
  const markup = renderToStaticMarkup(React.createElement(Dashboard, {
    mode: 'preview', profile: null, apiStatus: 'offline', activePage: 'query',
    onNavigate() {}, onLogout() {}, children: React.createElement(QueryConsolePage, { mode: 'preview', apiStatus: 'offline', token: null }),
  }))
  assert.match(markup, /<strong>Query Console<\/strong>/)
  assert.match(markup, /aria-current="page">.*Query Console/s)
  assert.match(markup, /Preview is read-only/)
})

test('enterprise navigation groups only existing functional destinations', () => {
  const bySection = Object.groupBy(navigationModule.navigation, item => item.section)
  assert.deepEqual(Object.keys(bySection), [
    'Overview', 'Data & Connectivity', 'Query Workspace', 'Privacy Management',
    'Security & Governance', 'Research & Evaluation', 'Operations', 'Administration',
  ])
  assert.deepEqual(bySection['Query Workspace'].map(item => item.id), ['query', 'history'])
  assert.deepEqual(bySection['Research & Evaluation'].map(item => item.id), ['experiments', 'comparative-results'])
  assert.equal(navigationModule.navigation.length, 13)
  assert.equal(navigationModule.resolvePage('#/comparative-results'), 'comparative-results')
})

test('API uses same-origin requests by default for the configured Vite proxy', () => {
  assert.equal(api.API_BASE, '')
  assert.deepEqual(navigationModule.navigation.map(item => item.id), [
    'overview', 'datasets', 'query', 'history', 'budgets', 'risk', 'attacks', 'audit', 'users', 'experiments', 'comparative-results', 'architecture', 'settings',
  ])
  assert.equal(navigationModule.resolvePage('#/settings'), 'settings')
  assert.equal(navigationModule.resolvePage('#/not-a-page'), 'overview')
})

test('login sends the exact backend payload and returns the token response', async () => {
  const originalFetch = globalThis.fetch
  let request
  globalThis.fetch = async (url, init) => {
    request = { url, init }
    return new Response(JSON.stringify({ access_token: 'test-token', token_type: 'bearer' }), { status: 200 })
  }
  try {
    const result = await authService.signIn('researcher_demo', 'test-password')
    assert.equal(request.url, '/api/auth/login')
    assert.equal(request.init.method, 'POST')
    assert.equal(request.init.headers.get('Content-Type'), 'application/json')
    assert.deepEqual(JSON.parse(request.init.body), { username: 'researcher_demo', password: 'test-password' })
    assert.equal(result.token_type, 'bearer')
  } finally { globalThis.fetch = originalFetch }
})

test('401 credential errors stay distinct from backend network failures', async () => {
  const originalFetch = globalThis.fetch
  try {
    globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Invalid username or password' }), { status: 401 })
    await assert.rejects(authService.signIn('researcher_demo', 'wrong'), error => error.status === 401 && error.message === 'Invalid username or password')
    globalThis.fetch = async () => { throw new TypeError('connection refused') }
    await assert.rejects(authService.signIn('researcher_demo', 'secret'), error => error.status === undefined && /Could not reach/.test(error.message))
  } finally { globalThis.fetch = originalFetch }
})

test('validation errors do not echo request values such as passwords', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: [{ loc: ['body', 'password'], msg: 'invalid', input: 'secret-password-value' }] }), { status: 422 })
  try {
    await assert.rejects(authService.signIn('researcher_demo', 'secret-password-value'), error => error.status === 422 && !error.message.includes('secret-password-value'))
  } finally { globalThis.fetch = originalFetch }
})

test('profile and query analysis send bearer auth and preserve API responses', async () => {
  const originalFetch = globalThis.fetch
  const calls = []
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init })
    return new Response(JSON.stringify(url.endsWith('/me')
      ? { id: 4, username: 'researcher_demo', full_name: 'Researcher', roles: ['researcher'] }
      : { canonical_sql: 'SELECT COUNT(*) FROM employees', fingerprint: 'abc', query_type: 'count', table: 'employees', aggregate_column: null, referenced_columns: [] }), { status: 200 })
  }
  try {
    const profile = await authService.getCurrentUser('valid-token')
    const result = await queryService.analyzeQuery('SELECT COUNT(*) FROM employees', 'valid-token')
    assert.equal(profile.username, 'researcher_demo')
    assert.equal(result.query_type, 'count')
    assert.equal(calls[0].url, '/api/auth/me')
    assert.equal(calls[0].init.headers.get('Authorization'), 'Bearer valid-token')
    assert.equal(calls[1].url, '/api/queries/analyze')
    assert.deepEqual(JSON.parse(calls[1].init.body), { sql: 'SELECT COUNT(*) FROM employees' })
  } finally { globalThis.fetch = originalFetch }
})

test('dataset listing and protected execution send the selected dataset and SQL', async () => {
  const originalFetch = globalThis.fetch
  const calls = []
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init })
    return new Response(JSON.stringify(url === '/api/datasets'
      ? { items: [] }
      : { query_id: 12, dataset_id: 4, dataset_name: 'Synthetic', query_type: 'count', protected_result: 20, epsilon: 0.5, sensitivity: 1, noise_scale: 2, risk_score: 0.2, risk_level: 'low', risk_components: {}, privacy_spent: 0.5, remaining_budget: 9.5, budget_state: 'NORMAL', query_fingerprint: 'abc', cache_hit: false, processing_ms: 2, decision: 'RELEASED', explanation: 'Protected output.' }), { status: 200 })
  }
  try {
    assert.deepEqual(await datasetService.listDatasets('valid-token'), { items: [] })
    const result = await queryService.executeProtectedQuery('SELECT COUNT(*) FROM employees', 4, 'valid-token')
    assert.equal(result.protected_result, 20)
    assert.equal(calls[0].url, '/api/datasets')
    assert.equal(calls[1].url, '/api/queries/execute')
    assert.deepEqual(JSON.parse(calls[1].init.body), { sql: 'SELECT COUNT(*) FROM employees', dataset_id: 4 })
    assert.equal(calls[1].init.headers.get('Authorization'), 'Bearer valid-token')
  } finally { globalThis.fetch = originalFetch }
})

test('health reports database degradation separately and sanitizes server errors', async () => {
  const originalFetch = globalThis.fetch
  try {
    globalThis.fetch = async () => new Response(JSON.stringify({ status: 'ok', database: { status: 'unavailable' }, readiness: 'degraded' }), { status: 200 })
    assert.equal(await api.checkApiHealth(), 'degraded')
    globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'secret database connection string' }), { status: 500 })
    await assert.rejects(api.apiRequest('/health'), error => error.status === 500 && !error.message.includes('connection string'))
  } finally { globalThis.fetch = originalFetch }
})

test('expired protected tokens trigger the application session-expired event', async () => {
  const originalFetch = globalThis.fetch
  const originalWindow = globalThis.window
  let dispatchedEvent
  globalThis.window = { dispatchEvent(event) { dispatchedEvent = event.type } }
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Invalid or expired access token' }), { status: 401 })
  try {
    await assert.rejects(api.apiRequest('/api/auth/me', {}, 'expired-token'), error => error.status === 401)
    assert.equal(dispatchedEvent, 'privacyguard:unauthorized')
  } finally {
    globalThis.fetch = originalFetch
    if (originalWindow === undefined) delete globalThis.window
    else globalThis.window = originalWindow
  }
})

test('every navigation destination renders a page heading', () => {
  const destinations = [
    ['overview', OverviewPage, { onNavigate() {} }],
    ['datasets', DatasetManagementPage, { mode: 'preview', token: null, apiStatus: 'offline', profile: null, onNavigate() {} }],
    ['query', QueryConsolePage, { mode: 'preview', apiStatus: 'offline', token: null }],
    ['history', operationalPages.QueryHistoryPage, {}],
    ['budgets', operationalPages.PrivacyBudgetsPage, {}],
    ['risk', operationalPages.RiskAnalysisPage, {}],
    ['attacks', researchPages.AttackSimulatorPage, {}],
    ['audit', operationalPages.AuditLogsPage, {}],
    ['users', operationalPages.UserRolesPage, {}],
    ['experiments', researchPages.ExperimentsPage, {}],
    ['architecture', researchPages.ArchitecturePage, {}],
    ['settings', researchPages.SettingsPage, { apiStatus: 'offline' }],
  ]
  for (const [id, Component, props] of destinations) {
    const markup = renderToStaticMarkup(React.createElement(Component, props))
    assert.match(markup, /<h1>[^<]+<\/h1>/, `${id} should render a heading`)
  }
})

test('user-management API failures render an error instead of an empty record table', () => {
  const markup = renderToStaticMarkup(React.createElement(operationalPages.UserManagementResults, {
    state: 'error', error: 'Permission denied (403).', users: [], columns: [], onSelect() {},
  }))
  assert.match(markup, /role="alert"/)
  assert.match(markup, /Could not load user accounts/)
  assert.match(markup, /Permission denied \(403\)\./)
  assert.doesNotMatch(markup, /0 records/)
  assert.doesNotMatch(markup, /No records found/)
})

test('a successful empty user response renders the genuine empty-table state', () => {
  const markup = renderToStaticMarkup(React.createElement(operationalPages.UserManagementResults, {
    state: 'success', error: '', users: [], columns: [], onSelect() {},
  }))
  assert.match(markup, /0 records/)
  assert.match(markup, /No records found/)
})

test('a successful populated user response renders records and keeps search available', () => {
  const user = { id: 7, username: 'researcher_demo', name: 'Demo Researcher', role: 'researcher', state: 'Active' }
  const columns = [
    { id: 'username', label: 'USER', value: row => row.username },
    { id: 'role', label: 'ROLE', value: row => row.role },
  ]
  const markup = renderToStaticMarkup(React.createElement(operationalPages.UserManagementResults, {
    state: 'success', error: '', users: [user], columns, onSelect() {},
  }))
  assert.match(markup, /researcher_demo/)
  assert.match(markup, /1 record/)
  assert.match(markup, /Search users/)
})

test('Vite proxy default agrees with documented backend port and keeps environment overrides', () => {
  const root = fileURLToPath(new URL('../..', import.meta.url))
  const viteConfig = readFileSync(`${root}/frontend/vite.config.ts`, 'utf8')
  const envExample = readFileSync(`${root}/.env.example`, 'utf8')
  const readme = readFileSync(`${root}/README.md`, 'utf8')
  const campaignRunner = readFileSync(`${root}/backend/scripts/run_validation_campaign.py`, 'utf8')
  const campaignReadme = readFileSync(`${root}/backend/scripts/README_validation_campaign.md`, 'utf8')
  assert.match(viteConfig, /env\.VITE_API_PROXY_TARGET\s*\|\|\s*env\.VITE_API_BASE_URL\s*\|\|\s*'http:\/\/127\.0\.0\.1:8000'/)
  assert.match(envExample, /VITE_API_BASE_URL=\s*$/m)
  assert.match(envExample, /127\.0\.0\.1:8000/)
  assert.match(readme, /--port 8000/)
  assert.match(campaignRunner, /DEFAULT_API_BASE_URL\s*=\s*"http:\/\/127\.0\.0\.1:8000"/)
  assert.match(campaignReadme, /defaults to `http:\/\/127\.0\.0\.1:8000`/)
})

test('history and audit pages render grouped labeled filter controls', () => {
  const history = renderToStaticMarkup(React.createElement(operationalPages.QueryHistoryPage, {
    mode: 'authenticated', token: null, apiStatus: 'offline', profile: { roles: ['administrator'] },
  }))
  assert.match(history, /Search query ID, user, dataset or fingerprint/)
  assert.match(history, /aria-label="Query history filters"/)
  assert.match(history, /User ID/)
  assert.match(history, /Query Type/)
  assert.match(history, /From Date/)
  assert.match(history, /To Date/)
  assert.match(history, /filter-row-three/)

  const audit = renderToStaticMarkup(React.createElement(operationalPages.AuditLogsPage, {
    mode: 'authenticated', token: null, apiStatus: 'offline', profile: { roles: ['administrator'] },
  }))
  assert.match(audit, /Search by event, user, status or safe metadata/)
  assert.match(audit, /aria-label="Audit log filters"/)
  assert.match(audit, /Event Type/)
  assert.match(audit, /All statuses/)
  assert.match(audit, /ADMIN ACCESS/)
})

test('offline login status provides an explicit retry action', () => {
  const markup = renderToStaticMarkup(React.createElement(LoginPage, {
    apiStatus: 'offline', onRetry() {}, async onLogin() {}, onPreview() {},
  }))
  assert.match(markup, /Backend unavailable/)
  assert.match(markup, />Retry<\/button>/)
  assert.match(markup, /Explore dashboard preview/)
})

const overviewFixture = {
  window_days: 7,
  metrics: { total_requests: 3, protected_releases: 1, approved_requests: 2, rejected_requests: 1, other_requests: 0, high_risk_requests: 0, risk_scored_requests: 2, risk_unscored_or_rejected_requests: 1, high_risk_threshold: 0.67, high_risk_percentage_of_scored: 0, privacy_spent: 0.5, remaining_budget: 9.5, accessible_datasets: 1 },
  daily_activity: [{ date: '2026-11-20', approved: 2, rejected: 1, other: 0, total: 3 }],
  decision_distribution: { released: 1, cached: 1, rejected: 1 },
  recent_activity: [{ id: 'P-1', query_id: 1, request_kind: 'protected', user: 'researcher', dataset_id: 4, dataset_name: 'synthetic-employees', query_type: 'count', epsilon: 0.5, risk_score: 0.2, decision: 'released', created_at: '2026-11-20T12:30:00Z' }],
  budget_health: { available: true, scope: 'shared_dataset', initial_budget: 10, spent_budget: 0.5, remaining_budget: 9.5, utilization: 0.05, datasets: [{ dataset_id: 4, dataset_name: 'synthetic-employees', available: true, scope: 'dataset', initial_budget: 10, spent_budget: 0.5, remaining_budget: 9.5, utilization: 0.05 }] },
  recent_audit_activity: [{ id: 1, event_type: 'protected_query_released', actor: 'researcher', timestamp: '2026-11-20T12:30:00Z', status: 'success', description: 'A protected query release was created.' }],
  operational_signals: { api_health: 'available', database: 'available', sql_analysis: 'available', protected_releases: 'available', experiments: 'not_implemented' },
}

test('live overview renders persisted KPIs, chart, recent activity and budget', () => {
  const markup = renderToStaticMarkup(React.createElement(LiveOverview, { summary: overviewFixture, loading: false, error: '', apiStatus: 'online', onNavigate() {} }))
  assert.match(markup, /Persisted overview metrics/)
  assert.match(markup, /Unique protected releases/)
  assert.match(markup, /2 scored · 0\.0% above 0\.67/)
  assert.match(markup, /not a formal Differential Privacy guarantee/)
  assert.match(markup, /1 stored|P-1/)
  assert.match(markup, /aria-label="Persisted approved, rejected and other request counts by date"/)
  assert.match(markup, /synthetic-employees/)
  assert.match(markup, /0\.500 ε/)
  assert.match(markup, /Recent system events/)
  assert.match(markup, /not implemented/)
  assert.doesNotMatch(markup, /38%|6\.2 ε|3\.8 ε/)
})

test('live overview renders clear empty, API error and retry states', () => {
  const empty = structuredClone(overviewFixture)
  empty.metrics.total_requests = 0
  empty.metrics.protected_releases = 0
  empty.daily_activity = [{ date: '2026-11-20', approved: 0, rejected: 0, other: 0, total: 0 }]
  empty.decision_distribution = {}
  empty.recent_activity = []
  empty.budget_health.available = false
  empty.budget_health.initial_budget = null
  empty.budget_health.spent_budget = null
  empty.budget_health.remaining_budget = null
  empty.budget_health.utilization = null
  const markup = renderToStaticMarkup(React.createElement(LiveOverview, { summary: empty, loading: false, error: '', apiStatus: 'online', onNavigate() {} }))
  assert.match(markup, /No persisted query activity in this period/)
  assert.match(markup, /No query activity yet/)
  assert.match(markup, /Budget totals unavailable/)
  const failed = renderToStaticMarkup(React.createElement(LiveOverview, { summary: null, loading: false, error: 'The API returned a server error \(500\). Please retry shortly.', apiStatus: 'online', onRetry() {}, onNavigate() {} }))
  assert.match(failed, /Live overview could not be loaded/)
  assert.match(failed, />Retry<\/button>/)
})

test('dashboard service calls the registered authenticated summary route and reports failures', async () => {
  const originalFetch = globalThis.fetch
  let call
  globalThis.fetch = async (url, init) => {
    call = { url, init }
    return new Response(JSON.stringify(overviewFixture), { status: 200 })
  }
  try {
    const data = await operationsService.getDashboardSummary('dashboard-token')
    assert.equal(data.metrics.protected_releases, 1)
    assert.equal(call.url, '/api/dashboard/summary?days=7')
    assert.equal(call.init.headers.get('Authorization'), 'Bearer dashboard-token')
    globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'not found' }), { status: 404 })
    await assert.rejects(operationsService.getDashboardSummary('dashboard-token'), error => error.status === 404 && /404 for \/api\/dashboard\/summary/.test(error.message))
  } finally { globalThis.fetch = originalFetch }
})

test('API keeps authentication, permission, missing-route and server errors distinct', async () => {
  const originalFetch = globalThis.fetch
  try {
    globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Permission denied' }), { status: 403 })
    await assert.rejects(api.apiRequest('/api/dashboard/summary', {}, 'current-token'), error => error.status === 403 && /signed in/.test(error.message) && /role permissions/.test(error.message))
    globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Invalid or expired access token' }), { status: 401 })
    await assert.rejects(api.apiRequest('/api/dashboard/summary', {}, 'expired-token'), error => error.status === 401 && /Invalid or expired/.test(error.message))
    globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'not found' }), { status: 404 })
    await assert.rejects(api.apiRequest('/api/dashboard/summary', {}, 'current-token'), error => error.status === 404 && /404 for \/api\/dashboard\/summary/.test(error.message))
    globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'internal secret' }), { status: 500 })
    await assert.rejects(api.apiRequest('/api/dashboard/summary', {}, 'current-token'), error => error.status === 500 && !error.message.includes('internal secret'))
  } finally { globalThis.fetch = originalFetch }
})

test('attack and experiment pages show persisted-result states and seeded-only caveat', () => {
  const markup = renderToStaticMarkup(React.createElement(researchPages.AttackSimulatorPage, { mode: 'preview', token: null, apiStatus: 'offline' }))
  assert.match(markup, /Difference attack/)
  assert.match(markup, /Raw synthetic aggregate/)
  assert.match(markup, /seeded experiment sampler is separate from production randomness/)
  assert.match(markup, /No persisted run selected/)
  assert.doesNotMatch(markup, /Walkthrough|42 \+ 42/)
})

test('research runner exposes versioned attack thresholds and synthetic evidence qualification', () => {
  const markup = renderToStaticMarkup(React.createElement(researchPages.ExperimentsPage, { mode: 'preview', token: null, apiStatus: 'offline' }))
  assert.match(markup, /Relative attack-success tolerance/)
  assert.match(markup, /Narrowing count-error tolerance/)
  assert.match(markup, /M5 minimum ε/)
  assert.match(markup, /M5 risk penalty/)
  assert.match(markup, /M5 budget-use penalty/)
  assert.match(markup, /Protocol v2 stores the minimum synthetic target and inferred values in owner-scoped results to verify attack metrics/)
  assert.match(markup, /for aggregate-reconstruction scenarios this includes the target aggregate/)
  assert.match(markup, /Binary success uses Wilson intervals/)
})

test('comparative results page separates persisted benchmarks from cited literature', () => {
  const markup = renderToStaticMarkup(React.createElement(comparativePage.ComparativeResultsPage, { mode: 'preview', token: null, apiStatus: 'offline' }))
  assert.match(markup, /Comparative Results/)
  assert.match(markup, /Published Literature Comparison/)
  assert.match(markup, /Sign in to view persisted benchmark records/)
  assert.doesNotMatch(markup, /Attack success rate by baseline/)
})

test('illustrative campaign is deterministic, isolated, and covers five scenarios and six methods', () => {
  const first = comparativeDemo.buildIllustrativeCampaign()
  const second = comparativeDemo.buildIllustrativeCampaign()
  assert.deepEqual(first, second)
  assert.deepEqual(Object.keys(first), ['difference', 'repeated', 'fixed_narrowing', 'adaptive_narrowing', 'overlapping'])
  for (const rows of Object.values(first)) {
    assert.equal(rows.length, 4 * 12 * 6)
    assert.deepEqual(new Set(rows.map(row => row.baseline)), new Set(['M0', 'M1', 'M2', 'M3', 'M4', 'M5']))
    assert.ok(rows.every(row => row.replicate >= 1 && row.replicate <= 4 && row.trial >= 1 && row.trial <= 12))
    assert.ok(rows.every(row => Number.isFinite(row.aggregateMae) && Number.isFinite(row.aggregateRmse) && Number.isFinite(row.nominalEpsilon) && row.answerability >= 0 && row.answerability <= 1))
    assert.ok(rows.every(row => row.cacheHits + row.cacheMisses + row.rejections === row.requests))
  }
})

test('illustrative dashboard is unmistakably labeled and exposes no empirical export controls', () => {
  const data = comparativeDemo.buildIllustrativeCampaign()
  const markup = renderToStaticMarkup(React.createElement(comparativePage.IllustrativeDashboard, { data, onExit() {} }))
  assert.match(markup, /ILLUSTRATIVE SIMULATED DATA — NOT EMPIRICAL RESULTS/)
  assert.match(markup, /No API · No persistence · No export/)
  assert.match(markup, /SIMULATED/)
  assert.match(markup, /Illustrative Wilson interval/)
  assert.doesNotMatch(markup, /Download CSV|Export measurements|Persisted run #/)
})

test('empirical attack chart preserves missing denominator and labels scenario-specific reconstruction', () => {
  const markup = renderToStaticMarkup(React.createElement(comparativePage.AttackSuccessChart, { results: [
    { baseline: 'M5', baseline_name: 'PrivacyGuard Adaptive DP', metrics: { metric_states: { attack_success_rate: { state: 'MEASURED' } }, attack_success_rate: 0, attack_success_count: null, attack_attempt_count: null, attack_success_ci95: null } },
  ] }))
  assert.match(markup, /Denominator unavailable/)
  assert.match(markup, /Observed reconstruction success/)
  assert.doesNotMatch(markup, /0\/0 observed successes/)
})

test('repeated attack evidence distinguishes requests, independent samples, cache hits, and legacy runs', () => {
  const markup = renderToStaticMarkup(React.createElement(comparativePage.AttackEstimatorEvidence, { scenario: 'repeated', results: [
    { baseline: 'M4', baseline_name: 'Cache-only fixed DP', metrics: { metric_definition_version: 'comparative-metrics-v5', attack_estimator_version: 'repeated-unique-release-mean-v2', attack_observation_count: 100, unique_attack_observation_count: 20, unique_noise_sample_count: 20, measurements: [{ attack_independent_observation_count: 1, unique_attack_observation_count: 1, attack_success_threshold: 25000000 }], request_measurements: Array.from({ length: 80 }, () => ({ request_status: 'cached' })) } },
    { baseline: 'M5', baseline_name: 'PrivacyGuard Adaptive DP', metrics: { metric_definition_version: 'comparative-metrics-v4', attack_observation_count: 100, measurements: [], request_measurements: [] } },
  ] }))
  assert.match(markup, /cached copies are displayed as requests but do not add estimator samples/)
  assert.match(markup, /unique estimator sources\/trial: 1/)
  assert.match(markup, /independent protected releases\/trial: 1/i)
  assert.match(markup, /Cache hits: 80/)
  assert.match(markup, /LEGACY \/ UNVERIFIABLE SOURCE PROVENANCE/)
  assert.match(markup, /raw protected aggregate outputs are not persisted/)
})

test('empirical distribution and trade-off plots show missing data instead of zero-valued charts', () => {
  const emptyResults = [{ baseline: 'M5', baseline_name: 'PrivacyGuard Adaptive DP', metrics: { metric_states: {}, measurements: [], request_measurements: [], nominal_cumulative_epsilon: null, aggregate_mae: null } }]
  const distribution = renderToStaticMarkup(React.createElement(comparativePage.TrialDistributionPlot, { results: emptyResults, field: 'aggregate_mae', title: 'Persisted trial error' }))
  const tradeoff = renderToStaticMarkup(React.createElement(comparativePage.UtilitySpendPlot, { results: emptyResults }))
  assert.match(distribution, /does not persist trial-level values/)
  assert.match(tradeoff, /Both aggregate error and nominal expenditure must be measured/)
  assert.doesNotMatch(distribution + tradeoff, /0\.00/)
})

test('empirical nominal budget utilization keeps its percentage unit explicit', () => {
  const markup = renderToStaticMarkup(React.createElement(comparativePage.MetricComparisonPlot, { metric: 'budget_utilization_percentage', results: [
    { baseline: 'M5', baseline_name: 'PrivacyGuard Adaptive DP', metrics: { metric_states: { budget_utilization_percentage: { state: 'MEASURED' } }, budget_utilization_percentage: 12.5 } },
  ] }))
  assert.match(markup, /12\.5%/)
  assert.match(markup, /nominal budget utilization/i)
})

test('six-parameter evaluation preserves missing states and refuses an unsupported composite score', () => {
  const makeResult = (baseline, metrics) => ({ baseline, baseline_name: baseline, metrics: { metric_states: {}, ...metrics } })
  const run = {
    configuration: { protocol_version: 'privacyguard-research-protocol-v2', scenario: 'difference', trials: 5 },
    quality_control: { status: 'completed_with_warnings', inferentially_eligible: false },
    results: [
      makeResult('M0', { attack_success_rate: 1, attack_success_count: 5, attack_attempt_count: 5 }),
      makeResult('M1', { attack_success_rate: 0, attack_success_count: 0, attack_attempt_count: 5, nominal_cumulative_epsilon: 5, aggregate_mae: 100, query_latency_ms_mean: 2 }),
      makeResult('M5', { attack_success_rate: 0, attack_success_count: 0, attack_attempt_count: 5, nominal_cumulative_epsilon: 1.5, aggregate_mae: 250, query_latency_ms_mean: null, mean_selected_epsilon: 0.3, mean_risk_score: 0.7 }),
    ],
  }
  const dimensions = comparativePage.buildSixParameterEvaluation(run)
  assert.equal(dimensions.length, 6)
  assert.equal(dimensions.find(item => item.id === 'attack').cells.M5, '0/5 · 0.00%')
  assert.equal(dimensions.find(item => item.id === 'budget').status, 'BETTER')
  assert.equal(dimensions.find(item => item.id === 'utility').value, '250')
  assert.equal(dimensions.find(item => item.id === 'performance').value, 'Not measured')
  assert.equal(dimensions.find(item => item.id === 'cache').status, 'NOT TESTED')
  assert.equal(dimensions.find(item => item.id === 'adaptive').status, 'QUALITATIVE')
  assert.equal(comparativePage.buildOutperformanceScorecard(run, dimensions).title, 'Outperformance not established')
})

test('attack-success chart displays the Wilson bounds supplied by count-based API serialization', () => {
  const results = [
    { baseline: 'M1', metrics: { attack_success_rate: 0, attack_success_count: 0, attack_attempt_count: 20, attack_success_ci95: [0, 0.161125] } },
    { baseline: 'M5', metrics: { attack_success_rate: 1, attack_success_count: 20, attack_attempt_count: 20, attack_success_ci95: [0.838875, 1] } },
  ]
  const markup = renderToStaticMarkup(React.createElement(comparativePage.AttackSuccessChart, { results }))
  assert.match(markup, /0\/20 observed successes/)
  assert.match(markup, /20\/20 observed successes/)
  assert.match(markup, /16\.11%/)
  assert.match(markup, /83\.89%/)
  assert.doesNotMatch(markup, /95% CI 0\.00%–0\.00%/)
  assert.doesNotMatch(markup, /95% CI 100\.00%–100\.00%/)
})

test('paired comparison view shows paired sample size, interval, correction, and method assumptions', () => {
  const run = { paired_comparisons: { status: 'AVAILABLE', comparisons: [{ reference_baseline: 'M1', baseline: 'M5', metric: 'aggregate_mae', n_pairs: 5, mean_difference_baseline_minus_reference: 10, ci95_mean_difference: [2, 18], effect_size_paired_dz: 1.2, holm_adjusted_p_value: 0.1, statistically_significant_after_holm: null, status: 'exploratory', method: 'paired sign-flip randomization test; paired percentile bootstrap CI', assumptions: 'paired trials are exchangeable' }] } }
  const markup = renderToStaticMarkup(React.createElement(comparativePage.PairedComparisonTable, { run }))
  assert.match(markup, /M1 → M5/)
  assert.match(markup, /5/)
  assert.match(markup, /Holm p/)
  assert.match(markup, /exploratory/)
  assert.match(markup, /paired trials are exchangeable/)
})

test('literature numeric values render units exactly once and preserve missing values', () => {
  const renderValue = row => renderToStaticMarkup(React.createElement(comparativePage.LiteratureValue, { row }))
  assert.equal(renderValue({ value: 100, unit: '%' }), '<b>100%</b>')
  assert.equal(renderValue({ value: 80, unit: '%' }), '<b>80%</b>')
  assert.equal(renderValue({ value: null, unit: 'Not reported' }), '<b>Not reported</b>')
})

test('research metric states preserve measured zero and distinguish unavailable, invalid and pending values', () => {
  const { formatMetricValue } = metricState
  assert.equal(formatMetricValue(0, { state: 'MEASURED', reason: null }), '0')
  assert.equal(formatMetricValue(null, { state: 'NOT_MEASURED', reason: 'No observations' }), 'N/A')
  assert.equal(formatMetricValue(4, { state: 'INVALID', reason: 'Inconsistent' }), 'Invalid measurement')
  assert.equal(formatMetricValue(null, { state: 'PENDING', reason: null }), 'Pending')
  assert.equal(formatMetricValue(null, { state: 'NOT_APPLICABLE', reason: 'Raw baseline' }), 'N/A · not applicable')
  assert.equal(formatMetricValue(0.000439, undefined, value => `${(value * 100).toFixed(2)}%`), '0.04%')
})

test('research service posts synthetic run configuration to protected endpoints and downloads CSV with bearer auth', async () => {
  const originalFetch = globalThis.fetch
  const config = { scenario: 'difference', dataset_size: 5000, baselines: ['B0', 'B4'], trials: 2, repetitions: 3, seed: 17, epsilon: 0.5, budget_epsilon: 10, adaptive_epsilon_min: 0.1, adaptive_risk_penalty: 0.1, adaptive_cumulative_penalty: 0.05 }
  const requests = []
  try {
    globalThis.fetch = async (url, init) => {
      requests.push({ url, init })
      if (String(url).endsWith('.csv')) return new Response('run_id,trial\n1,1', { status: 200, headers: { 'Content-Type': 'text/csv' } })
      return new Response(JSON.stringify({ id: 1, status: 'completed', results: [] }), { status: 200 })
    }
    await researchService.runExperiment(config, 'test-token', true)
    assert.equal(requests[0].url, '/api/attacks/simulate')
    assert.equal(requests[0].init.headers.get('Authorization'), 'Bearer test-token')
    assert.deepEqual(JSON.parse(requests[0].init.body), config)
    const csv = await researchService.downloadExperimentCsv(1, 'test-token')
    assert.match(await csv.text(), /run_id,trial/)
    assert.equal(requests[1].init.headers.Authorization, 'Bearer test-token')
  } finally { globalThis.fetch = originalFetch }
})

test('administrator password reset form uses password inputs, confirmation and safe initial state', () => {
  const markup = renderToStaticMarkup(React.createElement(operationalPages.PasswordResetForm, { username: 'researcher_demo', token: 'transient-token' }))
  assert.match(markup, /Reset password for researcher_demo/)
  assert.match(markup, /New password/)
  assert.match(markup, /Confirm new password/)
  assert.equal((markup.match(/type="password"/g) || []).length, 2)
  assert.match(markup, /At least 12 characters/)
  assert.match(markup, /disabled/)
  assert.doesNotMatch(markup, /transient-token/)
  assert.doesNotMatch(markup, /researcher-old-password/)
})

test('user management API uses authenticated owner-protected account routes without exposing old credentials', async () => {
  const originalFetch = globalThis.fetch
  const calls = []
  const newPassword = 'A newly chosen secure password 2026!'
  try {
    globalThis.fetch = async (url, init) => {
      calls.push({ url: String(url), init })
      return new Response(JSON.stringify({ username: 'researcher_demo', status: 'password_reset' }), { status: 200 })
    }
    await usersService.listManagedUsers('admin-token')
    const result = await usersService.resetManagedUserPassword('admin-token', 'researcher_demo', newPassword)
    assert.equal(result.status, 'password_reset')
    assert.equal(calls[0].url, '/api/users')
    assert.equal(calls[0].init.headers.get('Authorization'), 'Bearer admin-token')
    assert.equal(calls[1].url, '/api/users/researcher_demo/password-reset')
    assert.equal(calls[1].init.headers.get('Authorization'), 'Bearer admin-token')
    assert.deepEqual(JSON.parse(calls[1].init.body), { new_password: newPassword })
    assert.doesNotMatch(calls[1].init.body, /current_password|old_password/)
  } finally { globalThis.fetch = originalFetch }
})

test('user-list API preserves successful empty results and surfaces authorization/network failures', async () => {
  const originalFetch = globalThis.fetch
  try {
    globalThis.fetch = async () => new Response(JSON.stringify({ items: [], total: 0 }), { status: 200 })
    assert.deepEqual(await usersService.listManagedUsers('admin-token'), { items: [], total: 0 })

    globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Permission denied' }), { status: 403 })
    await assert.rejects(usersService.listManagedUsers('admin-token'), error => error.status === 403 && /not authorized/.test(error.message))

    globalThis.fetch = async () => { throw new TypeError('connection refused') }
    await assert.rejects(usersService.listManagedUsers('admin-token'), error => /Could not reach/.test(error.message))
  } finally { globalThis.fetch = originalFetch }
})

test('benchmark-results service sends authenticated persisted-record filters', async () => {
  const originalFetch = globalThis.fetch
  let call
  globalThis.fetch = async (url, init) => { call = { url: String(url), init }; return new Response(JSON.stringify({ items: [], total: 0, page: 2, page_size: 20 }), { status: 200 }) }
  try {
    const response = await researchService.getBenchmarkResults('research-token', { page: 2, page_size: 20, scenario: 'difference', dataset_size: 5000, baseline: 'M5', trials: 5, date_from: '2026-01-01' })
    assert.equal(response.total, 0)
    assert.match(call.url, /\/api\/experiments\/benchmark-results\?/)
    assert.match(call.url, /baseline=M5/)
    assert.match(call.url, /scenario=difference/)
    assert.equal(call.init.headers.get('Authorization'), 'Bearer research-token')
  } finally { globalThis.fetch = originalFetch }
})

test('benchmark summary service requests owner-scoped lightweight run metadata', async () => {
  const originalFetch = globalThis.fetch
  let call
  globalThis.fetch = async (url, init) => { call = { url: String(url), init }; return new Response(JSON.stringify({ items: [{ id: 14, name: 'run', configuration: { scenario: 'difference' }, seed: 10, status: 'completed', created_at: '2026-11-26T00:00:00Z' }], total: 1, page: 1, page_size: 20 }), { status: 200 }) }
  try {
    const response = await researchService.getBenchmarkRunSummaries('research-token', { page: 1, page_size: 20, scenario: 'difference' })
    assert.equal(response.items[0].id, 14)
    assert.match(call.url, /\/api\/experiments\/benchmark-runs\?/)
    assert.match(call.url, /scenario=difference/)
    assert.equal(call.init.headers.get('Authorization'), 'Bearer research-token')
  } finally { globalThis.fetch = originalFetch }
})

test('saved experiment detail uses an authenticated bounded read timeout', async () => {
  const originalFetch = globalThis.fetch
  let call
  globalThis.fetch = async (url, init) => { call = { url: String(url), init }; return new Response(JSON.stringify({ id: 14 }), { status: 200 }) }
  try {
    await researchService.getExperimentRun(14, 'research-token')
    assert.match(call.url, /\/api\/experiments\/runs\/14$/)
    assert.equal(call.init.headers.get('Authorization'), 'Bearer research-token')
    assert.ok(call.init.signal instanceof AbortSignal)
    assert.equal(call.init.signal.aborted, false)
  } finally { globalThis.fetch = originalFetch }
})
