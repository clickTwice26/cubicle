import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { InFlight, LiveEvent, LiveFunction, IsolateView } from '../../lib/live'
import { cx } from '../ui'

/**
 * The request path, drawn and animated: edge → router → each function.
 *
 * A packet is launched the moment `invocation.start` arrives and lands on the
 * function's node; when the matching `invocation.end` arrives it flashes the
 * node green or red. Packets are plain absolutely-positioned divs moved with a
 * transform, created and destroyed outside React — at a few hundred requests a
 * second, reconciling them as state would be the bottleneck.
 */

interface Props {
  functions: LiveFunction[]
  isolates: IsolateView[]
  inFlight: InFlight[]
  focused: string | null
  onFocus: (id: string | null) => void
  onEvent: LiveData['onEvent']
}

type LiveData = { onEvent: (handler: (event: LiveEvent) => void) => () => void }

const FLIGHT_MS = 620

export function FlowCanvas({
  functions,
  isolates,
  inFlight,
  focused,
  onFocus,
  onEvent,
}: Props) {
  const stage = useRef<HTMLDivElement>(null)
  const layer = useRef<HTMLDivElement>(null)
  const edge = useRef<HTMLDivElement>(null)
  const router = useRef<HTMLDivElement>(null)
  const lanes = useRef(new Map<string, HTMLElement>())
  const [, setTick] = useState(0)

  // Positions are read from the DOM, so a resize has to invalidate them.
  useLayoutEffect(() => {
    const observer = new ResizeObserver(() => setTick((n) => n + 1))
    if (stage.current) observer.observe(stage.current)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    const centreOf = (element: HTMLElement | null | undefined) => {
      const box = stage.current?.getBoundingClientRect()
      if (!element || !box) return null
      const own = element.getBoundingClientRect()
      return {
        x: own.left - box.left + own.width / 2,
        y: own.top - box.top + own.height / 2,
      }
    }

    const flash = (element: HTMLElement | null | undefined, tone: string) => {
      if (!element) return
      const ping = document.createElement('span')
      ping.className = 'animate-ping-once pointer-events-none absolute inset-0 rounded-[10px]'
      ping.style.background = tone
      element.appendChild(ping)
      window.setTimeout(() => ping.remove(), 900)
    }

    const launch = (targetId: string, tone: string) => {
      const from = centreOf(edge.current)
      const via = centreOf(router.current)
      const to = centreOf(lanes.current.get(targetId))
      if (!from || !via || !to || !layer.current) return

      const packet = document.createElement('span')
      packet.className = 'pointer-events-none absolute h-2 w-2 rounded-full'
      packet.style.background = tone
      packet.style.boxShadow = `0 0 10px 2px ${tone}`
      packet.style.left = '0px'
      packet.style.top = '0px'
      packet.style.transform = `translate(${from.x - 4}px, ${from.y - 4}px)`
      layer.current.appendChild(packet)

      // Two hops so the packet visibly passes through the router rather than
      // cutting the corner.
      const hop = (to: { x: number; y: number }, ms: number) =>
        new Promise<void>((resolve) => {
          requestAnimationFrame(() => {
            packet.style.transition = `transform ${ms}ms cubic-bezier(0.4, 0, 0.2, 1)`
            packet.style.transform = `translate(${to.x - 4}px, ${to.y - 4}px)`
            window.setTimeout(resolve, ms)
          })
        })

      void hop(via, FLIGHT_MS * 0.4)
        .then(() => {
          flash(router.current, 'var(--accent-soft)')
          return hop(to, FLIGHT_MS * 0.6)
        })
        .then(() => {
          packet.style.transition = 'opacity 160ms ease'
          packet.style.opacity = '0'
          window.setTimeout(() => packet.remove(), 200)
        })
    }

    return onEvent((event) => {
      if (event.kind === 'invocation.start') {
        flash(edge.current, 'var(--accent-soft)')
        launch(event.function_id as string, 'var(--accent)')
      }
      if (event.kind === 'invocation.end') {
        const status = event.status as number
        flash(
          lanes.current.get(event.function_id as string),
          status >= 400 ? 'var(--err-bg)' : 'var(--ok-bg)',
        )
      }
      if (event.kind === 'isolate.spawn') {
        flash(lanes.current.get(event.function_id as string), 'var(--warn-bg)')
      }
    })
  }, [onEvent])

  const busyByFunction = new Map<string, number>()
  const warmByFunction = new Map<string, number>()
  for (const isolate of isolates) {
    if (isolate.phase === 'gone') continue
    warmByFunction.set(isolate.function_id, (warmByFunction.get(isolate.function_id) ?? 0) + 1)
    if (isolate.phase === 'busy')
      busyByFunction.set(
        isolate.function_id,
        (busyByFunction.get(isolate.function_id) ?? 0) + 1,
      )
  }
  const inFlightByFunction = new Map<string, number>()
  for (const request of inFlight)
    inFlightByFunction.set(
      request.function_id,
      (inFlightByFunction.get(request.function_id) ?? 0) + 1,
    )

  return (
    <div
      ref={stage}
      className="relative grid grid-cols-[104px_112px_1fr] items-center gap-4 overflow-hidden px-5 py-6 sm:gap-8 sm:px-7"
    >
      {/* The wires. Drawn behind everything and purely decorative — the packet
          layer is what actually moves. */}
      <svg className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden>
        <defs>
          <linearGradient id="wire" x1="0" x2="1">
            <stop offset="0%" stopColor="var(--border-strong)" stopOpacity="0.2" />
            <stop offset="50%" stopColor="var(--border-strong)" stopOpacity="0.8" />
            <stop offset="100%" stopColor="var(--border-strong)" stopOpacity="0.2" />
          </linearGradient>
        </defs>
      </svg>

      <Node label="Edge" sub="Caddy" innerRef={edge} />
      <Node label="Router" sub="control plane" innerRef={router} />

      <div className="grid gap-2.5">
        {functions.length === 0 ? (
          <div className="rounded-xl border border-dashed border-line px-4 py-6 text-center text-[13px] text-ink-3">
            No functions in this cluster yet.
          </div>
        ) : null}
        {functions.map((fn) => {
          const busy = busyByFunction.get(fn.id) ?? 0
          const warm = warmByFunction.get(fn.id) ?? 0
          const pending = inFlightByFunction.get(fn.id) ?? 0
          const dimmed = focused !== null && focused !== fn.id
          return (
            <button
              key={fn.id}
              type="button"
              onClick={() => onFocus(focused === fn.id ? null : fn.id)}
              ref={(element) => {
                if (element) lanes.current.set(fn.id, element)
                else lanes.current.delete(fn.id)
              }}
              className={cx(
                'relative flex items-center gap-3 overflow-hidden rounded-[10px] border px-3.5 py-2.5 text-left transition',
                focused === fn.id
                  ? 'border-accent bg-accent-soft'
                  : 'border-line bg-panel hover:border-line-strong',
                dimmed && 'opacity-40',
              )}
            >
              <span
                className={cx(
                  'h-2 w-2 flex-none rounded-full transition',
                  busy > 0 && 'animate-pulse-dot',
                )}
                style={{
                  background:
                    busy > 0 ? 'var(--accent)' : warm > 0 ? 'var(--ok)' : 'var(--text-3)',
                }}
              />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px] font-semibold">{fn.name}</span>
                <span className="block truncate font-mono text-[11px] text-ink-3">
                  /{fn.namespace}
                </span>
              </span>
              <span className="flex flex-none items-center gap-1.5">
                {pending > 0 ? (
                  <span className="rounded-full bg-accent px-1.5 py-0.5 font-mono text-[10.5px] font-bold text-accent-ink">
                    {pending} in flight
                  </span>
                ) : null}
                <span
                  className="font-mono text-[11px]"
                  style={{
                    color: warm >= fn.max_instances ? 'var(--warn)' : 'var(--text-2)',
                  }}
                  title={`${busy} working · ${warm} warm · ${fn.max_instances} max`}
                >
                  {warm === 0 ? 'cold' : `${busy}/${warm} of ${fn.max_instances}`}
                </span>
              </span>
            </button>
          )
        })}
      </div>

      {/* Packets live here so they are never clipped by a lane's overflow. */}
      <div ref={layer} className="pointer-events-none absolute inset-0" aria-hidden />
    </div>
  )
}

function Node({
  label,
  sub,
  innerRef,
}: {
  label: string
  sub: string
  innerRef: React.RefObject<HTMLDivElement | null>
}) {
  return (
    <div
      ref={innerRef}
      className="relative overflow-hidden rounded-[10px] border border-line bg-panel-2 px-3 py-3 text-center"
    >
      <div className="text-[12.5px] font-semibold">{label}</div>
      <div className="mt-0.5 font-mono text-[10.5px] text-ink-3">{sub}</div>
    </div>
  )
}
