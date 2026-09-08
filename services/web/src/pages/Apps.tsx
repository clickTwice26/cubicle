import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, ChevronDown, Github, Layers, Plus, Server } from '../components/Icons'
import {
  Badge,
  Button,
  Card,
  Chip,
  CopyButton,
  EmptyState,
  Field,
  Modal,
  PAGE,
  PageHeader,
  Skeleton,
  StatusDot,
  cx,
  useToast,
} from '../components/ui'
import {
  useApps,
  useCreateApp,
  useGitCredentials,
  useHosting,
  type Application,
} from '../lib/apps'
import { relativeTime } from '../lib/format'

const TONE: Record<string, 'ok' | 'warn' | 'err' | 'idle'> = {
  running: 'ok',
  deploying: 'warn',
  created: 'idle',
  stopped: 'idle',
  failed: 'err',
}

/**
 * Applications: the long-running half of the platform.
 *
 * A function is an isolate the cluster keeps warm for one request. An app is a
 * container it keeps up — a Next.js site, an API, anything with a Dockerfile —
 * holding a hostname of its own and reachable by name from everything else on
 * the cluster.
 */
export default function Apps() {
  const { data: apps, isLoading } = useApps()
  const [creating, setCreating] = useState(false)

  return (
    <div className={PAGE}>
      <PageHeader
        title="Applications"
        subtitle="Containers the cluster keeps up, built from a repository and routed by hostname"
        action={
          <Button variant="primary" icon={<Plus size={15} />} onClick={() => setCreating(true)}>
            New app
          </Button>
        }
      />

      <AddressGuide />

      {isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : apps && apps.length > 0 ? (
        <div className="grid gap-3.5 md:grid-cols-2 xl:grid-cols-3">
          {apps.map((app) => (
            <AppCard key={app.id} app={app} />
          ))}
        </div>
      ) : (
        <EmptyState
          title="No applications yet"
          body="Point Cubicle at a repository and it builds it, runs it and gives it a hostname."
          action={
            <Button variant="primary" icon={<Plus size={15} />} onClick={() => setCreating(true)}>
              New app
            </Button>
          }
        />
      )}

      <NewAppModal open={creating} onClose={() => setCreating(false)} />
    </div>
  )
}

/**
 * How an app is reached, with this instance's real values in it.
 *
 * Three addresses that arrive at different times, and the DNS record that
 * unlocks the middle one. Open by default until a wildcard is plausibly in
 * place, because the first app someone deploys is the one where a hostname
 * that does not resolve looks like a broken deploy.
 */
function AddressGuide() {
  const { data: hosting } = useHosting()
  const [open, setOpen] = useState(false)

  if (!hosting) return null

  const record = hosting.wildcard_record

  return (
    <Card className="mb-5 overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-2.5 px-5 py-3.5 text-left transition hover:bg-panel-2"
      >
        <span className="text-sm font-semibold">How apps are reached</span>
        <span className="text-[12.5px] text-ink-3">
          {hosting.configured
            ? `Instant link now · ${hosting.example_hostname} once DNS points here`
            : 'Instant links only — this instance has no domain configured'}
        </span>
        <ChevronDown
          size={14}
          className={cx('ml-auto flex-none text-ink-3 transition', open && 'rotate-180')}
        />
      </button>

      {open ? (
        <div className="grid gap-4 border-t border-line px-5 py-4">
          <Step
            n="1"
            title="Instant link — works right now"
            body={
              <>
                Every app answers at{' '}
                <span className="font-mono">{hosting.instance_url}/&lt;token&gt;</span> the moment
                it is live. No DNS, no certificate, and the token never changes. This is the
                address to check a deploy with. The path is stripped before the request reaches
                the container, so an app that builds absolute URLs will want a hostname instead.
              </>
            }
          />

          {hosting.configured ? (
            <Step
              n="2"
              title="One wildcard record — every app gets a subdomain"
              body={
                <>
                  <span className="block">
                    Add this to the DNS for{' '}
                    <span className="font-mono">{hosting.base_domain}</span>, pointing at the IP
                    this instance runs on:
                  </span>
                  <span className="mt-2 grid gap-2 sm:grid-cols-[70px_minmax(0,1fr)_120px]">
                    <Cell label="Type" value={record.type} />
                    <Cell label="Name" value={record.name} />
                    <Cell
                      label="Value"
                      value={hosting.server_ip || "this server's IP"}
                      copy={Boolean(hosting.server_ip)}
                    />
                  </span>
                  {hosting.server_ip_private ? (
                    <span className="mt-2 block text-ink-3">
                      That is the address this machine has on its own network. Behind a router
                      or a cloud load balancer, the record wants the public address in front of
                      it instead.
                    </span>
                  ) : null}
                  <span className="mt-2 block">
                    Then a new app is at{' '}
                    <span className="font-mono">{hosting.example_hostname}</span> — the app's own
                    name under this instance's hostname
                    {hosting.edge_mode === 'caddy'
                      ? ', and Caddy gets it a certificate on the first request'
                      : ''}
                    . Behind Cloudflare, set the record to{' '}
                    <strong>DNS only</strong>: their universal certificate does not cover a
                    second-level wildcard, so a proxied record serves a certificate warning.
                  </span>
                </>
              }
            />
          ) : (
            <Step
              n="2"
              title="Subdomains need a domain on this instance"
              body={
                <>
                  This instance is served from{' '}
                  <span className="font-mono">{hosting.instance_url}</span>, so there is nothing
                  to hang app subdomains off. Re-run the installer with{' '}
                  <span className="font-mono">--domain</span> to change that. Instant links work
                  either way.
                </>
              }
            />
          )}

          {hosting.edge_mode === 'proxy' && hosting.proxy_snippet ? (
            <Step
              n="3"
              title="Your own web server needs to know about them"
              body={
                <>
                  <span className="block">
                    This instance was installed behind an existing server, so that server owns
                    ports 80 and 443 and Cubicle never sees a request it has not been told to
                    forward. An app hostname it has no block for is its 404, not ours — and the
                    certificate is its to obtain, because Cubicle is not the thing being asked
                    for one.
                  </span>
                  <span className="mt-2 block">
                    Add this once, reload, and every app that will ever exist here is covered:
                  </span>
                  <span className="mt-2 block">
                    <pre className="m-0 max-h-[280px] overflow-auto rounded-[9px] border border-line bg-bg px-3.5 py-3 font-mono text-[11.5px] leading-[1.6] whitespace-pre">
                      {hosting.proxy_snippet}
                    </pre>
                  </span>
                  <span className="mt-2 flex items-center gap-2">
                    <CopyButton value={hosting.proxy_snippet} />
                    <span className="text-ink-3">
                      The wildcard certificate is the part that cannot be skipped — a name with
                      no certificate is a browser warning, not a slower page.
                    </span>
                  </span>
                </>
              }
            />
          ) : null}

          <Step
            n={hosting.edge_mode === 'proxy' && hosting.proxy_snippet ? '4' : '3'}
            title="Custom domains — anything you already own"
            body={
              <>
                Add a hostname on an app's Overview tab and point its own record here. It is
                routed as soon as it resolves, and gets its own certificate. Use this for
                anything the public sees.
              </>
            }
          />
        </div>
      ) : null}
    </Card>
  )
}

function Step({ n, title, body }: { n: string; title: string; body: React.ReactNode }) {
  return (
    <div className="grid gap-2.5 sm:grid-cols-[26px_minmax(0,1fr)]">
      <span className="grid h-[26px] w-[26px] place-items-center rounded-full border border-line-strong font-mono text-[11.5px] text-ink-2">
        {n}
      </span>
      <div>
        <div className="text-[13.5px] font-semibold">{title}</div>
        <div className="mt-1 text-[13px] leading-relaxed text-ink-2">{body}</div>
      </div>
    </div>
  )
}

function Cell({ label, value, copy }: { label: string; value: string; copy?: boolean }) {
  return (
    <span className="flex items-center gap-1.5 rounded-[8px] border border-line bg-bg px-2.5 py-1.5">
      <span className="min-w-0 flex-1">
        <span className="block text-[10.5px] font-bold tracking-[0.05em] text-ink-3 uppercase">
          {label}
        </span>
        <span className="block truncate font-mono text-[12px]">{value}</span>
      </span>
      {copy ? <CopyButton value={value} label="" /> : null}
    </span>
  )
}

function AppCard({ app }: { app: Application }) {
  const deployment = app.deployment
  return (
    <Link to={`/console/apps/${app.id}`} className="block">
      <Card className="h-full p-4 transition hover:border-line-strong">
        <div className="flex items-start gap-2.5">
          <span className="mt-1.5">
            <StatusDot tone={TONE[app.status] ?? 'idle'} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="truncate text-[15px] font-semibold">{app.name}</span>
              {app.status === 'deploying' ? <Badge tone="warn">deploying</Badge> : null}
              {app.status === 'failed' ? <Badge tone="err">failed</Badge> : null}
            </div>
            <div className="mt-0.5 truncate font-mono text-[11.5px] text-ink-3">
              {app.url ? app.url.replace(/^https?:\/\//, '') : app.instant_url.replace(/^https?:\/\//, '')}
            </div>
          </div>
          <ArrowRight size={14} className="mt-1 flex-none text-ink-3" />
        </div>

        <div className="mt-3.5 flex flex-wrap items-center gap-2 text-[12px] text-ink-2">
          {app.source_kind === 'git' ? (
            <span className="inline-flex items-center gap-1.5">
              <Github size={12} />
              <span className="max-w-[190px] truncate font-mono">
                {app.repo_url.replace(/^https:\/\/(www\.)?github\.com\//, '')}
              </span>
              <span className="text-ink-3">#{app.branch}</span>
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5">
              <Layers size={12} />
              <span className="max-w-[220px] truncate font-mono">{app.image_ref}</span>
            </span>
          )}
        </div>

        <div className="mt-3 flex items-center gap-3 border-t border-line pt-3 text-[11.5px] text-ink-3">
          <span className="inline-flex items-center gap-1.5">
            <Server size={12} />
            {app.replicas} × {app.memory_mb} MB
          </span>
          <span className="font-mono">:{app.port}</span>
          <span className="ml-auto">
            {deployment
              ? `#${deployment.number} · ${relativeTime(deployment.created_at ?? '')}`
              : 'never deployed'}
          </span>
        </div>
      </Card>
    </Link>
  )
}

function NewAppModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const toast = useToast()
  const create = useCreateApp()
  const { data: credentials } = useGitCredentials()

  const [name, setName] = useState('')
  const [kind, setKind] = useState<'git' | 'image'>('git')
  const [repo, setRepo] = useState('')
  const [branch, setBranch] = useState('main')
  const [credential, setCredential] = useState('')
  const [image, setImage] = useState('')
  const [port, setPort] = useState('3000')
  const [deployNow, setDeployNow] = useState(true)

  const ready = name.trim() && (kind === 'git' ? repo.trim() : image.trim())

  const submit = () =>
    create.mutate(
      {
        name: name.trim(),
        source_kind: kind,
        repo_url: repo.trim(),
        branch: branch.trim() || 'main',
        credential_id: credential || null,
        image_ref: image.trim(),
        port: Number(port) || 3000,
        deploy_now: deployNow,
      },
      {
        onSuccess: (app) => {
          toast.push(`${app.name} created`, 'ok', deployNow ? 'deploying' : undefined)
          onClose()
          setName('')
          setRepo('')
          setImage('')
        },
        onError: (error) => toast.push(error.message, 'err'),
      },
    )

  return (
    <Modal
      open={open}
      onClose={onClose}
      width={560}
      title="New application"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" loading={create.isPending} disabled={!ready} onClick={submit}>
            {deployNow ? 'Create and deploy' : 'Create'}
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        <Field
          label="Name"
          autoFocus
          value={name}
          placeholder="storefront"
          onChange={(event) => setName(event.target.value)}
          hint="Becomes the hostname and the name other apps reach it by."
        />

        <div>
          <span className="mb-2 block text-[12.5px] text-ink-2">Source</span>
          <div className="flex flex-wrap gap-2">
            <Chip active={kind === 'git'} onClick={() => setKind('git')}>
              git repository
            </Chip>
            <Chip active={kind === 'image'} onClick={() => setKind('image')}>
              published image
            </Chip>
          </div>
        </div>

        {kind === 'git' ? (
          <>
            <Field
              label="Repository"
              value={repo}
              placeholder="https://github.com/you/storefront"
              onChange={(event) => setRepo(event.target.value)}
            />
            <div className="grid gap-4 sm:grid-cols-2">
              <Field
                label="Branch"
                value={branch}
                placeholder="main"
                onChange={(event) => setBranch(event.target.value)}
              />
              <div>
                <span className="mb-1.5 block text-[12.5px] text-ink-2">Credential</span>
                <select
                  value={credential}
                  onChange={(event) => setCredential(event.target.value)}
                  className="h-10 w-full rounded-[9px] border border-line-strong bg-bg px-3 text-[13px] text-ink outline-none focus:border-accent"
                >
                  <option value="">public repository</option>
                  {(credentials ?? []).map((entry) => (
                    <option key={entry.id} value={entry.id}>
                      {entry.name} ({entry.provider})
                    </option>
                  ))}
                </select>
                <div className="mt-1.5 text-xs text-ink-3">
                  Private? Add a token under Settings → Git credentials.
                </div>
              </div>
            </div>
          </>
        ) : (
          <Field
            label="Image"
            value={image}
            placeholder="ghcr.io/you/storefront:1.4.0"
            onChange={(event) => setImage(event.target.value)}
            hint="Pulled as-is. Nothing is built."
          />
        )}

        <Field
          label="Port"
          value={port}
          placeholder="3000"
          onChange={(event) => setPort(event.target.value.replace(/[^\d]/g, ''))}
          hint="What the container listens on. A cubicle.json in the repo can override it."
        />

        <button
          type="button"
          onClick={() => setDeployNow((value) => !value)}
          className={cx(
            'flex items-center gap-2.5 rounded-[10px] border px-3.5 py-3 text-left transition',
            deployNow ? 'border-accent bg-accent-soft' : 'border-line',
          )}
        >
          <span className="text-[13px]">
            <span className="font-semibold">Deploy straight away</span>
            <span className="mt-0.5 block text-[12.5px] text-ink-2">
              Clone, build and start it as soon as it is created.
            </span>
          </span>
        </button>
      </div>
    </Modal>
  )
}
