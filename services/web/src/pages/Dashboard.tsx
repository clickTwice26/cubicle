import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Download } from '../components/Icons'
import { Button, Card, EmptyState, PageHeader, Skeleton, StatusDot, cx } from '../components/ui'
import { useDashboard } from '../lib/hooks'
import { statusTone } from '../lib/format'
import type { ChartBar } from '../lib/types'

const WINDOWS = [
  { hours: 1, label: 'Last 1h' },
  { hours: 24, label: 'Last 24h' },
  { hours: 168, label: 'Last 7d' },
]

export default function Dashboard() {
  const [hours, setHours] = useState(24)
  const { data, isLoading } = useDashboard(hours)

  return (
    <div className="mx-auto max-w-[1240px] px-5 py-7 sm:px-8">
      <PageHeader
        title="Overview"
        subtitle={
          data
            ? `${data.function_count} function${data.function_count === 1 ? '' : 's'} · ${data.node_count} node${data.node_count === 1 ? '' : 's'} · ${data.warm_isolates} warm isolate${data.warm_isolates === 1 ? '' : 's'}`
            : ' '
        }
        action={
          <div className="flex flex-wrap gap-2">
            <a href="/api/cluster/metering/export.csv">
              <Button size="sm" icon={<Download size={14} />}>
                Export
              </Button>
            </a>
            {WINDOWS.map((window) => (
              <Button
                key={window.hours}
                size="sm"
                onClick={() => setHours(window.hours)}
                className={cx(hours === window.hours && 'border-accent bg-accent-soft')}
              >
                {window.label}
              </Button>
            ))}
          </div>
        }
      />

      <div className="mb-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
        {(data?.kpis ?? Array.from({ length: 4 })).map((kpi, index) => (
          <Card key={index} className="px-4.5 pt-4.5 pb-4">
            {kpi ? (
              <>
                <div className="mb-2.5 text-[12.5px] text-ink-2">{kpi.label}</div>
                <div className="flex items-end gap-2.5">
                  <div className="font-mono text-[26px] leading-none font-semibold tracking-[-0.02em]">
                    {kpi.value}
                  </div>
                  {kpi.delta ? (
                    <div
                      className="pb-1 text-xs font-semibold"
                      style={{
                        color:
                          kpi.direction === 'up'
                            ? 'var(--warn)'
                            : kpi.direction === 'down'
                              ? 'var(--ok)'
                              : 'var(--text-3)',
                      }}
                    >
                      {kpi.delta}
                    </div>
                  ) : null}
                </div>
              </>
            ) : (
              <>
                <Skeleton className="mb-3 h-3 w-24" />
                <Skeleton className="h-7 w-20" />
              </>
            )}
          </Card>
        ))}
      </div>

      <Card className="mb-5 px-5 py-5">
        <div className="mb-4 flex items-center justify-between">
          <div className="text-sm font-semibold">Invocations</div>
          <div className="flex gap-4 text-xs text-ink-2">
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-[2px] bg-accent" />
              Success
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-[2px] bg-err" />
              Errors
            </span>
          </div>
        </div>
        <Chart bars={data?.chart ?? []} loading={isLoading} />
      </Card>

      <Card className="overflow-hidden">
        <div className="hidden grid-cols-[2.2fr_1fr_1fr_0.9fr_0.9fr_0.9fr] gap-3 border-b border-line px-5 py-3 text-[11.5px] font-semibold tracking-[0.04em] text-ink-3 uppercase md:grid">
          <span>Function</span>
          <span>Runtime</span>
          <span>Pool</span>
          <span>Invocations</span>
          <span>p95</span>
          <span>Errors</span>
        </div>

        {isLoading ? (
          <div className="space-y-3 p-5">
            {Array.from({ length: 3 }).map((_, index) => (
              <Skeleton key={index} className="h-10 w-full" />
            ))}
          </div>
        ) : data && data.functions.length > 0 ? (
          data.functions.map((fn) => (
            <Link
              key={fn.id}
              to={`/console/functions/${fn.id}`}
              className="grid grid-cols-1 items-center gap-3 border-b border-line px-5 py-3.5 transition last:border-b-0 hover:bg-panel-2 md:grid-cols-[2.2fr_1fr_1fr_0.9fr_0.9fr_0.9fr]"
            >
              <div className="flex min-w-0 items-center gap-3">
                <StatusDot tone={statusTone(fn.status)} />
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold">
                    {fn.namespace}/{fn.name}
                    {fn.warm ? (
                      <span className="ml-2 font-mono text-[10.5px] text-ok">warm</span>
                    ) : null}
                  </div>
                  <div className="truncate font-mono text-[11.5px] text-ink-3">{fn.url}</div>
                </div>
              </div>
              <div className="text-[13px] text-ink-2">{fn.runtime_label}</div>
              <div className="font-mono text-[13px] text-ink-2">{fn.node_pool}</div>
              <div className="font-mono text-[13px]">{fn.stats.invocations_label}</div>
              <div className="font-mono text-[13px]">{fn.stats.p95}</div>
              <div
                className="font-mono text-[13px]"
                style={{ color: (fn.stats.errors ?? 0) > 0 ? 'var(--err)' : 'var(--text)' }}
              >
                {fn.stats.error_rate}
              </div>
            </Link>
          ))
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
    </div>
  )
}

function Chart({ bars, loading }: { bars: ChartBar[]; loading: boolean }) {
  if (loading) return <Skeleton className="h-[130px] w-full" />
  const peak = Math.max(1, ...bars.map((bar) => bar.ok + bar.err))
  const empty = bars.every((bar) => bar.ok + bar.err === 0)

  if (empty) {
    return (
      <div className="flex h-[130px] items-end gap-[5px]">
        {bars.map((bar) => (
          <div key={bar.bucket} className="h-px flex-1 rounded-[2px] bg-[var(--border)]" />
        ))}
      </div>
    )
  }

  return (
    <div className="flex h-[130px] items-end gap-[5px]">
      {bars.map((bar) => {
        const total = bar.ok + bar.err
        return (
          <div
            key={bar.bucket}
            className="flex h-full flex-1 flex-col justify-end gap-0.5"
            title={`${new Date(bar.bucket).toLocaleString()} — ${bar.ok} ok, ${bar.err} errors`}
          >
            <div
              className="rounded-t-[2px] bg-err"
              style={{ height: `${(bar.err / peak) * 100}%` }}
            />
            <div
              className="rounded-[2px] bg-accent"
              style={{ height: `${(bar.ok / peak) * 100}%`, minHeight: total ? 2 : 0 }}
            />
          </div>
        )
      })}
    </div>
  )
}
