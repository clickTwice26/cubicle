import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowRight,
  Check,
  ChevronDown,
  Copy,
  Github,
  Layers,
  Plus,
  Server,
} from '../components/Icons'
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
  useAppLibrary,
  useApps,
  useCreateApp,
  useGitCredentials,
  useHosting,
  type Application,
  type LibraryApp,
} from '../lib/apps'
import {
  CAPTAIN_DEFINITION_EXAMPLE,
  CUBICLE_JSON_EXAMPLE,
  DEFINITION_KEYS,
  deployPrompt,
} from '../lib/appGuide'
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

      {/* Before and after: what the repository needs, then how the result is reached. */}
      <div className="mb-5 grid gap-2.5">
        <RepoGuide />
        <AddressGuide />
      </div>

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

/** What a repository has to get right, whatever builds its image. */
const CHECKS: [string, string][] = [
  ['Listens on 0.0.0.0', 'not localhost, since the edge reaches it from another container'],
  ['Plain HTTP on the exposed port', 'TLS is taken care of in front of it'],
  ['Logs to stdout and stderr', 'which is what the Logs tab shows'],
  ['Secrets from the Environment tab', 'never baked into the image'],
  ['State in Postgres or Redis', 'the container disk is replaced on every deploy'],
  ['A .dockerignore', 'keeping .git, node_modules and .env out of the build'],
]

/**
 * What a repository needs before it is worth pointing Cubicle at.
 *
 * The honest answer is "a Dockerfile", so that comes first and the rest is
 * framed as optional: a definition for when something needs saying, the
 * CapRover file for projects that already have one, and a prompt that hands
 * all of it to an assistant with the repository open. The prompt is reachable
 * from the header too — it is the thing most people come here for, and
 * expanding a card to find a button is one step too many.
 */
function RepoGuide() {
  const { data: hosting } = useHosting()
  const [open, setOpen] = useState(false)
  const [preview, setPreview] = useState(false)
  const prompt = useMemo(() => deployPrompt(hosting), [hosting])
  const toggle = () => setOpen((value) => !value)

  return (
    <Card className="overflow-hidden">
      <div className="flex items-center gap-1.5 pr-3 transition hover:bg-panel-2">
        <button
          type="button"
          aria-expanded={open}
          onClick={toggle}
          className="flex min-w-0 flex-1 items-center gap-2.5 py-3.5 pl-5 text-left"
        >
          <span className="flex-none text-sm font-semibold">Preparing a repository</span>
          <span className="hidden truncate text-[12.5px] text-ink-3 sm:inline">
            A Dockerfile is all it needs · cubicle.json when something needs saying
          </span>
        </button>
        {/* On a phone the title needs the room; the same button is inside the card. */}
        <span className="hidden sm:block">
          <PromptButton prompt={prompt} size="sm" variant="ghost" />
        </span>
        {/* The same toggle as the title, kept where the other card has its chevron. */}
        <button
          type="button"
          tabIndex={-1}
          aria-hidden="true"
          onClick={toggle}
          className="grid h-8 w-[30px] flex-none place-items-center text-ink-3"
        >
          <ChevronDown size={14} className={cx('transition', open && 'rotate-180')} />
        </button>
      </div>

      {open ? (
        <div className="grid gap-4 border-t border-line px-5 py-4">
          <Step
            n="1"
            title="A Dockerfile at the root — that is the whole contract"
            body={
              <>
                <div>
                  A repository with a Dockerfile and nothing else is built exactly as it is, with
                  the repository as the build context. The port comes from its{' '}
                  <Mono>EXPOSE</Mono> — the final stage's, in a multi-stage build — and the
                  container is handed <Mono>PORT</Mono> as well, so there is nothing to set here.
                </div>
                <div className="mt-2.5 grid gap-x-5 gap-y-1.5 sm:grid-cols-2">
                  {CHECKS.map(([head, tail]) => (
                    <div key={head} className="flex gap-2">
                      <Check size={13} className="mt-[3px] flex-none text-ok" />
                      <span>
                        <span className="font-medium text-ink">{head}</span> — {tail}
                      </span>
                    </div>
                  ))}
                </div>
                <div className="mt-2.5 text-ink-3">
                  No Dockerfile? Next.js, Vite and React, Node, plain HTML and Python with a
                  Procfile get a generated one —{' '}
                  <Link to="/docs/apps" className="underline underline-offset-2 hover:text-ink">
                    see how it is built
                  </Link>
                  . That is a guess, though, and a Dockerfile is an instruction.
                </div>
              </>
            }
          />

          <Step
            n="2"
            title="cubicle.json — only when something needs saying"
            body={
              <>
                <div>
                  At the root, next to the Dockerfile. Every key is optional, and at most one of{' '}
                  <Mono>dockerfilePath</Mono>, <Mono>dockerfileLines</Mono> and{' '}
                  <Mono>imageName</Mono> may be set — they are three answers to the same question.
                </div>
                {/* Side by side only once the example fits without scrolling sideways. */}
                <div className="mt-2.5 grid items-start gap-3 xl:grid-cols-[auto_minmax(0,1fr)]">
                  <Snippet filename="cubicle.json" value={CUBICLE_JSON_EXAMPLE} />
                  <div className="overflow-hidden rounded-[9px] border border-line">
                    {DEFINITION_KEYS.map(({ key, means }) => (
                      <div
                        key={key}
                        className="grid gap-0.5 border-b border-line px-3 py-2 last:border-b-0 sm:grid-cols-[118px_minmax(0,1fr)] sm:gap-3"
                      >
                        <span className="font-mono text-[12px] text-ink">{key}</span>
                        <span className="text-[12.5px] leading-snug">{means}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </>
            }
          />

          <Step
            n="3"
            title="Coming from CapRover? Keep the captain-definition"
            body={
              <>
                <div>
                  It is read as-is: the key names are the same, so a project that deploys there
                  deploys here without a second file to keep in step, and{' '}
                  <Mono>cubicle.json</Mono> wins when a repository has both. Put an{' '}
                  <Mono>EXPOSE</Mono> in its <Mono>dockerfileLines</Mono> and the port needs no
                  setting either.
                </div>
                <div className="mt-2.5 max-w-[560px]">
                  <Snippet filename="captain-definition" value={CAPTAIN_DEFINITION_EXAMPLE} />
                </div>
              </>
            }
          />

          <Step
            n="4"
            title="Or have your AI assistant write it"
            body={
              <>
                <div>
                  One prompt carrying everything above — the build and port rules, the health
                  check, the file format and this instance's own addresses. Paste it into Claude
                  Code, Cursor, Copilot or ChatGPT with the repository open: it reads the project,
                  writes the Dockerfile, <Mono>.dockerignore</Mono> and <Mono>cubicle.json</Mono>{' '}
                  it actually needs, tries the build, and finishes with the environment variables
                  to set here.
                </div>
                <div className="mt-2.5 flex flex-wrap items-center gap-2">
                  <PromptButton prompt={prompt} />
                  <Button variant="ghost" onClick={() => setPreview((value) => !value)}>
                    {preview ? 'Hide the prompt' : 'Show the prompt'}
                  </Button>
                </div>
                {preview ? (
                  <pre className="mt-2.5 mb-0 max-h-[360px] overflow-auto rounded-[9px] border border-line bg-bg px-3.5 py-3 font-mono text-[11.5px] leading-[1.6] whitespace-pre-wrap text-ink">
                    {prompt}
                  </pre>
                ) : null}
              </>
            }
          />
        </div>
      ) : null}
    </Card>
  )
}

/**
 * Copies the setup prompt. A real button rather than the inline copy link,
 * because on this page it is the action — and it says so when it worked.
 */
function PromptButton({
  prompt,
  variant = 'primary',
  size = 'md',
}: {
  prompt: string
  variant?: 'primary' | 'ghost'
  size?: 'sm' | 'md'
}) {
  const toast = useToast()
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!copied) return
    const timer = window.setTimeout(() => setCopied(false), 1800)
    return () => window.clearTimeout(timer)
  }, [copied])

  return (
    <Button
      type="button"
      variant={variant}
      size={size}
      className="flex-none"
      icon={copied ? <Check size={13} /> : <Copy size={13} />}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(prompt)
          setCopied(true)
        } catch {
          toast.push('The browser blocked the clipboard — use Show the prompt instead', 'err')
        }
      }}
    >
      {copied ? 'Copied' : 'Copy AI prompt'}
    </Button>
  )
}

function Snippet({ filename, value }: { filename: string; value: string }) {
  return (
    <div className="min-w-0 overflow-hidden rounded-[9px] border border-line bg-bg">
      <div className="flex items-center justify-between gap-2 border-b border-line px-3 py-1.5">
        <span className="font-mono text-[11px] text-ink-3">{filename}</span>
        <CopyButton value={value} />
      </div>
      <pre className="m-0 overflow-x-auto px-3.5 py-3 font-mono text-[11.5px] leading-[1.6] whitespace-pre text-ink">
        {value.trimEnd()}
      </pre>
    </div>
  )
}

function Mono({ children }: { children: ReactNode }) {
  return <span className="font-mono text-[12px] text-ink">{children}</span>
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
    <Card className="overflow-hidden">
      <button
        type="button"
        aria-expanded={open}
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
  const { data: hosting } = useHosting()
  const prompt = useMemo(() => deployPrompt(hosting), [hosting])

  const { data: library } = useAppLibrary()
  const [name, setName] = useState('')
  const [kind, setKind] = useState<'git' | 'image' | 'library'>('library')
  const [picked, setPicked] = useState<LibraryApp | null>(null)
  const [filter, setFilter] = useState('')
  const [envDraft, setEnvDraft] = useState<Record<string, string>>({})
  const [repo, setRepo] = useState('')
  const [branch, setBranch] = useState('main')
  const [credential, setCredential] = useState('')
  const [image, setImage] = useState('')
  const [port, setPort] = useState('3000')
  const [deployNow, setDeployNow] = useState(true)

  const ready =
    name.trim() &&
    (kind === 'git' ? repo.trim() : kind === 'image' ? image.trim() : Boolean(picked))

  const submit = () =>
    create.mutate(
      {
        name: name.trim(),
        ...(kind === 'library' && picked
          ? { template: picked.slug, source_kind: 'image' as const, env: envDraft }
          : {
              source_kind: kind as 'git' | 'image',
              repo_url: repo.trim(),
              branch: branch.trim() || 'main',
              credential_id: credential || null,
              image_ref: image.trim(),
              port: Number(port) || 3000,
            }),
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
            <Chip active={kind === 'library'} onClick={() => setKind('library')}>
              from the library
            </Chip>
            <Chip active={kind === 'git'} onClick={() => setKind('git')}>
              git repository
            </Chip>
            <Chip active={kind === 'image'} onClick={() => setKind('image')}>
              published image
            </Chip>
          </div>
        </div>

        {kind === 'library' ? (
          <LibraryPicker
            apps={library?.apps ?? []}
            picked={picked}
            filter={filter}
            onFilter={setFilter}
            onPick={(entry) => {
              setPicked(entry)
              setEnvDraft({})
              // The name is the hostname, so the entry's own is the right
              // default — and it is still editable above.
              if (!name.trim()) setName(entry.slug)
            }}
            onClear={() => {
              setPicked(null)
              setEnvDraft({})
              setFilter('')
            }}
            env={envDraft}
            onEnv={(key, value) => setEnvDraft((current) => ({ ...current, [key]: value }))}
          />
        ) : null}

        {kind === 'git' ? (
          <>
            <div>
              <Field
                label="Repository"
                value={repo}
                placeholder="https://github.com/you/storefront"
                onChange={(event) => setRepo(event.target.value)}
              />
              <div className="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-xs text-ink-3">
                <span>Needs a Dockerfile at its root, and nothing else.</span>
                <CopyButton value={prompt} label="Copy a prompt that writes one" />
              </div>
            </div>
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
        ) : kind === 'image' ? (
          <Field
            label="Image"
            value={image}
            placeholder="ghcr.io/you/storefront:1.4.0"
            onChange={(event) => setImage(event.target.value)}
            hint="Pulled as-is. Nothing is built."
          />
        ) : null}

        {kind === 'library' ? null : (
          <Field
            label="Port"
            value={port}
            placeholder="3000"
            onChange={(event) => setPort(event.target.value.replace(/[^\d]/g, ''))}
            hint={
              kind === 'git'
                ? 'Only a fallback: EXPOSE in the Dockerfile, or port in cubicle.json, wins.'
                : 'Only a fallback: used when the image does not EXPOSE exactly one port.'
            }
          />
        )}

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

/**
 * The catalogue, inside the dialog.
 *
 * Picking an entry fills in the image, the port, the volumes and whatever
 * environment it can work out for itself — so the common case is a name and a
 * click. What is left on screen afterwards is only what genuinely needs a
 * person: a timezone, a sign-up policy, occasionally nothing at all.
 */
function LibraryPicker({
  apps,
  picked,
  filter,
  onFilter,
  onPick,
  onClear,
  env,
  onEnv,
}: {
  apps: LibraryApp[]
  picked: LibraryApp | null
  filter: string
  onFilter: (value: string) => void
  onPick: (entry: LibraryApp) => void
  onClear: () => void
  env: Record<string, string>
  onEnv: (key: string, value: string) => void
}) {
  const needle = filter.trim().toLowerCase()
  const shown = needle
    ? apps.filter((entry) =>
        `${entry.name} ${entry.summary} ${entry.category}`.toLowerCase().includes(needle),
      )
    : apps

  if (picked) {
    // Only what is genuinely a choice. Fixed plumbing and values derived from
    // the app's own address are applied without a word about them.
    const asks = picked.env.filter((spec) => spec.prompt)

    return (
      <div className="grid gap-3">
        <div className="flex items-start gap-3 rounded-[10px] border border-accent bg-accent-soft px-3.5 py-3">
          <div className="min-w-0 flex-1">
            <div className="text-[13.5px] font-semibold">{picked.name}</div>
            <div className="mt-0.5 text-[12.5px] leading-relaxed text-ink-2">
              {picked.summary}
            </div>
            <div className="mt-1.5 font-mono text-[11px] text-ink-3">
              {picked.image} · :{picked.port} · {picked.memory_mb} MB
              {picked.volumes.length
                ? ` · ${picked.volumes.length} volume${picked.volumes.length === 1 ? '' : 's'}`
                : ''}
              {picked.links.length ? ` · links ${picked.links.join(', ')}` : ''}
            </div>
          </div>
          <Button size="sm" variant="ghost" className="flex-none" onClick={onClear}>
            Change
          </Button>
        </div>

        {picked.requires ? (
          <div className="rounded-[9px] border border-line bg-panel-2 px-3.5 py-2.5 text-[12.5px] text-ink-2">
            {picked.requires}
          </div>
        ) : null}

        {asks.map((spec) => (
          <Field
            key={spec.key}
            label={spec.label}
            type={spec.secret ? 'password' : 'text'}
            value={env[spec.key] ?? ''}
            placeholder={
              spec.generated ? 'generated if left blank' : spec.value || spec.key
            }
            onChange={(event) => onEnv(spec.key, event.target.value)}
            hint={spec.help}
          />
        ))}
      </div>
    )
  }

  return (
    <div className="grid gap-2.5">
      <input
        value={filter}
        autoFocus
        onChange={(event) => onFilter(event.target.value)}
        placeholder="Search the library…"
        className="h-9 w-full rounded-[9px] border border-line-strong bg-bg px-3 text-[13px] text-ink outline-none placeholder:text-ink-3 focus:border-accent"
      />
      <div className="grid max-h-[320px] gap-2 overflow-y-auto pr-1">
        {shown.map((entry) => (
          <button
            key={entry.slug}
            type="button"
            onClick={() => onPick(entry)}
            className="rounded-[10px] border border-line px-3.5 py-2.5 text-left transition hover:border-line-strong hover:bg-panel-2"
          >
            <span className="flex items-baseline gap-2">
              <span className="text-[13.5px] font-semibold">{entry.name}</span>
              <span className="text-[11px] text-ink-3">{entry.category}</span>
              <span className="ml-auto font-mono text-[11px] text-ink-3">
                {entry.memory_mb} MB
              </span>
            </span>
            <span className="mt-0.5 block text-[12.5px] leading-relaxed text-ink-2">
              {entry.summary}
            </span>
          </button>
        ))}
        {shown.length === 0 ? (
          <span className="px-1 py-6 text-center text-[13px] text-ink-3">
            Nothing matches that. Deploy it from an image or a repository instead.
          </span>
        ) : null}
      </div>
    </div>
  )
}
