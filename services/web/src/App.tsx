import { Suspense, lazy } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { ConsoleLayout } from './components/Layout'
import { Spinner } from './components/ui'
import { useMe, useSetupStatus } from './lib/hooks'

const Landing = lazy(() => import('./pages/Landing'))
const Docs = lazy(() => import('./pages/Docs'))
const Setup = lazy(() => import('./pages/Setup'))
const Login = lazy(() => import('./pages/Login'))
const Dashboard = lazy(() => import('./pages/Dashboard'))
const FunctionDetail = lazy(() => import('./pages/FunctionDetail'))
const Playground = lazy(() => import('./pages/Playground'))
const PlaygroundGroup = lazy(() => import('./pages/PlaygroundGroup'))
const GlobalEnv = lazy(() => import('./pages/GlobalEnv'))
const Logs = lazy(() => import('./pages/Logs'))
const Cluster = lazy(() => import('./pages/Cluster'))
const DataService = lazy(() => import('./pages/DataService'))
const Settings = lazy(() => import('./pages/Settings'))

function Loading() {
  return (
    <div className="grid min-h-screen place-items-center text-ink-3">
      <Spinner size={22} />
    </div>
  )
}

/** Console routes need a completed setup and a signed-in operator. */
function Guarded({ children }: { children: React.ReactNode }) {
  const location = useLocation()
  const { data: status, isLoading: statusLoading } = useSetupStatus()
  const { data: me, isLoading: meLoading, isError } = useMe({ enabled: status?.setup_complete })

  if (statusLoading) return <Loading />
  if (status && !status.setup_complete) return <Navigate to="/setup" replace />
  if (meLoading) return <Loading />
  if (isError || !me)
    return <Navigate to="/login" replace state={{ from: location.pathname }} />

  return <ConsoleLayout>{children}</ConsoleLayout>
}

export default function App() {
  return (
    <Suspense fallback={<Loading />}>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/docs" element={<Docs />} />
        <Route path="/docs/:slug" element={<Docs />} />
        <Route path="/setup" element={<Setup />} />
        <Route path="/login" element={<Login />} />

        <Route
          path="/console"
          element={
            <Guarded>
              <Dashboard />
            </Guarded>
          }
        />
        <Route
          path="/console/functions/:functionId"
          element={
            <Guarded>
              <FunctionDetail />
            </Guarded>
          }
        />
        <Route
          path="/console/playground"
          element={
            <Guarded>
              <Playground />
            </Guarded>
          }
        />
        <Route
          path="/console/playground/:groupId"
          element={
            <Guarded>
              <PlaygroundGroup />
            </Guarded>
          }
        />
        <Route
          path="/console/env"
          element={
            <Guarded>
              <GlobalEnv />
            </Guarded>
          }
        />
        <Route
          path="/console/logs"
          element={
            <Guarded>
              <Logs />
            </Guarded>
          }
        />
        <Route
          path="/console/cluster"
          element={
            <Guarded>
              <Cluster />
            </Guarded>
          }
        />
        <Route
          path="/console/services/:kind"
          element={
            <Guarded>
              <DataService />
            </Guarded>
          }
        />
        <Route
          path="/console/settings"
          element={
            <Guarded>
              <Settings />
            </Guarded>
          }
        />

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  )
}
