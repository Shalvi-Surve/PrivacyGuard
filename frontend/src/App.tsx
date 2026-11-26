import { useEffect, useState } from 'react'
import { resolvePage } from './app/navigation'
import { AppShell } from './components/layout/AppShell'
import { signIn, signOut, getCurrentUser } from './services/auth.service'
import { checkApiHealth } from './services/api'
import type { ApiStatus, AppMode, PageId, UserProfile } from './types/app'
import { LoginPage } from './pages/LoginPage'
import { OverviewPage } from './pages/OverviewPage'
import { QueryConsolePage } from './pages/QueryConsolePage'
import { DatasetManagementPage } from './pages/DatasetManagementPage'
import { ArchitecturePage, AttackSimulatorPage, ExperimentsPage, SettingsPage } from './pages/ResearchPages'
import { AuditLogsPage, PrivacyBudgetsPage, QueryHistoryPage, RiskAnalysisPage, UserRolesPage } from './pages/OperationalPages'
import { ComparativeResultsPage } from './pages/ComparativeResultsPage'

function readToken() {
  try { return window.sessionStorage.getItem('privacyguard-token') } catch { return null }
}
function writeToken(token: string) {
  try { window.sessionStorage.setItem('privacyguard-token', token) } catch { /* current tab can still use its in-memory token */ }
}
function clearToken() {
  try { window.sessionStorage.removeItem('privacyguard-token') } catch { /* nothing to clear */ }
}

export default function App() {
  const [token, setToken] = useState<string | null>(() => readToken())
  const [mode, setMode] = useState<AppMode>(() => readToken() ? 'authenticated' : 'login')
  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [apiStatus, setApiStatus] = useState<ApiStatus>('checking')
  const [healthAttempt, setHealthAttempt] = useState(0)
  const [activePage, setActivePage] = useState<PageId>(() => typeof window === 'undefined' ? 'overview' : resolvePage(window.location.hash))

  useEffect(() => {
    function syncRoute() { setActivePage(resolvePage(window.location.hash)) }
    window.addEventListener('hashchange', syncRoute)
    if (!window.location.hash) window.history.replaceState(null, '', '#/overview')
    return () => window.removeEventListener('hashchange', syncRoute)
  }, [])

  useEffect(() => {
    function expireSession() {
      clearToken(); setToken(null); setProfile(null); setMode('login'); setActivePage('overview')
      window.location.hash = '/overview'
    }
    window.addEventListener('privacyguard:unauthorized', expireSession)
    return () => window.removeEventListener('privacyguard:unauthorized', expireSession)
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), 3500)
    checkApiHealth(controller.signal).then(setApiStatus).catch(() => setApiStatus('offline')).finally(() => window.clearTimeout(timeout))
    return () => { controller.abort(); window.clearTimeout(timeout) }
  }, [healthAttempt])

  useEffect(() => {
    if (!token) return
    let active = true
    getCurrentUser(token).then(user => { if (active) setProfile(user) }).catch(error => {
      if (!active) return
      if (error instanceof Error && 'status' in error && error.status === 401) {
        clearToken(); setToken(null); setMode('login'); setProfile(null)
      } else setApiStatus('offline')
    })
    return () => { active = false }
  }, [token])

  async function login(username: string, password: string) {
    const result = await signIn(username, password)
    writeToken(result.access_token)
    setToken(result.access_token)
    setMode('authenticated')
    setApiStatus('online')
    setActivePage('overview')
    window.location.hash = '/overview'
  }

  async function logout() {
    const currentToken = token
    clearToken(); setToken(null); setProfile(null); setMode('login'); setActivePage('overview')
    window.location.hash = '/overview'
    try { await signOut(currentToken) } catch { /* local session is cleared even if API logout is unreachable */ }
  }

  function navigate(page: PageId) {
    setActivePage(page)
    window.location.hash = `/${page}`
  }

  function retryBackend() {
    setApiStatus('checking')
    setHealthAttempt(value => value + 1)
  }

  function renderPage() {
    switch (activePage) {
      case 'overview': return <OverviewPage onNavigate={navigate} mode={mode} token={token} apiStatus={apiStatus} onRetry={retryBackend} />
      case 'datasets': return <DatasetManagementPage mode={mode} token={token} apiStatus={apiStatus} profile={profile} onNavigate={navigate} />
      case 'query': return <QueryConsolePage mode={mode} apiStatus={apiStatus} token={token} />
      case 'history': return <QueryHistoryPage mode={mode} token={token} apiStatus={apiStatus} profile={profile} />
      case 'budgets': return <PrivacyBudgetsPage mode={mode} token={token} apiStatus={apiStatus} />
      case 'risk': return <RiskAnalysisPage />
      case 'attacks': return <AttackSimulatorPage mode={mode} token={token} apiStatus={apiStatus} />
      case 'audit': return <AuditLogsPage mode={mode} token={token} apiStatus={apiStatus} profile={profile} />
      case 'users': return <UserRolesPage mode={mode} token={token} apiStatus={apiStatus} profile={profile} />
      case 'experiments': return <ExperimentsPage mode={mode} token={token} apiStatus={apiStatus} />
      case 'comparative-results': return <ComparativeResultsPage mode={mode} token={token} apiStatus={apiStatus} onRetry={retryBackend} onNavigate={navigate} />
      case 'architecture': return <ArchitecturePage />
      case 'settings': return <SettingsPage apiStatus={apiStatus} />
    }
  }

  if (mode === 'login') return <LoginPage apiStatus={apiStatus} onRetry={retryBackend} onLogin={login} onPreview={() => setMode('preview')} />
  return <AppShell mode={mode} profile={profile} apiStatus={apiStatus} activePage={activePage} onNavigate={navigate} onLogout={logout} onRetry={retryBackend}>{renderPage()}</AppShell>
}

export { AppShell as Dashboard }
