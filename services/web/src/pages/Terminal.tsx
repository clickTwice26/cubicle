import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Terminal as XTerm } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { ChevronDown, Pencil, Plus, Shield, X } from '../components/Icons'
import {
  Badge,
  Button,
  Card,
  ConfirmButton,
  EmptyState,
  PAGE,
  PageHeader,
  Select,
  Skeleton,
  StatusDot,
  cx,
  useToast,
} from '../components/ui'
import { useMe, useNodes } from '../lib/hooks'
import {
  TerminalSocket,
  useCreateTerminalSession,
  useEndTerminalSession,
  useRenameTerminalSession,
  useSetTerminalEnabled,
  useTerminalSessions,
  useTerminalStatus,
  type ShellStatus,
} from '../lib/terminal'
import { useTheme } from '../lib/theme'
import { relativeTime } from '../lib/format'

const TABS_KEY = (nodeId: string) => `cubicle-terminal-tabs:${nodeId}`

function readOpenTabs(nodeId: string): string[] {
  try {
    const raw = localStorage.getItem(TABS_KEY(nodeId))
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed.filter((v) => typeof v === 'string') : []
  } catch {
    return []
  }
}

function writeOpenTabs(nodeId: string, names: string[]): void {
  try {
    localStorage.setItem(TABS_KEY(nodeId), JSON.stringify(names))
  } catch {
    /* private browsing — the tab strip just will not survive a reload */
  }
}

/**
 * A real shell on a node's host.
 *
 * This is the one console page that runs commands as root rather than
 * showing what the cluster is doing — see the guard below and the docs page
 * this links to. Everything past that guard is a fairly ordinary tabbed
 * workspace: each open tab is its own WebSocket onto its own tmux session, so
 * closing a tab stops watching it without ending it, and reopening the page
 * reconnects to whatever was left running.
 */
export default function TerminalPage() {
  const { data: me, isLoading: meLoading } = useMe()
  const owner = me?.role === 'owner'
  const { data: status, isLoading: statusLoading } = useTerminalStatus({ enabled: owner })

  if (meLoading)
    return (
      <PageShell>
        <Skeleton className="h-40 w-full" />
      </PageShell>
    )

  if (!owner) {
    return (
      <PageShell>
        <EmptyState
          title="Owner access required"
          body="A real shell on the host is the one thing here that needs the owner role specifically, not just admin — ask an owner to open it, or to turn it on for the instance."
        />
      </PageShell>
    )
  }

  if (statusLoading)
    return (
      <PageShell>
        <Skeleton className="h-40 w-full" />
      </PageShell>
    )

  if (!status?.enabled)
    return (
      <PageShell>
        <EnableCard />
      </PageShell>
    )

  return (
    <PageShell>
      <Workspace />
    </PageShell>
  )
}

function PageShell({ children }: { children: ReactNode }) {
  return (
    <div className={PAGE}>
      <PageHeader
        title="Terminal"
        subtitle="A live shell on this cluster's node, opened from the browser"
      />
      {children}
    </div>
  )
}

function EnableCard() {
  const toast = useToast()
  const setEnabled = useSetTerminalEnabled()

  return (
    <Card className="p-6">
      <div className="flex items-start gap-3.5">
        <span className="mt-0.5 grid h-9 w-9 flex-none place-items-center rounded-full border border-line bg-panel-2 text-ink-2">
          <Shield size={16} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[15px] font-semibold">Terminal access is off</div>
          <p className="mt-1.5 max-w-[62ch] text-[13.5px] leading-relaxed text-ink-2">
            Turning this on gives every owner of this instance a real shell on the node's host —
            not a container, the machine itself, with the same access a root SSH session would
            have. It is off by default because that is the whole point of the feature, not a
            missing safeguard: the owner role gate on every session is the actual control.
          </p>
          <div className="mt-4">
            <Button
              variant="primary"
              loading={setEnabled.isPending}
              onClick={() =>
                setEnabled.mutate(true, {
                  onSuccess: () => toast.push('Terminal access is on', 'ok'),
                  onError: (error) => toast.push(error.message, 'err'),
                })
              }
            >
              Turn on terminal access
            </Button>
          </div>
        </div>
      </div>
    </Card>
  )
}

function Workspace() {
  const { data: nodes } = useNodes()
  const [nodeId, setNodeId] = useState<string>('')

  const activeNode = useMemo(() => {
    if (!nodes || nodes.length === 0) return undefined
    if (nodeId && nodes.some((n) => n.id === nodeId)) return nodeId
    return nodes.find((n) => n.is_local)?.id ?? nodes[0].id
  }, [nodes, nodeId])

  const { data, isLoading } = useTerminalSessions(activeNode, { enabled: Boolean(activeNode) })
  const [openTabs, setOpenTabs] = useState<string[]>([])
  const [active, setActive] = useState<string | null>(null)
  const create = useCreateTerminalSession()
  const toast = useToast()

  // Reload the open-tab list for whichever node is now selected.
  useEffect(() => {
    if (!activeNode) return
    const tabs = readOpenTabs(activeNode)
    setOpenTabs(tabs)
    setActive(tabs[0] ?? null)
  }, [activeNode])

  useEffect(() => {
    if (activeNode) writeOpenTabs(activeNode, openTabs)
  }, [activeNode, openTabs])

  const openTab = (name: string) => {
    setOpenTabs((current) => (current.includes(name) ? current : [...current, name]))
    setActive(name)
  }

  const closeTab = (name: string) => {
    setOpenTabs((current) => current.filter((n) => n !== name))
    setActive((current) => (current === name ? null : current))
  }

  const newSession = () => {
    if (!activeNode) return
    create.mutate(
      { node_id: activeNode },
      {
        onSuccess: (session) => openTab(session.name),
        onError: (error) => toast.push(error.message, 'err'),
      },
    )
  }

  const knownNames = new Set((data?.sessions ?? []).map((s) => s.name))

  return (
    <div className="grid gap-3.5">
      {nodes && nodes.length > 1 ? (
        <Select
          label="Node"
          size="sm"
          className="max-w-[260px]"
          value={activeNode}
          onChange={(event) => setNodeId(event.target.value)}
        >
          {nodes.map((node) => (
            <option key={node.id} value={node.id}>
              {node.name}
              {node.is_local ? ' (this machine)' : ''}
            </option>
          ))}
        </Select>
      ) : null}

      <Card className="overflow-hidden">
        <div className="flex items-center gap-1 overflow-x-auto border-b border-line bg-panel-2 px-2 py-1.5">
          {openTabs.map((name) => (
            <TabButton
              key={name}
              name={name}
              active={active === name}
              known={knownNames.has(name)}
              nodeId={activeNode}
              onSelect={() => setActive(name)}
              onClose={() => closeTab(name)}
            />
          ))}
          <button
            type="button"
            onClick={newSession}
            disabled={create.isPending || !activeNode}
            title="New session"
            className="ml-1 grid h-8 w-8 flex-none place-items-center rounded-md text-ink-3 transition hover:bg-panel-3 hover:text-ink disabled:opacity-50"
          >
            <Plus size={15} />
          </button>

          <SessionPicker
            sessions={data?.sessions ?? []}
            loading={isLoading}
            openTabs={openTabs}
            onPick={openTab}
          />
        </div>

        {active ? (
          <ActiveSessionBar
            name={active}
            nodeId={activeNode}
            onEnded={() => closeTab(active)}
          />
        ) : null}

        <div className="relative h-[min(68vh,640px)]">
          {openTabs.length === 0 ? (
            <div className="grid h-full place-items-center">
              <EmptyState
                dashed={false}
                title="No session open"
                body="Start one, or pick an existing session from the list on the right of the tab bar."
                action={
                  <Button variant="primary" icon={<Plus size={15} />} onClick={newSession}>
                    New session
                  </Button>
                }
              />
            </div>
          ) : (
            openTabs.map((name) => (
              <TerminalPane
                key={name}
                name={name}
                nodeId={activeNode}
                active={active === name}
              />
            ))
          )}
        </div>
      </Card>
    </div>
  )
}

/** Every session on the node, for reopening one that is not already a tab. */
function SessionPicker({
  sessions,
  loading,
  openTabs,
  onPick,
}: {
  sessions: { name: string; attached: boolean; activity_at: string }[]
  loading: boolean
  openTabs: string[]
  onPick: (name: string) => void
}) {
  const [open, setOpen] = useState(false)
  const others = sessions.filter((s) => !openTabs.includes(s.name))

  return (
    <div className="relative ml-auto flex-none">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[12px] text-ink-2 transition hover:bg-panel-3 hover:text-ink"
      >
        Sessions
        {sessions.length ? (
          <Badge tone="neutral" className="px-1.5 py-0">
            {sessions.length}
          </Badge>
        ) : null}
        <ChevronDown size={12} className={cx('transition', open && 'rotate-180')} />
      </button>
      {open ? (
        <div className="absolute top-full right-0 z-20 mt-1.5 w-[260px] overflow-hidden rounded-[10px] border border-line bg-panel shadow-card">
          {loading ? (
            <div className="px-3.5 py-3 text-[12.5px] text-ink-3">Loading…</div>
          ) : sessions.length === 0 ? (
            <div className="px-3.5 py-3 text-[12.5px] text-ink-3">
              No sessions on this node yet.
            </div>
          ) : others.length === 0 ? (
            <div className="px-3.5 py-3 text-[12.5px] text-ink-3">
              Every session is already open.
            </div>
          ) : (
            others.map((session) => (
              <button
                key={session.name}
                type="button"
                onClick={() => {
                  onPick(session.name)
                  setOpen(false)
                }}
                className="flex w-full items-center gap-2 border-b border-line px-3.5 py-2.5 text-left text-[12.5px] transition last:border-b-0 hover:bg-panel-2"
              >
                <StatusDot tone={session.attached ? 'ok' : 'idle'} />
                <span className="flex-1 truncate font-mono">{session.name}</span>
                <span className="text-ink-3">{relativeTime(session.activity_at)}</span>
              </button>
            ))
          )}
        </div>
      ) : null}
    </div>
  )
}

function TabButton({
  name,
  active,
  known,
  nodeId,
  onSelect,
  onClose,
}: {
  name: string
  active: boolean
  known: boolean
  nodeId: string | undefined
  onSelect: () => void
  onClose: () => void
}) {
  const [renaming, setRenaming] = useState(false)
  const [draft, setDraft] = useState(name)
  const rename = useRenameTerminalSession()
  const toast = useToast()

  const submitRename = () => {
    const next = draft.trim()
    setRenaming(false)
    if (!next || next === name) return
    rename.mutate(
      { name, newName: next, nodeId },
      { onError: (error) => toast.push(error.message, 'err') },
    )
  }

  return (
    <div
      className={cx(
        'group flex flex-none items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[12.5px] transition',
        active ? 'bg-panel text-ink shadow-card' : 'text-ink-2 hover:bg-panel-3 hover:text-ink',
      )}
    >
      {!known ? (
        <span title="Not yet confirmed on the node — opening now">
          <StatusDot tone="warn" />
        </span>
      ) : null}
      {renaming ? (
        <input
          autoFocus
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={submitRename}
          onKeyDown={(event) => {
            if (event.key === 'Enter') submitRename()
            if (event.key === 'Escape') {
              setDraft(name)
              setRenaming(false)
            }
          }}
          className="h-5 w-[110px] rounded border border-accent bg-bg px-1 font-mono text-[12px] outline-none"
        />
      ) : (
        <button type="button" onClick={onSelect} className="max-w-[140px] truncate font-mono">
          {name}
        </button>
      )}
      <button
        type="button"
        onClick={() => setRenaming(true)}
        title="Rename"
        className="hidden text-ink-3 hover:text-ink group-hover:block"
      >
        <Pencil size={11} />
      </button>
      <button
        type="button"
        onClick={onClose}
        title="Close tab — the session keeps running until you end it"
        className="text-ink-3 hover:text-ink"
      >
        <X size={11} />
      </button>
    </div>
  )
}

/** Above the active pane: which session this is, and the one deliberately
 * separate control that actually ends it rather than just stopping watching
 * it — a click here loses whatever is running, which a tab's close button
 * never does. */
function ActiveSessionBar({
  name,
  nodeId,
  onEnded,
}: {
  name: string
  nodeId: string | undefined
  onEnded: () => void
}) {
  const end = useEndTerminalSession()
  const toast = useToast()

  return (
    <div className="flex items-center gap-2.5 border-b border-line bg-panel-2 px-3.5 py-1.5 text-[12px] text-ink-3">
      <span className="font-mono text-ink-2">{name}</span>
      <ConfirmButton
        as="text"
        label="End session"
        confirmLabel="Click again — this stops the shell"
        className="ml-auto"
        onConfirm={() =>
          end.mutate(
            { name, nodeId },
            {
              onSuccess: onEnded,
              onError: (error) => toast.push(error.message, 'err'),
            },
          )
        }
      />
    </div>
  )
}

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

function xtermTheme(): Record<string, string> {
  return {
    background: cssVar('--panel') || '#0f0f12',
    foreground: cssVar('--text') || '#f3f3f5',
    cursor: cssVar('--accent') || '#c6f741',
    cursorAccent: cssVar('--panel') || '#0f0f12',
    selectionBackground: 'rgba(198, 247, 65, 0.25)',
    black: '#1a1a1e',
    red: '#f87171',
    green: '#4ade80',
    yellow: '#fbbf24',
    blue: '#60a5fa',
    magenta: '#c084fc',
    cyan: '#22d3ee',
    white: '#d4d4d8',
    brightBlack: '#52525b',
    brightRed: '#fca5a5',
    brightGreen: '#86efac',
    brightYellow: '#fde047',
    brightBlue: '#93c5fd',
    brightMagenta: '#d8b4fe',
    brightCyan: '#67e8f9',
    brightWhite: '#f4f4f5',
  }
}

/**
 * One xterm.js instance, one reconnecting WebSocket. Kept mounted (hidden,
 * not unmounted) while its tab is not active, so its scrollback and its
 * connection both survive switching tabs — a background session is still a
 * live session, the same as a real terminal multiplexer.
 */
function TerminalPane({
  name,
  nodeId,
  active,
}: {
  name: string
  nodeId: string | undefined
  active: boolean
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const termRef = useRef<XTerm | null>(null)
  const fitRef = useRef<FitAddon | null>(null)
  const { theme } = useTheme()
  const [status, setStatus] = useState<ShellStatus>('connecting')
  const [detail, setDetail] = useState<string | undefined>()

  useEffect(() => {
    const el = containerRef.current
    if (!el) return

    const term = new XTerm({
      fontFamily: '"IBM Plex Mono", ui-monospace, SFMono-Regular, monospace',
      fontSize: 13,
      lineHeight: 1.35,
      cursorBlink: true,
      scrollback: 5000,
      theme: xtermTheme(),
    })
    const fit = new FitAddon()
    term.loadAddon(fit)
    term.open(el)
    fit.fit()
    termRef.current = term
    fitRef.current = fit

    const socket = new TerminalSocket(name, nodeId, term.cols || 80, term.rows || 24)
    socket.onStatus = (next, reason) => {
      setStatus(next)
      setDetail(reason)
    }
    socket.onData = (chunk) => term.write(chunk)
    term.onData((data) => socket.write(new TextEncoder().encode(data)))
    term.onResize(({ cols, rows }) => socket.resize(cols, rows))
    socket.connect()

    const refit = () => fit.fit()
    const observer = new ResizeObserver(refit)
    observer.observe(el)

    return () => {
      observer.disconnect()
      socket.close()
      term.dispose()
    }
    // Reconnecting to a different name/node is a new pane in every way that
    // matters — remounting is simpler and no less correct than patching one
    // xterm instance over to a different shell underneath it.
  }, [name, nodeId])

  useEffect(() => {
    if (termRef.current) termRef.current.options.theme = xtermTheme()
  }, [theme])

  useEffect(() => {
    if (active) {
      fitRef.current?.fit()
      termRef.current?.focus()
    }
  }, [active])

  return (
    <div className={cx('absolute inset-0', !active && 'hidden')}>
      <div ref={containerRef} className="h-full px-1 py-1" />
      {status !== 'open' ? (
        <div className="pointer-events-none absolute inset-x-0 top-2 flex justify-center">
          <Badge tone={status === 'connecting' ? 'neutral' : 'err'}>
            {status === 'connecting'
              ? 'Connecting…'
              : `Disconnected${detail ? ` — ${detail}` : ''}, retrying`}
          </Badge>
        </div>
      ) : null}
    </div>
  )
}
