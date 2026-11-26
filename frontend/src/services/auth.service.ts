import { apiRequest } from './api'
import type { UserProfile } from '../types/app'

export type AuthToken = { access_token: string; token_type: 'bearer' }

export function signIn(username: string, password: string) {
  return apiRequest<AuthToken>('/api/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) })
}

export function getCurrentUser(token: string) {
  return apiRequest<UserProfile>('/api/auth/me', {}, token)
}

export function signOut(token: string | null) {
  if (!token) return Promise.resolve()
  return apiRequest<void>('/api/auth/logout', { method: 'POST' }, token)
}
