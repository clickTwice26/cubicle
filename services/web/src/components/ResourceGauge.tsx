import { useClusterResources } from '../lib/hooks'
import type { Headroom } from '../lib/types'
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
    <div className="hidden items-center gap-3.5 rounded-[9px] border border-line px-3 py-1.5 xl:flex">
      <Gauge label="mem" value={data.memory} format={memoryLabel} />
      <span className="h-4 w-px bg-line" />
      <Gauge label="cpu" value={data.cpu} format={(n) => `${n.toFixed(1)}`} suffix=" cores" />
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
}: {
  label: string
  value: Headroom
  format: (n: number) => string
  suffix?: string
}) {
  // Amber before it bites, red once it has — the same thresholds the ceilings
  // card uses, so the two never disagree about what "nearly full" means.
  const tone =
    value.pct >= 100 ? 'bg-err' : value.pct >= 80 ? 'bg-warn' : 'bg-accent'

  const title = value.limited
    ? `${format(value.free)}${suffix} free of ${format(value.cap)}${suffix}` +
      (value.reserved ? ` · ${format(value.reserved)}${suffix} held by Postgres and Redis` : '')
    : `${format(value.held)}${suffix} committed · no ceiling set on this cluster`

  return (
    <span className="flex items-center gap-2" title={title}>
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
