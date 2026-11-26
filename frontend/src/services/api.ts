// Empty means same-origin requests, which Vite proxies to FastAPI in development.
// Production can set VITE_API_BASE_URL to an explicit API origin at build time.
export const API_BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(message: string, readonly status?: number) {
    super(message)
    this.name = 'ApiError'
  }
}

export async function apiRequest<T>(path: string, init: RequestInit = {}, token?: string | null): Promise<T> {
  const headers = new Headers(init.headers)
  if (typeof init.body === 'string' && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  if (token) headers.set('Authorization', `Bearer ${token}`)
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers, signal: init.signal ?? AbortSignal.timeout(8000) })
  } catch (error) {
    const message = error instanceof DOMException && error.name === 'TimeoutError'
      ? 'The API request timed out.'
      : 'Could not reach the PrivacyGuard API. Check the backend connection.'
    throw new ApiError(message)
  }
  const payload = response.status === 204 ? null : await response.json().catch(() => null)
  if (!response.ok) {
    if (response.status === 401 && token && typeof window !== 'undefined') {
      window.dispatchEvent(new Event('privacyguard:unauthorized'))
    }
    const rawDetail = payload && typeof payload === 'object' && 'detail' in payload ? payload.detail : undefined
    const detail = typeof rawDetail === 'string' ? rawDetail : ''
    const safeMessage = response.status >= 500
      ? `The API returned a server error (${response.status}). Please retry shortly.`
      : response.status === 404
        ? `The API returned 404 for ${path.split('?')[0]}. Check the backend version and API URL.`
        : response.status === 403
          ? `You are signed in, but your role is not authorized to access ${path.split('?')[0]}. Ask an administrator to verify your role permissions.`
        : response.status === 422 && !detail
          ? 'Some request fields are invalid. Check the form and try again.'
          : detail || `Request failed (${response.status}).`
    throw new ApiError(safeMessage, response.status)
  }
  return payload as T
}

export async function checkApiHealth(signal?: AbortSignal): Promise<'online' | 'degraded'> {
  const health = await apiRequest<{ status: string; database?: { status?: string } }>('/health', { signal })
  return health.database?.status === 'unavailable' ? 'degraded' : 'online'
}
