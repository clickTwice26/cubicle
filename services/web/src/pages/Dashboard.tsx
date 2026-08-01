import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Download } from '../components/Icons'
import { Button, Card, EmptyState, PAGE, PageHeader, Skeleton, StatusDot, cx } from '../components/ui'
import { useDashboard } from '../lib/hooks'
import { statusTone } from '../lib/format'
import type { ChartBar, Dashboard as DashboardData, FunctionSummary, Kpi } from '../lib/types'

const WINDOWS = [
  { hours: 1, label: '1h' },
  { hours: 24, label: '24h' },
  { hours: 168, label: '7d' },
]

export default function Dashboard() {
  const [hours, setHours] = useState(24)
  const { data, isLoading } = useDashboard(hours)

  return (
    <div className={PAGE}>
      <PageHeader
        title="Overview"
        subtitle="How this cluster has behaved over the window, and which functions account for it."
        action={
          <div className="flex flex-wrap items-center gap-2">
            <Window hours={hours} onChange={setHours} />
            <a href="/api/cluster/metering/export.csv">
              <Button size="sm" variant="ghost" icon={<Download size={14} />}>
                Export
              </Button>
            </a>
          </div>
        }
      />

      <Stats kpis={data?.kpis} loading={isLoading} />
      <Activity data={data} loading={isLoading} hours={hours} />
      <Functions data={data} loading={isLoading} />
    </div>
  )
}

function Window({ hours, onChange }: { hours: number; onChange: (next: number) => void }) {
  return (
    <div className="flex rounded-[9px] border border-line-strong bg-bg p-[3px]">
      {WINDOWS.map((window) => (
        <button
          key={window.hours}
          type="button"
          onClick={() => onChange(window.hours)}
          aria-pressed={hours === window.hours}
          className={cx(
            'rounded-[6px] px-3 py-1 text-[12.5px] transition',
            hours === window.hours
              ? 'bg-accent-soft font-semibold text-ink'
              : 'text-ink-2 hover:text-ink',
          )}
        >
          {window.label}
        </button>
      ))}
    </div>
  )
}

/**
 * One strip rather than four boxes.
 *
 * The same four numbers in four bordered cards gave each of them equal weight
 * and three extra borders. Dividers separate them just as well, and leave the
 * traffic figure free to be the largest thing on the page.
 */
function Stats({ kpis, loading }: { kpis?: Kpi[]; loading: boolean }) {
  if (loading || !kpis) {
    return (
      <Card className="mb-4 grid grid-cols-2 divide-line lg:grid-cols-4 lg:divide-x">
        {Array.from({ length: 4 }).map((_, index) => (
          <div key={index} className="px-5 py-4">
            <Skeleton className="mb-3 h-3 w-24" />
            <Skeleton className="h-7 w-20" />
          </div>
        ))}
      </Card>
    )
  }

  return (
    <Card className="mb-4 grid grid-cols-2 divide-y divide-line lg:grid-cols-4 lg:divide-y-0 lg:divide-x">
      {kpis.map((kpi) => (
        <div key={kpi.key ?? kpi.label} className="min-w-0 px-5 py-4">
          <div className="mb-2 text-[12.5px] text-ink-2">{kpi.label}</div>
          <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
            <span
              className={cx(
                'font-mono leading-none font-semibold tracking-[-0.02em]',
                kpi.key === 'invocations' ? 'text-[27px]' : 'text-[22px]',
              )}
            >
              {kpi.value}
            </span>
            <Delta kpi={kpi} />
          </div>
          {kpi.hint ? (
            <div className="mt-2 truncate text-[11.5px] text-ink-3" title={kpi.hint}>
              {kpi.hint}
            </div>
          ) : null}
        </div>
      ))}
    </Card>
  )
}

/**
 * A change, coloured by what it means rather than by its sign.
 *
 * More traffic is not a warning; more failures are. The server says which is
 * which, because the console cannot tell from a label that reads "Error rate".
 */
function Delta({ kpi }: { kpi: Kpi }) {
  if (!kpi.delta || kpi.direction === 'flat') return null

  const worse = kpi.polarity === 'lower_better' && kpi.direction === 'up'
  const better = kpi.polarity === 'lower_better' && kpi.direction === 'down'

  return (
    <span
      className={cx(
        'font-mono text-[12px] font-semibold',
        worse ? 'text-err' : better ? 'text-ok' : 'text-ink-3',
      )}
      title={`vs the previous ${kpi.label.toLowerCase()} window`}
    >
      {kpi.direction === 'up' ? '↑' : '↓'} {kpi.delta.replace(/^[+-]/, '')}
    </span>
  )
}

function Activity({
  data,
  loading,
  hours,
}: {
  data?: DashboardData
  loading: boolean
  hours: number
}) {
  const bars = data?.chart ?? []
  const totals = useMemo(
    () => bars.reduce((acc, bar) => ({ ok: acc.ok + bar.ok, err: acc.err + bar.err }), { ok: 0, err: 0 }),
    [bars],
  )
  const peak = Math.max(1, ...bars.map((bar) => bar.ok + bar.err))
  const span = hours === 1 ? 'minute' : hours === 24 ? 'hour' : 'day'

  return (
    <Card className="mb-4 px-5 pt-4.5 pb-4">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1.5">
        <div>
          <div className="text-sm font-semibold">Invocations</div>
          <div className="mt-0.5 text-[11.5px] text-ink-3">
            {bars.length} buckets · roughly one per {span}
          </div>
        </div>
        <div className="flex items-center gap-4 text-[11.5px] text-ink-2">
          <Legend tone="bg-accent" label={`${totals.ok.toLocaleString()} ok`} />
          <Legend
            tone={totals.err ? 'bg-err' : 'bg-line-strong'}
            label={`${totals.err.toLocaleString()} failed`}
          />
        </div>
      </div>

      {loading ? (
        <Skeleton className="h-[136px] w-full" />
      ) : (
        <Chart bars={bars} peak={peak} />
      )}
    </Card>
  )
}

function Legend({ tone, label }: { tone: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={cx('h-2 w-2 rounded-[2px]', tone)} />
      {label}
    </span>
  )
}

/**
 * The bars, with just enough scale to read them.
 *
 * Previously there was no axis at all: you could see a shape but not how many
 * anything was, nor when. A peak label and the two ends of the window cost one
 * line each and make the shape mean something.
 */
function Chart({ bars, peak }: { bars: ChartBar[]; peak: number }) {
  const empty = bars.every((bar) => bar.ok + bar.err === 0)
  const first = bars[0]
  const last = bars[bars.length - 1]

  const when = (bucket?: string) =>
    bucket
      ? new Date(bucket).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      : ''

  return (
    <div>
      <div className="flex gap-3">
        <div className="flex w-9 flex-none flex-col justify-between py-[1px] text-right font-mono text-[10.5px] text-ink-3">
          <span>{empty ? '' : peak.toLocaleString()}</span>
          <span>0</span>
        </div>

        <div className="relative min-w-0 flex-1">
          <div className="absolute inset-x-0 top-0 border-t border-dashed border-line" />
          <div className="absolute inset-x-0 bottom-0 border-t border-line" />
          <div className="flex h-[122px] items-end gap-[3px]">
            {bars.map((bar) => {
              const total = bar.ok + bar.err
              return (
                <div
                  key={bar.bucket}
                  className="group flex h-full flex-1 flex-col justify-end gap-px"
                  title={`${new Date(bar.bucket).toLocaleString()} — ${bar.ok} ok, ${bar.err} failed`}
                >
                  {bar.err > 0 ? (
                    <div
                      className="rounded-t-[2px] bg-err"
                      style={{ height: `${(bar.err / peak) * 100}%`, minHeight: 2 }}
                    />
                  ) : null}
                  <div
                    className={cx(
                      'rounded-[2px] transition-colors',
                      total ? 'bg-accent group-hover:bg-ink' : 'bg-line',
                    )}
                    style={{
                      height: total ? `${(bar.ok / peak) * 100}%` : '1px',
                      minHeight: bar.ok ? 2 : 1,
                    }}
                  />
                </div>
              )
            })}
          </div>
        </div>
      </div>

      <div className="mt-1.5 flex justify-between pl-12 font-mono text-[10.5px] text-ink-3">
        <span>{when(first?.bucket)}</span>
        <span>{empty ? 'no invocations in this window' : 'now'}</span>
        <span>{when(last?.bucket)}</span>
      </div>
    </div>
  )
}

/**
 * Busiest first, and only the columns that say whether something is wrong.
 *
 * Runtime and node pool were columns of their own; they are configuration, not
 * health, so they moved under the name where the URL already sits. That is two
 * fewer columns to scan past on the way to the error rate.
 */
function Functions({ data, loading }: { data?: DashboardData; loading: boolean }) {
  const rows = useMemo(() => {
    if (!data) return []
    return [...data.functions].sort((a, b) => {
      const failing = (fn: FunctionSummary) => (fn.stats.errors ?? 0) > 0
      if (failing(a) !== failing(b)) return failing(a) ? -1 : 1
      return (b.stats.invocations ?? 0) - (a.stats.invocations ?? 0)
    })
  }, [data])

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-line px-5 py-3.5">
        <div className="text-sm font-semibold">Functions</div>
        <div className="text-[11.5px] text-ink-3">
          {data ? `${data.function_count} deployed · ${data.warm_isolates} warm · ${data.node_count} node${data.node_count === 1 ? '' : 's'}` : ''}
        </div>
      </div>

      {loading ? (
        <div className="space-y-3 p-5">
          {Array.from({ length: 3 }).map((_, index) => (
            <Skeleton key={index} className="h-10 w-full" />
          ))}
        </div>
      ) : rows.length > 0 ? (
        <>
          <div className="hidden grid-cols-[2.6fr_0.9fr_0.8fr_0.9fr] gap-3 border-b border-line px-5 py-2.5 text-[11px] font-semibold tracking-[0.04em] text-ink-3 uppercase md:grid">
            <span>Function</span>
            <span className="text-right">Invocations</span>
            <span className="text-right">p95</span>
            <span className="text-right">Errors</span>
          </div>
          {rows.map((fn) => (
            <Row key={fn.id} fn={fn} />
          ))}
        </>
      ) : (
        <div className="p-5">
          <EmptyState
            title="No functions yet"
            body="Create a namespace in the playground, then add a function under it."
            action={
              <Link to="/console/playground">
                <Button variant="primary">Open the playground</Button>
              </Link>
            }
          />
        </div>
      )}
    </Card>
  )
}

function Row({ fn }: { fn: FunctionSummary }) {
  const failing = (fn.stats.errors ?? 0) > 0

  return (
    <Link
      to={`/console/functions/${fn.id}`}
      className="grid grid-cols-1 items-center gap-x-3 gap-y-1.5 border-b border-line px-5 py-3 transition last:border-b-0 hover:bg-panel-2 md:grid-cols-[2.6fr_0.9fr_0.8fr_0.9fr]"
    >
      <div className="flex min-w-0 items-center gap-3">
        <StatusDot tone={statusTone(fn.status)} />
        <div className="min-w-0">
          <div className="flex items-center gap-2 truncate text-[13.5px] font-semibold">
            {fn.namespace}/{fn.name}
            {fn.warm ? <span className="font-mono text-[10px] text-ok">warm</span> : null}
          </div>
          <div className="truncate font-mono text-[11px] text-ink-3">
            {fn.runtime_label} · {fn.node_pool} · {fn.url}
          </div>
        </div>
      </div>

      <Cell label="Invocations" value={fn.stats.invocations_label} />
      <Cell label="p95" value={fn.stats.p95} />
      <Cell label="Errors" value={fn.stats.error_rate} tone={failing ? 'text-err' : undefined} />
    </Link>
  )
}

/** Labelled when stacked on a phone, bare in the grid on a desktop. */
function Cell({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-2 md:justify-end">
      <span className="text-[11.5px] text-ink-3 md:hidden">{label}</span>
      <span className={cx('font-mono text-[13px]', tone ?? 'text-ink')}>{value}</span>
    </div>
  )
}
