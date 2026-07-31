import { useEffect, useState } from 'react'
import { cx } from '../ui'

/**
 * A sketch of the Live activity console: requests crossing the edge and the
 * router, isolates waking up to serve them and going quiet again.
 *
 * Deliberately a loop over scripted data rather than a live feed — the landing
 * page is public and unauthenticated, and it has no cluster to read from. The
 * caption says so. What it shows is the real shape of the runtime: one request
 * per isolate, a pool that widens under load and narrows again.
 */

const PACKETS = [0, 1, 2, 3, 4, 5]

interface Lane {
  name: string
  namespace: string
  method: string
}

const LANES: Lane[] = [
  { name: 'create-charge', namespace: 'payments', method: 'POST' },
  { name: 'send-receipt', namespace: 'payments', method: 'POST' },
  { name: 'status', namespace: 'payments', method: 'GET' },
]

/** The pool breathing: how many isolates are warm, and how many are working. */
const FRAMES: { warm: number; busy: number; perSecond: number }[] = [
  { warm: 1, busy: 0, perSecond: 2 },
  { warm: 2, busy: 1, perSecond: 6 },
  { warm: 4, busy: 3, perSecond: 14 },
  { warm: 6, busy: 5, perSecond: 22 },
  { warm: 6, busy: 4, perSecond: 19 },
  { warm: 4, busy: 2, perSecond: 9 },
  { warm: 3, busy: 1, perSecond: 4 },
  { warm: 2, busy: 0, perSecond: 1 },
]

export function FlowStrip() {
  const [frame, setFrame] = useState(0)

  useEffect(() => {
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (reduced) return
    const timer = window.setInterval(() => setFrame((n) => (n + 1) % FRAMES.length), 1600)
    return () => window.clearInterval(timer)
  }, [])

  const { warm, busy, perSecond } = FRAMES[frame]

  // text-left: the hero centres its children, and a panel of labels and
  // readouts should not inherit that.
  return (
    <div className="overflow-hidden rounded-2xl border border-line bg-panel text-left shadow-card">
      <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-3">
        <span className="flex items-center gap-2 text-[13px] font-semibold">
          <span className="h-2 w-2 animate-pulse-dot rounded-full bg-ok" />
          Live activity
        </span>
        <span className="font-mono text-[11.5px] text-ink-3">prod-cluster</span>
        <span className="ml-auto flex items-center gap-4 font-mono text-[11.5px] text-ink-2">
          <Readout label="req/s" value={perSecond} />
          <Readout label="warm" value={warm} />
          <Readout label="busy" value={busy} tone />
        </span>
      </div>

      <div className="grid grid-cols-[76px_1fr] items-center gap-3 px-4 py-5 sm:grid-cols-[92px_92px_1fr] sm:gap-5 sm:px-6">
        <Node label="Edge" sub="Caddy" />
        <Node label="Router" sub="control plane" className="hidden sm:block" />

        <div className="relative grid gap-2">
          {/* The wire the packets travel along, behind the lanes. */}
          <span
            aria-hidden
            className="pointer-events-none absolute top-1/2 -left-5 hidden h-px w-5 bg-line-strong sm:block"
          />
          {LANES.map((lane, index) => (
            <LaneRow
              key={lane.name}
              lane={lane}
              active={index === frame % LANES.length}
              warm={index === 0 ? Math.max(1, warm - 2) : index === 1 ? Math.min(2, warm) : 0}
              busy={index === 0 ? Math.max(0, busy - 1) : index === 1 ? Math.min(1, busy) : 0}
            />
          ))}

          {/* Packets. Pure CSS: each one loops on its own delay, so there is no
              timer driving the animation and nothing to fall behind. */}
          <span aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
            {PACKETS.map((n) => (
              <span
                key={n}
                className="animate-travel absolute h-1.5 w-1.5 rounded-full bg-accent"
                style={
                  {
                    top: `${18 + (n % 3) * 32}%`,
                    left: '-4%',
                    '--travel': '104%',
                    '--travel-ms': `${1800 + (n % 3) * 400}ms`,
                    '--travel-delay': `${n * 320}ms`,
                    boxShadow: '0 0 8px 1px var(--accent)',
                  } as React.CSSProperties
                }
              />
            ))}
          </span>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line px-5 py-2.5 font-mono text-[11px] text-ink-3">
        <span>
          <span className="text-warn">●</span> booting
        </span>
        <span>
          <span className="text-accent">●</span> working
        </span>
        <span>
          <span className="text-ok">●</span> idle
        </span>
        <span className="ml-auto">an illustration — the console animates your own traffic</span>
      </div>
    </div>
  )
}

function Readout({ label, value, tone }: { label: string; value: number; tone?: boolean }) {
  return (
    <span className="flex items-baseline gap-1">
      <span
        className="text-[13px] font-semibold tabular-nums transition-[color] duration-300"
        style={{ color: tone && value > 0 ? 'var(--accent)' : 'var(--text)' }}
      >
        {value}
      </span>
      <span className="text-ink-3">{label}</span>
    </span>
  )
}

function Node({ label, sub, className }: { label: string; sub: string; className?: string }) {
  return (
    <div
      className={cx(
        'rounded-[10px] border border-line bg-panel-2 px-2.5 py-2.5 text-center',
        className,
      )}
    >
      <div className="text-[12.5px] font-semibold">{label}</div>
      <div className="mt-0.5 font-mono text-[10px] text-ink-3">{sub}</div>
    </div>
  )
}

function LaneRow({
  lane,
  active,
  warm,
  busy,
}: {
  lane: Lane
  active: boolean
  warm: number
  busy: number
}) {
  return (
    <div
      className={cx(
        'relative flex items-center gap-2.5 rounded-[10px] border px-3 py-2 transition-colors duration-500',
        active ? 'border-accent bg-accent-soft' : 'border-line bg-panel',
      )}
    >
      <span
        className={cx('h-1.5 w-1.5 flex-none rounded-full', busy > 0 && 'animate-pulse-dot')}
        style={{
          background: busy > 0 ? 'var(--accent)' : warm > 0 ? 'var(--ok)' : 'var(--text-3)',
        }}
      />
      <span className="min-w-0 flex-1 truncate text-[12.5px] font-semibold">{lane.name}</span>
      <span className="hidden font-mono text-[10.5px] text-ink-3 sm:inline">
        /{lane.namespace}
      </span>
      <span className="flex flex-none items-center gap-1">
        {/* One dot per isolate, so the pool visibly widens and narrows. */}
        {Array.from({ length: Math.max(warm, 1) }, (_, i) => (
          <span
            key={i}
            className="h-3.5 w-1.5 rounded-full transition-all duration-500"
            style={{
              background:
                warm === 0 ? 'var(--border-strong)' : i < busy ? 'var(--accent)' : 'var(--ok)',
              opacity: warm === 0 ? 0.5 : 1,
            }}
          />
        ))}
      </span>
      <span className="w-[46px] flex-none text-right font-mono text-[10.5px] text-ink-3">
        {warm === 0 ? 'cold' : `${busy}/${warm}`}
      </span>
    </div>
  )
}
