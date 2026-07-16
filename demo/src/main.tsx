import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import ErrorBoundary from './ErrorBoundary'
import OfflineBanner from './OfflineBanner'
import TextSizeControl from './TextSizeControl'
import { warmDemoBackend } from './api'
import './i18n'
import './index.css'

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
