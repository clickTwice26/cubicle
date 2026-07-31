import { useEffect, useRef, useState } from 'react'
import type { IsolateView, RecentInvocation, TickerEntry } from '../../lib/live'
import { RATE_WINDOW } from '../../lib/live'
import { cx } from '../ui'

/** A number that rolls to its new value instead of snapping. */
export function Counter({ value, digits = 0 }: { value: number; digits?: number }) {
  const [shown, setShown] = useState(value)
  const from = useRef(value)
  const frame = useRef(0)

  useEffect(() => {
    const start = performance.now()
    const origin = from.current
    const delta = value - origin
    if (delta === 0) return

    const step = (now: number) => {
      // Ease out: fast enough to feel immediate, slow enough to read.
      const t = Math.min(1, (now - start) / 420)
      const eased = 1 - (1 - t) ** 3
      setShown(origin + delta * eased)
      if (t < 1) frame.current = requestAnimationFrame(step)
      else from.current = value
    }
    frame.current = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame.current)
  }, [value])

  return <>{shown.toFixed(digits)}</>
}

export function Stat({
  label,
  value,
  sub,
  tone,
  pulse,
}: {
  label: string
  value: React.ReactNode
  sub?: string
  tone?: 'accent' | 'ok' | 'warn' | 'err'
  pulse?: boolean
}) {
  const colour = tone ? `var(--${tone === 'accent' ? 'accent' : tone})` : undefined
  return (
    <div
      className={cx(
        'relative overflow-hidden rounded-xl border border-line bg-panel px-4 py-3.5 transition',
        pulse && 'border-accent',
      )}
    >
      {pulse ? (
        <span className="pointer-events-none absolute inset-y-0 -left-1/3 w-1/3 animate-sweep bg-accent-soft" />
      ) : null}
      <div className="relative text-[11.5px] tracking-[0.03em] text-ink-2 uppercase">
        {label}
      </div>
      <div
        className="relative mt-1 font-mono text-[26px] leading-none font-semibold tracking-[-0.02em]"
        style={{ color: colour }}
      >
        {value}
      </div>
      {sub ? <div className="relative mt-1 text-[11.5px] text-ink-3">{sub}</div> : null}
    </div>
  )
}

/**
 * Every isolate in the cluster, one tile each.
 *
 * The tile is the animation: it scales in when the container starts, breathes
 * while the runtime boots, pulses on every request it serves, and shrinks away
 * when the pool reclaims it.
 */
export function IsolateGrid({
  isolates,
  focused,
}: {
  isolates: IsolateView[]
  focused: string | null
}) {
  if (isolates.length === 0) {
    return (
      <div className="px-5 py-10 text-center text-[13px] text-ink-3">
        Nothing warm right now — every function is scaled to zero.
        <div className="mt-1 text-[12px] text-ink-3">
          Send a request and watch the isolate boot here.
        </div>
      </div>
    )
  }

  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(132px,1fr))] gap-2.5 px-5 py-5">
      {isolates.map((isolate) => {
        const dimmed = focused !== null && focused !== isolate.function_id
        return (
          <div
            key={isolate.id}
            title={`${isolate.function} · ${isolate.id} · ${isolate.node}`}
            className={cx(
              'relative overflow-hidden rounded-[10px] border px-3 py-2.5 transition-opacity',
              isolate.phase === 'gone'
                ? 'animate-isolate-out border-line'
                : 'animate-isolate-in',
              isolate.phase === 'busy' && 'animate-work border-accent bg-accent-soft',
              isolate.phase === 'idle' && 'border-line bg-panel-2',
              isolate.phase === 'booting' && 'animate-boot border-warn bg-warn-bg',
              dimmed && 'opacity-30',
            )}
          >
            <div className="flex items-center gap-1.5">
              <span
                className="h-1.5 w-1.5 flex-none rounded-full"
                style={{
                  background:
                    isolate.phase === 'busy'
                      ? 'var(--accent)'
                      : isolate.phase === 'booting'
                        ? 'var(--warn)'
                        : 'var(--ok)',
                }}
              />
              <span className="truncate text-[12px] font-semibold">{isolate.function}</span>
            </div>
            <div className="mt-1 truncate font-mono text-[10.5px] text-ink-3">{isolate.id}</div>
            <div className="mt-1.5 flex items-center justify-between font-mono text-[10.5px] text-ink-2">
              <span>
                {isolate.phase === 'booting'
                  ? 'booting…'
                  : isolate.phase === 'gone'
                    ? 'reclaimed'
                    : `${isolate.invocations} req`}
              </span>
              <span>{isolate.memory_mb}MB</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

/** Invocations per second for the last minute, as a sliding bar chart. */
export function Throughput({ rate }: { rate: number[] }) {
  const peak = Math.max(1, ...rate)
  return (
    <div className="px-5 py-4">
      <div className="mb-2 flex items-baseline justify-between">
        <span className="text-[11.5px] tracking-[0.03em] text-ink-2 uppercase">
          Invocations / second
        </span>
        <span className="font-mono text-[11.5px] text-ink-3">
          peak {peak} · last {RATE_WINDOW}s
        </span>
      </div>
      <div className="flex h-[72px] items-end gap-[2px]">
        {rate.map((count, index) => (
          <div
            key={index}
            className="flex-1 rounded-[2px] transition-[height] duration-200 ease-out"
            style={{
              height: `${Math.max(count ? 6 : 2, (count / peak) * 100)}%`,
              background: count ? 'var(--accent)' : 'var(--border)',
              opacity: index > RATE_WINDOW - 4 ? 1 : 0.55 + (index / RATE_WINDOW) * 0.45,
            }}
            title={`${count}/s`}
          />
        ))}
      </div>
    </div>
  )
}

/**
 * Recent durations as a scatter of dots.
 *
 * Log scale, because one cold start is two orders of magnitude slower than a
 * warm request: on a linear axis a single 3s outlier flattens every 5ms
 * response onto the baseline, which is exactly the part worth seeing.
 */
export function LatencyPlot({ points }: { points: RecentInvocation[] }) {
  const recent = points.slice(-80)
  const worst = Math.max(50, ...recent.map((p) => p.duration_ms))
  const height = (ms: number) => {
    const top = Math.log10(Math.max(worst, 10))
    return Math.min(96, (Math.log10(Math.max(ms, 1)) / top) * 96)
  }
  return (
    <div className="px-5 py-4">
      <div className="mb-2 flex items-baseline justify-between">
        <span className="text-[11.5px] tracking-[0.03em] text-ink-2 uppercase">Latency</span>
        <span className="font-mono text-[11.5px] text-ink-3">
          {recent.length ? `${Math.round(worst)}ms worst · log scale` : 'no traffic yet'}
        </span>
      </div>
      <div className="relative h-[72px] border-b border-line">
        {recent.map((point, index) => (
          <span
            key={point.request_id + index}
            className="animate-isolate-in absolute h-1.5 w-1.5 rounded-full"
            style={{
              left: `${(index / Math.max(1, recent.length - 1)) * 98}%`,
              bottom: `${height(point.duration_ms)}%`,
              background: point.cold
                ? 'var(--warn)'
                : point.status >= 400
                  ? 'var(--err)'
                  : 'var(--ok)',
            }}
            title={`${point.function} · ${Math.round(point.duration_ms)}ms${point.cold ? ' · cold start' : ''}`}
          />
        ))}
      </div>
    </div>
  )
}

const TONE_COLOUR: Record<TickerEntry['tone'], string> = {
  ok: 'var(--ok)',
  err: 'var(--err)',
  warn: 'var(--warn)',
  info: 'var(--info)',
  muted: 'var(--text-3)',
}

export function Ticker({ entries }: { entries: TickerEntry[] }) {
  if (entries.length === 0) {
    return (
      <div className="px-5 py-8 text-center text-[13px] text-ink-3">
        Waiting for the first event…
      </div>
    )
  }
  return (
    <div className="max-h-[320px] overflow-y-auto">
      {entries.map((entry) => (
        <div
          key={entry.id}
          className="animate-rise flex items-baseline gap-3 border-b border-line px-5 py-2 font-mono text-[12px] last:border-b-0"
        >
          <span className="flex-none text-ink-3">
            {new Date(entry.at).toLocaleTimeString([], { hour12: false })}
          </span>
          <span
            className="w-[52px] flex-none truncate font-semibold"
            style={{ color: TONE_COLOUR[entry.tone] }}
          >
            {entry.kind.replace('invocation.', '').replace('isolate.', '')}
          </span>
          <span className="w-[150px] flex-none truncate text-ink">{entry.label}</span>
          <span className="min-w-0 flex-1 truncate text-ink-2">{entry.detail}</span>
        </div>
      ))}
    </div>
  )
}
