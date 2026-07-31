import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { CodeEditor } from '../components/CodeEditor'
import { ChevronLeft, Play, Plus } from '../components/Icons'
import {
  Badge,
  Button,
  Card,
  Checkbox,
  Chip,
  ConfirmButton,
  CopyButton,
  EmptyState,
  Field,
  MethodBadge,
  Skeleton,
  Tabs,
  cx,
  useToast,
} from '../components/ui'
import {
  useClearContext,
  useContextState,
  useCreateFunction,
  useDeleteFunction,
  useDeleteGroup,
  useDeployFunction,
  useFunction,
  useFunctions,
  useGroups,
  useTestInvoke,
  useUpdateFunction,
} from '../lib/hooks'
import { CTX_LABEL, RUNTIME_LABEL, newSessionId, slugify } from '../lib/format'
import type { CtxAccess, Method, Runtime, TestResult } from '../lib/types'

const METHODS: Method[] = ['GET', 'POST', 'PUT', 'DELETE']
const RUNTIMES: Runtime[] = ['python312', 'python311']
const CTX_MODES: CtxAccess[] = ['rw', 'r', 'w', 'none']
const MEMORY = [128, 256, 512, 1024]
const TIMEOUTS = [5, 30, 60, 300]
const FILES = ['handler.py', 'requirements.txt', 'cubicle.toml', 'README.md'] as const

export default function PlaygroundGroup() {
  const { groupId = '' } = useParams()
  const navigate = useNavigate()
  const toast = useToast()

  const { data: groups } = useGroups()
  const group = groups?.find((entry) => entry.id === groupId)
  const { data: functions, isLoading } = useFunctions(groupId)
  const deleteGroup = useDeleteGroup()
  const deleteFunction = useDeleteFunction()

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [session, setSession] = useState(newSessionId)
  const [creating, setCreating] = useState(false)

  const [fnName, setFnName] = useState('')
  const [fnMethod, setFnMethod] = useState<Method>('POST')
  const [fnRuntime, setFnRuntime] = useState<Runtime>('python312')
  const [fnCtx, setFnCtx] = useState<CtxAccess>('rw')

  const createFunction = useCreateFunction(groupId)
  const { data: context } = useContextState(groupId, session)
  const clearContext = useClearContext(groupId)

  useEffect(() => {
    if (functions && functions.length > 0 && !selectedId) setSelectedId(functions[0].id)
    if (functions && functions.length === 0) setSelectedId(null)
  }, [functions, selectedId])

  if (!group) {
    return (
      <div className="mx-auto max-w-[1100px] px-5 py-7 sm:px-8">
        <Skeleton className="h-8 w-56" />
      </div>
    )
  }

  const submitNew = () => {
    createFunction.mutate(
      {
        name: slugify(fnName),
        method: fnMethod,
        runtime: fnRuntime,
        ctx_access: fnCtx,
      },
      {
        onSuccess: (fn) => {
          toast.push(`${fn.name} created`, 'ok', 'building')
          setCreating(false)
          setFnName('')
          setSelectedId(fn.id)
        },
        onError: (error) => toast.push(error.message, 'err'),
      },
    )
  }

  return (
    <div className="mx-auto max-w-[1100px] px-5 py-7 sm:px-8">
      <Link
        to="/console/playground"
        className="mb-3.5 inline-flex items-center gap-1.5 text-[13px] text-ink-2 transition hover:text-ink"
      >
        <ChevronLeft size={14} />
        All groups
      </Link>

      <div className="mb-2 flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <h1 className="m-0 text-2xl tracking-[-0.02em]">{group.name}</h1>
          <div className="mt-1.5 flex items-center gap-2.5">
            <span className="text-xs text-ink-2">namespace</span>
            <Badge tone="accent">{group.ns}</Badge>
          </div>
        </div>
        <Button variant="primary" icon={<Plus size={15} />} onClick={() => setCreating(true)}>
          New function
        </Button>
      </div>

      <Card className="my-4.5 flex items-center gap-2.5 px-3.5 py-3">
        <span className="flex-none text-[11.5px] font-bold tracking-[0.05em] text-ink-3 uppercase">
          Base URL
        </span>
        <span className="flex-1 overflow-x-auto font-mono text-[12.5px] whitespace-nowrap">
          {group.base_url}
        </span>
        <CopyButton value={group.base_url} />
      </Card>

      <Card className="mb-5 flex flex-wrap items-center gap-3 px-3.5 py-3">
        <span className="flex-none text-[11.5px] font-bold tracking-[0.05em] text-ink-3 uppercase">
          Session
        </span>
        <Badge tone="accent">{session}</Badge>
        <span className="text-[12.5px] text-ink-2">
          {context ? Object.keys(context.data).length : 0} key
          {context && Object.keys(context.data).length === 1 ? '' : 's'} ·{' '}
          {context?.size_bytes ?? 0} B · ttl 30m
        </span>
        <button
          type="button"
          onClick={() => setSession(newSessionId())}
          className="ml-auto text-[12.5px] text-ink-3 transition hover:text-ink"
        >
          New session
        </button>
      </Card>

      {creating ? (
        <Card className="mb-5 border-accent p-6">
          <div className="mb-4 text-[15px] font-semibold">New function in {group.ns}</div>
          <div className="grid gap-4.5">
            <Field
              label="Function name"
              autoFocus
              value={fnName}
              placeholder="create-charge"
              onChange={(event) => setFnName(event.target.value)}
            />
            <ChipGroup
              label="Method"
              options={METHODS}
              value={fnMethod}
              onChange={setFnMethod}
            />
            <ChipGroup
              label="Runtime"
              options={RUNTIMES}
              value={fnRuntime}
              onChange={setFnRuntime}
              render={(option) => RUNTIME_LABEL[option]}
            />
            <ChipGroup
              label="Runtime context access"
              hint="What this function may do with the shared session context."
              options={CTX_MODES}
              value={fnCtx}
              onChange={setFnCtx}
              render={(option) => CTX_LABEL[option]}
            />
          </div>
          <div className="mt-4 flex items-center gap-2.5 rounded-[9px] border border-line bg-bg px-3.5 py-2.5">
            <span className="flex-none text-[11.5px] font-bold tracking-[0.05em] text-ink-3 uppercase">
              Endpoint
            </span>
            <span className="overflow-x-auto font-mono text-[12.5px] whitespace-nowrap">
              {group.base_url}
              {slugify(fnName) || 'my-function'}
            </span>
          </div>
          <div className="mt-4 flex gap-2.5">
            <Button
              variant="primary"
              loading={createFunction.isPending}
              disabled={!slugify(fnName)}
              onClick={submitNew}
            >
              Create function
            </Button>
            <Button variant="ghost" onClick={() => setCreating(false)}>
              Cancel
            </Button>
          </div>
        </Card>
      ) : null}

      {isLoading ? (
        <Skeleton className="h-32 w-full" />
      ) : functions && functions.length > 0 ? (
        <Card className="overflow-hidden">
          <div className="hidden grid-cols-[82px_1fr_1.5fr_96px_94px_60px] gap-3 border-b border-line px-5 py-3 text-[11.5px] font-semibold tracking-[0.04em] text-ink-3 uppercase md:grid">
            <span>Method</span>
            <span>Function</span>
            <span>Endpoint</span>
            <span>Runtime</span>
            <span>Context</span>
            <span />
          </div>
          {functions.map((fn) => (
            <div
              key={fn.id}
              role="button"
              tabIndex={0}
              onClick={() => setSelectedId(fn.id)}
              onKeyDown={(event) => event.key === 'Enter' && setSelectedId(fn.id)}
              className={cx(
                'grid cursor-pointer grid-cols-1 items-center gap-3 border-b border-line px-5 py-3.5 transition last:border-b-0 md:grid-cols-[82px_1fr_1.5fr_96px_94px_60px]',
                selectedId === fn.id ? 'bg-accent-soft' : 'hover:bg-panel-2',
              )}
            >
              <MethodBadge method={fn.method} />
              <div className="truncate text-sm font-semibold">
                {fn.name}
                {fn.version_status !== 'ready' ? (
                  <span
                    className="ml-2 font-mono text-[10.5px]"
                    style={{
                      color: fn.version_status === 'failed' ? 'var(--err)' : 'var(--warn)',
                    }}
                  >
                    {fn.version_status}
                  </span>
                ) : null}
              </div>
              <div className="truncate font-mono text-[12.5px] text-ink-2">{fn.path}</div>
              <div className="text-[13px] text-ink-2">{fn.runtime_label}</div>
              <div>
                <Badge>{CTX_LABEL[fn.ctx_access]}</Badge>
              </div>
              <div className="text-right">
                <ConfirmButton
                  label="Delete"
                  confirmLabel="Confirm"
                  onConfirm={() =>
                    deleteFunction.mutate(fn.id, {
                      onSuccess: () => {
                        toast.push(`${fn.name} deleted`)
                        if (selectedId === fn.id) setSelectedId(null)
                      },
                    })
                  }
                />
              </div>
            </div>
          ))}
        </Card>
      ) : (
        <EmptyState
          title="No functions in this group"
          body={
            <>
              Anything you add here is served under{' '}
              <span className="font-mono">/{group.ns}/</span>
            </>
          }
        />
      )}

      {selectedId ? (
        <FunctionPanel functionId={selectedId} session={session} baseUrl={group.base_url} />
      ) : null}

      <Card className="mt-5 overflow-hidden">
        <div className="flex items-center gap-3 border-b border-line px-5 py-4">
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold">Runtime context</div>
            <div className="mt-0.5 text-[12.5px] text-ink-2">
              Carried on <span className="font-mono">X-Cubicle-Session</span> · readable by
              every function in this namespace
            </div>
          </div>
          <button
            type="button"
            onClick={() =>
              clearContext.mutate(session, { onSuccess: () => toast.push('Context cleared') })
            }
            className="flex-none text-[12.5px] text-ink-3 transition hover:text-err"
          >
            Clear
          </button>
        </div>
        <div className="grid md:grid-cols-[1.2fr_1fr]">
          <div className="min-w-0 border-b border-line px-5 py-4 md:border-r md:border-b-0">
            <div className="mb-2.5 text-[11.5px] font-bold tracking-[0.05em] text-ink-3 uppercase">
              context.json
            </div>
            <pre className="m-0 font-mono text-[12.5px] leading-[1.65] whitespace-pre-wrap text-ink-2">
              {context && Object.keys(context.data).length
                ? JSON.stringify(context.data, null, 2)
                : '{}'}
            </pre>
          </div>
          <div className="min-w-0 px-5 py-4">
            <div className="mb-2.5 text-[11.5px] font-bold tracking-[0.05em] text-ink-3 uppercase">
              Write log
            </div>
            {context && context.log.length > 0 ? (
              <div className="flex flex-col gap-2.5">
                {context.log.map((entry, index) => (
                  <div key={index} className="flex items-baseline gap-2.5 text-[12.5px]">
                    <span className="flex-none font-mono text-[11.5px] text-ink-3">
                      {entry.time}
                    </span>
                    <div className="min-w-0">
                      <span className="font-semibold">{entry.fn}</span>{' '}
                      <span className="text-ink-2">{entry.detail}</span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-[12.5px] text-ink-3">Nothing written yet this session.</div>
            )}
          </div>
        </div>
      </Card>

      <div className="mt-4.5 flex justify-end">
        <ConfirmButton
          label="Delete group and its functions"
          confirmLabel="Click again to delete this namespace"
          onConfirm={() =>
            deleteGroup.mutate(group.id, {
              onSuccess: () => {
                toast.push(`Namespace ${group.ns} deleted`)
                navigate('/console/playground')
              },
            })
          }
        />
      </div>
    </div>
  )
}

// ── selected function ────────────────────────────────────────────────────────

function FunctionPanel({
  functionId,
  session,
  baseUrl,
}: {
  functionId: string
  session: string
  baseUrl: string
}) {
  const toast = useToast()
  const { data: fn } = useFunction(functionId, {
    refetchInterval: (query) =>
      query.state.data && ['pending', 'building'].includes(query.state.data.version_status)
        ? 2000
        : false,
  })
  const update = useUpdateFunction(functionId)
  const deploy = useDeployFunction(functionId)
  const remove = useDeleteFunction()
  const test = useTestInvoke(functionId)

  const [tab, setTab] = useState<'code' | 'test' | 'settings'>('code')
  const [file, setFile] = useState<(typeof FILES)[number]>('handler.py')
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [requestBody, setRequestBody] = useState('{\n  "amount": 4200,\n  "currency": "usd"\n}')
  const [result, setResult] = useState<TestResult | null>(null)

  const saved = fn?.files?.[file] ?? ''
  const draftKey = `${functionId}:${file}`
  const value = drafts[draftKey] ?? saved
  const dirty = value !== saved

  useEffect(() => {
    setDrafts({})
    setResult(null)
  }, [functionId])

  if (!fn) return <Skeleton className="mt-5 h-64 w-full" />

  const save = () => {
    const changed: Record<string, string> = {}
    for (const name of FILES) {
      const key = `${functionId}:${name}`
      if (drafts[key] !== undefined && drafts[key] !== fn.files[name])
        changed[name] = drafts[key]
    }
    if (Object.keys(changed).length === 0) {
      toast.push('No changes to deploy', 'info')
      return
    }
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
      {
        onSuccess: setResult,
        onError: (error) => toast.push(error.message, 'err'),
      },
    )
  }

  return (
    <Card className="mt-5 overflow-hidden">
      <div className="flex flex-wrap items-center gap-3.5 border-b border-line px-5 pt-3">
        <div className="flex items-center gap-2.5 pb-3">
          <span className="font-mono text-[13.5px] font-semibold">{fn.name}</span>
          <span className="font-mono text-[11.5px] text-ink-3">{fn.runtime_label}</span>
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
        <div className="ml-auto">
          <Tabs
            value={tab}
            onChange={setTab}
            className="border-b-0"
            tabs={[
              { value: 'code', label: 'Code' },
              { value: 'test', label: 'Test' },
              { value: 'settings', label: 'Settings' },
            ]}
          />
        </div>
      </div>

      {tab === 'code' ? (
        <>
          <div className="flex flex-wrap items-center gap-2 border-b border-line bg-panel-2 px-5 py-2.5">
            {FILES.map((name) => (
              <button
                key={name}
                type="button"
                onClick={() => setFile(name)}
                className={cx(
                  'rounded-md border px-2.5 py-1 font-mono text-xs transition',
                  file === name
                    ? 'border-accent bg-accent-soft text-ink'
                    : 'border-line text-ink-2 hover:text-ink',
                )}
              >
                {name}
                {drafts[`${functionId}:${name}`] !== undefined &&
                drafts[`${functionId}:${name}`] !== fn.files[name] ? (
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
          </div>

          <div className="border-b border-line">
            <CodeEditor
              value={value}
              language={file.endsWith('.py') ? 'python' : 'text'}
              onChange={(next) => setDrafts((current) => ({ ...current, [draftKey]: next }))}
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
              onClick={() =>
                setDrafts((current) => {
                  const next = { ...current }
                  delete next[draftKey]
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
        </>
      ) : null}

      {tab === 'test' ? (
        <>
          <div className="flex flex-wrap items-center gap-2.5 border-b border-line px-5 py-4">
            <MethodBadge method={fn.method} />
            <span className="min-w-[220px] flex-1 overflow-x-auto rounded-[9px] border border-line bg-bg px-3.5 py-2.5 font-mono text-[12.5px] whitespace-nowrap">
              {baseUrl}
              {fn.name}
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

          <div className="grid md:grid-cols-2">
            <div className="border-b border-line px-5 py-4 md:border-r md:border-b-0">
              <div className="mb-2.5 text-[11.5px] font-bold tracking-[0.05em] text-ink-3 uppercase">
                Request body
              </div>
              <textarea
                value={requestBody}
                spellCheck={false}
                onChange={(event) => setRequestBody(event.target.value)}
                className="min-h-[180px] w-full resize-y rounded-[9px] border border-line bg-bg px-3.5 py-3 font-mono text-[12.5px] leading-relaxed text-ink outline-none focus:border-accent"
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
              <pre className="m-0 max-h-[260px] overflow-auto font-mono text-[12.5px] leading-relaxed whitespace-pre-wrap text-ink-2">
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
        </>
      ) : null}

      {tab === 'settings' ? (
        <div className="grid gap-5 p-5">
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
          <ChipGroup
            label="Warm instances"
            hint="Above zero keeps isolates resident, trading held memory for no cold starts."
            options={[0, 1, 2]}
            value={fn.min_instances}
            onChange={(min_instances) => update.mutate({ min_instances })}
            render={(option) => (option === 0 ? 'scale to zero' : `${option} warm`)}
          />

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
                    onSuccess: () => toast.push(`${fn.name} deleted`),
                  })
                }
              />
            </span>
          </div>
        </div>
      ) : null}
    </Card>
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
