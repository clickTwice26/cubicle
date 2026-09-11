import { useState } from 'react'
import { useClusterResources } from '../lib/hooks'
import type { Headroom, ResourceConsumer } from '../lib/types'
import { cx } from './ui'

/**
 * What this cluster has left, in the header, refreshed every five seconds.
 *
 * Two shapes, because a cluster without a ceiling has no remainder to show.
 * With one, this is headroom — the number that decides whether the next request
 * gets a container. Without one, it is simply what is committed, said plainly
 * rather than dressed up as a fraction of a denominator that does not exist.
 *
 * Desktop only: the header already carries four controls on a phone, and this
 * is ambient information rather than something you act on.
 */

const memoryLabel = (mb: number) => (mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${Math.round(mb)} MB`)

export function ResourceGauge() {
  const { data, isError } = useClusterResources()

  // Nothing rather than a zero: a gauge that reads empty because the request
  // failed is worse than no gauge, since it looks like an idle cluster.
  if (isError || !data) return null

  return (
    <div className="relative hidden items-center gap-3.5 rounded-[9px] border border-line px-3 py-1.5 xl:flex">
      <Gauge
        label="mem"
        value={data.memory}
        format={memoryLabel}
        consumers={data.consumers}
        resource="memory"
      />
      <span className="h-4 w-px bg-line" />
      <Gauge
        label="cpu"
        value={data.cpu}
        format={(n) => `${n.toFixed(1)}`}
        suffix=" cores"
        consumers={data.consumers}
        resource="cpu"
      />
      <span className="h-4 w-px bg-line" />
      <span
        className="font-mono text-[11.5px] text-ink-3"
        title={`${data.isolates} warm container${data.isolates === 1 ? '' : 's'} in this cluster`}
      >
        {data.isolates} iso
      </span>
    </div>
  )
}

function Gauge({
  label,
  value,
  format,
  suffix = '',
  consumers = [],
  resource,
}: {
  label: string
  value: Headroom
  format: (n: number) => string
  suffix?: string
  consumers?: ResourceConsumer[]
  resource: 'memory' | 'cpu'
}) {
  const [open, setOpen] = useState(false)
  // Amber before it bites, red once it has — the same thresholds the ceilings
  // card uses, so the two never disagree about what "nearly full" means.
  const tone =
    value.pct >= 100 ? 'bg-err' : value.pct >= 80 ? 'bg-warn' : 'bg-accent'

  const title = value.limited
    ? `${format(value.free)}${suffix} free of ${format(value.cap)}${suffix}` +
      (value.reserved ? ` · ${format(value.reserved)}${suffix} held by Postgres and Redis` : '')
    : `${format(value.held)}${suffix} committed · no ceiling set on this cluster`

  return (
    <span
      className="relative flex items-center gap-2"
      title={title}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      {open && consumers.length ? (
        <Breakdown consumers={consumers} resource={resource} format={format} suffix={suffix} />
      ) : null}
      <span className="text-[11px] tracking-[0.04em] text-ink-3 uppercase">{label}</span>

      {value.limited ? (
        <>
          <span className="h-1.5 w-12 overflow-hidden rounded-full bg-line">
            <span
              className={cx('block h-full rounded-full transition-[width] duration-500', tone)}
              style={{ width: `${Math.max(2, value.pct)}%` }}
            />
          </span>
          <span className="font-mono text-[11.5px] text-ink-2 tabular-nums">
            {format(value.free)}
            <span className="text-ink-3"> free</span>
          </span>
        </>
      ) : (
        <span className="font-mono text-[11.5px] text-ink-2 tabular-nums">
          {format(value.held)}
          <span className="text-ink-3"> used</span>
        </span>
      )}
    </span>
  )
}

const KIND_LABEL: Record<ResourceConsumer['kind'], string> = {
  app: 'app',
  service: 'service',
  function: 'function',
}

/**
 * What is actually holding the resource, on hover.
 *
 * The gauge says how much is left; the first question after that is always
 * which of these to go and shrink. Percentages are of what is committed, not
 * of the ceiling — an operator looking at this wants the shares to add up to
 * what they can see, not to a denominator that includes headroom.
 */
function Breakdown({
  consumers,
  resource,
  format,
  suffix,
}: {
  consumers: ResourceConsumer[]
  resource: 'memory' | 'cpu'
  format: (n: number) => string
  suffix: string
}) {
  const value = (entry: ResourceConsumer) =>
    resource === 'memory' ? entry.memory_mb : entry.cpus
  const total = consumers.reduce((sum, entry) => sum + value(entry), 0)
  const rows = [...consumers].sort((a, b) => value(b) - value(a)).filter((e) => value(e) > 0)

  return (
    <span className="animate-rise absolute top-[calc(100%+10px)] left-0 z-40 block w-[290px] cursor-default rounded-xl border border-line-strong bg-panel p-3 shadow-2xl">
      <span className="mb-2 block text-[11px] font-bold tracking-[0.05em] text-ink-3 uppercase">
        {resource === 'memory' ? 'Memory' : 'CPU'} committed
      </span>
      {rows.map((entry) => {
        const pct = total ? (value(entry) / total) * 100 : 0
        return (
          <span key={`${entry.kind}:${entry.name}`} className="mb-1.5 block last:mb-0">
            <span className="flex items-baseline gap-2 text-[12px]">
              <span className="min-w-0 flex-1 truncate font-mono">
                {entry.name}
                {entry.instances > 1 ? (
                  <span className="text-ink-3"> ×{entry.instances}</span>
                ) : null}
              </span>
              <span className="flex-none text-[10.5px] text-ink-3">{KIND_LABEL[entry.kind]}</span>
              <span className="flex-none font-mono tabular-nums">
                {format(value(entry))}
                {suffix}
              </span>
              <span className="w-9 flex-none text-right font-mono text-ink-3 tabular-nums">
                {pct.toFixed(0)}%
              </span>
            </span>
            <span className="mt-1 block h-1 overflow-hidden rounded-full bg-line">
              <span
                className={cx(
                  'block h-full rounded-full',
                  entry.kind === 'app'
                    ? 'bg-accent'
                    : entry.kind === 'service'
                      ? 'bg-info'
                      : 'bg-warn',
                )}
                style={{ width: `${Math.max(2, pct)}%` }}
              />
            </span>
          </span>
        )
      })}
      {rows.length === 0 ? (
        <span className="block text-[12px] text-ink-3">Nothing running yet.</span>
      ) : null}
    </span>
  )
}
