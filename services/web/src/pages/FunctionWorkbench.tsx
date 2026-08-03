import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { AiSidebar } from '../components/AiSidebar'
import { CodeEditor } from '../components/CodeEditor'
import { Bars, Bolt, ChevronLeft, Play } from '../components/Icons'
import {
  Badge,
  Button,
  Card,
  Checkbox,
  Chip,
  ConfirmButton,
  CopyButton,
  MethodBadge,
  PAGE,
  Skeleton,
  StatusDot,
  Tabs,
  cx,
  useToast,
} from '../components/ui'
import {
  useClearContext,
  useContextState,
  useDeleteFunction,
  useDeployFunction,
  useDestroyIsolate,
  useFunction,
  useFunctionIsolates,
  useGroups,
  useTestInvoke,
  useUpdateFunction,
} from '../lib/hooks'
import { useGroupSession } from '../lib/session'
import { CTX_LABEL, FUNCTION_TYPE_LABEL, RUNTIME_LABEL, statusTone } from '../lib/format'
import type { CtxAccess, FunctionType, Method, Runtime, TestResult } from '../lib/types'

const METHODS: Method[] = ['GET', 'POST', 'PUT', 'DELETE']
const RUNTIMES: Runtime[] = ['python312', 'python311']
const CTX_MODES: CtxAccess[] = ['rw', 'r', 'w', 'none']
const FUNCTION_TYPES: FunctionType[] = ['dependent', 'independent']
const MEMORY = [128, 256, 512, 1024]
const TIMEOUTS = [5, 30, 60, 300]
const MAX_INSTANCES = [1, 2, 4, 8]

//: 0 defers to the instance-wide TTL, which is what every function did before
//: this setting existed. The rest span seconds to minutes, which is the range
//: worth choosing in — anything longer is what the instance default is for.
const KILL_TIMES = [0, 15, 30, 60, 300, 900]
const KILL_MIN = 5
const KILL_MAX = 3600

function killLabel(seconds: number) {
  if (seconds % 60 === 0 && seconds >= 60) return `${seconds / 60}m`
  if (seconds < 60) return `${seconds}s`
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
}
const FILES = ['handler.py', 'requirements.txt', 'cubicle.toml', 'README.md'] as const

const TABS = ['code', 'test', 'instances', 'settings'] as const

/** `httpx==0.28.1` and `httpx>=0.27` are the same requirement, differently pinned. */
const pkgName = (line: string) =>
  line
    .split(/[<>=!~[\s]/)[0]
    .trim()
    .toLowerCase()
type Tab = (typeof TABS)[number]
type FileName = (typeof FILES)[number]

/**
 * One function, full width: its code, a request runner and its settings.
 *
 * Split out of the group page so the editor gets the whole viewport instead of
 * whatever is left under the function list. The tab and the open file live in
 * the URL, so a particular file of a particular function is a link you can
 * send someone.
 */
export default function FunctionWorkbench() {
  const { groupId = '', functionId = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const toast = useToast()

  const { data: groups } = useGroups()
  const group = groups?.find((entry) => entry.id === groupId)
  const [session, newSession] = useGroupSession(groupId)

  const { data: fn, isLoading } = useFunction(functionId, {
    refetchInterval: (query) =>
      query.state.data && ['pending', 'building'].includes(query.state.data.version_status)
        ? 2000
        : false,
  })
  const update = useUpdateFunction(functionId)
  const deploy = useDeployFunction(functionId)
  const remove = useDeleteFunction()
  const test = useTestInvoke(functionId)
  const { data: context } = useContextState(groupId, session)
  const clearContext = useClearContext(groupId)

  const tab: Tab = TABS.includes(params.get('tab') as Tab) ? (params.get('tab') as Tab) : 'code'
  const file: FileName = FILES.includes(params.get('file') as FileName)
    ? (params.get('file') as FileName)
    : 'handler.py'

  const patch = (changes: Record<string, string | null>) => {
    const updated = new URLSearchParams(params)
    for (const [key, value] of Object.entries(changes)) {
      if (value === null) updated.delete(key)
      else updated.set(key, value)
    }
    setParams(updated, { replace: true })
  }

  const [aiOpen, setAiOpen] = useState(false)
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [requestBody, setRequestBody] = useState('{\n  "amount": 4200,\n  "currency": "usd"\n}')
  const [result, setResult] = useState<TestResult | null>(null)

  useEffect(() => {
    setDrafts({})
    setResult(null)
  }, [functionId])

  if (isLoading || !fn || !group) {
    return (
      <div className={cx(PAGE, 'space-y-4')}>
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-96 w-full" />
      </div>
    )
  }

  const saved = fn.files?.[file] ?? ''
  const value = drafts[file] ?? saved
  const dirty = value !== saved
  const endpoint = `${group.base_url}${fn.name}`

  const save = () => {
    const changed: Record<string, string> = {}
    for (const name of FILES) {
      if (drafts[name] !== undefined && drafts[name] !== fn.files[name])
        changed[name] = drafts[name]
    }
    if (Object.keys(changed).length === 0) {
      toast.push('No changes to deploy', 'info')
      return
    }
    // The builder rebuilds from the files it is given; the handler always has
    // to be among them even when only requirements changed.
    if (!changed['handler.py']) changed['handler.py'] = fn.files['handler.py']

    deploy.mutate(changed, {
      onSuccess: (next) => {
        setDrafts({})
        if (next.version_status === 'failed') {
          toast.push('Build failed — see the build log', 'err')
        } else {
          toast.push(`Deployed version ${next.version}`, 'ok', `${next.build_ms}ms`)
        }
      },
      onError: (error) => toast.push(error.message, 'err'),
    })
  }

  const send = () => {
    let parsed: unknown = null
    if (requestBody.trim()) {
      try {
        parsed = JSON.parse(requestBody)
      } catch {
        toast.push('Request body is not valid JSON', 'err')
        return
      }
    }
    test.mutate(
      { body: parsed, session_id: session },
      { onSuccess: setResult, onError: (error) => toast.push(error.message, 'err') },
    )
  }

  return (
    <div className={PAGE}>
      <Link
        to={`/console/playground/${groupId}`}
        className="mb-3.5 inline-flex items-center gap-1.5 text-[13px] text-ink-2 transition hover:text-ink"
      >
        <ChevronLeft size={14} />
        {group.name}
      </Link>

      <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-3">
          <span className="mt-1.5">
            <StatusDot tone={statusTone(fn.status)} />
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="m-0 text-[23px] tracking-[-0.02em]">{fn.name}</h1>
              <MethodBadge method={fn.method} />
              <span
                className="font-mono text-[11.5px]"
                style={{
                  color:
                    fn.version_status === 'ready'
                      ? 'var(--ok)'
                      : fn.version_status === 'failed'
                        ? 'var(--err)'
                        : 'var(--warn)',
                }}
              >
                v{fn.version} · {fn.version_status}
              </span>
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-2 font-mono text-[12.5px] text-ink-2">
              <span className="break-all">{endpoint}</span>
              <CopyButton value={endpoint} label="" />
              <span>· {fn.runtime_label}</span>
            </div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={fn.auth_required ? 'neutral' : 'warn'}>
            {fn.auth_required ? 'API key required' : 'public endpoint'}
          </Badge>
          <Link to={`/console/functions/${functionId}`}>
            <Button icon={<Bars size={14} />}>Metrics &amp; logs</Button>
          </Link>
        </div>
      </div>

      <Tabs
        value={tab}
        onChange={(next) => patch({ tab: next === 'code' ? null : next })}
        className="mb-5"
        tabs={[
          { value: 'code', label: 'Code' },
          { value: 'test', label: 'Test' },
          { value: 'instances', label: 'Instances' },
          { value: 'settings', label: 'Settings' },
        ]}
      />

      {tab === 'code' ? (
        <Card className="overflow-hidden">
          <div className="flex flex-wrap items-center gap-2 border-b border-line bg-panel-2 px-5 py-2.5">
            {FILES.map((name) => (
              <button
                key={name}
                type="button"
                onClick={() => patch({ file: name === 'handler.py' ? null : name })}
                className={cx(
                  'rounded-md border px-2.5 py-1 font-mono text-xs transition',
                  file === name
                    ? 'border-accent bg-accent-soft text-ink'
                    : 'border-line text-ink-2 hover:text-ink',
                )}
              >
                {name}
                {drafts[name] !== undefined && drafts[name] !== fn.files[name] ? (
                  <span className="ml-1 text-warn">•</span>
                ) : null}
              </button>
            ))}
            <span
              className="ml-auto text-xs"
              style={{ color: dirty ? 'var(--warn)' : 'var(--text-3)' }}
            >
              {dirty ? 'unsaved changes' : 'in sync with cluster'}
            </span>
            <button
              type="button"
              onClick={() => setAiOpen(true)}
              title="Describe a change and it writes the handler"
              className={cx(
                'flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-semibold transition',
                aiOpen
                  ? 'border-accent bg-accent-soft text-ink'
                  : 'border-line text-ink-2 hover:border-accent hover:text-ink',
              )}
            >
              <Bolt size={12} className="text-accent" />
              Cubicle AI
            </button>
          </div>

          <div className="border-b border-line">
            <CodeEditor
              value={value}
              language={file.endsWith('.py') ? 'python' : 'text'}
              minHeight={460}
              onChange={(next) => setDrafts((current) => ({ ...current, [file]: next }))}
            />
          </div>

          <div className="flex flex-wrap items-center gap-2.5 px-5 py-3.5">
            <Button
              variant={dirty ? 'primary' : 'ghost'}
              loading={deploy.isPending}
              onClick={save}
            >
              Save &amp; deploy
            </Button>
            <Button
              variant="ghost"
              disabled={!dirty}
              onClick={() =>
                setDrafts((current) => {
                  const next = { ...current }
                  delete next[file]
                  return next
                })
              }
            >
              Revert
            </Button>
            <span className="ml-auto text-[12.5px] text-ink-3">
              {fn.stats.last_deploy ? `deployed ${fn.stats.last_deploy}` : 'not deployed yet'}
              {fn.build_ms ? ` · build ${(fn.build_ms / 1000).toFixed(1)}s` : ''}
            </span>
          </div>

          {fn.version_status === 'failed' && fn.build_log ? (
            <pre className="m-0 max-h-64 overflow-auto border-t border-line bg-err-bg px-5 py-4 font-mono text-[12px] leading-relaxed whitespace-pre-wrap text-ink">
              {fn.build_log}
            </pre>
          ) : null}
        </Card>
      ) : null}

      {tab === 'test' ? (
        <>
          <Card className="overflow-hidden">
            <div className="flex flex-wrap items-center gap-2.5 border-b border-line px-5 py-4">
              <MethodBadge method={fn.method} />
              <span className="min-w-[220px] flex-1 overflow-x-auto rounded-[9px] border border-line bg-bg px-3.5 py-2.5 font-mono text-[12.5px] whitespace-nowrap">
                {endpoint}
              </span>
              <Button
                variant="primary"
                onClick={send}
                loading={test.isPending}
                icon={<Play size={13} />}
                disabled={fn.version_status !== 'ready'}
              >
                {test.isPending ? 'Sending…' : 'Send'}
              </Button>
            </div>

            <div className="grid lg:grid-cols-2">
              <div className="border-b border-line px-5 py-4 lg:border-r lg:border-b-0">
                <div className="mb-2.5 text-[11.5px] font-bold tracking-[0.05em] text-ink-3 uppercase">
                  Request body
                </div>
                <textarea
                  value={requestBody}
                  spellCheck={false}
                  onChange={(event) => setRequestBody(event.target.value)}
                  className="min-h-[240px] w-full resize-y rounded-[9px] border border-line bg-bg px-3.5 py-3 font-mono text-[12.5px] leading-relaxed text-ink outline-none focus:border-accent"
                />
                <div className="mt-2 font-mono text-[11.5px] text-ink-3">
                  X-Cubicle-Session: {session}
                </div>
              </div>
              <div className="px-5 py-4">
                <div className="mb-2.5 flex items-center justify-between">
                  <div className="text-[11.5px] font-bold tracking-[0.05em] text-ink-3 uppercase">
                    Response
                  </div>
                  <div
                    className="font-mono text-[11.5px]"
                    style={{
                      color: !result
                        ? 'var(--text-3)'
                        : result.status_code < 400
                          ? 'var(--ok)'
                          : 'var(--err)',
                    }}
                  >
                    {test.isPending
                      ? 'running…'
                      : result
                        ? `${result.status_code} · ${result.duration_ms.toFixed(0)}ms${result.cold ? ' · cold start' : ''}`
                        : '—'}
                  </div>
                </div>
                <pre className="m-0 max-h-[320px] overflow-auto font-mono text-[12.5px] leading-relaxed whitespace-pre-wrap text-ink-2">
                  {result
                    ? JSON.stringify(result.body, null, 2)
                    : 'Send a request to see the response.'}
                </pre>
                {result?.logs.length ? (
                  <div className="mt-3 border-t border-line pt-3">
                    <div className="mb-1.5 text-[11.5px] font-bold tracking-[0.05em] text-ink-3 uppercase">
                      Handler output
                    </div>
                    <pre className="m-0 max-h-40 overflow-auto font-mono text-[11.5px] leading-relaxed whitespace-pre-wrap text-ink-2">
                      {result.logs.join('\n')}
                    </pre>
                  </div>
                ) : null}
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-5 border-t border-line bg-panel-2 px-5 py-3.5">
              <div className="flex items-center gap-2">
                <span className="text-[11.5px] font-bold tracking-[0.05em] text-ink-3 uppercase">
                  ctx read
                </span>
                <span className="font-mono text-[12.5px] text-info">
                  {result?.context_read.length ? result.context_read.join(', ') : '—'}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-[11.5px] font-bold tracking-[0.05em] text-ink-3 uppercase">
                  ctx wrote
                </span>
                <span className="font-mono text-[12.5px] text-ok">
                  {result?.context_wrote.length ? result.context_wrote.join(', ') : '—'}
                </span>
              </div>
            </div>
          </Card>

          <Card className="mt-5 overflow-hidden">
            <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-4">
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold">
                  Runtime context <Badge tone="accent">{session}</Badge>
                </div>
                <div className="mt-0.5 text-[12.5px] text-ink-2">
                  {context ? Object.keys(context.data).length : 0} key
                  {context && Object.keys(context.data).length === 1 ? '' : 's'} ·{' '}
                  {context?.size_bytes ?? 0} B · shared with every function in{' '}
                  <span className="font-mono">{group.ns}</span>
                </div>
              </div>
              <Button size="sm" variant="ghost" onClick={newSession}>
                New session
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() =>
                  clearContext.mutate(session, {
                    onSuccess: () => toast.push('Context cleared'),
                  })
                }
              >
                Clear
              </Button>
            </div>
            <pre className="m-0 max-h-64 overflow-auto px-5 py-4 font-mono text-[12.5px] leading-[1.65] whitespace-pre-wrap text-ink-2">
              {context && Object.keys(context.data).length
                ? JSON.stringify(context.data, null, 2)
                : '{}'}
            </pre>
          </Card>
        </>
      ) : null}

      {tab === 'instances' ? (
        <Instances functionId={functionId} name={fn.name} live={tab === 'instances'} />
      ) : null}

      {/* The assistant only ever produces a draft; deploying stays a
              deliberate second action, exactly as it is for typed changes. */}
      <AiSidebar
        open={aiOpen}
        onClose={() => setAiOpen(false)}
        functionId={functionId}
        currentCode={drafts['handler.py'] ?? fn.files?.['handler.py'] ?? ''}
        requirements={drafts['requirements.txt'] ?? fn.files?.['requirements.txt'] ?? ''}
        sessionId={session}
        onApply={(code, packages) =>
          setDrafts((current) => {
            const next: Record<string, string> = { ...current, 'handler.py': code }
            if (packages.length) {
              const existing = (
                current['requirements.txt'] ??
                fn.files?.['requirements.txt'] ??
                ''
              )
                .split('\n')
                .map((line) => line.trim())
                .filter(Boolean)
              // Merge by package name so a re-pin replaces rather than doubles.
              const byName = new Map(existing.map((line) => [pkgName(line), line]))
              for (const line of packages) byName.set(pkgName(line), line)
              next['requirements.txt'] = [...byName.values()].join('\n') + '\n'
            }
            return next
          })
        }
      />

      {tab === 'settings' ? (
        <Card className="grid gap-5 p-5">
          <ChipGroup
            label="Method"
            options={METHODS}
            value={fn.method}
            onChange={(method) => update.mutate({ method })}
          />
          <ChipGroup
            label="Runtime"
            options={RUNTIMES}
            value={fn.runtime}
            onChange={(runtime) => update.mutate({ runtime })}
            render={(option) => RUNTIME_LABEL[option]}
            hint="Changing the interpreter rebuilds the current version."
          />
          <ChipGroup
            label="Type"
            hint="A label for whoever reads this namespace next. Nothing is enforced: an independent function sent a body still receives it."
            options={FUNCTION_TYPES}
            value={fn.function_type}
            onChange={(function_type) => update.mutate({ function_type })}
            render={(option) => FUNCTION_TYPE_LABEL[option]}
          />
          <ChipGroup
            label="Runtime context access"
            options={CTX_MODES}
            value={fn.ctx_access}
            onChange={(ctx_access) => update.mutate({ ctx_access })}
            render={(option) => CTX_LABEL[option]}
          />
          <div className="grid gap-5 sm:grid-cols-2">
            <ChipGroup
              label="Memory"
              options={MEMORY}
              value={fn.memory_mb}
              onChange={(memory_mb) => update.mutate({ memory_mb })}
              render={(option) => (option >= 1024 ? `${option / 1024} GB` : `${option} MB`)}
            />
            <ChipGroup
              label="Timeout"
              options={TIMEOUTS}
              value={fn.timeout_s}
              onChange={(timeout_s) => update.mutate({ timeout_s })}
              render={(option) => `${option}s`}
            />
          </div>
          <div className="grid gap-5 sm:grid-cols-2">
            <ChipGroup
              label="Warm instances"
              hint="Above zero keeps isolates resident, trading held memory for no cold starts."
              options={[0, 1, 2]}
              value={fn.min_instances}
              onChange={(min_instances) => update.mutate({ min_instances })}
              render={(option) => (option === 0 ? 'scale to zero' : `${option} warm`)}
            />
            <ChipGroup
              label="Max instances"
              hint="The ceiling on concurrent isolates. Requests past it wait for a free one rather than starting another container."
              options={MAX_INSTANCES}
              value={fn.max_instances}
              onChange={(max_instances) => update.mutate({ max_instances })}
              render={(option) => `${option} max`}
            />
            <KillTime
              value={fn.idle_timeout_s}
              fallback={fn.effective_idle_timeout_s}
              onChange={(idle_timeout_s) => update.mutate({ idle_timeout_s })}
            />
          </div>
          <div className="rounded-[9px] border border-line bg-panel-2 px-3.5 py-2.5 text-[12.5px] text-ink-2">
            At most <span className="font-mono font-semibold text-ink">{fn.max_instances}</span>{' '}
            request
            {fn.max_instances === 1 ? '' : 's'} run concurrently, each in its own container with{' '}
            <span className="font-mono">{fn.memory_mb} MB</span> — up to{' '}
            <span className="font-mono font-semibold text-ink">
              {(fn.max_instances * fn.memory_mb) / 1024 >= 1
                ? `${((fn.max_instances * fn.memory_mb) / 1024).toFixed(1)} GB`
                : `${fn.max_instances * fn.memory_mb} MB`}
            </span>{' '}
            held by this function at peak.
          </div>

          <div className="border-t border-line pt-4">
            <Checkbox
              checked={fn.auth_required}
              onChange={(auth_required) => update.mutate({ auth_required })}
              label="Require an API key to invoke this endpoint. Turn off for public webhooks."
            />
          </div>

          <div className="flex items-center gap-3 border-t border-line pt-4">
            <span className="text-[12.5px] text-ink-3">
              {update.isPending ? 'Saving…' : 'Changes apply immediately.'}
            </span>
            <span className="ml-auto">
              <ConfirmButton
                label="Delete function"
                confirmLabel="Click again to delete"
                onConfirm={() =>
                  remove.mutate(functionId, {
                    onSuccess: () => {
                      toast.push(`${fn.name} deleted`)
                      navigate(`/console/playground/${groupId}`)
                    },
                  })
                }
              />
            </span>
          </div>
        </Card>
      ) : null}
    </div>
  )
}

/**
 * The containers serving this function right now.
 *
 * Polled while the tab is open rather than streamed: this is a handful of
 * rows that change on the scale of seconds, and a second SSE connection per
 * function page would cost more than it is worth.
 */
function Instances({
  functionId,
  name,
  live,
}: {
  functionId: string
  name: string
  live: boolean
}) {
  const toast = useToast()
  const { data, isLoading } = useFunctionIsolates(functionId, live)
  const destroy = useDestroyIsolate(functionId)
  const [pending, setPending] = useState<string | null>(null)

  if (isLoading || !data) return <Skeleton className="h-40 w-full" />

  const busy = data.isolates.filter((isolate) => isolate.busy).length

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-3.5">
        <div>
          <div className="text-sm font-semibold">
            {data.isolates.length} running instance{data.isolates.length === 1 ? '' : 's'}
            {busy > 0 ? (
              <span className="font-normal text-ink-2"> · {busy} working</span>
            ) : null}
          </div>
          <div className="mt-0.5 text-[12.5px] text-ink-2">
            One container per concurrent request · {data.min_instances} warm ·{' '}
            {data.max_instances} max · {data.memory_mb} MB each
          </div>
        </div>
        <Badge tone={data.isolates.length ? 'accent' : 'neutral'}>
          {data.isolates.length
            ? `${
                (data.isolates.length * data.memory_mb) / 1024 >= 1
                  ? `${((data.isolates.length * data.memory_mb) / 1024).toFixed(1)} GB`
                  : `${data.isolates.length * data.memory_mb} MB`
              } held`
            : 'scaled to zero'}
        </Badge>
      </div>

      {data.isolates.length === 0 ? (
        <div className="px-5 py-10 text-center text-[13px] text-ink-3">
          Nothing running — this function is scaled to zero.
          <div className="mt-1 text-[12px]">
            The next request starts a container; it appears here while it boots.
          </div>
        </div>
      ) : (
        <>
          <div className="hidden grid-cols-[130px_84px_1fr_90px_90px_92px] gap-3 border-b border-line px-5 py-2.5 text-[11px] font-bold tracking-[0.05em] text-ink-3 uppercase sm:grid">
            <span>Container</span>
            <span>State</span>
            <span>Node</span>
            <span>Requests</span>
            <span>Idle</span>
            <span />
          </div>
          {data.isolates.map((isolate) => (
            <div
              key={isolate.id}
              className="grid grid-cols-1 items-center gap-3 border-b border-line px-5 py-3 text-[13px] last:border-b-0 sm:grid-cols-[130px_84px_1fr_90px_90px_92px]"
            >
              <span className="font-mono text-[12.5px]">{isolate.id}</span>
              <span className="flex items-center gap-1.5">
                <span
                  className={cx(
                    'h-1.5 w-1.5 rounded-full',
                    isolate.busy && 'animate-pulse-dot',
                  )}
                  style={{ background: isolate.busy ? 'var(--accent)' : 'var(--ok)' }}
                />
                {isolate.busy ? 'working' : 'idle'}
              </span>
              <span className="truncate font-mono text-[12px] text-ink-2">
                {isolate.node} · {isolate.cpus.toFixed(2)} vCPU
              </span>
              <span className="font-mono text-ink-2">{isolate.invocations}</span>
              <span className="font-mono text-ink-2">
                {isolate.idle_s < 60
                  ? `${Math.round(isolate.idle_s)}s`
                  : `${Math.round(isolate.idle_s / 60)}m`}
              </span>
              <span className="flex justify-end">
                <ConfirmButton
                  label={pending === isolate.id ? 'Destroying…' : 'Destroy'}
                  confirmLabel={isolate.busy ? 'Kill mid-request' : 'Click again'}
                  onConfirm={() => {
                    if (pending) return
                    setPending(isolate.id)
                    destroy.mutate(isolate.id, {
                      onSuccess: () => toast.push(`Instance ${isolate.id} destroyed`),
                      onError: (error) => toast.push(error.message, 'err'),
                      onSettled: () => setPending(null),
                    })
                  }}
                />
              </span>
            </div>
          ))}
        </>
      )}

      <div className="border-t border-line px-5 py-3 text-[12.5px] text-ink-3">
        Destroying an instance does not stop <span className="font-mono">{name}</span> — the
        next request finds another warm one or starts a replacement. An instance that is working
        loses the request it is serving.
      </div>
    </Card>
  )
}

/**
 * How long an idle instance may live, in the range worth choosing in.
 *
 * Presets cover seconds to minutes; anything beyond that is what the instance
 * default is for. The field takes a value that is not on the list, because the
 * right number here depends on how often a particular function is called and
 * no set of presets will guess it.
 *
 * Committed on blur or Enter rather than per keystroke: this saves immediately,
 * and typing "300" would otherwise apply 3, then 30, then 300.
 */
function KillTime({
  value,
  fallback,
  onChange,
}: {
  value: number
  fallback: number
  onChange: (next: number) => void
}) {
  const [draft, setDraft] = useState('')
  const custom = value !== 0 && !KILL_TIMES.includes(value)

  // Adopt the stored value when it changes underneath — another tab, or a
  // preset clicked after something custom was typed.
  useEffect(() => setDraft(custom ? String(value) : ''), [value, custom])

  const commit = () => {
    const seconds = Number(draft)
    if (!draft.trim() || !Number.isFinite(seconds)) {
      setDraft(custom ? String(value) : '')
      return
    }
    const clamped = Math.round(Math.min(KILL_MAX, Math.max(KILL_MIN, seconds)))
    setDraft(String(clamped))
    if (clamped !== value) onChange(clamped)
  }

  return (
    <div>
      <span className="mb-2 block text-[12.5px] text-ink-2">Kill time</span>
      <div className="mb-2 text-[12.5px] text-ink-3">
        How long an instance may sit idle before it is reclaimed. Shorter frees memory sooner;
        longer avoids the next cold start.
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {KILL_TIMES.map((option) => (
          <Chip
            key={option}
            active={value === option}
            onClick={() => onChange(option)}
          >
            {option === 0 ? `default (${killLabel(fallback)})` : killLabel(option)}
          </Chip>
        ))}

        <span
          className={cx(
            'flex items-center gap-1.5 rounded-full border px-2.5 py-1 transition',
            custom ? 'border-accent bg-accent-soft' : 'border-line',
          )}
        >
          <input
            type="number"
            inputMode="numeric"
            min={KILL_MIN}
            max={KILL_MAX}
            value={draft}
            placeholder="custom"
            aria-label="Custom kill time in seconds"
            onChange={(event) => setDraft(event.target.value)}
            onBlur={commit}
            onKeyDown={(event) => {
              if (event.key === 'Enter') event.currentTarget.blur()
            }}
            className="w-[68px] border-0 bg-transparent p-0 font-mono text-[12px] text-ink outline-none placeholder:text-ink-3"
          />
          <span className="text-[12px] text-ink-3">s</span>
        </span>
      </div>

      <div className="mt-1.5 text-[12px] text-ink-3">
        {custom ? `${killLabel(value)} — ` : ''}
        {KILL_MIN}s to {killLabel(KILL_MAX)}.
      </div>
    </div>
  )
}

function ChipGroup<T extends string | number>({
  label,
  hint,
  options,
  value,
  onChange,
  render,
}: {
  label: string
  hint?: string
  options: readonly T[]
  value: T
  onChange: (next: T) => void
  render?: (option: T) => string
}) {
  return (
    <div>
      <span className="mb-2 block text-[12.5px] text-ink-2">{label}</span>
      {hint ? <div className="mb-2 text-[12.5px] text-ink-3">{hint}</div> : null}
      <div className="flex flex-wrap gap-2">
        {options.map((option) => (
          <Chip key={option} active={value === option} onClick={() => onChange(option)}>
            {render ? render(option) : String(option)}
          </Chip>
        ))}
      </div>
    </div>
  )
}
