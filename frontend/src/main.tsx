import React, { Component, type ErrorInfo, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './style.css'

class StartupBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() { return { failed: true } }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('PrivacyGuard failed to render', error, info.componentStack)
  }

  render() {
    if (this.state.failed) return <main className="startup-error"><h1>PrivacyGuard could not load</h1><p>Refresh the page to try again. If this continues, contact your workspace administrator.</p></main>
    return this.props.children
  }
}

const mountNode = document.getElementById('root')
if (mountNode) {
  createRoot(mountNode).render(<React.StrictMode><StartupBoundary><App /></StartupBoundary></React.StrictMode>)
} else {
  document.body.innerHTML = '<main class="startup-error"><h1>PrivacyGuard could not load</h1><p>The application root element is missing.</p></main>'
}
