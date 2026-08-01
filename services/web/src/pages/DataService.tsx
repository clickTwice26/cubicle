import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Bolt, Database, Layers, Power, Refresh, Table, Trash } from '../components/Icons'
import {
  Button,
  Card,
  Checkbox,
  Chip,
  CopyButton,
  Field,
  Modal,
  PAGE,
  PageHeader,
  Skeleton,
  StatusDot,
  useToast,
} from '../components/ui'
import { useServiceAction, useServices } from '../lib/hooks'
import { formatBytes } from '../lib/format'

const OPTIONS = {
  postgres: {
    title: 'PostgreSQL',
    icon: Database,
    versions: ['16.3', '15.6', '14.11'],
    storage: ['10 GB', '20 GB', '50 GB', '100 GB'],
    memory: ['512 MB', '1 GB', '2 GB', '4 GB'],
    eviction: null,
  },
  redis: {
    title: 'Redis',
    icon: Layers,
    versions: ['7.2', '7.0', '6.2'],
    storage: null,
    memory: ['256 MB', '512 MB', '1 GB', '2 GB'],
    eviction: ['noeviction', 'allkeys-lru', 'volatile-lru'],
  },
} as const

export default function DataService() {
  const { kind = 'postgres' } = useParams<{ kind: 'postgres' | 'redis' }>()
  const safeKind = (kind === 'redis' ? 'redis' : 'postgres') as 'postgres' | 'redis'
  const config = OPTIONS[safeKind]
  const Icon = config.icon

  const toast = useToast()
  const { data: services, isLoading } = useServices()
  const actions = useServiceAction(safeKind)
  const service = services?.find((entry) => entry.kind === safeKind)

  const [version, setVersion] = useState<string>(config.versions[0])
  const [memory, setMemory] = useState<string>(config.memory[1])
  const [storage, setStorage] = useState<string>(config.storage?.[1] ?? '20 GB')
  const [eviction, setEviction] = useState<string>(config.eviction?.[1] ?? 'allkeys-lru')
  const [pool, setPool] = useState('general')
  const [url, setUrl] = useState<string | null>(null)
  const [destroying, setDestroying] = useState(false)

  if (isLoading || !services) {
    return (
      <div className={PAGE}>
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }

  const created = service?.created

  return (
    <div className={PAGE}>
      <PageHeader
        title={config.title}
        subtitle="Managed alongside your functions on the same cluster · no external dependency"
      />

      {created ? (
        <Card className="overflow-hidden">
          <div className="flex flex-wrap items-center gap-3.5 border-b border-line px-5 py-5">
            <span className="grid h-[38px] w-[38px] flex-none place-items-center rounded-[10px] bg-accent-soft">
              <Icon size={18} />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2.5">
                <span className="text-base font-semibold">{config.title}</span>
                <span className="font-mono text-xs text-ink-3">{service.version}</span>
              </div>
              <div className="mt-0.5 flex items-center gap-2 text-[13px] text-ink-2">
                <StatusDot tone={service.status === 'running' ? 'ok' : 'idle'} />
                {service.status === 'running' ? 'Running' : 'Stopped'}
                {service.node ? ` · ${service.node}` : ''}
              </div>
            </div>
            <div className="flex flex-none flex-wrap items-center gap-2">
              {service.status === 'running' ? (
                <Link to={`/console/services/${safeKind}/data`}>
                  <Button variant="primary" icon={<Table size={14} />}>
                    {safeKind === 'postgres' ? 'Browse data' : 'Browse keys'}
                  </Button>
                </Link>
              ) : null}
              <Button
                variant={service.status === 'running' ? 'secondary' : 'primary'}
                icon={<Power size={14} />}
                loading={actions.start.isPending || actions.stop.isPending}
                onClick={() =>
                  service.status === 'running'
                    ? actions.stop.mutate(undefined, {
                        onSuccess: () => toast.push(`${config.title} stopped`),
                        onError: (error) => toast.push(error.message, 'err'),
                      })
                    : actions.start.mutate(undefined, {
                        onSuccess: () => toast.push(`${config.title} started`),
                        onError: (error) => toast.push(error.message, 'err'),
                      })
                }
              >
                {service.status === 'running' ? 'Stop' : 'Start'}
              </Button>
              <Button
                variant="ghost"
                icon={<Refresh size={14} />}
                loading={actions.recreate.isPending}
                title="Rebuild the container — the volume and credentials are kept"
                onClick={() =>
                  actions.recreate.mutate(undefined, {
                    onSuccess: () => toast.push(`${config.title} container rebuilt`),
                    onError: (error) => toast.push(error.message, 'err'),
                  })
                }
              >
                Recreate
              </Button>
              <Button
                variant="danger"
                icon={<Trash size={13} />}
                onClick={() => setDestroying(true)}
              >
                Destroy
              </Button>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4 border-b border-line px-5 py-4.5 sm:grid-cols-3">
            {safeKind === 'postgres' ? (
              <>
                <Stat
                  label="Storage"
                  value={`${formatBytes(Number(service.stats.size_bytes ?? 0))} / ${service.config.storage ?? '—'}`}
                />
                <Stat
                  label="Connections"
                  value={`${service.stats.connections ?? 0} / ${service.stats.max_connections ?? 100}`}
                />
                <Stat label="Tables" value={String(service.stats.tables ?? 0)} />
              </>
            ) : (
              <>
                <Stat
                  label="Memory"
                  value={`${formatBytes(Number(service.stats.used_memory ?? 0))} / ${service.config.memory ?? '—'}`}
                />
                <Stat label="Keys" value={String(service.stats.keys ?? 0)} />
                <Stat label="Eviction" value={String(service.config.eviction ?? '—')} />
              </>
            )}
          </div>

          <div className="border-b border-line px-5 py-4">
            <div className="mb-2 text-xs text-ink-2">Connection string</div>
            <div className="flex items-center gap-2.5 rounded-[9px] border border-line bg-bg px-3.5 py-2.5">
              <span className="flex-1 overflow-x-auto font-mono text-[12.5px] whitespace-nowrap">
                {url ?? service.connection_url ?? '— stopped —'}
              </span>
              {service.connection_url ? (
                url ? (
                  <CopyButton value={url} />
                ) : (
                  <button
                    type="button"
                    className="flex-none text-xs text-ink-3 transition hover:text-ink"
                    onClick={async () => {
                      try {
                        const full = await actions.reveal()
                        setUrl(full.connection_url)
                      } catch (error) {
                        toast.push((error as Error).message, 'err')
                      }
                    }}
                  >
                    Reveal
                  </button>
                )
              ) : null}
            </div>
            <div className="mt-2 text-xs text-ink-3">
              Functions do not need this — <span className="font-mono">cubicle_db</span>{' '}
              receives it automatically at invocation.
            </div>
          </div>

          {service.stats.error ? (
            <div className="border-b border-line bg-warn-bg px-5 py-3 text-[12.5px]">
              {String(service.stats.error)}
            </div>
          ) : null}

          <DestroyDialog
            open={destroying}
            onClose={() => setDestroying(false)}
            title={config.title}
            confirmWord={safeKind}
            pending={actions.destroy.isPending}
            detail={
              <>
                This stops the container and, unless you keep the volume, deletes{' '}
                <b>every table and row</b> in this cluster's {config.title}. Functions using{' '}
                <span className="font-mono">cubicle_db</span> will see it as unavailable on
                their next invocation. There is no undo.
              </>
            }
            onConfirm={(keepData) =>
              actions.destroy.mutate(keepData, {
                onSuccess: () => {
                  toast.push(`${config.title} destroyed`)
                  setDestroying(false)
                },
                onError: (error) => toast.push(error.message, 'err'),
              })
            }
          />
        </Card>
      ) : (
        <Card className="p-6">
          <div className="mb-1 text-[15px] font-semibold">Create a {config.title} instance</div>
          <div className="mb-5 text-[13.5px] text-ink-2">
            Provisioned on your cluster, on the function network. Nothing runs until you create
            it.
          </div>

          <div className="grid gap-4.5">
            <Group
              label="Version"
              options={config.versions}
              value={version}
              onChange={setVersion}
            />
            {config.storage ? (
              <Group
                label="Storage"
                options={config.storage}
                value={storage}
                onChange={setStorage}
                hint="Recorded as the target for this instance. Volume size limits depend on your storage driver."
              />
            ) : null}
            <Group
              label={safeKind === 'redis' ? 'Max memory' : 'Memory'}
              options={config.memory}
              value={memory}
              onChange={setMemory}
            />
            {config.eviction ? (
              <Group
                label="Eviction policy"
                options={config.eviction}
                value={eviction}
                onChange={setEviction}
              />
            ) : null}
            <Group
              label="Node pool"
              options={['general', 'compute']}
              value={pool}
              onChange={setPool}
            />
          </div>

          <Button
            variant="primary"
            size="lg"
            className="mt-6"
            icon={<Bolt size={15} />}
            loading={actions.create.isPending}
            onClick={() =>
              actions.create.mutate(
                {
                  version,
                  memory,
                  storage,
                  eviction,
                  node_pool: pool,
                },
                {
                  onSuccess: () => toast.push(`${config.title} created`),
                  onError: (error) => toast.push(error.message, 'err'),
                },
              )
            }
          >
            Create database
          </Button>
        </Card>
      )}
    </div>
  )
}

/**
 * Destroying a data service deletes its volume. A second click is not enough
 * confirmation for that, so this asks for the name — the same bar every tool
 * that can lose your data should set.
 */
function DestroyDialog({
  open,
  onClose,
  title,
  confirmWord,
  detail,
  pending,
  onConfirm,
}: {
  open: boolean
  onClose: () => void
  title: string
  confirmWord: string
  detail: React.ReactNode
  pending: boolean
  onConfirm: (keepData: boolean) => void
}) {
  const [typed, setTyped] = useState('')
  const [keepData, setKeepData] = useState(false)

  useEffect(() => {
    if (open) {
      setTyped('')
      setKeepData(false)
    }
  }, [open])

  const armed = typed.trim() === confirmWord

  return (
    <Modal
      open={open}
      onClose={onClose}
      width={520}
      title={`Destroy ${title}?`}
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
            onClick={() => onConfirm(keepData)}
            className={armed ? 'border-err bg-err-bg' : undefined}
          >
            Destroy {title}
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        <div className="rounded-[10px] border border-err bg-err-bg px-3.5 py-3 text-[13px] leading-relaxed">
          {detail}
        </div>

        <Checkbox
          checked={keepData}
          onChange={setKeepData}
          label="Keep the data volume — the container goes, the data stays on disk for a manual restore"
        />

        <Field
          label={`Type ${confirmWord} to confirm`}
          value={typed}
          autoFocus
          placeholder={confirmWord}
          onChange={(event) => setTyped(event.target.value)}
        />
      </div>
    </Modal>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="mb-1.5 text-xs text-ink-2">{label}</div>
      <div className="font-mono text-sm">{value}</div>
    </div>
  )
}

function Group({
  label,
  hint,
  options,
  value,
  onChange,
}: {
  label: string
  hint?: string
  options: readonly string[]
  value: string
  onChange: (next: string) => void
}) {
  return (
    <div>
      <span className="mb-2 block text-[12.5px] text-ink-2">{label}</span>
      <div className="flex flex-wrap gap-2">
        {options.map((option) => (
          <Chip key={option} active={value === option} onClick={() => onChange(option)}>
            {option}
          </Chip>
        ))}
      </div>
      {hint ? <div className="mt-2 text-xs text-ink-3">{hint}</div> : null}
    </div>
  )
}
