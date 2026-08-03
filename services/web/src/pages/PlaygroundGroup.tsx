import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ArrowRight, ChevronLeft, Plus, Trash } from '../components/Icons'
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
  Modal,
  PAGE,
  Skeleton,
  useToast,
} from '../components/ui'
import {
  useClearContext,
  useContextState,
  useCreateFunction,
  useRuntimes,
  useDeleteFunction,
  useDeleteGroup,
  useFunctions,
  useGroups,
} from '../lib/hooks'
import { useGroupSession } from '../lib/session'
import {
  CTX_LABEL,
  FUNCTION_TYPE_HINT,
  FUNCTION_TYPE_LABEL,
  slugify,
} from '../lib/format'
import type { CtxAccess, FunctionType, Method, Runtime } from '../lib/types'

const METHODS: Method[] = ['GET', 'POST', 'PUT', 'DELETE']

const CTX_MODES: CtxAccess[] = ['rw', 'r', 'w', 'none']
const TYPES: FunctionType[] = ['dependent', 'independent']

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
  const [deleting, setDeleting] = useState(false)

  const [fnName, setFnName] = useState('')
  const [fnMethod, setFnMethod] = useState<Method>('POST')
  const [fnRuntime, setFnRuntime] = useState<Runtime>('python312')
  const { data: runtimes } = useRuntimes()
  const installed = (runtimes ?? []).filter((entry) => entry.installed)
  const runtimeKeys = (installed.length ? installed.map((entry) => entry.key) : ['python312']) as Runtime[]
  const runtimeLabels = Object.fromEntries((runtimes ?? []).map((entry) => [entry.key, entry.label]))
  const missing = (runtimes ?? []).length - installed.length
  const [fnCtx, setFnCtx] = useState<CtxAccess>('rw')
  const [fnType, setFnType] = useState<FunctionType>('dependent')

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
        function_type: fnType,
      },
      {
        onSuccess: (fn) => {
          toast.push(`${fn.name} created`, 'ok', 'building')
          setCreating(false)
          setFnName('')
          setFnType('dependent')
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
        <div className="flex flex-wrap items-center gap-2.5">
          <Button variant="primary" icon={<Plus size={15} />} onClick={() => setCreating(true)}>
            New function
          </Button>
          <Button variant="danger" icon={<Trash size={14} />} onClick={() => setDeleting(true)}>
            Delete namespace
          </Button>
        </div>
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

      <Modal
        open={creating}
        onClose={() => setCreating(false)}
        title={`New function in ${group.ns}`}
        width={520}
        footer={
          <>
            <Button variant="ghost" onClick={() => setCreating(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              loading={createFunction.isPending}
              disabled={!slugify(fnName)}
              onClick={submitNew}
            >
              Create function
            </Button>
          </>
        }
      >
        <div className="grid gap-4.5">
          <Field
            label="Function name"
            autoFocus
            value={fnName}
            placeholder="create-charge"
            onChange={(event) => setFnName(event.target.value)}
          />
          <ChipGroup label="Method" options={METHODS} value={fnMethod} onChange={setFnMethod} />
          {/* Only what is installed. A runtime whose image is not on the node
              would fail on the first invocation, not at create time, which is
              the worst moment to find out. */}
          <ChipGroup
            label="Runtime"
            hint={
              missing
                ? `${missing} more available in Settings → Runtimes.`
                : undefined
            }
            options={runtimeKeys}
            value={fnRuntime}
            onChange={setFnRuntime}
            render={(option) => runtimeLabels[option] ?? option}
          />
          <ChipGroup
            label="Type"
            hint="A label only — nothing is refused either way. Independent means the function takes no input; dependent means a body may be sent."
            options={TYPES}
            value={fnType}
            onChange={setFnType}
            render={(option) => FUNCTION_TYPE_LABEL[option]}
          />
          <ChipGroup
            label="Runtime context access"
            hint="What this function may do with the shared session context."
            options={CTX_MODES}
            value={fnCtx}
            onChange={setFnCtx}
            render={(option) => CTX_LABEL[option]}
          />
          {/* The URL is longer than the dialog on any narrow screen. It wraps
              rather than scrolls, because a preview you have to drag sideways
              to read is not a preview. min-w-0 keeps it from widening the flex
              row it sits in — without it the whole modal scrolls. */}
          <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1 rounded-[9px] border border-line bg-bg px-3.5 py-2.5">
            <span className="flex-none text-[11.5px] font-bold tracking-[0.05em] text-ink-3 uppercase">
              Endpoint
            </span>
            <span className="min-w-0 font-mono text-[12.5px] [overflow-wrap:anywhere]">
              {group.base_url}
              {slugify(fnName) || 'my-function'}
            </span>
          </div>
        </div>
      </Modal>

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
              <div className="min-w-0 truncate text-sm font-semibold">
                {fn.name}
                {fn.function_type === 'independent' ? (
                  <span
                    className="ml-2 font-mono text-[10.5px] font-normal text-ink-3"
                    title={FUNCTION_TYPE_HINT.independent}
                  >
                    independent
                  </span>
                ) : null}
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

      <DeleteGroupModal
        open={deleting}
        onClose={() => setDeleting(false)}
        ns={group.ns}
        functionCount={functions?.length ?? 0}
        pending={deleteGroup.isPending}
        onConfirm={() =>
          deleteGroup.mutate(group.id, {
            onSuccess: () => {
              toast.push(`Namespace ${group.ns} deleted`)
              navigate('/console/playground')
            },
            onError: (error) => toast.push(error.message, 'err'),
          })
        }
      />
    </div>
  )
}

/**
 * Deleting a namespace takes every function under it, so opening the dialog is
 * not the confirmation — typing the namespace back is. Same shape as destroying
 * a data service, which is the other action here that cannot be undone.
 */
function DeleteGroupModal({
  open,
  onClose,
  ns,
  functionCount,
  pending,
  onConfirm,
}: {
  open: boolean
  onClose: () => void
  ns: string
  functionCount: number
  pending: boolean
  onConfirm: () => void
}) {
  const [typed, setTyped] = useState('')

  useEffect(() => {
    if (open) setTyped('')
  }, [open])

  const armed = typed.trim() === ns

  return (
    <Modal
      open={open}
      onClose={onClose}
      width={520}
      title={`Delete namespace ${ns}?`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="danger"
            disabled={!armed}
            loading={pending}
            icon={<Trash size={13} />}
            onClick={onConfirm}
            className={armed ? 'border-err bg-err-bg' : undefined}
          >
            Delete namespace
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        <div className="rounded-[10px] border border-err bg-err-bg px-3.5 py-3 text-[13px] leading-relaxed">
          This deletes {functionCount} function{functionCount === 1 ? '' : 's'} with their code,
          every deployed version, and the runtime context under{' '}
          <span className="font-mono">/{ns}/</span>. Requests to those endpoints stop resolving
          the moment you confirm. It cannot be undone.
        </div>
        <Field
          label={`Type ${ns} to confirm`}
          value={typed}
          autoFocus
          placeholder={ns}
          onChange={(event) => setTyped(event.target.value)}
        />
      </div>
    </Modal>
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
