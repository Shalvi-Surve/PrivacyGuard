import type { PageId } from '../types/app'

export type DemoQuery = {
  id: string; user: string; role: string; type: 'COUNT' | 'SUM'; table: string
  fingerprint: string; timestamp: string; risk: number; epsilon: number | null
  decision: 'Approved' | 'Rejected' | 'Review'; status: string; sql: string
}

export const demoQueries: DemoQuery[] = [
  { id: 'Q-2084', user: 'analyst_demo', role: 'analyst', type: 'COUNT', table: 'employees', fingerprint: 'a8c2e1…51d3', timestamp: '10:42:18', risk: 0.18, epsilon: 0.5, decision: 'Approved', status: 'Analyzed', sql: "SELECT COUNT(*) FROM employees WHERE department = 'Engineering';" },
  { id: 'Q-2083', user: 'researcher_demo', role: 'researcher', type: 'SUM', table: 'employees', fingerprint: 'f32b09…d118', timestamp: '10:38:04', risk: 0.62, epsilon: 0.3, decision: 'Review', status: 'Reviewed', sql: "SELECT SUM(salary) FROM employees WHERE department = 'Finance';" },
  { id: 'Q-2082', user: 'hr_demo', role: 'hr', type: 'COUNT', table: 'employees', fingerprint: 'a8c2e1…51d3', timestamp: '10:21:51', risk: 0.74, epsilon: null, decision: 'Rejected', status: 'Policy review', sql: "SELECT COUNT(*) FROM employees WHERE department = 'Engineering';" },
  { id: 'Q-2081', user: 'analyst_demo', role: 'analyst', type: 'SUM', table: 'employees', fingerprint: '6bd4f0…ea20', timestamp: '09:56:32', risk: 0.31, epsilon: 0.7, decision: 'Approved', status: 'Analyzed', sql: "SELECT SUM(salary) FROM employees WHERE department = 'Product';" },
  { id: 'Q-2080', user: 'doctor_demo', role: 'doctor', type: 'COUNT', table: 'employees', fingerprint: 'cc9a63…a302', timestamp: '09:44:07', risk: 0.42, epsilon: 0.4, decision: 'Approved', status: 'Analyzed', sql: 'SELECT COUNT(*) FROM employees WHERE age >= 40;' },
  { id: 'Q-2079', user: 'researcher_demo', role: 'researcher', type: 'COUNT', table: 'employees', fingerprint: 'df6810…b44c', timestamp: '09:26:55', risk: 0.83, epsilon: null, decision: 'Rejected', status: 'Unsupported query', sql: "SELECT COUNT(*) FROM employees WHERE department = 'Engineering' AND age > 55;" },
  { id: 'Q-2078', user: 'analyst_demo', role: 'analyst', type: 'SUM', table: 'employees', fingerprint: '6bd4f0…ea20', timestamp: '09:10:26', risk: 0.28, epsilon: 0.7, decision: 'Approved', status: 'Analyzed', sql: "SELECT SUM(salary) FROM employees WHERE department = 'Product';" },
  { id: 'Q-2077', user: 'hr_demo', role: 'hr', type: 'COUNT', table: 'employees', fingerprint: 'a8c2e1…51d3', timestamp: '08:54:11', risk: 0.36, epsilon: 0.5, decision: 'Approved', status: 'Analyzed', sql: "SELECT COUNT(*) FROM employees WHERE department = 'Engineering';" },
]

export const demoUsers = [
  { username: 'admin', name: 'Demo Administrator', role: 'administrator', state: 'Active' },
  { username: 'analyst_demo', name: 'Demo Analyst', role: 'analyst', state: 'Active' },
  { username: 'hr_demo', name: 'Demo HR User', role: 'hr', state: 'Active' },
  { username: 'doctor_demo', name: 'Demo Doctor', role: 'doctor', state: 'Active' },
  { username: 'researcher_demo', name: 'Demo Researcher', role: 'researcher', state: 'Active' },
]

export const seededRoles = [
  { role: 'administrator', permissions: ['users:manage', 'settings:manage', 'audit:read', 'queries:submit', 'queries:execute_protected', 'datasets:read', 'datasets:manage', 'history:read_all', 'budgets:read_all', 'experiments:run'] },
  { role: 'analyst', permissions: ['queries:submit', 'history:read_own', 'budgets:read_own'] },
  { role: 'hr', permissions: ['queries:submit', 'history:read_own', 'budgets:read_own'] },
  { role: 'doctor', permissions: ['queries:submit', 'history:read_own', 'budgets:read_own'] },
  { role: 'researcher', permissions: ['queries:submit', 'history:read_own', 'budgets:read_own', 'experiments:run'] },
]

export const demoLedger = [
  { id: 'L-1094', query: 'Q-2081', actor: 'analyst_demo', epsilon: 0.7, event: 'Release preview', time: 'Today, 09:56' },
  { id: 'L-1093', query: 'Q-2080', actor: 'doctor_demo', epsilon: 0.4, event: 'Release preview', time: 'Today, 09:44' },
  { id: 'L-1092', query: 'Q-2078', actor: 'analyst_demo', epsilon: 0.7, event: 'Release preview', time: 'Today, 09:10' },
  { id: 'L-1091', query: 'Q-2077', actor: 'hr_demo', epsilon: 0.5, event: 'Release preview', time: 'Today, 08:54' },
  { id: 'L-1090', query: 'Q-2075', actor: 'researcher_demo', epsilon: 0.8, event: 'Release preview', time: 'Yesterday, 16:22' },
  { id: 'L-1089', query: 'Q-2072', actor: 'analyst_demo', epsilon: 0.7, event: 'Release preview', time: 'Yesterday, 15:51' },
]

export const demoSnapshot = {
  generatedLabel: 'Coherent illustrative workspace scenario · not measured output',
  queriesAnalyzed: 1284,
  approvedQueries: 962,
  rejectedQueries: 128,
  reviewQueries: 194,
  privacyBudgetInitial: 10,
  privacyBudgetConsumed: 3.8,
  activeUsers: 5,
  latencyMs: null as number | null,
  dailyActivity: [140, 155, 132, 190, 210, 175, 204],
  protectedActivity: [105, 116, 99, 143, 158, 131, 153],
  queryTypes: [{ label: 'COUNT', value: 832 }, { label: 'SUM', value: 452 }],
  riskLevels: [{ label: 'Low', value: 740 }, { label: 'Medium', value: 350 }, { label: 'High', value: 194 }],
}

export const demoAudit = [
  { id: 'A-5042', time: '10:42:18', user: 'analyst_demo', event: 'Query analyzed', resource: 'employees', status: 'Completed' },
  { id: 'A-5041', time: '10:38:04', user: 'researcher_demo', event: 'Query reviewed', resource: 'employees', status: 'Reviewed' },
  { id: 'A-5040', time: '10:21:51', user: 'hr_demo', event: 'Query rejected', resource: 'employees', status: 'Rejected' },
  { id: 'A-5039', time: '09:56:32', user: 'analyst_demo', event: 'Budget preview', resource: 'dataset: employees', status: 'Recorded' },
  { id: 'A-5038', time: '09:30:02', user: 'admin', event: 'Settings viewed', resource: 'privacy policy', status: 'Completed' },
]

export const architectureComponents = [
  { id: 'react', title: 'React application', status: 'Implemented', description: 'PrivacyGuard UI with login, query analysis and labelled preview screens.' },
  { id: 'auth', title: 'Authentication', status: 'Implemented', description: 'JWT login, current profile and stateless client logout endpoints.' },
  { id: 'rbac', title: 'RBAC checks', status: 'Partial', description: 'Permission dependencies protect analysis and protected execution; dataset grants scope reads and releases.' },
  { id: 'parser', title: 'SQL parser & validator', status: 'Implemented', description: 'SQLGlot validates a constrained COUNT/SUM subset used by analysis and protected execution.' },
  { id: 'history', title: 'Query history', status: 'Partial', description: 'Protected release attempts and cache hits are persisted; history retrieval UI/API remains pending.' },
  { id: 'risk', title: 'Risk policy', status: 'Partial', description: 'Heuristic signals from structural history and query shape feed the protected release epsilon policy.' },
  { id: 'budget', title: 'Budget accountant', status: 'Implemented', description: 'Conditional dataset budget reservation and ledger updates are part of the protected release transaction.' },
  { id: 'postgres', title: 'PostgreSQL execution', status: 'Planned', description: 'Only the SQLite synthetic employee aggregate path is implemented and verified so far.' },
  { id: 'dp', title: 'Differential Privacy release', status: 'Partial', description: 'Protected COUNT and bounded SUM use Laplace noise; other dataset and experiment mechanisms remain pending.' },
  { id: 'audit', title: 'Audit and experiments', status: 'Implemented', description: 'Protected query events are audited; synthetic attack scenarios and comparative run results are permission-scoped and persisted.' },
]

export const pageDescriptions: Record<PageId, string> = {
  overview: 'Privacy operations at a glance.', datasets: 'Manage role-scoped synthetic employee datasets.', query: 'Analyze restricted SQL or request a budgeted protected aggregate.',
  history: 'Review persisted SQL analysis and protected release metadata.', budgets: 'Inspect persisted dataset epsilon composition and release ledger.',
  risk: 'Explore explainable policy signals and the current model boundary.', attacks: 'Learn how correlated aggregates can support inference attacks.',
  audit: 'Search the persisted administrative and query event trail.', users: 'Inspect seeded demonstration roles and accounts without changing permissions.',
  experiments: 'Run reproducible synthetic attack and baseline comparisons with persisted measurements.',
  'comparative-results': 'Compare persisted synthetic experiment results and separately sourced literature findings.',
  architecture: 'Explore implemented and planned middleware components.', settings: 'Review local configuration without exposing secrets or implying persistence.',
}
