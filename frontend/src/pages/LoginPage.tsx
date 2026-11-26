import { useState } from 'react'
import type { FormEvent } from 'react'
import { Icon } from '../components/Icon'
import type { ApiStatus } from '../types/app'

export function LoginPage({ apiStatus, onRetry, onLogin, onPreview }: {
  apiStatus: ApiStatus
  onRetry: () => void
  onLogin: (username: string, password: string) => Promise<void>
  onPreview: () => void
}) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setLoading(true)
    try { await onLogin(username.trim(), password) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Sign in failed. Please try again.') }
    finally { setLoading(false) }
  }

  return (
    <main className="login-page">
      <section className="login-story">
        <div className="login-brand"><span className="brand-icon"><Icon name="shield" size={21} /></span><span className="brand-name"><span>PRIVACY</span><span className="brand-light">GUARD</span></span></div>
        <div className="story-copy">
          <div className="story-eyebrow"><span className="eyebrow-line" /> PRIVACY CONTROL PLANE</div>
          <h1>Intelligent Privacy.<br /><span>Controlled Access.</span></h1>
          <p>Query-History-Aware Adaptive Differential Privacy Middleware for Multi-Level Enterprise Databases.</p>
          <div className="story-points">
            <div><span><Icon name="check" size={15} /></span><p><b>Context-aware controls</b><small>Designed to consider query patterns over time</small></p></div>
            <div><span><Icon name="check" size={15} /></span><p><b>Explainable decisions</b><small>Surface policy signals alongside each request</small></p></div>
            <div><span><Icon name="check" size={15} /></span><p><b>Research-ready workspace</b><small>Built for controlled evaluation with synthetic data</small></p></div>
          </div>
        </div>
        <div className="story-footer"><span>CONTROLLED RESEARCH PROTOTYPE</span><span>v0.1</span></div>
      </section>
      <section className="login-panel">
        <div className="login-form-wrap">
          <div className="mobile-brand"><span className="brand-icon"><Icon name="shield" size={21} /></span><span className="brand-name"><span>PRIVACY</span><span className="brand-light">GUARD</span></span></div>
          <div className="form-heading"><div className="form-kicker">WELCOME BACK</div><h2>Sign in to your workspace</h2><p>Use a seeded research account. Its password is set locally when the accounts are seeded.</p></div>
          <div className={`login-connection ${apiStatus}`} role="status" aria-live="polite"><span className="connection-indicator" />{apiStatus === 'checking' ? 'Checking backend connection…' : apiStatus === 'online' ? 'Backend online · authentication available' : apiStatus === 'degraded' ? 'Backend online · database unavailable; sign-in will not work yet' : 'Backend unavailable · sign-in requires a connection'}{apiStatus === 'offline' && <button type="button" onClick={onRetry}>Retry</button>}{apiStatus === 'degraded' && <button type="button" onClick={onRetry}>Check again</button>}</div>
          {apiStatus === 'offline' && <div className="inline-alert" role="note">The API could not be reached. Check that FastAPI is running at the configured API URL, then retry. Preview remains available separately.</div>}
          {apiStatus === 'degraded' && <div className="inline-alert" role="note">FastAPI is responding, but its database check failed. Authentication requires database access; preview remains available.</div>}
          {error && <div className="inline-alert error" role="alert">{error}</div>}
          <form onSubmit={submit}>
            <label htmlFor="username">Username</label>
            <input id="username" name="username" autoComplete="username" placeholder="Enter your username" value={username} onChange={e => setUsername(e.target.value)} required />
            <div className="password-label"><label htmlFor="password">Password</label></div>
            <div className="password-input"><input id="password" name="password" type={showPassword ? 'text' : 'password'} autoComplete="current-password" placeholder="Enter your password" value={password} onChange={e => setPassword(e.target.value)} required /><button type="button" className="password-toggle" onClick={() => setShowPassword(value => !value)} aria-label={showPassword ? 'Hide password' : 'Show password'}>{showPassword ? 'Hide' : 'Show'}</button></div>
            <button className="primary-button sign-in-button" disabled={loading} type="submit">{loading ? <><span className="spinner" /> Signing in…</> : <>Sign in <span>→</span></>}</button>
          </form>
          <div className="login-divider"><span /><small>OR</small><span /></div>
          <button className="preview-button" type="button" onClick={onPreview}>Explore dashboard preview <Icon name="arrow" size={15} /></button>
          <p className="preview-note">Preview uses labelled illustrative data. It does not authenticate or call protected APIs.</p>
          <div className="login-security"><Icon name="lock" size={15} /><span>Identity and permissions are verified by the connected middleware API.</span></div>
        </div>
        <div className="login-copyright">PrivacyGuard · Information Security Research Prototype</div>
      </section>
    </main>
  )
}
