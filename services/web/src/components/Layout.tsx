import { useEffect, useMemo, useState } from 'react'
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom'
import { ClusterSwitcher } from './ClusterSwitcher'
import { useInstance, useLogout, useMe, useServices } from '../lib/hooks'
import { useTheme } from '../lib/theme'
import {
  Bars,
  Bolt,
  Book,
  Globe,
  Grid,
  Lines,
  Moon,
  Search,
  Sliders,
  Sun,
  Terminal,
} from './Icons'
import { Spinner, cx } from './ui'

export function Logo({ size = 26, label = true }: { size?: number; label?: boolean }) {
  return (
    <span className="flex items-center gap-2.5">
      <span
        className="grid flex-none place-items-center rounded-[7px] bg-accent text-accent-ink"
        style={{ width: size, height: size }}
      >
        <Bolt size={size * 0.58} />
      </span>
      {label ? <span className="text-[17px] font-bold tracking-[-0.02em]">Cubicle</span> : null}
    </span>
  )
}

export function ThemeToggle({ className }: { className?: string }) {
  const { theme, toggle } = useTheme()
  return (
    <button
      type="button"
      onClick={toggle}
      title={theme === 'dark' ? 'Switch to light' : 'Switch to dark'}
      aria-label="Toggle theme"
      className={cx(
        'grid h-8 w-8 place-items-center rounded-lg border border-line bg-transparent text-ink-2 transition hover:bg-panel-2 hover:text-ink',
        className,
      )}
    >
      {theme === 'dark' ? <Moon size={14} /> : <Sun size={14} />}
    </button>
  )
}

const NAV = [
  { to: '/console', end: true, label: 'Overview', icon: Grid },
  { to: '/console/live', end: false, label: 'Live activity', icon: Bolt },
  { to: '/console/playground', end: false, label: 'Function playground', icon: Terminal },
  { to: '/console/env', end: false, label: 'Global env', icon: Globe },
  { to: '/console/logs', end: false, label: 'Logs & monitoring', icon: Lines },
  { to: '/console/cluster', end: false, label: 'Cluster & metering', icon: Bars },
  { to: '/console/settings', end: false, label: 'Settings', icon: Sliders },
] as const

const NAV_ITEM =
  'flex h-[38px] w-full items-center gap-2.5 rounded-[9px] border-0 px-2.5 text-left text-[13.5px] font-medium transition'

function navClass({ isActive }: { isActive: boolean }) {
  return cx(
    NAV_ITEM,
    isActive
      ? 'bg-accent-soft font-semibold text-ink'
      : 'bg-transparent text-ink-2 hover:bg-panel-2',
  )
}

export function ConsoleLayout({ children }: { children: React.ReactNode }) {
  const { data: me } = useMe()
  const { data: instance } = useInstance()
  const { data: services } = useServices()
  const logout = useLogout()
  const navigate = useNavigate()
  const location = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)

  const postgres = services?.find((s) => s.kind === 'postgres')
  const redis = services?.find((s) => s.kind === 'redis')

  const crumb = useMemo(() => {
    const path = location.pathname.replace(/^\/console\/?/, '')
    if (!path) return 'Overview'
    const [head, tail] = path.split('/')
    const names: Record<string, string> = {
      live: 'Live activity',
      env: 'Global env',
      logs: 'Logs',
      cluster: 'Cluster',
      settings: 'Settings',
      playground: 'Playground',
      functions: 'Function',
      services: 'Data services',
    }
    if (head === 'playground' && tail) {
      return path.split('/').length > 2 ? 'Playground / function' : 'Playground / namespace'
    }
    return names[head] ?? 'Overview'
  }, [location.pathname])

  useEffect(() => setMenuOpen(false), [location.pathname])

  return (
    <div className="flex min-h-screen bg-bg text-ink">
      <aside className="sticky top-0 hidden h-screen w-[236px] flex-none flex-col border-r border-line bg-panel lg:flex">
        <div className="px-4 pt-[18px] pb-3.5">
          <Link to="/console" className="flex items-center gap-2.5">
            <Logo size={26} />
          </Link>
        </div>

        <ClusterSwitcher />

        <nav className="flex flex-1 flex-col gap-[3px] px-3">
          {NAV.map(({ to, end, label, icon: Icon }) => (
            <NavLink key={to} to={to} end={end} className={navClass}>
              <Icon size={17} />
              {label}
            </NavLink>
          ))}

          <div className="px-2.5 pt-3.5 pb-1 text-[11px] font-bold tracking-[0.06em] text-ink-3 uppercase">
            Data services
          </div>
          <NavLink to="/console/services/postgres" className={navClass}>
            <ServiceDot status={postgres?.status} />
            PostgreSQL
          </NavLink>
          <NavLink to="/console/services/redis" className={navClass}>
            <ServiceDot status={redis?.status} />
            Redis
          </NavLink>

          <div className="mt-auto pb-2.5">
            <a
              href="/docs"
              className={cx(NAV_ITEM, 'bg-transparent text-ink-2 hover:bg-panel-2')}
            >
              <Book size={17} />
              Docs
            </a>
          </div>
        </nav>

        <div className="border-t border-line p-3">
          <div className="flex items-center gap-2.5 px-2 py-1.5">
            <span className="grid h-7 w-7 flex-none place-items-center rounded-full bg-panel-3 text-xs font-semibold text-ink-2">
              {me?.initials ?? '··'}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[12.5px] leading-tight font-semibold">
                {me?.name ?? 'Signed out'}
              </span>
              <span className="block truncate text-[11px] text-ink-3">{me?.email ?? ''}</span>
            </span>
            <ThemeToggle className="h-7 w-7" />
          </div>
          <button
            type="button"
            onClick={() => logout.mutate(undefined, { onSuccess: () => navigate('/login') })}
            className="mt-1 w-full rounded-lg px-2 py-1.5 text-left text-[12px] text-ink-3 transition hover:bg-panel-2 hover:text-ink"
          >
            {logout.isPending ? <Spinner size={12} /> : 'Sign out'}
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 flex h-[60px] flex-none items-center gap-3.5 border-b border-line px-5 backdrop-blur-[10px] sm:px-6 [background:color-mix(in_srgb,var(--bg)_86%,transparent)]">
          <button
            type="button"
            className="grid h-8 w-8 place-items-center rounded-lg border border-line lg:hidden"
            onClick={() => setMenuOpen((open) => !open)}
            aria-label="Open navigation"
          >
            <Lines size={16} />
          </button>

          <div className="flex items-center gap-2 text-sm text-ink-2">
            <Link to="/console" className="flex-shrink-0 font-mono whitespace-nowrap">
              {instance?.cluster_name ?? 'cubicle'}
            </Link>
            <span className="text-ink-3">/</span>
            <span className="flex-shrink-0 font-semibold whitespace-nowrap text-ink">
              {crumb}
            </span>
          </div>

          <div className="ml-4 hidden max-w-[420px] flex-1 md:block">
            <div className="flex h-9 items-center gap-2.5 rounded-[9px] border border-line bg-panel px-3 text-ink-3">
              <Search size={15} />
              <span className="text-[13.5px] whitespace-nowrap">Search functions, logs…</span>
              <span className="ml-auto rounded-[5px] border border-line px-1.5 py-px font-mono text-[11px]">
                ⌘K
              </span>
            </div>
          </div>
        </header>

        {menuOpen ? (
          <nav className="flex flex-col gap-1 border-b border-line bg-panel px-3 py-3 lg:hidden">
            {NAV.map(({ to, end, label, icon: Icon }) => (
              <NavLink key={to} to={to} end={end} className={navClass}>
                <Icon size={17} />
                {label}
              </NavLink>
            ))}
            <NavLink to="/console/services/postgres" className={navClass}>
              <ServiceDot status={postgres?.status} />
              PostgreSQL
            </NavLink>
            <NavLink to="/console/services/redis" className={navClass}>
              <ServiceDot status={redis?.status} />
              Redis
            </NavLink>
          </nav>
        ) : null}

        <main className="flex-1 overflow-auto">{children}</main>
      </div>
    </div>
  )
}

function ServiceDot({ status }: { status?: string }) {
  const colour =
    status === 'running'
      ? 'var(--ok)'
      : status === 'stopped'
        ? 'var(--text-3)'
        : 'var(--border-strong)'
  return (
    <span
      className="ml-[5px] inline-block h-[7px] w-[7px] flex-none rounded-full"
      style={{ background: colour }}
    />
  )
}
