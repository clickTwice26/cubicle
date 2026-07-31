import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ChevronLeft, Pencil, Plus } from '../components/Icons'
import {
  Badge,
  Button,
  Card,
  ConfirmButton,
  CopyButton,
  EmptyState,
  Field,
  KeyValue,
  Meter,
  Modal,
  Skeleton,
  StatusDot,
  Tabs,
  useToast,
} from '../components/ui'
import {
  useDeleteSecret,
  useFunction,
  useFunctionLogs,
  useFunctionMetrics,
  useSaveSecret,
  useSecrets,
  useVersions,
} from '../lib/hooks'
import { CTX_LABEL, levelColour, relativeTime, statusTone } from '../lib/format'

type Tab = 'overview' | 'metrics' | 'logs' | 'secrets'

export default function FunctionDetail() {
  const { functionId = '' } = useParams()
  const [tab, setTab] = useState<Tab>('overview')
  const { data: fn, isLoading } = useFunction(functionId)

  if (isLoading || !fn) {
    return (
      <div className="mx-auto max-w-[1240px] space-y-4 px-5 py-6 sm:px-8">
        <Skeleton className="h-8 w-56" />
        <Skeleton className="h-24 w-full" />
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-[1240px] px-5 py-6 sm:px-8">
      <Link
        to="/console"
        className="mb-4 inline-flex items-center gap-1.5 text-[13px] text-ink-2 transition hover:text-ink"
      >
        <ChevronLeft size={14} />
        All functions
      </Link>

      <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-center gap-3.5">
          <span className="mt-1">
            <StatusDot tone={statusTone(fn.status)} />
          </span>
          <div className="min-w-0">
            <h1 className="m-0 text-[23px] tracking-[-0.02em]">{fn.name}</h1>
            <div className="mt-1.5 flex flex-wrap items-center gap-2 font-mono text-[13px] text-ink-2">
              <span className="break-all">{fn.url}</span>
              <CopyButton value={fn.url} label="" />
              <span>· {fn.runtime_label}</span>
              <span>· {fn.node_pool}</span>
            </div>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link to={`/console/playground/${fn.group_id}`}>
            <Button icon={<Pencil size={14} />}>Edit code</Button>
          </Link>
          <Badge tone={fn.auth_required ? 'neutral' : 'warn'}>
            {fn.auth_required ? 'API key required' : 'public endpoint'}
          </Badge>
        </div>
      </div>

      <Tabs
        value={tab}
        onChange={setTab}
        className="mb-5"
        tabs={[
          { value: 'overview', label: 'Overview' },
          { value: 'metrics', label: 'Metrics' },
          { value: 'logs', label: 'Logs' },
          { value: 'secrets', label: 'Secrets' },
        ]}
      />

      {tab === 'overview' ? <Overview functionId={functionId} /> : null}
      {tab === 'metrics' ? <Metrics functionId={functionId} /> : null}
      {tab === 'logs' ? <Logs functionId={functionId} /> : null}
      {tab === 'secrets' ? <Secrets functionId={functionId} /> : null}
    </div>
  )
}

function Overview({ functionId }: { functionId: string }) {
  const { data: fn } = useFunction(functionId)
  const { data: metrics } = useFunctionMetrics(functionId)
  const { data: versions } = useVersions(functionId)
  if (!fn) return null

  const kpis = [
    { label: 'Invocations (24h)', value: fn.stats.invocations_label },
    { label: 'p95 latency', value: fn.stats.p95 },
    { label: 'Error rate', value: fn.stats.error_rate },
    { label: 'Cold starts', value: fn.stats.cold_rate },
  ]

  return (
    <>
      <div className="mb-5 grid grid-cols-2 gap-4 lg:grid-cols-4">
        {kpis.map((kpi) => (
          <Card key={kpi.label} className="p-4.5">
            <div className="mb-2 text-[12.5px] text-ink-2">{kpi.label}</div>
            <div className="font-mono text-[23px] font-semibold tracking-[-0.02em]">
              {kpi.value}
            </div>
          </Card>
        ))}
      </div>

      <div className="grid gap-5 lg:grid-cols-[1.4fr_1fr]">
        <Card className="px-5 py-5">
          <div className="mb-4 text-sm font-semibold">Latency (p95, ms)</div>
          {metrics && metrics.latency.some((point) => point.p95 > 0) ? (
            <div className="flex h-[120px] items-end gap-[5px]">
              {metrics.latency.map((point) => (
                <div
                  key={point.bucket}
                  className="relative h-full flex-1 rounded-[2px] bg-accent-soft"
                  title={`${new Date(point.bucket).toLocaleString()} — p95 ${point.p95.toFixed(0)}ms`}
                >
                  <div
                    className="absolute right-0 bottom-0 left-0 rounded-[2px] bg-accent"
                    style={{ height: `${point.fill}%` }}
                  />
                </div>
              ))}
            </div>
          ) : (
            <div className="flex h-[120px] items-center justify-center text-[13px] text-ink-3">
              No invocations in this window yet.
            </div>
          )}
        </Card>

        <Card className="px-5 py-5">
          <div className="mb-4 text-sm font-semibold">Configuration</div>
          <div className="grid gap-3.5">
            <KeyValue label="Trigger" value="HTTP" />
            <KeyValue label="Method" value={fn.method} />
            <KeyValue label="Memory" value={`${fn.memory_mb} MB`} />
            <KeyValue label="Timeout" value={`${fn.timeout_s}s`} />
            <KeyValue
              label="Warm instances"
              value={fn.min_instances === 0 ? 'scale to zero' : String(fn.min_instances)}
            />
            <KeyValue label="Context access" value={CTX_LABEL[fn.ctx_access]} />
            <KeyValue label="Entrypoint" value="handler.handler" />
            <KeyValue label="Version" value={`v${fn.version} · ${fn.version_status}`} />
            <KeyValue label="Last deploy" value={fn.stats.last_deploy ?? '—'} />
          </div>
        </Card>
      </div>

      <Card className="mt-5 overflow-hidden">
        <div className="border-b border-line px-5 py-4 text-sm font-semibold">Versions</div>
        {(versions ?? []).slice(0, 8).map((version) => (
          <div
            key={version.id}
            className="grid grid-cols-[70px_100px_1fr_auto] items-center gap-3 border-b border-line px-5 py-3 text-[13px] last:border-b-0"
          >
            <span className="font-mono font-semibold">v{version.number}</span>
            <span
              className="font-mono text-xs"
              style={{
                color:
                  version.status === 'ready'
                    ? 'var(--ok)'
                    : version.status === 'failed'
                      ? 'var(--err)'
                      : 'var(--warn)',
              }}
            >
              {version.status}
            </span>
            <span className="font-mono text-xs text-ink-3">
              build {(version.build_ms / 1000).toFixed(1)}s
            </span>
            <span className="text-xs text-ink-3">{relativeTime(version.created_at)}</span>
          </div>
        ))}
      </Card>
    </>
  )
}

function Metrics({ functionId }: { functionId: string }) {
  const { data } = useFunctionMetrics(functionId)
  if (!data) return <Skeleton className="h-64 w-full" />

  const percentiles = [
    { label: 'p50', value: data.stats.p50, width: 22, tone: 'accent' as const },
    { label: 'p90', value: data.stats.p90 ?? '—', width: 48, tone: 'accent' as const },
    { label: 'p95', value: data.stats.p95, width: 64, tone: 'warn' as const },
    { label: 'p99', value: data.stats.p99 ?? '—', width: 88, tone: 'err' as const },
  ]

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card className="px-5 py-5">
        <div className="mb-1.5 text-sm font-semibold">Cold starts</div>
        <div className="font-mono text-3xl font-semibold">
          {data.stats.cold_rate}
          <span className="text-[15px] text-ink-3"> of invocations</span>
        </div>
        <div className="mt-4 flex h-[90px] items-end gap-1">
          {data.latency.map((point) => (
            <div
              key={point.bucket}
              className="flex-1 rounded-[2px] bg-warn opacity-70"
              style={{ height: `${Math.max(point.cold_pct, point.cold ? 4 : 0)}%` }}
              title={`${point.cold} cold start${point.cold === 1 ? '' : 's'}`}
            />
          ))}
        </div>
      </Card>

      <Card className="px-5 py-5">
        <div className="mb-4 text-sm font-semibold">Percentiles (last 24h)</div>
        <div className="grid gap-3.5">
          {percentiles.map((row) => (
            <div key={row.label}>
              <div className="mb-1.5 flex justify-between text-[13px]">
                <span className="text-ink-2">{row.label}</span>
                <span className="font-mono">{row.value}</span>
              </div>
              <Meter value={row.width} tone={row.tone} />
            </div>
          ))}
        </div>
        <div className="mt-5 grid gap-3 border-t border-line pt-4">
          <KeyValue label="Invocations" value={data.stats.invocations_label} />
          <KeyValue label="Errors" value={data.stats.error_rate} />
          <KeyValue
            label="Metered compute"
            value={`${data.stats.gb_seconds.toFixed(2)} GB-s`}
          />
        </div>
      </Card>
    </div>
  )
}

function Logs({ functionId }: { functionId: string }) {
  const { data: logs, isLoading } = useFunctionLogs(functionId)
  if (isLoading) return <Skeleton className="h-64 w-full" />
  if (!logs?.length)
    return (
      <EmptyState title="No logs yet" body="Invoke the function and its output appears here." />
    )

  return (
    <Card className="overflow-hidden font-mono text-[12.5px]">
      {logs.map((line) => (
        <div
          key={line.id}
          className="flex items-baseline gap-3.5 border-b border-line px-4.5 py-2.5 last:border-b-0"
        >
          <span className="flex-none text-ink-3">{line.time}</span>
          <span
            className="w-[52px] flex-none font-semibold"
            style={{ color: levelColour(line.level) }}
          >
            {line.level}
          </span>
          <span className="flex-1 break-words text-ink">{line.message}</span>
          <span className="flex-none text-ink-3">{line.duration ?? ''}</span>
        </div>
      ))}
    </Card>
  )
}

function Secrets({ functionId }: { functionId: string }) {
  const toast = useToast()
  const { data: secrets } = useSecrets(functionId)
  const save = useSaveSecret(functionId)
  const remove = useDeleteSecret(functionId)
  const [open, setOpen] = useState(false)
  const [key, setKey] = useState('')
  const [value, setValue] = useState('')

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4">
        <div className="text-sm font-semibold">
          Environment secrets{' '}
          <span className="font-normal text-ink-3">
            · injected at invocation, encrypted at rest
          </span>
        </div>
        <Button size="sm" icon={<Plus size={13} />} onClick={() => setOpen(true)}>
          Add secret
        </Button>
      </div>

      {secrets?.length ? (
        secrets.map((secret) => (
          <div
            key={secret.key}
            className="grid grid-cols-[1.2fr_1.4fr_0.8fr_auto] items-center gap-3.5 border-b border-line px-5 py-3.5 text-[13px] last:border-b-0"
          >
            <span className="font-mono font-semibold">{secret.key}</span>
            <span className="font-mono tracking-[1px] text-ink-3">{secret.value}</span>
            <span className="text-ink-2">{relativeTime(secret.updated_at)}</span>
            <span className="flex justify-end">
              <ConfirmButton
                label="Delete"
                confirmLabel="Confirm"
                onConfirm={() =>
                  remove.mutate(secret.key, { onSuccess: () => toast.push('Secret deleted') })
                }
              />
            </span>
          </div>
        ))
      ) : (
        <div className="px-5 py-8 text-center text-[13px] text-ink-3">
          No secrets for this function. Cluster-wide values live in Global env.
        </div>
      )}

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Add secret"
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              loading={save.isPending}
              disabled={!key.trim()}
              onClick={() =>
                save.mutate(
                  { key: key.trim(), value },
                  {
                    onSuccess: () => {
                      toast.push('Secret saved')
                      setOpen(false)
                      setKey('')
                      setValue('')
                    },
                    onError: (error) => toast.push(error.message, 'err'),
                  },
                )
              }
            >
              Save secret
            </Button>
          </>
        }
      >
        <div className="grid gap-4">
          <Field
            label="Key"
            value={key}
            placeholder="STRIPE_KEY"
            onChange={(event) => setKey(event.target.value.toUpperCase())}
          />
          <Field
            label="Value"
            type="password"
            value={value}
            onChange={(event) => setValue(event.target.value)}
          />
          <p className="m-0 text-xs leading-relaxed text-ink-3">
            Stored envelope-encrypted and handed to the isolate at invocation. It is never
            written to disk inside the function and never appears in logs.
          </p>
        </div>
      </Modal>
    </Card>
  )
}
