import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import ErrorBoundary from './ErrorBoundary'
import OfflineBanner from './OfflineBanner'
import TextSizeControl from './TextSizeControl'
import TouchTitles from './TouchTitles'
import { warmDemoBackend } from './api'
import { installDiagnostics } from './diagnostics'
import { logDebug } from './debugBus'
import { installWebkitNavigationGuard } from './webkitNavigationGuard'
import './i18n'
import './index.css'

// Before anything else, including warmDemoBackend below — installing the
// fetch wrapper after the first request would miss it, and the very first
// request is the one most likely to reveal a deployment-level problem
// (CSP, CORS, DNS). Silent: everything lands in debugBus's ring buffer,
// which nothing reads until the DebugOverlay is opened. See diagnostics.ts.
installDiagnostics()

// Same guard as the app (homeschool-tutor/src/utils/webkitNavigationGuard.ts,
// #861): on WebKit 26.0 a pushState the engine fails to record makes a later
// second reload crash the page. The demo does not call pushState today, so
// this is preventive; it does nothing on any other engine.
installWebkitNavigationGuard(window, logDebug)

// Start waking the (possibly sleeping) demo backend before React even
// mounts — see warmDemoBackend's own comment.
warmDemoBackend()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <OfflineBanner />
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
    <TextSizeControl />
    <TouchTitles />
  </StrictMode>
)
