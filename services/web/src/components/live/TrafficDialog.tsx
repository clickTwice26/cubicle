import { useCallback, useEffect, useRef, useState } from 'react'
import { Button, Chip, Field, Modal, Meter, Select, cx } from '../ui'
import { api } from '../../lib/api'
import type { LiveFunction } from '../../lib/live'
import type { TestResult } from '../../lib/types'

/**
 * The traffic generator.
 *
 * Fires real invocations through the real endpoint — nothing here is
 * simulated, so what the dashboard animates is what the runtime actually did.
 *
 * Traffic is described as bursts rather than a flat request count because
 * concurrency is the interesting variable: ten requests one at a time reuse a
 * single isolate, while ten at once make the pool spawn up to the function's
 * ceiling. Being able to set both is what makes the isolate grid worth
 * watching.
 */

interface Props {
  open: boolean
  onClose: () => void
  functions: LiveFunction[]
  /** Pre-selects the function the dashboard is focused on, if any. */
  focused: string | null
}

export interface Progress {
  sent: number
  total: number
  failed: number
}

/** One request's outcome. Kept per request so the report can be honest about
 *  the tail rather than only the mean. */
interface Sample {
  ms: number
  status: number
  cold: boolean
}

interface Report {
  samples: Sample[]
  failed: number
  wall_ms: number
  stopped: boolean
}

const CONCURRENCY = [1, 2, 5, 10, 25]
const BURSTS = [1, 5, 10, 25, 100]
const INTERVALS = [0, 250, 500, 1000, 2000]

export function TrafficDialog({ open, onClose, functions, focused }: Props) {
  const [target, setTarget] = useState('')
  const [concurrency, setConcurrency] = useState(5)
  const [bursts, setBursts] = useState(10)
  const [interval, setInterval] = useState(500)
  // One line: the field is an input, and a generator body is small by nature.
  const [body, setBody] = useState('{"amount": 4200}')
  const [progress, setProgress] = useState<Progress | null>(null)
  const [report, setReport] = useState<Report | null>(null)
  const [error, setError] = useState('')
  const stop = useRef(false)
  const samples = useRef<Sample[]>([])

  const running = progress !== null && progress.sent < progress.total

  useEffect(() => {
    if (!open) return
    setError('')
    setTarget((current) => current || focused || functions[0]?.id || '')
  }, [open, focused, functions])

  // A run outlives the dialog, but not the page.
  useEffect(() => () => void (stop.current = true), [])

  const total = concurrency * bursts
  const duration = ((bursts - 1) * interval) / 1000

  const start = useCallback(async () => {
    let payload: unknown
    try {
      payload = body.trim() ? JSON.parse(body) : null
    } catch {
      setError('The request body is not valid JSON.')
      return
    }
    setError('')
    setReport(null)
    stop.current = false
    samples.current = []
    setProgress({ sent: 0, total, failed: 0 })

    let failed = 0
    const started = performance.now()

    for (let burst = 0; burst < bursts; burst += 1) {
      if (stop.current) break
      // Every request in a burst leaves together; that is what forces the pool
      // to widen instead of reusing one warm isolate.
      await Promise.all(
        Array.from({ length: concurrency }, () =>
          api
            .post<TestResult>(`/api/functions/${target}/test`, { body: payload })
            .then((result) => {
              samples.current.push({
                ms: result.duration_ms,
                status: result.status_code,
                cold: Boolean(result.cold),
              })
              // A 4xx or 5xx is a completed request that failed, which the
              // report counts differently from one that never landed.
              if (result.status_code >= 400) failed += 1
              setProgress((p) =>
                p ? { ...p, sent: p.sent + 1, failed: p.failed + (result.status_code >= 400 ? 1 : 0) } : p,
              )
            })
            .catch(() => {
              failed += 1
              setProgress((p) => (p ? { ...p, sent: p.sent + 1, failed: p.failed + 1 } : p))
            }),
        ),
      )
      if (burst < bursts - 1 && interval > 0 && !stop.current) {
        await new Promise((resolve) => setTimeout(resolve, interval))
      }
    }

    setReport({
      samples: [...samples.current],
      failed,
      wall_ms: performance.now() - started,
      stopped: stop.current,
    })
  }, [body, bursts, concurrency, interval, target, total])

  const chosen = functions.find((fn) => fn.id === target)

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Send traffic"
      width={560}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {running ? 'Run in background' : 'Close'}
          </Button>
          {running ? (
            <Button
              variant="danger"
              onClick={() => {
                stop.current = true
                setProgress((p) => (p ? { ...p, total: p.sent } : p))
              }}
            >
              Stop
            </Button>
          ) : report ? (
            <Button variant="primary" disabled={!target} onClick={start}>
              Run again
            </Button>
          ) : (
            <Button variant="primary" disabled={!target} onClick={start}>
              Send {total} request{total === 1 ? '' : 's'}
            </Button>
          )}
        </>
      }
    >
      {report && !running ? (
        <ReportView report={report} name={chosen ? `/${chosen.namespace}/${chosen.name}` : ''} />
      ) : (
      <div className="grid gap-4.5">
        <div>
          <span className="mb-1.5 block text-[12.5px] text-ink-2">Function</span>
          <Select
            mono={false}
            value={target}
            disabled={running}
            onChange={(event) => setTarget(event.target.value)}
          >
            {functions.map((fn) => (
              <option key={fn.id} value={fn.id}>
                /{fn.namespace}/{fn.name} · {fn.method}
              </option>
            ))}
          </Select>
        </div>

        <Row
          label="Requests at once"
          hint="How many go out together. Above the function's max instances the extra ones queue for a free isolate."
          options={CONCURRENCY}
          value={concurrency}
          disabled={running}
          onChange={setConcurrency}
        />
        <Row
          label="Repeat"
          hint="How many bursts to send."
          options={BURSTS}
          value={bursts}
          disabled={running}
          onChange={setBursts}
          render={(n) => `${n}×`}
        />
        <Row
          label="Interval"
          hint="Wait between bursts."
          options={INTERVALS}
          value={interval}
          disabled={running}
          onChange={setInterval}
          render={(n) => (n === 0 ? 'none' : n >= 1000 ? `${n / 1000}s` : `${n}ms`)}
        />

        <Field
          label="Request body"
          value={body}
          disabled={running}
          error={error || undefined}
          onChange={(event) => setBody(event.target.value)}
        />

        <div className="rounded-[9px] border border-line bg-panel-2 px-3.5 py-3 text-[12.5px] text-ink-2">
          <span className="font-mono font-semibold text-ink">{total}</span> request
          {total === 1 ? '' : 's'} to{' '}
          <span className="font-mono">
            /{chosen?.namespace}/{chosen?.name}
          </span>{' '}
          over{' '}
          <span className="font-mono font-semibold text-ink">
            {duration === 0 ? 'no delay' : `${duration}s`}
          </span>
          {chosen ? (
            <>
              {' '}
              · at most{' '}
              <span className="font-mono font-semibold text-ink">
                {Math.min(concurrency, chosen.max_instances)}
              </span>{' '}
              isolate{Math.min(concurrency, chosen.max_instances) === 1 ? '' : 's'} will run
              {concurrency > chosen.max_instances ? ', the rest queue' : ''}
            </>
          ) : null}
        </div>

        {progress ? (
          <div>
            <div className="mb-1.5 flex justify-between text-[12.5px]">
              <span className="text-ink-2">
                {running ? 'Sending…' : progress.sent === 0 ? 'Stopped' : 'Done'}
              </span>
              <span className="font-mono text-ink-2">
                {progress.sent} / {progress.total}
                {progress.failed > 0 ? (
                  <span className="text-err"> · {progress.failed} failed</span>
                ) : null}
              </span>
            </div>
            <Meter
              value={progress.total ? (progress.sent / progress.total) * 100 : 0}
              tone={progress.failed > 0 ? 'err' : 'accent'}
            />
          </div>
        ) : null}
      </div>
      )}
    </Modal>
  )
}

/**
 * What the run actually did.
 *
 * Percentiles rather than an average, because an average hides the thing you
 * ran the test to find: the request that waited behind a cold start, or behind
 * a full pool. The histogram is there for the same reason — two runs with the
 * same mean look nothing alike when one has a tail.
 */
function ReportView({ report, name }: { report: Report; name: string }) {
  const ms = report.samples.map((s) => s.ms).sort((a, b) => a - b)
  const count = ms.length
  const at = (q: number) => (count ? ms[Math.min(count - 1, Math.floor(q * count))] : 0)

  const seconds = report.wall_ms / 1000
  const rate = seconds > 0 ? count / seconds : 0
  const cold = report.samples.filter((s) => s.cold).length
  const ok = count - report.failed

  const codes = new Map<number, number>()
  for (const sample of report.samples) codes.set(sample.status, (codes.get(sample.status) ?? 0) + 1)

  return (
    <div className="grid gap-4.5">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-[15px] font-semibold">
          {count.toLocaleString()} request{count === 1 ? '' : 's'}
        </span>
        <span className="font-mono text-[12.5px] text-ink-3">{name}</span>
        {report.stopped ? <Chip active={false}>stopped early</Chip> : null}
      </div>

      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-[10px] border border-line bg-line sm:grid-cols-4">
        <Stat label="Throughput" value={rate >= 100 ? rate.toFixed(0) : rate.toFixed(1)} unit="req/s" />
        <Stat label="Wall time" value={seconds.toFixed(1)} unit="s" />
        <Stat
          label="Succeeded"
          value={ok.toLocaleString()}
          unit={count ? `${((ok / count) * 100).toFixed(1)}%` : ''}
          tone={report.failed ? undefined : 'ok'}
        />
        <Stat
          label="Failed"
          value={report.failed.toLocaleString()}
          unit={count ? `${((report.failed / count) * 100).toFixed(1)}%` : ''}
          tone={report.failed ? 'err' : undefined}
        />
      </div>

      <div>
        <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
          <span className="text-[12.5px] font-semibold">Latency</span>
          <span className="text-[11.5px] text-ink-3">
            {cold} cold start{cold === 1 ? '' : 's'}
            {count ? ` · ${((cold / count) * 100).toFixed(1)}% of requests` : ''}
          </span>
        </div>
        <div className="grid grid-cols-3 gap-px overflow-hidden rounded-[10px] border border-line bg-line sm:grid-cols-5">
          <Stat label="min" value={fmt(ms[0] ?? 0)} unit="ms" small />
          <Stat label="p50" value={fmt(at(0.5))} unit="ms" small />
          <Stat label="p95" value={fmt(at(0.95))} unit="ms" small />
          <Stat label="p99" value={fmt(at(0.99))} unit="ms" small />
          <Stat label="max" value={fmt(ms[count - 1] ?? 0)} unit="ms" small />
        </div>
      </div>

      <Histogram values={ms} />

      <div>
        <div className="mb-2 text-[12.5px] font-semibold">Responses</div>
        <div className="flex flex-wrap gap-1.5">
          {[...codes.entries()]
            .sort((a, b) => a[0] - b[0])
            .map(([code, n]) => (
              <span
                key={code}
                className={cx(
                  'rounded-full border px-2.5 py-1 font-mono text-[11.5px]',
                  code >= 400 ? 'border-err text-err' : 'border-line text-ink-2',
                )}
              >
                {code} × {n.toLocaleString()}
              </span>
            ))}
          {report.failed > codes.size && !codes.size ? (
            <span className="text-[12px] text-ink-3">every request failed to land</span>
          ) : null}
        </div>
      </div>
    </div>
  )
}

const fmt = (value: number) => (value >= 1000 ? (value / 1000).toFixed(2) : value.toFixed(0))

function Stat({
  label,
  value,
  unit,
  tone,
  small,
}: {
  label: string
  value: string
  unit?: string
  tone?: 'ok' | 'err'
  small?: boolean
}) {
  return (
    <div className="bg-panel px-3.5 py-3">
      <div className="text-[11px] tracking-[0.04em] text-ink-3 uppercase">{label}</div>
      <div
        className={cx(
          'mt-1 font-mono leading-none font-semibold',
          small ? 'text-[15px]' : 'text-[18px]',
          tone === 'ok' ? 'text-ok' : tone === 'err' ? 'text-err' : 'text-ink',
        )}
      >
        {value}
        {unit ? <span className="ml-1 text-[11px] font-normal text-ink-3">{unit}</span> : null}
      </div>
    </div>
  )
}

/**
 * Where the requests actually landed, in twenty buckets.
 *
 * Linear rather than logarithmic: the question this answers is "did some of
 * them take much longer", and a log axis flattens exactly that.
 */
function Histogram({ values }: { values: number[] }) {
  if (values.length < 2) return null

  const min = values[0]
  const max = values[values.length - 1]
  const span = Math.max(1, max - min)
  const buckets = new Array(20).fill(0)
  for (const value of values) {
    buckets[Math.min(19, Math.floor(((value - min) / span) * 20))] += 1
  }
  const peak = Math.max(...buckets)

  return (
    <div>
      <div className="mb-2 text-[12.5px] font-semibold">Distribution</div>
      <div className="flex h-16 items-end gap-[2px]">
        {buckets.map((n, index) => (
          <div
            key={index}
            className="flex-1 rounded-[2px] bg-accent transition-[height]"
            style={{ height: `${peak ? Math.max(2, (n / peak) * 100) : 2}%` }}
            title={`${Math.round(min + (index / 20) * span)}–${Math.round(
              min + ((index + 1) / 20) * span,
            )} ms · ${n} request${n === 1 ? '' : 's'}`}
          />
        ))}
      </div>
      <div className="mt-1 flex justify-between font-mono text-[10.5px] text-ink-3">
        <span>{fmt(min)} ms</span>
        <span>{fmt(max)} ms</span>
      </div>
    </div>
  )
}

function Row({
  label,
  hint,
  options,
  value,
  disabled,
  onChange,
  render,
}: {
  label: string
  hint?: string
  options: readonly number[]
  value: number
  disabled?: boolean
  onChange: (next: number) => void
  render?: (option: number) => string
}) {
  return (
    <div className={cx(disabled && 'pointer-events-none opacity-50')}>
      <span className="block text-[12.5px] text-ink-2">{label}</span>
      {hint ? <div className="mt-0.5 mb-2 text-[12px] text-ink-3">{hint}</div> : null}
      <div className={cx('flex flex-wrap gap-2', !hint && 'mt-2')}>
        {options.map((option) => (
          <Chip key={option} active={value === option} onClick={() => onChange(option)}>
            {render ? render(option) : String(option)}
          </Chip>
        ))}
      </div>
    </div>
  )
}
