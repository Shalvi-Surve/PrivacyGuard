import { apiRequest } from './api'

export type QueryHistoryItem = {
  id: string
  request_kind: 'analysis' | 'protected'
  user_id: number
  username: string
  dataset_id: number | null
  dataset_name: string | null
  query_type: string
  fingerprint: string | null
  epsilon: number | null
  risk_score: number | null
  decision: string
  created_at: string
  attributes: string[]
}

export type QueryHistoryPage = { items: QueryHistoryItem[]; total: number; page: number; page_size: number }
export type BudgetItem = {
  budget_id: number; dataset_id: number; dataset_name: string; source_type: string
  initial_epsilon: number; spent_epsilon: number; remaining_epsilon: number
  utilization: number; state: string; release_count: number; updated_at: string; accounting_status?: string
}
export type LedgerItem = { id: number; query_id: number | null; dataset_name: string; user: string | null; epsilon: number; event_type: string; created_at: string }
export type BudgetPage = { items: BudgetItem[]; total: number; page: number; page_size: number; ledger: LedgerItem[]; ledger_total: number; accounting_status?: string }
export type AuditItem = { id: number; user_id: number | null; username: string | null; event_type: string; status: string; metadata: Record<string, unknown>; created_at: string }
export type AuditPage = { items: AuditItem[]; total: number; page: number; page_size: number }
export type DashboardOverview = {
  window_days: number
  metrics: {
    total_requests: number; protected_releases: number; approved_requests: number
    rejected_requests: number; other_requests: number; high_risk_requests: number
    risk_scored_requests?: number; risk_unscored_or_rejected_requests?: number
    high_risk_threshold?: number; high_risk_percentage_of_scored?: number | null
    privacy_spent: number | null; remaining_budget: number | null; accessible_datasets: number
  }
  daily_activity: { date: string; approved: number; rejected: number; other: number; total: number }[]
  decision_distribution: Record<string, number>
  recent_activity: { id: string; query_id: number; request_kind: string; user: string; dataset_id: number | null; dataset_name: string | null; query_type: string; epsilon: number | null; risk_score: number | null; decision: string; created_at: string }[]
  budget_health: { available: boolean; scope: string; accounting_status?: string; initial_budget: number | null; spent_budget: number | null; remaining_budget: number | null; utilization: number | null; datasets: { dataset_id: number; dataset_name: string; available: boolean; scope: string; initial_budget: number | null; spent_budget: number | null; remaining_budget: number | null; utilization: number | null }[] }
  recent_audit_activity: { id: number; event_type: string; actor: string; timestamp: string; status: string; description: string }[]
  operational_signals: { api_health: string; database: string; sql_analysis: string; protected_releases: string; experiments: string }
}

function queryString(parameters: Record<string, string | number | undefined>) {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(parameters)) if (value !== undefined && value !== '') query.set(key, String(value))
  return query.toString()
}

export function listQueryHistory(token: string, filters: { page: number; page_size: number; search?: string; dataset_id?: number; user_id?: number; query_type?: string; decision?: string; date_from?: string; date_to?: string }) {
  return apiRequest<QueryHistoryPage>(`/api/queries/history?${queryString(filters)}`, {}, token)
}

export function getQueryHistoryDetail(id: string, token: string) {
  return apiRequest<QueryHistoryItem & { detail: string }>(`/api/queries/history/${encodeURIComponent(id)}`, {}, token)
}

export function listBudgets(token: string, page = 1, page_size = 25) {
  return apiRequest<BudgetPage>(`/api/budgets?${queryString({ page, page_size })}`, {}, token)
}

export function listAuditLogs(token: string, filters: { page: number; page_size: number; search?: string; event_type?: string; status?: string; user_id?: number; date_from?: string; date_to?: string }) {
  return apiRequest<AuditPage>(`/api/audit?${queryString(filters)}`, {}, token)
}

export function getDashboardSummary(token: string, days = 7) {
  return apiRequest<DashboardOverview>(`/api/dashboard/summary?days=${days}`, {}, token)
}
