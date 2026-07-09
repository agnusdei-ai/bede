import { useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import AppShell from './guards/AppShell'
import Login from './pages/Login'
import ParentSetup from './pages/ParentSetup'
import PodDashboard from './pages/PodDashboard'
import Progress from './pages/Progress'
import TutorSession from './pages/TutorSession'
import { useSessionStore } from './store/sessionStore'

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
      <AppShell>
        <GlobalAuthInterceptor />
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
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AppShell>
    </BrowserRouter>
  )
}
