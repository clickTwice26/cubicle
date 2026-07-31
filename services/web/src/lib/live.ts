/**
 * The live activity stream.
 *
 * One SSE connection feeds every panel on the activity page. Events arrive at
 * whatever rate the cluster is running at, which can be much faster than a
 * screen refreshes, so this splits into two paths:
 *
 *   - React state (counters, isolate tiles, the ticker) is accumulated into a
 *     buffer and flushed on an animation frame. A burst of 200 invocations
 *     costs one render, not two hundred.
 *   - Animations that have to fire the instant something happens — a packet
 *     leaving the ingress — subscribe to `onEvent` and drive the DOM directly,
 *     bypassing React entirely.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { subscribe } from './api'
import { useActiveCluster } from './cluster'

export interface LiveFunction {
  id: string
  name: string
  namespace: string
  method: string
  status: string
  memory_mb: number
  min_instances: number
  max_instances: number
  warm: number
}

export interface LiveIsolate {
  id: string
  function: string
  namespace: string
  function_id: string
  node: string
  busy: boolean
  invocations: number
  memory_mb: number
  cpus: number
  age_s: number
  idle_s: number
}

export interface LiveNode {
  name: string
  status: string
  pool: string
}

export interface RecentInvocation {
  request_id: string
  function_id: string
  function: string
  status: number
  duration_ms: number
  cold: boolean
  ts: number
}

export interface LiveTotals {
  invocations: number
  errors: number
  cold: number
}

/** An isolate as the UI knows it: server truth plus a bit of animation state. */
export interface IsolateView extends LiveIsolate {
  phase: 'booting' | 'busy' | 'idle' | 'gone'
  bornAt: number
  bootMs?: number
}

export interface InFlight {
  request_id: string
  function_id: string
  function: string
  method: string
  startedAt: number
}

export interface TickerEntry {
  id: string
  kind: string
  label: string
  detail: string
  tone: 'ok' | 'err' | 'warn' | 'info' | 'muted'
  at: number
}

export interface LiveEvent {
  kind: string
  ts: number
  [key: string]: unknown
}

/** How many seconds of per-second throughput the sparkline keeps. */
export const RATE_WINDOW = 60
const TICKER_MAX = 60
/** A finished isolate tile lingers this long so its exit animation can play. */
const GHOST_MS = 700

export interface LiveData {
  connected: boolean
  paused: boolean
  setPaused: (next: boolean) => void
  functions: LiveFunction[]
  nodes: LiveNode[]
  isolates: IsolateView[]
  inFlight: InFlight[]
  totals: LiveTotals
  windowMinutes: number
  /** Per-second invocation counts, oldest first, always RATE_WINDOW long. */
  rate: number[]
  latencies: RecentInvocation[]
  ticker: TickerEntry[]
  spawned: number
  onEvent: (handler: (event: LiveEvent) => void) => () => void
}

export function useLiveStream(): LiveData {
  const cluster = useActiveCluster()
  const [paused, setPaused] = useState(false)
  const [connected, setConnected] = useState(false)
  const [, forceRender] = useState(0)

  // Everything mutable lives in a ref: events mutate it at network speed and a
  // single rAF turns that into one React render.
  const store = useRef<Store | null>(null)
  store.current ??= emptyStore()

  const listeners = useRef(new Set<(event: LiveEvent) => void>())
  const frame = useRef(0)
  const pausedRef = useRef(paused)
  pausedRef.current = paused

  const schedule = useCallback(() => {
    const state = store.current!
    state.dirty = true
    if (frame.current) return
    frame.current = requestAnimationFrame(() => {
      frame.current = 0
      if (state.dirty) {
        state.dirty = false
        forceRender((n) => n + 1)
      }
    })
  }, [])

  const onEvent = useCallback((handler: (event: LiveEvent) => void) => {
    listeners.current.add(handler)
    return () => listeners.current.delete(handler)
  }, [])

  useEffect(() => {
    const state = store.current!
    // A cluster switch is a different world: drop everything rather than
    // letting the previous cluster's isolates linger under the new name.
    state.functions = []
    state.nodes = []
    state.isolates.clear()
    state.inFlight.clear()
    state.totals = { invocations: 0, errors: 0, cold: 0 }
    state.rate = new Array<number>(RATE_WINDOW).fill(0)
    state.latencies = []
    state.ticker = []
    state.spawned = 0
    schedule()

    const stop = subscribe<LiveEvent>(
      '/api/live/stream',
      (event) => {
        setConnected(true)
        if (pausedRef.current && event.kind !== 'state') return
        apply(state, event)
        for (const listener of listeners.current) listener(event)
        schedule()
      },
      () => setConnected(false),
    )
    return () => {
      stop()
      setConnected(false)
    }
  }, [cluster, schedule])

  // Ghost tiles and the rate window move on wall-clock time, not on events, so
  // an idle cluster still animates down to zero instead of freezing.
  useEffect(() => {
    const timer = window.setInterval(() => {
      const state = store.current!
      const now = Date.now()
      let changed = rollRate(state, now)
      for (const [id, isolate] of state.isolates) {
        if (isolate.phase === 'gone' && now - isolate.bornAt > GHOST_MS) {
          state.isolates.delete(id)
          changed = true
        }
      }
      if (changed) schedule()
    }, 250)
    return () => window.clearInterval(timer)
  }, [schedule])

  // Read straight from the store on each render: the rAF flush is what decides
  // when a render happens, so memoising here would only add a stale path.
  const state = store.current
  const isolates = [...state.isolates.values()].sort((a, b) => a.bornAt - b.bornAt)

  return {
    connected,
    paused,
    setPaused,
    functions: state.functions,
    nodes: state.nodes,
    isolates,
    inFlight: [...state.inFlight.values()],
    totals: state.totals,
    windowMinutes: state.windowMinutes,
    rate: state.rate,
    latencies: state.latencies,
    ticker: state.ticker,
    spawned: state.spawned,
    onEvent,
  }
}

type Store = ReturnType<typeof emptyStore>

function emptyStore() {
  return {
    functions: [] as LiveFunction[],
    nodes: [] as LiveNode[],
    isolates: new Map<string, IsolateView>(),
    inFlight: new Map<string, InFlight>(),
    totals: { invocations: 0, errors: 0, cold: 0 } as LiveTotals,
    windowMinutes: 5,
    rate: new Array<number>(RATE_WINDOW).fill(0),
    rateSecond: Math.floor(Date.now() / 1000),
    latencies: [] as RecentInvocation[],
    ticker: [] as TickerEntry[],
    spawned: 0,
    dirty: false,
  }
}

/** Advance the per-second buckets to now. Returns whether anything moved. */
function rollRate(state: Store, now: number): boolean {
  const second = Math.floor(now / 1000)
  if (second === state.rateSecond) return false
  const gap = Math.min(second - state.rateSecond, RATE_WINDOW)
  state.rate = [...state.rate.slice(gap), ...new Array<number>(gap).fill(0)]
  state.rateSecond = second
  return true
}

function apply(state: Store, event: LiveEvent): void {
  const now = Date.now()
  rollRate(state, now)

  switch (event.kind) {
    case 'state': {
      state.functions = (event.functions as LiveFunction[]) ?? []
      state.nodes = (event.nodes as LiveNode[]) ?? []
      state.totals = (event.totals as LiveTotals) ?? state.totals
      state.windowMinutes = (event.window_minutes as number) ?? 5
      state.latencies = (event.recent as RecentInvocation[]) ?? []
      state.isolates.clear()
      for (const isolate of (event.isolates as LiveIsolate[]) ?? []) {
        state.isolates.set(isolate.id, {
          ...isolate,
          phase: isolate.busy ? 'busy' : 'idle',
          // Backdated so an isolate that was already warm does not play a
          // spawn animation on connect.
          bornAt: now - isolate.age_s * 1000,
        })
      }
      // Seed the sparkline from history so the chart is not empty on arrival.
      for (const invocation of state.latencies) {
        const offset = Math.floor(now / 1000) - Math.floor(invocation.ts)
        if (offset >= 0 && offset < RATE_WINDOW) state.rate[RATE_WINDOW - 1 - offset] += 1
      }
      break
    }

    case 'tick': {
      // The authoritative isolate list: reconciles anything the event stream
      // missed, without disturbing tiles that are mid-animation.
      const seen = new Set<string>()
      for (const isolate of (event.isolates as LiveIsolate[]) ?? []) {
        seen.add(isolate.id)
        const existing = state.isolates.get(isolate.id)
        state.isolates.set(isolate.id, {
          ...isolate,
          phase: existing?.phase === 'booting' ? 'booting' : isolate.busy ? 'busy' : 'idle',
          bornAt: existing?.bornAt ?? now - isolate.age_s * 1000,
          bootMs: existing?.bootMs,
        })
      }
      for (const [id, isolate] of state.isolates) {
        if (!seen.has(id) && isolate.phase !== 'gone' && isolate.phase !== 'booting') {
          state.isolates.set(id, { ...isolate, phase: 'gone', bornAt: now })
        }
      }
      break
    }

    case 'invocation.start': {
      state.inFlight.set(event.request_id as string, {
        request_id: event.request_id as string,
        function_id: event.function_id as string,
        function: event.function as string,
        method: (event.method as string) ?? 'POST',
        startedAt: now,
      })
      break
    }

    case 'invocation.end': {
      state.inFlight.delete(event.request_id as string)
      const status = event.status as number
      const cold = Boolean(event.cold)
      state.totals = {
        invocations: state.totals.invocations + 1,
        errors: state.totals.errors + (status >= 400 ? 1 : 0),
        cold: state.totals.cold + (cold ? 1 : 0),
      }
      state.rate[RATE_WINDOW - 1] += 1
      state.latencies = [
        ...state.latencies.slice(-199),
        {
          request_id: event.request_id as string,
          function_id: event.function_id as string,
          function: event.function as string,
          status,
          duration_ms: event.duration_ms as number,
          cold,
          ts: event.ts,
        },
      ]
      push(state, {
        kind: event.kind,
        label: `${event.function}`,
        detail: `${status} · ${Math.round(event.duration_ms as number)}ms${cold ? ' · cold' : ''}`,
        tone: status >= 500 ? 'err' : status >= 400 ? 'warn' : 'ok',
        at: now,
      })
      break
    }

    case 'isolate.spawn': {
      state.spawned += 1
      state.isolates.set(event.isolate as string, {
        id: event.isolate as string,
        function: event.function as string,
        namespace: event.namespace as string,
        function_id: event.function_id as string,
        node: (event.node as string) ?? 'node-01',
        busy: false,
        invocations: 0,
        memory_mb: (event.memory_mb as number) ?? 128,
        cpus: 0,
        age_s: 0,
        idle_s: 0,
        phase: 'booting',
        bornAt: now,
      })
      push(state, {
        kind: event.kind,
        label: event.function as string,
        detail: 'cold start — booting isolate',
        tone: 'warn',
        at: now,
      })
      break
    }

    case 'isolate.ready': {
      patch(state, event.isolate as string, (isolate) => ({
        ...isolate,
        phase: 'idle',
        bootMs: event.boot_ms as number,
      }))
      push(state, {
        kind: event.kind,
        label: event.function as string,
        detail: `isolate ready in ${Math.round((event.boot_ms as number) ?? 0)}ms`,
        tone: 'info',
        at: now,
      })
      break
    }

    case 'isolate.busy':
      patch(state, event.isolate as string, (isolate) => ({
        ...isolate,
        busy: true,
        phase: 'busy',
      }))
      break

    case 'isolate.idle':
      patch(state, event.isolate as string, (isolate) => ({
        ...isolate,
        busy: false,
        phase: 'idle',
        invocations: (event.invocations as number) ?? isolate.invocations,
      }))
      break

    case 'isolate.gone': {
      patch(state, event.isolate as string, (isolate) => ({
        ...isolate,
        phase: 'gone',
        bornAt: now,
      }))
      push(state, {
        kind: event.kind,
        label: event.function as string,
        detail: event.reason === 'failed' ? 'isolate failed to start' : 'isolate reclaimed',
        tone: event.reason === 'failed' ? 'err' : 'muted',
        at: now,
      })
      break
    }
  }
}

function patch(state: Store, id: string, fn: (isolate: IsolateView) => IsolateView): void {
  const existing = state.isolates.get(id)
  if (existing) state.isolates.set(id, fn(existing))
}

let ticker = 0
function push(state: Store, entry: Omit<TickerEntry, 'id'>): void {
  state.ticker = [{ ...entry, id: `t${(ticker += 1)}` }, ...state.ticker].slice(0, TICKER_MAX)
}
