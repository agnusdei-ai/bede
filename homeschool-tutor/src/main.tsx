import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { installDiagnostics } from './hooks/diagnostics'
import './index.css'
import './i18n'

// Before React mounts, so the fetch wrapper is in place for the very first
// request (token validation on load) — the one most likely to expose a
// deployment-level problem. Silent: everything lands in debugBus's ring
// buffer, which nothing reads until the DebugOverlay is opened from the
// session header. See hooks/diagnostics.ts.
installDiagnostics()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {
      // SW registration is best-effort — don't break the app
    })
  })
}
