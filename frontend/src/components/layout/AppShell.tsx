import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { navigation } from '../../app/navigation'
import { demoQueries } from '../../data/demo'
import { Icon } from '../Icon'
import type { ApiStatus, AppMode, PageId, UserProfile } from '../../types/app'

export function AppShell({ mode, profile, apiStatus, activePage, onNavigate, onLogout, onRetry, children }: {
  mode: AppMode; profile: UserProfile | null; apiStatus: ApiStatus; activePage: PageId
  onNavigate: (page: PageId) => void; onLogout: () => void; onRetry?: () => void; children: ReactNode
}) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(false)
  const [profileOpen, setProfileOpen] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const title = navigation.find(item => item.id === activePage)?.label || 'Overview'
  const displayName = mode === 'preview' ? 'Demo preview' : profile?.full_name || profile?.username || 'Workspace user'
  const groups = Array.from(new Set(navigation.map(item => item.section)))
  const source = sourceInfo(mode, activePage)

  useEffect(() => {
    function keydown(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); setSearchOpen(value => !value) }
      if (event.key === 'Escape') { setSearchOpen(false); setProfileOpen(false); setMenuOpen(false) }
    }
    window.addEventListener('keydown', keydown)
    return () => window.removeEventListener('keydown', keydown)
  }, [])

  function navigate(page: PageId) {
    onNavigate(page)
    setMenuOpen(false)
    setSearchOpen(false)
  }

  return <div className={`app-shell ${collapsed ? 'sidebar-collapsed' : ''}`}>
    <aside className={`sidebar ${menuOpen ? 'open' : ''}`} id="app-sidebar">
      <div className="sidebar-brand"><span className="brand-icon"><Icon name="shield" size={20} /></span><span className="brand-copy"><span className="brand-name"><span>PRIVACY</span><span className="brand-light">GUARD</span></span><small>PRIVACY CONTROL PLANE</small></span><button className="collapse-button" onClick={() => setCollapsed(value => !value)} aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'} title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}>‹</button></div>
      <div className="workspace-select"><span className="workspace-avatar">R</span><span className="workspace-copy"><b>Research workspace</b><small>Local environment</small></span><span className="workspace-chevron">⌄</span></div>
      <nav aria-label="Main navigation" className="side-navigation">
        {groups.map(group => <div className="nav-group" key={group}><div className="nav-heading">{group}</div>{navigation.filter(item => item.section === group).map(item => <button key={item.id} className={`nav-link ${activePage === item.id ? 'active' : ''}`} aria-current={activePage === item.id ? 'page' : undefined} title={collapsed ? item.label : undefined} onClick={() => navigate(item.id)}><Icon name={item.icon} /><span className="nav-label">{item.label}</span>{item.id === 'risk' && <span className="nav-count">demo</span>}</button>)}</div>)}
      </nav>
      <div className="sidebar-bottom"><div className="environment-label"><span className="environment-dot" /> <span>LOCAL DEVELOPMENT</span></div><button className="user-menu" onClick={() => setProfileOpen(value => !value)} aria-expanded={profileOpen}><span className="user-avatar">{(displayName[0] || 'U').toUpperCase()}</span><span className="user-details"><b>{displayName}</b><small>{mode === 'preview' ? 'Preview mode' : profile?.roles?.join(', ') || 'Loading profile'}</small></span><span className="user-menu-chevron">⌃</span></button>{profileOpen && <div className="profile-popover"><b>{displayName}</b><span>{profile?.username || 'Illustrative workspace'}</span><span>{profile?.roles?.join(', ') || (mode === 'preview' ? 'Demo only' : 'Role unavailable')}</span><button onClick={onLogout}><Icon name="logout" size={15} /> {mode === 'preview' ? 'Exit preview' : 'Sign out'}</button></div>}</div>
    </aside>
    <main className="main-area">
      <header className="topbar">
        <button className="mobile-menu-button" aria-label={menuOpen ? 'Close navigation' : 'Open navigation'} aria-expanded={menuOpen} aria-controls="app-sidebar" onClick={() => setMenuOpen(value => !value)}><Icon name="menu" /></button>
        <div className="breadcrumbs"><span>PrivacyGuard</span><b>/</b><strong>{title}</strong></div>
        <div className="topbar-actions"><button className="global-search" onClick={() => setSearchOpen(true)}><Icon name="search" size={15} /><span>Search pages and queries</span><kbd>⌘ K</kbd></button><div className={`connection-pill ${apiStatus}`} title={apiStatus === 'online' ? 'GET /health responded successfully; database is available' : apiStatus === 'degraded' ? 'API process responds, but its database is unavailable' : apiStatus === 'offline' ? 'API request failed or timed out' : 'Checking backend health'}><span />{apiStatus === 'checking' ? 'Connecting' : apiStatus === 'online' ? 'API connected' : apiStatus === 'degraded' ? 'Database unavailable' : 'API offline'}</div><span className="topbar-divider" /><span className="environment-chip">LOCAL</span><span className="topbar-user">{displayName}</span><span className="topbar-avatar">{(displayName[0] || 'U').toUpperCase()}</span></div>
      </header>
      <div className="page-content">
        <div className={`source-banner ${source.className}`}><span className="source-marker" /> <b>{source.label}</b><span>{source.description}</span></div>
        {apiStatus === 'offline' && mode !== 'preview' && <div className="offline-banner" role="status"><span className="alert-dot" /> The API is unreachable. The workspace stays available; live actions show an error instead of blocking the interface.{onRetry && <button type="button" onClick={onRetry}>Retry connection</button>}</div>}
        {apiStatus === 'degraded' && mode !== 'preview' && <div className="offline-banner" role="status"><span className="alert-dot" /> FastAPI is online but its database is unavailable. Authentication and database-backed operations may fail; the workspace stays available.{onRetry && <button type="button" onClick={onRetry}>Check again</button>}</div>}
        {children}
        <footer className="page-footer"><span>PrivacyGuard · Information Security Research Prototype</span><span>Policy risk is not a formal Differential Privacy guarantee.</span></footer>
      </div>
    </main>
    {menuOpen && <button className="mobile-scrim" aria-label="Close navigation" onClick={() => setMenuOpen(false)} />}
    {searchOpen && <GlobalSearch onClose={() => setSearchOpen(false)} onNavigate={navigate} />}
  </div>
}

function sourceInfo(mode: AppMode, page: PageId) {
  if (mode === 'preview') return {
    label: 'DEMO MODE', className: 'preview-source',
    description: 'Illustrative data only · No protected API calls',
  }
  const liveSources: Partial<Record<PageId, { label: string; description: string }>> = {
    overview: {
      label: 'LIVE PERSISTED DATA',
      description: 'Dashboard metrics and activity come from persisted backend records · dataset contents may be synthetic',
    },
    datasets: {
      label: 'LIVE DATASET REGISTRY',
      description: 'Dataset metadata and access grants are persisted · Synthetic Employees contains generated records',
    },
    query: {
      label: 'LIVE PROTECTED QUERY API',
      description: 'SQL analysis and protected COUNT/SUM use the connected API · released results are privacy-protected',
    },
    history: {
      label: 'LIVE PERSISTED HISTORY',
      description: 'Request and release metadata are loaded from backend records · raw aggregate values are not shown',
    },
    budgets: {
      label: 'LIVE PRIVACY ACCOUNTING',
      description: 'Balances and ledger entries come from shared dataset accounting records',
    },
    audit: {
      label: 'LIVE PERSISTED AUDIT',
      description: 'Permitted audit events are loaded from backend records',
    },
  }
  const live = liveSources[page]
  if (live) return { ...live, className: 'live-source' }
  if (page === 'experiments') return {
    label: 'PERSISTED SYNTHETIC EXPERIMENTS', className: 'live-source',
    description: 'Synthetic workloads and per-user saved results are persisted by the backend · registered datasets are not read',
  }
  if (page === 'comparative-results') return {
    label: 'PERSISTED RESEARCH RESULTS', className: 'live-source',
    description: 'Owner-scoped synthetic benchmark records are retrieved from the backend · published literature is shown separately',
  }
  return {
    label: 'ILLUSTRATIVE / PLANNED', className: 'sample-source',
    description: 'This module contains labelled demonstrations or planned capabilities; see its page for implementation status',
  }
}

function GlobalSearch({ onClose, onNavigate }: { onClose: () => void; onNavigate: (page: PageId) => void }) {
  const [query, setQuery] = useState('')
  const normalized = query.trim().toLowerCase()
  const pages = useMemo(() => navigation.filter(item => !normalized || `${item.label} ${item.section}`.toLowerCase().includes(normalized)), [normalized])
  const queries = useMemo(() => demoQueries.filter(item => !normalized || `${item.id} ${item.user} ${item.type} ${item.table} ${item.sql}`.toLowerCase().includes(normalized)).slice(0, 4), [normalized])
  return <div className="search-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}><section className="search-dialog" role="dialog" aria-modal="true" aria-label="Global search"><div className="search-field"><Icon name="search" /><input autoFocus aria-label="Search pages and demo queries" placeholder="Search pages, users, query IDs…" value={query} onChange={event => setQuery(event.target.value)} /><kbd>ESC</kbd></div><div className="search-results">{pages.length > 0 && <><div className="search-section-label">PAGES</div>{pages.map(item => <button key={item.id} onClick={() => onNavigate(item.id)}><Icon name={item.icon} size={16} /><span>{item.label}</span><small>{item.section}</small><Icon name="chevron" size={14} /></button>)}</>}{queries.length > 0 && <><div className="search-section-label">DEMO QUERIES</div>{queries.map(item => <button key={item.id} onClick={() => onNavigate('history')}><Icon name="terminal" size={16} /><span>{item.id} · {item.type} {item.table}</span><small>{item.user}</small><Icon name="chevron" size={14} /></button>)}</>}{pages.length === 0 && queries.length === 0 && <div className="search-no-results">No matching pages or demo queries.</div>}</div><div className="search-footer">Navigate with the results · Demo query records are illustrative</div></section></div>
}
