import React from 'react'
import ReactDOM from 'react-dom/client'
import { Capacitor } from '@capacitor/core'
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

// Native RC1 clients must never load remotely updated frontend assets.
// Web/PWA behavior is unchanged.
if (!Capacitor.isNativePlatform() && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {
      // SW registration is best-effort — don't break the app
    })
  })
}
