import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import ErrorBoundary from './ErrorBoundary'
import OfflineBanner from './OfflineBanner'
import TextSizeControl from './TextSizeControl'
import { warmDemoBackend } from './api'
import { installDiagnostics } from './diagnostics'
import './i18n'
import './index.css'

// Before anything else, including warmDemoBackend below — installing the
// fetch wrapper after the first request would miss it, and the very first
// request is the one most likely to reveal a deployment-level problem
// (CSP, CORS, DNS). Silent: everything lands in debugBus's ring buffer,
// which nothing reads until the DebugOverlay is opened. See diagnostics.ts.
installDiagnostics()

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
  </StrictMode>
)
