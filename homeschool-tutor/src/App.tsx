import { Suspense, lazy, useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { BookOpen } from 'lucide-react'
import AppShell from './guards/AppShell'
import ErrorBoundary from './components/ErrorBoundary'
import OfflineBanner from './components/OfflineBanner'
import Login from './pages/Login'
import { useSessionStore } from './store/sessionStore'

// Login is eager — it's the universal entry point for every user, parent and
// child alike. Everything past it is route-split so a child's tablet never
// downloads the parent-only setup/dashboard/progress/sandbox screens before
// reaching /session.
const ParentSetup = lazy(() => import('./pages/ParentSetup'))
const PodDashboard = lazy(() => import('./pages/PodDashboard'))
const Progress = lazy(() => import('./pages/Progress'))
const Sandbox = lazy(() => import('./pages/Sandbox'))
const TutorSession = lazy(() => import('./pages/TutorSession'))

function RouteFallback() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-parchment-100 via-sage-50 to-faith-100 flex items-center justify-center">
      <div className="text-center">
        <div className="inline-flex items-center justify-center w-16 h-16 bg-sage-100 rounded-2xl mb-4 animate-pulse-soft">
          <BookOpen size={32} className="text-sage-600" />
        </div>
        <p className="text-sage-600 font-display text-lg font-semibold">Bede</p>
      </div>
    </div>
  )
}

function GlobalAuthInterceptor() {
  const navigate = useNavigate()
  const logout = useSessionStore((s) => s.logout)

  useEffect(() => {
    const originalFetch = window.fetch.bind(window)

    window.fetch = async (...args) => {
      const response = await originalFetch(...args)
      if (response.status === 401) {
        const url = typeof args[0] === 'string' ? args[0] : (args[0] as Request).url
        if (url.startsWith('/api/') || url.includes(window.location.host)) {
          logout()
          navigate('/', { replace: true })
        }
      }
      return response
    }

    return () => {
      window.fetch = originalFetch
    }
  }, [logout, navigate])

  return null
}

function RequireAuth({
  children,
  allowedRole,
}: {
  children: React.ReactNode
  allowedRole?: 'parent' | 'child'
}) {
  const { token, role } = useSessionStore()
  const location = useLocation()

  if (!token) {
    // Preserve the full path + query so student URLs survive the login redirect
    const returnTo = encodeURIComponent(location.pathname + location.search)
    return <Navigate to={`/?returnTo=${returnTo}`} replace />
  }
  if (allowedRole && role !== allowedRole) {
    return <Navigate to={role === 'parent' ? '/setup' : '/session'} replace />
  }
  return <>{children}</>
}

export default function App() {
  return (
    <BrowserRouter>
      <OfflineBanner />
      <ErrorBoundary>
        <AppShell>
          <GlobalAuthInterceptor />
          <Suspense fallback={<RouteFallback />}>
            <Routes>
              <Route path="/" element={<Login />} />
              <Route
                path="/setup"
                element={
                  <RequireAuth allowedRole="parent">
                    <ParentSetup />
                  </RequireAuth>
                }
              />
              <Route
                path="/pod"
                element={
                  <RequireAuth allowedRole="parent">
                    <PodDashboard />
                  </RequireAuth>
                }
              />
              <Route
                path="/progress"
                element={
                  <RequireAuth allowedRole="parent">
                    <Progress />
                  </RequireAuth>
                }
              />
              <Route
                path="/session"
                element={
                  <RequireAuth>
                    <TutorSession />
                  </RequireAuth>
                }
              />
              <Route
                path="/sandbox"
                element={
                  <RequireAuth allowedRole="parent">
                    <Sandbox />
                  </RequireAuth>
                }
              />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
        </AppShell>
      </ErrorBoundary>
    </BrowserRouter>
  )
}
