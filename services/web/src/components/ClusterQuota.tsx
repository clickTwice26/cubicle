import { useEffect, useState } from 'react'
import { Badge, Button, Card, CardHeader, Meter, Select, useToast } from './ui'
import { useClusters, useMe, useSetClusterQuota } from '../lib/hooks'
import type { Cluster } from '../lib/types'

/**
 * Ceilings for every cluster on the instance — super admin only, card and all.
 *
 * It lives in Settings rather than on the cluster page because it is not a
 * property of the cluster you happen to be looking at: the point of a ceiling is
 * that one person sets them all, and comparing them is most of the job. Hiding
 * it is presentation, not protection — `RequireOwner` on the endpoint is what
 * refuses the write.
 */

/** Presets in the units an operator actually thinks in. Zero is no ceiling. */
const MEMORY = [
  { label: 'unlimited', value: 0 },
  { label: '512 MB', value: 512 },
  { label: '1 GB', value: 1024 },
  { label: '2 GB', value: 2048 },
  { label: '4 GB', value: 4096 },
  { label: '8 GB', value: 8192 },
  { label: '16 GB', value: 16384 },
  { label: '32 GB', value: 32768 },
]

const CPU = [
  { label: 'unlimited', value: 0 },
  { label: '0.5 cores', value: 0.5 },
  { label: '1 core', value: 1 },
  { label: '2 cores', value: 2 },
  { label: '4 cores', value: 4 },
  { label: '8 cores', value: 8 },
  { label: '16 cores', value: 16 },
]

const STORAGE = [
  { label: 'unlimited', value: 0 },
  { label: '10 GB', value: 10 },
  { label: '50 GB', value: 50 },
  { label: '100 GB', value: 100 },
  { label: '500 GB', value: 500 },
  { label: '1 TB', value: 1024 },
]

const memoryLabel = (mb: number) => (mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb} MB`)

export function ClusterQuotaCard() {
  const { data: me } = useMe()
  const { data: clusters } = useClusters()

  // `me` is undefined for a moment on load; drawing then hiding would be worse
  // than never drawing, so wait for the answer before deciding.
  if (me?.role !== 'owner' || !clusters?.length) return null

  return (
    <Card className="mb-5 overflow-hidden">
      <CardHeader
        title="Resource ceilings"
        subtitle="Caps on everything each cluster may allocate, across the whole instance. They bound the per-function settings underneath them, and only you can change them."
      />

      {clusters.map((cluster) => (
        <ClusterRow key={cluster.id} cluster={cluster} />
      ))}

      <div className="border-t border-line bg-panel-2 px-5 py-3 text-[12.5px] leading-relaxed text-ink-2">
        A request that cannot fit under a ceiling waits for room, then answers{' '}
        <span className="font-mono">503 cluster_at_capacity</span>. One that could never fit —
        because the cluster's own Postgres and Redis already use the ceiling — is refused straight
        away rather than made to wait for it.
      </div>
    </Card>
  )
}

function ClusterRow({ cluster }: { cluster: Cluster }) {
  const toast = useToast()
  const save = useSetClusterQuota(cluster.slug)
  const [memory, setMemory] = useState(cluster.max_memory_mb)
  const [cpu, setCpu] = useState(cluster.max_cpu_cores)
  const [storage, setStorage] = useState(cluster.max_storage_gb)

  // Refetches land while this is on screen; adopt them rather than sit on a
  // stale value the operator would then save back over.
  useEffect(() => {
    setMemory(cluster.max_memory_mb)
    setCpu(cluster.max_cpu_cores)
    setStorage(cluster.max_storage_gb)
  }, [cluster.max_memory_mb, cluster.max_cpu_cores, cluster.max_storage_gb])

  const dirty =
    memory !== cluster.max_memory_mb ||
    cpu !== cluster.max_cpu_cores ||
    storage !== cluster.max_storage_gb

  return (
    <div className="border-b border-line px-5 py-4 last:border-b-0">
      <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <span className="text-[13.5px] font-semibold">{cluster.name}</span>
        {cluster.is_default ? <Badge>default</Badge> : null}
        <span className="font-mono text-[11.5px] text-ink-3">{cluster.slug}</span>
        <Button
          className="ml-auto"
          variant={dirty ? 'primary' : 'ghost'}
          size="sm"
          disabled={!dirty}
          loading={save.isPending}
          onClick={() =>
            save.mutate(
              { max_memory_mb: memory, max_cpu_cores: cpu, max_storage_gb: storage },
              {
                onSuccess: () => toast.push(`Ceilings updated for ${cluster.name}`),
                onError: (error) => toast.push(error.message, 'err'),
              },
            )
          }
        >
          {dirty ? 'Save' : 'Saved'}
        </Button>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <Control
          label="Memory"
          options={MEMORY}
          value={memory}
          onChange={setMemory}
          used={cluster.used_memory_mb}
          cap={cluster.max_memory_mb}
          format={memoryLabel}
          note="Warm containers plus the managed Postgres and Redis."
        />
        <Control
          label="CPU"
          options={CPU}
          value={cpu}
          onChange={setCpu}
          used={cluster.used_cpu_cores}
          cap={cluster.max_cpu_cores}
          format={(n) => `${n.toFixed(2)} cores`}
          note="A container's share scales with its memory."
        />
        <Control
          label="Storage"
          options={STORAGE}
          value={storage}
          onChange={setStorage}
          cap={cluster.max_storage_gb}
          format={(gb) => (gb >= 1024 ? `${gb / 1024} TB` : `${gb} GB`)}
          note="Stored, but nothing is refused on it yet."
          pending
        />
      </div>
    </div>
  )
}

function Control({
  label,
  options,
  value,
  onChange,
  used,
  cap,
  format,
  note,
  pending,
}: {
  label: string
  options: { label: string; value: number }[]
  value: number
  onChange: (next: number) => void
  /** Omitted when the figure is not measured — better blank than a false zero. */
  used?: number
  cap: number
  format: (value: number) => string
  note: string
  pending?: boolean
}) {
  const measured = used !== undefined
  const pct = measured && cap > 0 ? Math.min(100, (used / cap) * 100) : 0
  // Amber before it bites, red once it has: an operator wants warning, not news.
  const tone = pct >= 100 ? 'err' : pct >= 80 ? 'warn' : 'accent'

  return (
    <div className="min-w-0">
      <div className="mb-1.5 flex items-center gap-2">
        <span className="text-[12.5px] text-ink-2">{label}</span>
        {pending ? <Badge tone="warn">not enforced</Badge> : null}
      </div>

      <Select value={value} onChange={(event) => onChange(Number(event.target.value))}>
        {/* A value set outside this list stays selectable, so saving never
            silently rounds someone's ceiling to the nearest preset. */}
        {!options.some((option) => option.value === value) ? (
          <option value={value}>{format(value)}</option>
        ) : null}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </Select>

      <div className="mt-2 min-h-[6px]">
        {measured && cap > 0 ? <Meter value={pct} tone={tone} /> : null}
      </div>

      <div className="mt-1.5 text-[12px] text-ink-3">
        {measured ? (
          <>
            <span className="font-mono">{format(used)}</span> committed ·{' '}
          </>
        ) : null}
        {note}
      </div>
    </div>
  )
}
