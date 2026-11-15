import React from 'react'
import ReactDOM from 'react-dom/client'
import { Capacitor } from '@capacitor/core'
import App from './App'
import { installDiagnostics } from './hooks/diagnostics'
import { retireServiceWorker } from './utils/serviceWorker'
import { reloadOnceForNewRelease } from './utils/staleBuild'
import { logDebug } from './hooks/debugBus'
import './index.css'
import './i18n'

// Before React mounts, so the fetch wrapper is in place for the very first
// request (token validation on load) — the one most likely to expose a
// deployment-level problem. Silent: everything lands in debugBus's ring
// buffer, which nothing reads until the DebugOverlay is opened from the
// session header. See hooks/diagnostics.ts.
installDiagnostics()

// Vite reports a page file that failed to preload here, before the import
// itself throws. A tab still running the previous release after an update hits
// exactly this; reloading once fetches the new one (utils/staleBuild.ts). If it
// already reloaded moments ago, the import throws as usual and the error
// screen takes over.
window.addEventListener('vite:preloadError', (event) => {
  logDebug('PAGE FILE FAILED TO PRELOAD; reloading once for a new release')
  if (reloadOnceForNewRelease()) event.preventDefault()
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)

// Bede registers no service worker. An older version did, and could leave a
// tablet running a stale release; this removes it and its caches. Nothing is
// reloaded, so an open lesson is never interrupted. Native RC1 clients never
// registered one, so they have nothing to retire. See utils/serviceWorker.ts
// and docs/RELIABILITY.md.
if (!Capacitor.isNativePlatform()) {
  window.addEventListener('load', () => { void retireServiceWorker() })
}
