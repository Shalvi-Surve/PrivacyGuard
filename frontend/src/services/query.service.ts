import { apiRequest } from './api'
import type { ProtectedQueryResult, QueryAnalysis } from '../types/app'

export function analyzeQuery(sql: string, token: string, dataset_id?: number) {
  return apiRequest<QueryAnalysis>('/api/queries/analyze', { method: 'POST', body: JSON.stringify({ sql, dataset_id }) }, token)
}

export function executeProtectedQuery(sql: string, dataset_id: number, token: string) {
  return apiRequest<ProtectedQueryResult>('/api/queries/execute', {
    method: 'POST',
    body: JSON.stringify({ sql, dataset_id }),
  }, token)
}
