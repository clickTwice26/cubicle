import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ArrowRight, ChevronLeft, Plus } from '../components/Icons'
import {
  Badge,
  Button,
  Card,
  Chip,
  ConfirmButton,
  CopyButton,
  EmptyState,
  Field,
  MethodBadge,
  PAGE,
  Skeleton,
  useToast,
} from '../components/ui'
import {
  useClearContext,
  useContextState,
  useCreateFunction,
  useDeleteFunction,
  useDeleteGroup,
  useFunctions,
  useGroups,
} from '../lib/hooks'
import { useGroupSession } from '../lib/session'
import { CTX_LABEL, RUNTIME_LABEL, slugify } from '../lib/format'
import type { CtxAccess, Method, Runtime } from '../lib/types'

const METHODS: Method[] = ['GET', 'POST', 'PUT', 'DELETE']
const RUNTIMES: Runtime[] = ['python312', 'python311']
const CTX_MODES: CtxAccess[] = ['rw', 'r', 'w', 'none']

export default function PlaygroundGroup() {
  const { groupId = '' } = useParams()
  const navigate = useNavigate()
  const toast = useToast()

  const { data: groups } = useGroups()
  const group = groups?.find((entry) => entry.id === groupId)
  const { data: functions, isLoading } = useFunctions(groupId)
  const deleteGroup = useDeleteGroup()
  const deleteFunction = useDeleteFunction()

  const [session, newSession] = useGroupSession(groupId)
  const [creating, setCreating] = useState(false)

  const [fnName, setFnName] = useState('')
  const [fnMethod, setFnMethod] = useState<Method>('POST')
  const [fnRuntime, setFnRuntime] = useState<Runtime>('python312')
  const [fnCtx, setFnCtx] = useState<CtxAccess>('rw')

  const createFunction = useCreateFunction(groupId)
  const { data: context } = useContextState(groupId, session)
  const clearContext = useClearContext(groupId)

  if (!group) {
    return (
      <div className={PAGE}>
        <Skeleton className="h-8 w-56" />
      </div>
    )
  }

  const open = (functionId: string) => navigate(`/console/playground/${groupId}/${functionId}`)

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
          // Straight into the editor — a new function is an empty handler
          // waiting to be written.
          open(fn.id)
        },
        onError: (error) => toast.push(error.message, 'err'),
      },
    )
  }

  return (
    <div className={PAGE}>
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
          onClick={newSession}
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
          <div className="hidden grid-cols-[82px_minmax(140px,1fr)_minmax(0,1.5fr)_96px_94px_146px] gap-3 border-b border-line px-5 py-3 text-[11.5px] font-semibold tracking-[0.04em] text-ink-3 uppercase md:grid">
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
              onClick={() => open(fn.id)}
              onKeyDown={(event) => event.key === 'Enter' && open(fn.id)}
              className="grid cursor-pointer grid-cols-1 items-center gap-3 border-b border-line px-5 py-3.5 transition last:border-b-0 hover:bg-panel-2 md:grid-cols-[82px_minmax(140px,1fr)_minmax(0,1.5fr)_96px_94px_146px]"
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
              {/* The row is clickable, but a visible control is what tells you
                  so — and it is what keyboard users tab to. */}
              <div
                className="flex items-center justify-end gap-2"
                onClick={(event) => event.stopPropagation()}
              >
                <Button size="sm" icon={<ArrowRight size={13} />} onClick={() => open(fn.id)}>
                  View
                </Button>
                <ConfirmButton
                  label="Delete"
                  confirmLabel="Confirm"
                  onConfirm={() =>
                    deleteFunction.mutate(fn.id, {
                      onSuccess: () => toast.push(`${fn.name} deleted`),
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
