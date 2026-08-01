import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom'
import { ClusterSwitcher } from './ClusterSwitcher'
import { CommandPalette } from './CommandPalette'
import { useInstance, useLogout, useMe, useServices, useUpdateStatus } from '../lib/hooks'
import { useTheme } from '../lib/theme'
import {
  Bars,
  Bolt,
  Book,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Database,
  Globe,
  Grid,
  Help,
  Layers,
  Lines,
  Moon,
  Power,
  Search,
  Sliders,
  Sun,
  Terminal,
  X,
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

/** Placeholder — matches the theme toggle beside it, and does nothing yet. */
export function HelpButton({ className }: { className?: string }) {
  return (
    <button
      type="button"
      title="Help"
      aria-label="Help"
      className={cx(
        'grid h-8 w-8 place-items-center rounded-lg border border-line bg-transparent text-ink-2 transition hover:bg-panel-2 hover:text-ink',
        className,
      )}
    >
      <Help size={14} />
    </button>
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

const SIDEBAR_KEY = 'cubicle-sidebar-collapsed'

/**
 * Whether the sidebar is a rail rather than a full column.
 *
 * Kept in localStorage: an operator who collapsed it wants it collapsed on the
 * next page too, and the flash of a wide sidebar on every load would be worse
 * than the preference itself.
 */
function useCollapsed(): [boolean, () => void] {
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(SIDEBAR_KEY) === '1'
    } catch {
      return false
    }
  })
  const toggle = () =>
    setCollapsed((value) => {
      const next = !value
      try {
        localStorage.setItem(SIDEBAR_KEY, next ? '1' : '0')
      } catch {
        /* private browsing — the choice just will not persist */
      }
      return next
    })
  return [collapsed, toggle]
}

export function ConsoleLayout({ children }: { children: React.ReactNode }) {
  const { data: me } = useMe()
  const { data: instance } = useInstance()
  const { data: services } = useServices()
  const logout = useLogout()
  const navigate = useNavigate()
  const location = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)
  const [collapsed, toggleCollapsed] = useCollapsed()
  const [searchOpen, setSearchOpen] = useState(false)

  // ⌘K on a Mac, Ctrl+K everywhere else — and the label has to match, or the
  // hint in the bar is wrong for half the people reading it.
  const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)
  const shortcut = isMac ? '⌘K' : 'Ctrl K'

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() === 'k' && (event.metaKey || event.ctrlKey)) {
        event.preventDefault()
        setSearchOpen((value) => !value)
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

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
      <aside
        className={cx(
          'sticky top-0 hidden h-screen flex-none flex-col border-r border-line bg-panel transition-[width] duration-200 ease-out lg:flex',
          collapsed ? 'w-[64px]' : 'w-[236px]',
        )}
      >
        {/* The toggle sits with the logo in both states — a control that moves
            when you use it is a control you have to hunt for. */}
        <div
          className={cx(
            'pt-[18px] pb-3.5',
            collapsed
              ? 'flex flex-col items-center gap-1.5 px-2'
              : 'flex items-center gap-2 px-4',
          )}
        >
          <Link to="/console" className="flex items-center gap-2.5">
            <Logo size={26} label={!collapsed} />
          </Link>
          <button
            type="button"
            onClick={toggleCollapsed}
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            aria-expanded={!collapsed}
            className={cx(
              'grid h-7 w-7 place-items-center rounded-lg text-ink-3 transition hover:bg-panel-2 hover:text-ink',
              collapsed ? '' : 'ml-auto',
            )}
          >
            {collapsed ? <ChevronRight size={15} /> : <ChevronLeft size={15} />}
          </button>
        </div>

        <ClusterSwitcher collapsed={collapsed} />

        <nav className={cx('flex flex-1 flex-col gap-[3px]', collapsed ? 'px-2.5' : 'px-3')}>
          {NAV.map(({ to, end, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              title={collapsed ? label : undefined}
              className={(state) => cx(navClass(state), collapsed && 'justify-center px-0')}
            >
              <Icon size={17} />
              <span className={cx(collapsed && 'hidden')}>{label}</span>
            </NavLink>
          ))}

          {/* The rail has no room for a heading, and shrinking the type to
              nothing is unreliable — two font-size utilities on one element
              are resolved by stylesheet order, not class order. A rule says
              the same thing in 64px. */}
          {collapsed ? (
            <div className="mx-1 mt-3 mb-1 border-t border-line" />
          ) : (
            <div className="px-2.5 pt-3.5 pb-1 text-[11px] font-bold tracking-[0.06em] text-ink-3 uppercase">
              Data services
            </div>
          )}
          <ServiceLink
            to="/console/services/postgres"
            label="PostgreSQL"
            icon={Database}
            status={postgres?.status}
            collapsed={collapsed}
          />
          <ServiceLink
            to="/console/services/redis"
            label="Redis"
            icon={Layers}
            status={redis?.status}
            collapsed={collapsed}
          />

          <div className="mt-auto pb-2.5">
            <UpdateNudge collapsed={collapsed} />
            <a
              href="/docs"
              title={collapsed ? 'Docs' : undefined}
              className={cx(
                NAV_ITEM,
                'bg-transparent text-ink-2 hover:bg-panel-2',
                collapsed && 'justify-center px-0',
              )}
            >
              <Book size={17} />
              <span className={cx(collapsed && 'hidden')}>Docs</span>
            </a>
          </div>
        </nav>
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

          {/* The trail is desktop-only. On a phone the cluster name and the
              separator cost more width than they are worth, and the drawer
              already shows which page is current — so this is a plain title. */}
          <div className="flex min-w-0 items-center gap-2 text-sm text-ink-2">
            <Link
              to="/console"
              className="hidden flex-shrink-0 font-mono whitespace-nowrap sm:block"
            >
              {instance?.cluster_name ?? 'cubicle'}
            </Link>
            <span className="hidden text-ink-3 sm:block">/</span>
            <span className="truncate font-semibold text-ink">{crumb}</span>
          </div>

          <div className="ml-4 hidden max-w-[420px] flex-1 md:block">
            <button
              type="button"
              onClick={() => setSearchOpen(true)}
              className="flex h-9 w-full items-center gap-2.5 rounded-[9px] border border-line bg-panel px-3 text-ink-3 transition hover:border-line-strong hover:text-ink-2"
            >
              <Search size={15} />
              <span className="text-[13.5px] whitespace-nowrap">Search functions, logs…</span>
              <span className="ml-auto rounded-[5px] border border-line px-1.5 py-px font-mono text-[11px]">
                {shortcut}
              </span>
            </button>
          </div>

          {/* One `ml-auto`, not two. With both the search button and this group
              claiming it, the free space was split between them and neither
              ended up against the edge. */}
          <div className="ml-auto flex flex-none items-center gap-1.5 sm:gap-2">
            <button
              type="button"
              onClick={() => setSearchOpen(true)}
              aria-label="Search"
              className="grid h-8 w-8 place-items-center rounded-lg border border-line text-ink-2 transition hover:text-ink md:hidden"
            >
              <Search size={15} />
            </button>
            <HelpButton />
            <ThemeToggle />
            <AccountMenu
              me={me}
              onSignOut={() =>
                logout.mutate(undefined, { onSuccess: () => navigate('/login') })
              }
              signingOut={logout.isPending}
            />
          </div>
        </header>

        <MobileNav
          open={menuOpen}
          onClose={() => setMenuOpen(false)}
          postgres={postgres?.status}
          redis={redis?.status}
        />

        {/* Deliberately not `overflow-x-hidden`: clipping a row that is too
            wide puts its Delete button somewhere you cannot reach. Anything
            still too wide should scroll, and be fixed where it is defined. */}
        <main className="min-w-0 flex-1 overflow-auto">{children}</main>
      </div>

      <CommandPalette open={searchOpen} onClose={() => setSearchOpen(false)} />
    </div>
  )
}

/**
 * The same sidebar, as a drawer over the page.
 *
 * It used to be a block that pushed the page down when opened, which moved
 * whatever you were reading and left navigation and content fighting for the
 * same column. A drawer covers instead of displaces, so closing it puts you
 * back exactly where you were.
 *
 * Always mounted rather than conditionally rendered — a panel that only exists
 * while open cannot animate its way in.
 */
function MobileNav({
  open,
  onClose,
  postgres,
  redis,
}: {
  open: boolean
  onClose: () => void
  postgres?: string
  redis?: string
}) {
  // Escape closes it, and the page underneath must not scroll while a drawer
  // is over it — on iOS that scrolls the thing you cannot see.
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = previous
    }
  }, [open, onClose])

  return (
    <div className="lg:hidden" aria-hidden={!open}>
      <button
        type="button"
        tabIndex={-1}
        aria-label="Close navigation"
        onClick={onClose}
        className={cx(
          'fixed inset-0 z-40 bg-[color-mix(in_srgb,var(--bg)_45%,#000)] transition-opacity duration-200',
          open ? 'opacity-100' : 'pointer-events-none opacity-0',
        )}
      />

      <nav
        className={cx(
          'fixed inset-y-0 left-0 z-50 flex w-[272px] max-w-[85vw] flex-col border-r border-line bg-panel transition-transform duration-200 ease-out',
          open ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        <div className="flex h-[60px] flex-none items-center justify-between border-b border-line px-4">
          <Link to="/console" onClick={onClose}>
            <Logo size={24} />
          </Link>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close navigation"
            className="grid h-8 w-8 place-items-center rounded-lg text-ink-3 transition hover:bg-panel-2 hover:text-ink"
          >
            <X size={16} />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto py-2">
          <ClusterSwitcher collapsed={false} />

          <div className="flex flex-col gap-[3px] px-3">
            {NAV.map(({ to, end, label, icon: Icon }) => (
              <NavLink key={to} to={to} end={end} onClick={onClose} className={navClass}>
                <Icon size={17} />
                {label}
              </NavLink>
            ))}

            <div className="px-2.5 pt-3.5 pb-1 text-[11px] font-bold tracking-[0.06em] text-ink-3 uppercase">
              Data services
            </div>
            <ServiceLink
              to="/console/services/postgres"
              label="PostgreSQL"
              icon={Database}
              status={postgres}
              collapsed={false}
              onNavigate={onClose}
            />
            <ServiceLink
              to="/console/services/redis"
              label="Redis"
              icon={Layers}
              status={redis}
              collapsed={false}
              onNavigate={onClose}
            />
          </div>
        </div>

        <div className="flex-none border-t border-line px-3 py-2.5">
          <UpdateNudge collapsed={false} />
          <a
            href="/docs"
            className={cx(NAV_ITEM, 'bg-transparent text-ink-2 hover:bg-panel-2')}
          >
            <Book size={17} />
            Docs
          </a>
        </div>
      </nav>
    </div>
  )
}

/**
 * Identity and sign-out, in the header where the account controls of every
 * other console live. The sidebar keeps navigation and nothing else, which is
 * what lets it collapse to a 64px rail without losing anything.
 */
function AccountMenu({
  me,
  onSignOut,
  signingOut,
}: {
  me?: { name: string; email: string; initials: string; role?: string }
  onSignOut: () => void
  signingOut: boolean
}) {
  const [open, setOpen] = useState(false)
  const container = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const close = (event: MouseEvent) => {
      if (!container.current?.contains(event.target as Node)) setOpen(false)
    }
    const escape = (event: KeyboardEvent) => event.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', escape)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', escape)
    }
  }, [open])

  return (
    <div className="relative" ref={container}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="menu"
        aria-expanded={open}
        title={me?.email ?? 'Account'}
        className="flex h-8 items-center gap-2 rounded-lg border border-line pr-2 pl-1 transition hover:bg-panel-2"
      >
        <span className="grid h-6 w-6 flex-none place-items-center rounded-full bg-panel-3 text-[10.5px] font-semibold text-ink-2">
          {me?.initials ?? '··'}
        </span>
        <span className="hidden max-w-[120px] truncate text-[13px] text-ink-2 lg:block">
          {me?.name ?? 'Account'}
        </span>
        <ChevronDown size={13} className={cx('text-ink-3 transition', open && 'rotate-180')} />
      </button>

      {open ? (
        <div
          role="menu"
          className="animate-rise absolute right-0 top-full z-30 mt-1.5 w-[236px] overflow-hidden rounded-xl border border-line-strong bg-panel shadow-2xl"
        >
          <div className="border-b border-line px-3.5 py-3">
            <div className="truncate text-[13px] font-semibold">{me?.name ?? 'Signed out'}</div>
            <div className="truncate text-[11.5px] text-ink-3">{me?.email ?? ''}</div>
          </div>
          <button
            type="button"
            role="menuitem"
            onClick={onSignOut}
            className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left text-[13px] text-ink-2 transition hover:bg-panel-2 hover:text-err"
          >
            {signingOut ? <Spinner size={13} /> : <Power size={14} />}
            Sign out
          </button>
        </div>
      ) : null}
    </div>
  )
}

/**
 * A data service in the nav.
 *
 * The icon says which service, matching the one on its own page, so the two
 * rows are told apart at a glance instead of by reading. Status stays as a
 * dot, because a coloured icon would read as decoration rather than state —
 * and in the rail it becomes a badge on the corner, where it is the only
 * thing that still fits.
 */
/**
 * A quiet pointer to Settings when the instance is behind its branch.
 *
 * Only the super admin can act on it, so only they are told. It reads the same
 * cached answer the Settings card does — this costs no extra request.
 */
function UpdateNudge({ collapsed }: { collapsed: boolean }) {
  const { data: me } = useMe()
  const { data: update } = useUpdateStatus(me?.role === 'owner')

  if (!update?.available) return null

  return (
    <Link
      to="/console/settings"
      title={collapsed ? 'Update available' : undefined}
      className={cx(
        NAV_ITEM,
        'bg-accent-soft text-ink hover:bg-accent-soft',
        collapsed && 'justify-center px-0',
      )}
    >
      <span className="relative flex h-[17px] w-[17px] items-center justify-center">
        <span className="h-1.5 w-1.5 rounded-full bg-accent" />
        <span className="absolute h-1.5 w-1.5 animate-ping rounded-full bg-accent" />
      </span>
      <span className={cx('font-semibold', collapsed && 'hidden')}>Update available</span>
    </Link>
  )
}

function ServiceLink({
  to,
  label,
  icon: Icon,
  status,
  collapsed,
  onNavigate,
}: {
  to: string
  label: string
  icon: (props: { size?: number; className?: string }) => React.ReactElement
  status?: string
  collapsed: boolean
  /** Set in the drawer, so following a link also closes it. */
  onNavigate?: () => void
}) {
  const colour =
    status === 'running'
      ? 'var(--ok)'
      : status === 'stopped'
        ? 'var(--text-3)'
        : 'var(--border-strong)'
  return (
    <NavLink
      to={to}
      title={collapsed ? `${label} — ${status ?? 'not created'}` : undefined}
      onClick={onNavigate}
      className={(state) => cx(navClass(state), collapsed && 'justify-center px-0')}
    >
      <span className="relative flex-none">
        <Icon size={17} />
        {collapsed ? (
          <span
            className="absolute -right-[3px] -bottom-[3px] h-[7px] w-[7px] rounded-full ring-2 ring-panel"
            style={{ background: colour }}
          />
        ) : null}
      </span>
      <span className={cx('flex-1', collapsed && 'hidden')}>{label}</span>
      {collapsed ? null : (
        <span
          className="h-[7px] w-[7px] flex-none rounded-full"
          style={{ background: colour }}
        />
      )}
    </NavLink>
  )
}
