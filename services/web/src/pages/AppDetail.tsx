import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  ArrowRight,
  ChevronLeft,
  Play,
  Plus,
  Power,
  Refresh,
  Trash,
} from '../components/Icons'
import {
  Badge,
  Button,
  Card,
  CardHeader,
  Checkbox,
  Chip,
  ConfirmButton,
  CopyButton,
  Field,
  Modal,
  PAGE,
  Skeleton,
  StatusDot,
  Tabs,
  cx,
  useToast,
} from '../components/ui'
import {
  subscribeEvents,
  useAddDomain,
  useApp,
  useAppEnv,
  useDeleteApp,
  useDeployApp,
  useDeployment,
  useDeployments,
  useRemoveDomain,
  useRestartApp,
  useSetAppEnv,
  useStopApp,
  useUpdateApp,
  type Application,
  type LogLine,
} from '../lib/apps'
import { relativeTime } from '../lib/format'

const TABS = ['overview', 'deployments', 'logs', 'env', 'settings'] as const
type Tab = (typeof TABS)[number]

const STATUS_TONE: Record<string, 'ok' | 'warn' | 'err' | 'idle'> = {
  running: 'ok',
  deploying: 'warn',
  created: 'idle',
  stopped: 'idle',
  failed: 'err',
}

const DEPLOY_TONE: Record<string, 'accent' | 'warn' | 'err' | 'neutral'> = {
  live: 'accent',
  building: 'warn',
  releasing: 'warn',
  pending: 'warn',
  failed: 'err',
}

export default function AppDetail() {
  const { appId = '' } = useParams()
  const navigate = useNavigate()
  const toast = useToast()

  const { data: app, isLoading } = useApp(appId)
  const deploy = useDeployApp(appId)
  const stop = useStopApp(appId)
  const restart = useRestartApp(appId)
  const remove = useDeleteApp()

  const [tab, setTab] = useState<Tab>('overview')

  if (isLoading || !app) {
    return (
      <div className={cx(PAGE, 'space-y-4')}>
        <Skeleton className="h-8 w-56" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  const busy = app.status === 'deploying'

  return (
    <div className={PAGE}>
      <Link
        to="/console/apps"
        className="mb-3.5 inline-flex items-center gap-1.5 text-[13px] text-ink-2 transition hover:text-ink"
      >
        <ChevronLeft size={14} />
        Applications
      </Link>

      <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-3">
          <span className="mt-2">
            <StatusDot tone={STATUS_TONE[app.status] ?? 'idle'} />
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="m-0 text-[23px] tracking-[-0.02em]">{app.name}</h1>
              <Badge tone={app.status === 'failed' ? 'err' : 'neutral'}>{app.status}</Badge>
              {app.deployment ? (
                <span className="font-mono text-[11.5px] text-ink-3">
                  #{app.deployment.number}
                </span>
              ) : null}
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
              {app.instant_url ? (
                <a
                  href={app.instant_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1.5 font-mono text-[12.5px] text-ink-2 transition hover:text-ink"
                >
                  {app.instant_url.replace(/^https?:\/\//, '')}
                  <ArrowRight size={12} />
                </a>
              ) : null}
              {app.url ? (
                <a
                  href={app.url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1.5 font-mono text-[12.5px] text-ink-3 transition hover:text-ink"
                >
                  {app.url.replace(/^https?:\/\//, '')}
                  <ArrowRight size={12} />
                </a>
              ) : null}
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="primary"
            icon={<Play size={13} />}
            loading={deploy.isPending || busy}
            onClick={() =>
              deploy.mutate(undefined, {
                onSuccess: () => {
                  toast.push('Deploy started')
                  setTab('deployments')
                },
                onError: (error) => toast.push(error.message, 'err'),
              })
            }
          >
            Deploy
          </Button>
          <Button
            icon={<Refresh size={13} />}
            loading={restart.isPending}
            title="Start this release again with the current environment"
            onClick={() =>
              restart.mutate(undefined, {
                onSuccess: () => toast.push('Restarting'),
                onError: (error) => toast.push(error.message, 'err'),
              })
            }
          >
            Restart
          </Button>
          <Button
            variant="ghost"
            icon={<Power size={13} />}
            loading={stop.isPending}
            onClick={() =>
              stop.mutate(undefined, {
                onSuccess: () => toast.push(`${app.name} stopped`),
                onError: (error) => toast.push(error.message, 'err'),
              })
            }
          >
            Stop
          </Button>
        </div>
      </div>

      {app.last_error ? (
        <Card className="mb-5 border-err bg-err-bg px-4 py-3 text-[13px] leading-relaxed">
          {app.last_error}
        </Card>
      ) : null}

      <Tabs
        value={tab}
        onChange={setTab}
        className="mb-5"
        tabs={[
          { value: 'overview', label: 'Overview' },
          { value: 'deployments', label: 'Deployments' },
          { value: 'logs', label: 'Logs' },
          { value: 'env', label: 'Environment' },
          { value: 'settings', label: 'Settings' },
        ]}
      />

      {tab === 'overview' ? <Overview app={app} /> : null}
      {tab === 'deployments' ? <Deployments app={app} /> : null}
      {tab === 'logs' ? <Logs app={app} /> : null}
      {tab === 'env' ? <EnvTab app={app} /> : null}
      {tab === 'settings' ? (
        <SettingsTab
          app={app}
          onDeleted={() => {
            toast.push(`${app.name} deleted`)
            navigate('/console/apps')
          }}
          remove={remove}
        />
      ) : null}
    </div>
  )
}

// ── overview ─────────────────────────────────────────────────────────────────

function Overview({ app }: { app: Application }) {
  const toast = useToast()
  const addDomain = useAddDomain(app.id)
  const removeDomain = useRemoveDomain(app.id)
  const [hostname, setHostname] = useState('')

  const webhook = `${window.location.origin}${app.webhook_path}`

  return (
    <div className="grid gap-5 lg:grid-cols-[1.3fr_1fr] lg:items-start">
      <div className="grid gap-5">
        <Card className="overflow-hidden">
          <CardHeader
            title="Instant link"
            subtitle="On this instance's own hostname · no DNS, no certificate, never changes"
          />
          <div className="px-5 py-4">
            <div className="flex items-center gap-2 rounded-[9px] border border-accent bg-accent-soft px-3 py-2.5">
              <a
                href={app.instant_url}
                target="_blank"
                rel="noreferrer"
                className="min-w-0 flex-1 truncate font-mono text-[12.5px] font-semibold"
              >
                {app.instant_url}
              </a>
              <CopyButton value={app.instant_url} label="" />
            </div>
            <p className="mt-2.5 mb-0 text-[12.5px] leading-relaxed text-ink-2">
              Works the moment the app is live, which makes it the address to check a deploy
              with. The path is stripped before the request reaches your app, so an app that
              builds absolute URLs needs its own base path set — use a hostname below for
              anything you are handing to other people.
            </p>
          </div>
        </Card>

        <Card className="overflow-hidden">
          <CardHeader title="Domains" subtitle="Each gets a certificate on its first request" />
          {app.domains.length ? (
            app.domains.map((domain) => (
              <div
                key={domain.id}
                className="flex flex-wrap items-center gap-2.5 border-b border-line px-5 py-3 last:border-b-0"
              >
                <a
                  href={`https://${domain.hostname}`}
                  target="_blank"
                  rel="noreferrer"
                  className="min-w-0 flex-1 truncate font-mono text-[12.5px] transition hover:text-accent"
                >
                  {domain.hostname}
                </a>
                {domain.primary ? <Badge tone="accent">primary</Badge> : null}
                <CopyButton value={`https://${domain.hostname}`} label="" />
                <ConfirmButton
                  label="Remove"
                  confirmLabel="Confirm"
                  onConfirm={() =>
                    removeDomain.mutate(domain.id, {
                      onSuccess: () => toast.push('Domain removed'),
                      onError: (error) => toast.push(error.message, 'err'),
                    })
                  }
                />
              </div>
            ))
          ) : (
            <div className="px-5 py-6 text-center text-[13px] text-ink-3">
              No hostname yet. Add one below and point its DNS at this machine.
            </div>
          )}
          <form
            className="flex flex-wrap items-center gap-2 border-t border-line bg-panel-2 px-5 py-3"
            onSubmit={(event) => {
              event.preventDefault()
              if (!hostname.trim()) return
              addDomain.mutate(
                { hostname: hostname.trim() },
                {
                  onSuccess: () => {
                    toast.push('Domain added')
                    setHostname('')
                  },
                  onError: (error) => toast.push(error.message, 'err'),
                },
              )
            }}
          >
            <input
              value={hostname}
              onChange={(event) => setHostname(event.target.value)}
              placeholder="shop.example.com"
              className="h-9 min-w-[200px] flex-1 rounded-[9px] border border-line-strong bg-bg px-3 font-mono text-[12.5px] text-ink outline-none placeholder:text-ink-3 focus:border-accent"
            />
            <Button size="sm" type="submit" icon={<Plus size={13} />} loading={addDomain.isPending}>
              Add domain
            </Button>
          </form>
        </Card>

        <Card className="overflow-hidden">
          <CardHeader
            title="Instances"
            subtitle={`${app.replicas} requested · ${app.memory_mb} MB and ${app.cpus} CPU each`}
          />
          {app.containers.length ? (
            app.containers.map((container) => (
              <div
                key={container.name}
                className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-3 text-[12.5px] last:border-b-0"
              >
                <StatusDot tone={container.status === 'running' ? 'ok' : 'idle'} />
                <span className="min-w-0 flex-1 truncate font-mono">{container.name}</span>
                <span className="text-ink-3">{container.status}</span>
                <Badge>#{container.deployment}</Badge>
              </div>
            ))
          ) : (
            <div className="px-5 py-6 text-center text-[13px] text-ink-3">
              Nothing running for this app right now.
            </div>
          )}
        </Card>
      </div>

      <div className="grid gap-5">
        <Card className="overflow-hidden">
          <CardHeader title="Release" />
          <div className="grid gap-3 px-5 py-4 text-[13px]">
            <Row label="Source">
              {app.source_kind === 'git' ? (
                <span className="font-mono text-[12px]">
                  {app.repo_url.replace(/^https:\/\//, '')} · {app.branch}
                </span>
              ) : (
                <span className="font-mono text-[12px]">{app.image_ref}</span>
              )}
            </Row>
            <Row label="Build">
              {app.definition?.source ? String(app.definition.source) : '—'}
            </Row>
            <Row label="Commit">
              {app.deployment?.commit_sha ? (
                <span className="font-mono text-[12px]">
                  {app.deployment.commit_sha} {app.deployment.commit_message}
                </span>
              ) : (
                '—'
              )}
            </Row>
            <Row label="Port">
              <span className="font-mono text-[12px]">{app.port}</span>
            </Row>
            <Row label="Deployed">
              {app.deployment?.created_at ? relativeTime(app.deployment.created_at) : 'never'}
            </Row>
          </div>
        </Card>

        <Card className="overflow-hidden">
          <CardHeader
            title="Auto deploy"
            subtitle="Point a GitHub webhook here to deploy on every push"
          />
          <div className="px-5 py-4">
            <div className="flex items-center gap-2 rounded-[9px] border border-line bg-bg px-3 py-2.5">
              <span className="min-w-0 flex-1 truncate font-mono text-[11.5px]">{webhook}</span>
              <CopyButton value={webhook} label="" />
            </div>
            <p className="mt-2.5 mb-0 text-[12.5px] leading-relaxed text-ink-2">
              In the repository: Settings → Webhooks → Add webhook. Content type{' '}
              <span className="font-mono">application/json</span>, and paste this URL as both the
              payload URL and the secret — pushes to{' '}
              <span className="font-mono">{app.branch}</span> then deploy on their own.
            </p>
            <div className="mt-2.5 text-[12.5px] text-ink-3">
              {app.auto_deploy ? 'Auto deploy is on.' : 'Auto deploy is off — hooks are ignored.'}
            </div>
          </div>
        </Card>
      </div>
    </div>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1 sm:grid-cols-[86px_minmax(0,1fr)]">
      <span className="text-[11.5px] font-bold tracking-[0.04em] text-ink-3 uppercase">
        {label}
      </span>
      <span className="min-w-0 break-words text-ink-2">{children}</span>
    </div>
  )
}

// ── deployments ──────────────────────────────────────────────────────────────

function Deployments({ app }: { app: Application }) {
  const { data: deployments } = useDeployments(app.id)
  const [open, setOpen] = useState<string | null>(null)

  const active = (deployments ?? []).find((d) =>
    ['pending', 'building', 'releasing'].includes(d.status),
  )

  useEffect(() => {
    // A build that is running is the one you came here to watch.
    if (active && !open) setOpen(active.id)
  }, [active, open])

  return (
    <div className="grid gap-5">
      <Card className="overflow-hidden">
        <CardHeader title="Deployments" subtitle="Newest first · every build is kept" />
        {(deployments ?? []).map((deployment) => (
          <button
            key={deployment.id}
            type="button"
            onClick={() => setOpen(deployment.id === open ? null : deployment.id)}
            className={cx(
              'flex w-full flex-wrap items-center gap-3 border-b border-line px-5 py-3 text-left transition last:border-b-0',
              deployment.id === open ? 'bg-accent-soft' : 'hover:bg-panel-2',
            )}
          >
            <span className="font-mono text-[12.5px] font-semibold">#{deployment.number}</span>
            <Badge tone={DEPLOY_TONE[deployment.status] ?? 'neutral'}>{deployment.status}</Badge>
            <span className="min-w-0 flex-1 truncate text-[12.5px] text-ink-2">
              {deployment.commit_sha ? (
                <span className="font-mono text-[11.5px] text-ink-3">
                  {deployment.commit_sha}{' '}
                </span>
              ) : null}
              {deployment.commit_message || deployment.error || '—'}
            </span>
            <span className="text-[11.5px] text-ink-3">
              {deployment.trigger} · {deployment.triggered_by || 'console'}
            </span>
            <span className="font-mono text-[11.5px] text-ink-3">
              {deployment.build_ms ? `${(deployment.build_ms / 1000).toFixed(1)}s` : ''}
            </span>
            <span className="text-[11.5px] text-ink-3">
              {relativeTime(deployment.created_at ?? '')}
            </span>
          </button>
        ))}
        {deployments && deployments.length === 0 ? (
          <div className="px-5 py-8 text-center text-[13px] text-ink-3">
            Nothing has been deployed yet.
          </div>
        ) : null}
      </Card>

      {open ? <BuildLog appId={app.id} deploymentId={open} /> : null}
    </div>
  )
}

function BuildLog({ appId, deploymentId }: { appId: string; deploymentId: string }) {
  const { data: deployment } = useDeployment(appId, deploymentId)
  const [live, setLive] = useState<string[]>([])
  const [finished, setFinished] = useState<{ status: string; error?: string } | null>(null)
  const box = useRef<HTMLPreElement>(null)

  const running = deployment
    ? ['pending', 'building', 'releasing'].includes(deployment.status)
    : false

  useEffect(() => {
    setLive([])
    setFinished(null)
  }, [deploymentId])

  useEffect(() => {
    if (!running) return
    return subscribeEvents(`/api/apps/${appId}/deployments/${deploymentId}/stream`, {
      log: (lines) => setLive((current) => [...current, ...(lines as string[])].slice(-4000)),
      done: (payload) => setFinished(payload as { status: string; error?: string }),
    })
  }, [appId, deploymentId, running])

  useEffect(() => {
    // Follow the tail while it is being written.
    if (box.current && running) box.current.scrollTop = box.current.scrollHeight
  }, [live, running])

  const text = live.length ? live.join('\n') : (deployment?.build_log ?? '')

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center gap-2.5 border-b border-line bg-panel-2 px-5 py-2.5">
        <span className="text-[11.5px] font-bold tracking-[0.05em] text-ink-3 uppercase">
          Build log
        </span>
        {deployment ? (
          <Badge tone={DEPLOY_TONE[finished?.status ?? deployment.status] ?? 'neutral'}>
            {finished?.status ?? deployment.status}
          </Badge>
        ) : null}
        {running ? (
          <span className="text-[12px] text-ink-3">streaming…</span>
        ) : (
          <span className="text-[12px] text-ink-3">
            {deployment?.build_ms ? `${(deployment.build_ms / 1000).toFixed(1)}s` : ''}
          </span>
        )}
        <span className="ml-auto">
          <CopyButton value={text} />
        </span>
      </div>
      <pre
        ref={box}
        className="m-0 max-h-[460px] overflow-auto px-5 py-4 font-mono text-[12px] leading-[1.7] whitespace-pre-wrap text-ink-2"
      >
        {text || 'Waiting for the build to start…'}
      </pre>
      {(finished?.error ?? deployment?.error) ? (
        <div className="border-t border-err bg-err-bg px-5 py-3 font-mono text-[12.5px]">
          {finished?.error ?? deployment?.error}
        </div>
      ) : null}
    </Card>
  )
}

// ── logs ─────────────────────────────────────────────────────────────────────

function Logs({ app }: { app: Application }) {
  const [lines, setLines] = useState<LogLine[]>([])
  const [following, setFollowing] = useState(true)
  const box = useRef<HTMLPreElement>(null)

  useEffect(() => {
    if (!following) return
    return subscribeEvents(`/api/apps/${app.id}/logs/stream`, {
      log: (incoming) =>
        setLines((current) => [...current, ...(incoming as LogLine[])].slice(-2000)),
    })
  }, [app.id, following])

  useEffect(() => {
    if (box.current && following) box.current.scrollTop = box.current.scrollHeight
  }, [lines, following])

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center gap-2.5 border-b border-line bg-panel-2 px-5 py-2.5">
        <span className="text-[11.5px] font-bold tracking-[0.05em] text-ink-3 uppercase">
          Live logs
        </span>
        <span className="text-[12px] text-ink-3">
          every replica, as they write · {lines.length} lines
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Button size="sm" variant={following ? 'secondary' : 'primary'} onClick={() => setFollowing((v) => !v)}>
            {following ? 'Pause' : 'Resume'}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setLines([])}>
            Clear
          </Button>
        </div>
      </div>
      <pre
        ref={box}
        className="m-0 max-h-[560px] min-h-[280px] overflow-auto px-5 py-4 font-mono text-[12px] leading-[1.7] whitespace-pre-wrap text-ink-2"
      >
        {lines.length
          ? lines
              .map((line) => `${line.replica ? `[${line.replica}] ` : ''}${line.text}`)
              .join('\n')
          : app.status === 'running'
            ? 'Waiting for output…'
            : 'This app is not running.'}
      </pre>
    </Card>
  )
}

// ── environment ──────────────────────────────────────────────────────────────

function EnvTab({ app }: { app: Application }) {
  const toast = useToast()
  const { data } = useAppEnv(app.id)
  const save = useSetAppEnv(app.id)
  const restart = useRestartApp(app.id)
  const [draft, setDraft] = useState('')
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    if (!data || loaded) return
    setDraft(
      Object.entries(data.env)
        .map(([key, value]) => `${key}=${value}`)
        .join('\n'),
    )
    setLoaded(true)
  }, [data, loaded])

  const parsed = useMemo(() => {
    const env: Record<string, string> = {}
    for (const raw of draft.split('\n')) {
      const line = raw.trim()
      if (!line || line.startsWith('#')) continue
      const index = line.indexOf('=')
      if (index < 1) continue
      env[line.slice(0, index).trim()] = line.slice(index + 1).trim()
    }
    return env
  }, [draft])

  return (
    <Card className="overflow-hidden">
      <CardHeader
        title="Environment"
        subtitle="Stored encrypted · injected at start, so a change applies on the next release"
        action={<Badge>{Object.keys(parsed).length} variables</Badge>}
      />
      <div className="px-5 py-4">
        <textarea
          value={draft}
          spellCheck={false}
          onChange={(event) => setDraft(event.target.value)}
          placeholder={'DATABASE_URL=postgres://…\nNEXT_PUBLIC_API=https://api.example.com'}
          className="h-[320px] w-full resize-y rounded-[10px] border border-line-strong bg-bg p-3.5 font-mono text-[12.5px] leading-relaxed text-ink outline-none focus:border-accent"
        />
        <div className="mt-3 flex flex-wrap items-center gap-2.5">
          <Button
            variant="primary"
            loading={save.isPending}
            onClick={() =>
              save.mutate(parsed, {
                onSuccess: () => toast.push('Environment saved'),
                onError: (error) => toast.push(error.message, 'err'),
              })
            }
          >
            Save
          </Button>
          <Button
            loading={restart.isPending}
            disabled={app.status !== 'running'}
            onClick={() =>
              restart.mutate(undefined, {
                onSuccess: () => toast.push('Restarting with the new environment'),
                onError: (error) => toast.push(error.message, 'err'),
              })
            }
          >
            Restart to apply
          </Button>
          <span className="text-[12.5px] text-ink-3">
            One <span className="font-mono">KEY=value</span> per line. Linked services add theirs
            automatically.
          </span>
        </div>
      </div>
    </Card>
  )
}

// ── settings ─────────────────────────────────────────────────────────────────

const LINKABLE = ['postgres', 'redis']

function SettingsTab({
  app,
  onDeleted,
  remove,
}: {
  app: Application
  onDeleted: () => void
  remove: ReturnType<typeof useDeleteApp>
}) {
  const toast = useToast()
  const update = useUpdateApp(app.id)
  const [form, setForm] = useState({
    replicas: String(app.replicas),
    memory_mb: String(app.memory_mb),
    cpus: String(app.cpus),
    port: String(app.port),
    branch: app.branch,
    health_path: app.health_path,
  })
  const [links, setLinks] = useState<string[]>(app.links ?? [])
  const [autoDeploy, setAutoDeploy] = useState(app.auto_deploy)
  const [destroying, setDestroying] = useState(false)
  const [keepVolumes, setKeepVolumes] = useState(false)

  const patch = (field: keyof typeof form) => (event: { target: { value: string } }) =>
    setForm((current) => ({ ...current, [field]: event.target.value }))

  const save = () =>
    update.mutate(
      {
        replicas: Number(form.replicas) || 0,
        memory_mb: Number(form.memory_mb) || 512,
        cpus: Number(form.cpus) || 1,
        port: Number(form.port) || 3000,
        branch: form.branch.trim() || 'main',
        health_path: form.health_path.trim(),
        auto_deploy: autoDeploy,
        links,
      } as Partial<Application>,
      {
        onSuccess: () => toast.push('Saved'),
        onError: (error) => toast.push(error.message, 'err'),
      },
    )

  return (
    <div className="grid gap-5">
      <Card className="overflow-hidden">
        <CardHeader
          title="Scale and resources"
          subtitle="Instance count applies immediately; the rest on the next release"
        />
        <div className="grid gap-4 px-5 py-5 sm:grid-cols-2 lg:grid-cols-4">
          <Field
            label="Instances"
            value={form.replicas}
            onChange={patch('replicas')}
            hint="0 stops the app. More than one is load-balanced."
          />
          <Field label="Memory (MB)" value={form.memory_mb} onChange={patch('memory_mb')} />
          <Field label="CPUs" value={form.cpus} onChange={patch('cpus')} />
          <Field label="Port" value={form.port} onChange={patch('port')} />
        </div>
      </Card>

      <Card className="overflow-hidden">
        <CardHeader title="Build and health" />
        <div className="grid gap-4 px-5 py-5 sm:grid-cols-2">
          <Field
            label="Branch"
            value={form.branch}
            onChange={patch('branch')}
            hint="What a deploy and a webhook build."
          />
          <Field
            label="Health path"
            value={form.health_path}
            onChange={patch('health_path')}
            placeholder="/healthz"
            hint="Checked before traffic moves. Blank means: it started and stayed up."
          />
        </div>
        <div className="border-t border-line px-5 py-4">
          <Checkbox
            checked={autoDeploy}
            onChange={setAutoDeploy}
            label="Deploy automatically when the webhook fires"
          />
        </div>
      </Card>

      <Card className="overflow-hidden">
        <CardHeader
          title="Links"
          subtitle="Connection details injected into this app's environment at start"
        />
        <div className="flex flex-wrap gap-2 px-5 py-5">
          {LINKABLE.map((service) => (
            <Chip
              key={service}
              active={links.includes(service)}
              onClick={() =>
                setLinks((current) =>
                  current.includes(service)
                    ? current.filter((entry) => entry !== service)
                    : [...current, service],
                )
              }
            >
              {service}
            </Chip>
          ))}
          <span className="text-[12.5px] text-ink-3">
            Adds <span className="font-mono">DATABASE_URL</span> and{' '}
            <span className="font-mono">REDIS_URL</span> for the managed services on this cluster.
          </span>
        </div>
      </Card>

      <div className="flex flex-wrap items-center gap-2.5">
        <Button variant="primary" loading={update.isPending} onClick={save}>
          Save changes
        </Button>
        <span className="text-[12.5px] text-ink-3">
          Changing instances restarts the containers; everything else waits for the next deploy.
        </span>
      </div>

      <Card className="mt-2 overflow-hidden border-err">
        <CardHeader
          title="Delete this app"
          subtitle="Removes its containers, its routes and its build history"
          action={
            <Button variant="danger" icon={<Trash size={13} />} onClick={() => setDestroying(true)}>
              Delete
            </Button>
          }
        />
      </Card>

      <Modal
        open={destroying}
        onClose={() => setDestroying(false)}
        width={520}
        title={`Delete ${app.name}?`}
        footer={
          <>
            <Button variant="ghost" onClick={() => setDestroying(false)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              loading={remove.isPending}
              onClick={() =>
                remove.mutate(
                  { id: app.id, keepVolumes },
                  {
                    onSuccess: onDeleted,
                    onError: (error) => toast.push(error.message, 'err'),
                  },
                )
              }
            >
              Delete app
            </Button>
          </>
        }
      >
        <div className="grid gap-4">
          <div className="rounded-[10px] border border-err bg-err-bg px-3.5 py-3 text-[13px] leading-relaxed">
            The containers stop and are removed, the hostnames stop resolving here, and the
            deployment history goes with it. The repository is untouched.
          </div>
          <Checkbox
            checked={keepVolumes}
            onChange={setKeepVolumes}
            label="Keep the data volumes — anything written to them stays on disk"
          />
        </div>
      </Modal>
    </div>
  )
}
