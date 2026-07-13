import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import ErrorBoundary from './ErrorBoundary'
import OfflineBanner from './OfflineBanner'
import TextSizeControl from './TextSizeControl'
import './index.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <OfflineBanner />
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
    <TextSizeControl />
  </StrictMode>
)
