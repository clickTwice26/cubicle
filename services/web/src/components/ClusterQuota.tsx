import { useEffect, useState } from 'react'
import { Card, CardHeader, Meter, Button, Badge, cx, useToast } from './ui'
import { useClusters, useMe, useSetClusterQuota } from '../lib/hooks'
import { activeCluster } from '../lib/cluster'
import { formatBytes } from '../lib/format'

/**
 * The ceilings this cluster allocates under.
 *
 * Only the super admin can change them — a quota an admin can raise is not a
 * quota — so everyone else sees the same numbers without the controls. The
 * server enforces that independently; this only decides what to draw.
 */

/** Presets in the units an operator actually thinks in. */
const MEMORY = [
  { label: 'unlimited', value: 0 },
  { label: '1 GB', value: 1024 },
  { label: '2 GB', value: 2048 },
  { label: '4 GB', value: 4096 },
  { label: '8 GB', value: 8192 },
  { label: '16 GB', value: 16384 },
]

const CPU = [
  { label: 'unlimited', value: 0 },
  { label: '1 core', value: 1 },
  { label: '2', value: 2 },
  { label: '4', value: 4 },
  { label: '8', value: 8 },
  { label: '16', value: 16 },
]

const STORAGE = [
  { label: 'unlimited', value: 0 },
  { label: '10 GB', value: 10 },
  { label: '50 GB', value: 50 },
  { label: '100 GB', value: 100 },
  { label: '500 GB', value: 500 },
]

export function ClusterQuota() {
  const toast = useToast()
  const { data: me } = useMe()
  const { data: clusters } = useClusters()

  const current = activeCluster()
  const cluster =
    clusters?.find((c) => c.slug === current || c.id === current) ??
    clusters?.find((c) => c.is_default) ??
    clusters?.[0]

  const save = useSetClusterQuota(cluster?.slug ?? '')
  const [memory, setMemory] = useState(0)
  const [cpu, setCpu] = useState(0)
  const [storage, setStorage] = useState(0)

  useEffect(() => {
    if (!cluster) return
    setMemory(cluster.max_memory_mb)
    setCpu(cluster.max_cpu_cores)
    setStorage(cluster.max_storage_gb)
  }, [cluster])

  if (!cluster) return null

  const owner = me?.role === 'owner'
  const dirty =
    memory !== cluster.max_memory_mb ||
    cpu !== cluster.max_cpu_cores ||
    storage !== cluster.max_storage_gb

  return (
    <Card className="mb-5 overflow-hidden">
      <CardHeader
        title="Resource ceilings"
        subtitle={
          owner
            ? 'Caps on everything this cluster may allocate. They bound the per-function settings underneath them.'
            : 'Caps on everything this cluster may allocate. Only the super admin can change them.'
        }
        action={
          owner ? (
            <Button
              variant={dirty ? 'primary' : 'ghost'}
              size="sm"
              disabled={!dirty}
              loading={save.isPending}
              onClick={() =>
                save.mutate(
                  {
                    max_memory_mb: memory,
                    max_cpu_cores: cpu,
                    max_storage_gb: storage,
                  },
                  {
                    onSuccess: () => toast.push('Ceilings updated'),
                    onError: (error) => toast.push(error.message, 'err'),
                  },
                )
              }
            >
              Save ceilings
            </Button>
          ) : (
            <Badge>read only</Badge>
          )
        }
      />

      <div className="grid gap-5 px-5 py-5">
        <Row
          label="Memory"
          used={cluster.used_memory_mb}
          cap={cluster.max_memory_mb}
          format={(mb) => (mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb} MB`)}
          options={MEMORY}
          value={memory}
          editable={owner}
          onChange={setMemory}
          note="Counts every warm container plus the managed Postgres and Redis."
        />
        <Row
          label="CPU"
          used={cluster.used_cpu_cores}
          cap={cluster.max_cpu_cores}
          format={(n) => `${n.toFixed(2)} cores`}
          options={CPU}
          value={cpu}
          editable={owner}
          onChange={setCpu}
          note="A container's share scales with its memory: 512 MB gets half a core."
        />
        <Row
          label="Storage"
          cap={cluster.max_storage_gb}
          format={(gb) => formatBytes(gb * 1024 ** 3)}
          options={STORAGE}
          value={storage}
          editable={owner}
          onChange={setStorage}
          note="Set here, but nothing is refused on it yet: volume usage is measured for the whole instance rather than per cluster."
          pending
        />
      </div>

      {owner ? (
        <div className="border-t border-line bg-panel-2 px-5 py-3 text-[12.5px] leading-relaxed text-ink-2">
          A request that cannot fit under a ceiling waits for room, then answers{' '}
          <span className="font-mono">503 cluster_at_capacity</span>. One that could never fit —
          because the data services alone use the ceiling — is refused straight away rather than
          made to wait for it.
        </div>
      ) : null}
    </Card>
  )
}

function Row({
  label,
  used,
  cap,
  format,
  options,
  value,
  editable,
  onChange,
  note,
  pending,
}: {
  label: string
  /** Omitted when the figure is not measured — better blank than a false zero. */
  used?: number
  cap: number
  format: (value: number) => string
  options: { label: string; value: number }[]
  value: number
  editable: boolean
  onChange: (next: number) => void
  note: string
  pending?: boolean
}) {
  const measured = used !== undefined
  const pct = measured && cap > 0 ? Math.min(100, (used / cap) * 100) : 0
  // Amber before it bites, red once it has: an operator wants warning, not news.
  const tone = pct >= 100 ? 'err' : pct >= 80 ? 'warn' : 'accent'

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-[13.5px] font-semibold">{label}</span>
        {pending ? <Badge tone="warn">not enforced</Badge> : null}
        <span className="ml-auto font-mono text-[12.5px] text-ink-2">
          {measured ? format(used) : <span className="text-ink-3">not measured</span>}
          <span className="text-ink-3"> · ceiling {cap > 0 ? format(cap) : 'unlimited'}</span>
        </span>
      </div>

      {measured && cap > 0 ? (
        <Meter value={pct} tone={tone} />
      ) : (
        <div className="h-[6px] rounded-full border border-dashed border-line" />
      )}

      <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
        {editable ? (
          options.map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => onChange(option.value)}
              className={cx(
                'rounded-full border px-2.5 py-1 text-[12px] transition',
                value === option.value
                  ? 'border-accent bg-accent-soft font-semibold text-ink'
                  : 'border-line text-ink-2 hover:border-line-strong hover:text-ink',
              )}
            >
              {option.label}
            </button>
          ))
        ) : (
          <span className="text-[12.5px] text-ink-3">
            {cap > 0 ? format(cap) : 'no ceiling set'}
          </span>
        )}
      </div>

      <div className="mt-1.5 text-[12px] text-ink-3">{note}</div>
    </div>
  )
}
