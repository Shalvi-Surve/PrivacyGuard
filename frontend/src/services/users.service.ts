import { apiRequest } from './api'

export type ManagedUser = {
  id: number
  username: string
  full_name: string
  is_active: boolean
  roles: string[]
}

export function listManagedUsers(token: string) {
  return apiRequest<{ items: ManagedUser[]; total: number }>('/api/users', {}, token)
}

export function resetManagedUserPassword(token: string, username: string, newPassword: string) {
  return apiRequest<{ username: string; status: 'password_reset' }>(
    `/api/users/${encodeURIComponent(username)}/password-reset`,
    { method: 'POST', body: JSON.stringify({ new_password: newPassword }) },
    token,
  )
}
