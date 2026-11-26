import type { NavigationItem, PageId } from '../types/app'

export const navigation: NavigationItem[] = [
  { id: 'overview', label: 'Overview', icon: 'grid', section: 'Overview' },
  { id: 'datasets', label: 'Dataset Management', icon: 'database', section: 'Data & Connectivity' },
  { id: 'query', label: 'Query Console', icon: 'terminal', section: 'Query Workspace' },
  { id: 'history', label: 'Query History', icon: 'clock', section: 'Query Workspace' },
  { id: 'budgets', label: 'Privacy Budgets', icon: 'wallet', section: 'Privacy Management' },
  { id: 'risk', label: 'Risk Analysis', icon: 'pulse', section: 'Security & Governance' },
  { id: 'attacks', label: 'Attack Simulator', icon: 'target', section: 'Security & Governance' },
  { id: 'audit', label: 'Audit Logs', icon: 'file', section: 'Security & Governance' },
  { id: 'users', label: 'User & Role Management', icon: 'users', section: 'Security & Governance' },
  { id: 'experiments', label: 'Experiments & Evaluation', icon: 'flask', section: 'Research & Evaluation' },
  { id: 'comparative-results', label: 'Comparative Results', icon: 'pulse', section: 'Research & Evaluation' },
  { id: 'architecture', label: 'System Architecture', icon: 'nodes', section: 'Operations' },
  { id: 'settings', label: 'Settings', icon: 'settings', section: 'Administration' },
]

export function resolvePage(hash: string): PageId {
  const candidate = hash.replace(/^#\/?/, '') as PageId
  return navigation.some(item => item.id === candidate) ? candidate : 'overview'
}
