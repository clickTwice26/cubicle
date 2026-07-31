import { useCallback, useEffect, useRef, useState } from 'react'
import { Bolt, Play, Power } from '../components/Icons'
import { Badge, Button, Card, Skeleton, cx } from '../components/ui'
import { FlowCanvas } from '../components/live/FlowCanvas'
import {
  Counter,
  IsolateGrid,
  LatencyPlot,
  Stat,
  Throughput,
  Ticker,
} from '../components/live/Panels'
import { api } from '../lib/api'
import { useLiveStream } from '../lib/live'

/**
 * The cluster, live.
 *
 * Every number here is derived from the same SSE connection, so what you see
 * is the runtime's own view rather than a poll that happens to land nearby.
 * Nothing on this page writes anything, apart from the traffic generator,
 * which exists so an idle cluster still has something to show.
 */
export default function Live() {
  const live = useLiveStream()
  const [focused, setFocused] = useState<string | null>(null)
  const [firing, setFiring] = useState(false)
  const cancelled = useRef(false)

  useEffect(() => () => void (cancelled.current = true), [])

  // The generator drives real invocations through the real path — the packets
  // it produces are the same ones any other client would produce.
  const sendTraffic = useCallback(
    async (count: number) => {
      const target =
        live.functions.find((fn) => fn.id === focused) ??
        live.functions.find((fn) => fn.status !== 'paused')
      if (!target) return
      setFiring(true)
      cancelled.current = false
      try {
        for (let i = 0; i < count; i += 1) {
          if (cancelled.current) break
          void api
            .post(`/api/functions/${target.id}/test`, {
              body: { amount: 100 + i, source: 'live-dashboard' },
            })
            .catch(() => {
              /* a failed invocation is itself worth watching — the stream shows it */
            })
          // Spread them out so the animation reads as traffic, not one burst.
          await new Promise((resolve) => setTimeout(resolve, 180))
        }
      } finally {
        setFiring(false)
      }
    },
    [focused, live.functions],
  )

  const warm = live.isolates.filter((isolate) => isolate.phase !== 'gone')
  const busy = warm.filter((isolate) => isolate.phase === 'busy')
  const booting = warm.filter((isolate) => isolate.phase === 'booting')
  const perSecond = live.rate[live.rate.length - 2] ?? 0
  const focusedFunction = live.functions.find((fn) => fn.id === focused)

  return (
    <div className="mx-auto max-w-[1500px] px-5 py-7 sm:px-8">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="m-0 flex items-center gap-2.5 text-2xl tracking-[-0.02em]">
            Live activity
            <span
              className={cx(
                'h-2 w-2 rounded-full',
                live.connected && !live.paused && 'animate-pulse-dot',
              )}
              style={{
                background: !live.connected
                  ? 'var(--err)'
                  : live.paused
                    ? 'var(--warn)'
                    : 'var(--ok)',
              }}
            />
          </h1>
          <p className="mt-1.5 mb-0 text-[13px] text-ink-2">
            {!live.connected
              ? 'Reconnecting to the event stream…'
              : live.paused
                ? 'Paused — the cluster keeps running, the view does not.'
                : `Streaming every request and isolate as it happens · last ${live.windowMinutes} minutes`}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {focusedFunction ? (
            <Badge tone="accent">focused on {focusedFunction.name}</Badge>
          ) : null}
          <Button
            icon={<Play size={13} />}
            loading={firing}
            disabled={live.functions.length === 0}
            onClick={() => sendTraffic(12)}
            title="Invoke a function repeatedly so there is something to watch"
          >
            Send traffic
          </Button>
          <Button
            variant={live.paused ? 'primary' : 'secondary'}
            icon={<Power size={13} />}
            onClick={() => live.setPaused(!live.paused)}
          >
            {live.paused ? 'Resume' : 'Pause'}
          </Button>
        </div>
      </div>

      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-6">
        <Stat label="Functions" value={<Counter value={live.functions.length} />} />
        <Stat
          label="Warm isolates"
          value={<Counter value={warm.length} />}
          sub={booting.length ? `${booting.length} booting` : 'ready to serve'}
          tone={warm.length > 0 ? 'ok' : undefined}
          pulse={booting.length > 0}
        />
        <Stat
          label="Working now"
          value={<Counter value={busy.length} />}
          sub={`${live.inFlight.length} request${live.inFlight.length === 1 ? '' : 's'} in flight`}
          tone={busy.length > 0 ? 'accent' : undefined}
          pulse={busy.length > 0}
        />
        <Stat label="Per second" value={<Counter value={perSecond} />} sub="last full second" />
        <Stat
          label="Invocations"
          value={<Counter value={live.totals.invocations} />}
          sub={`${live.totals.cold} cold start${live.totals.cold === 1 ? '' : 's'}`}
        />
        <Stat
          label="Errors"
          value={<Counter value={live.totals.errors} />}
          tone={live.totals.errors > 0 ? 'err' : undefined}
          sub={
            live.totals.invocations
              ? `${((live.totals.errors / live.totals.invocations) * 100).toFixed(1)}% of traffic`
              : 'none yet'
          }
        />
      </div>

      <Card className="mb-4 overflow-hidden">
        <div className="flex items-center justify-between border-b border-line px-5 py-3">
          <div className="text-sm font-semibold">Request path</div>
          <div className="text-[12px] text-ink-3">
            {focused
              ? 'Click the highlighted function to clear the focus'
              : 'Click a function to focus it'}
          </div>
        </div>
        <FlowCanvas
          functions={live.functions}
          isolates={live.isolates}
          inFlight={live.inFlight}
          focused={focused}
          onFocus={setFocused}
          onEvent={live.onEvent}
        />
      </Card>

      <div className="mb-4 grid gap-4 lg:grid-cols-2">
        <Card className="overflow-hidden">
          <Throughput rate={live.rate} />
        </Card>
        <Card className="overflow-hidden">
          <LatencyPlot
            points={
              focused
                ? live.latencies.filter((point) => point.function_id === focused)
                : live.latencies
            }
          />
        </Card>
      </div>

      <Card className="mb-4 overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-3">
          <div className="text-sm font-semibold">
            Isolates{' '}
            <span className="font-normal text-ink-3">
              · one container per concurrent request, reclaimed when idle
            </span>
          </div>
          <div className="flex items-center gap-3 font-mono text-[11.5px] text-ink-3">
            <Legend colour="var(--warn)" label="booting" />
            <Legend colour="var(--accent)" label="working" />
            <Legend colour="var(--ok)" label="idle" />
            <span>{live.spawned} spawned this session</span>
          </div>
        </div>
        {live.connected ? (
          <IsolateGrid isolates={live.isolates} focused={focused} />
        ) : (
          <div className="p-5">
            <Skeleton className="h-24 w-full" />
          </div>
        )}
      </Card>

      <Card className="overflow-hidden">
        <div className="flex items-center justify-between border-b border-line px-5 py-3">
          <div className="flex items-center gap-2 text-sm font-semibold">
            <Bolt size={14} />
            Event stream
          </div>
          <div className="font-mono text-[11.5px] text-ink-3">newest first</div>
        </div>
        <Ticker entries={live.ticker} />
      </Card>
    </div>
  )
}

function Legend({ colour, label }: { colour: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: colour }} />
      {label}
    </span>
  )
}
