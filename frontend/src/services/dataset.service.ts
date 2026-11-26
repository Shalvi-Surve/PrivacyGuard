import { apiRequest } from './api'
import type { DatasetRecord } from '../types/app'

export type DatasetList = { items: DatasetRecord[] }

export function listDatasets(token: string) {
  return apiRequest<DatasetList>('/api/datasets', {}, token)
}

export function generateEmployeeDataset(token: string, payload: { name: string; size: number; seed: number; initial_epsilon: number }) {
  return apiRequest<DatasetRecord>('/api/datasets/synthetic/employees', { method: 'POST', body: JSON.stringify(payload) }, token)
}

export function deleteDataset(token: string, datasetId: number) {
  return apiRequest<void>(`/api/datasets/${datasetId}`, { method: 'DELETE' }, token)
}
