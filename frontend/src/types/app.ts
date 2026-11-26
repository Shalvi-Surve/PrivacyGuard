export type PageId = 'overview' | 'datasets' | 'query' | 'history' | 'budgets' | 'risk' | 'attacks' | 'audit' | 'users' | 'experiments' | 'comparative-results' | 'architecture' | 'settings'
export type AppMode = 'login' | 'preview' | 'authenticated'
export type ApiStatus = 'checking' | 'online' | 'degraded' | 'offline'

export type UserProfile = {
  id: number
  username: string
  full_name: string
  email?: string
  is_active?: boolean
  roles: string[]
}

export type NavigationItem = {
  id: PageId
  label: string
  icon: string
  section: string
}

export type QueryAnalysis = {
  analysis_id: number
  canonical_sql: string
  fingerprint: string
  query_type: 'count' | 'sum'
  table: string
  aggregate_column: string | null
  referenced_columns: string[]
}

export type DatasetRecord = {
  id: number
  name: string
  description: string
  source_type: string
  table_name: string
  record_count: number
  sensitivity: string
  created_at: string
  owner?: string | null
  access_roles?: string[]
  columns?: { name: string; data_type: string; missing_values: number }[]
}

export type ProtectedQueryResult = {
  query_id: number
  dataset_id: number
  dataset_name: string
  query_type: string
  protected_result: number
  epsilon: number
  epsilon_charged: number
  sensitivity: number
  noise_scale: number
  risk_score: number
  risk_level: string
  risk_components: Record<string, number>
  privacy_spent: number
  remaining_budget: number
  budget_state: string
  query_fingerprint: string
  cache_hit: boolean
  processing_ms: number
  decision: string
  explanation: string
  adjacency_model: string
  policy_version: string
  mechanism: string
  clipping_bounds: Record<string, number> | null
  dataset_version: number
  accounting_status: string
  privacy_guarantee_status: string
  allocation_decision: Record<string, unknown>
}
