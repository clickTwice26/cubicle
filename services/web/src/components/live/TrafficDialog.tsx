import { useCallback, useEffect, useRef, useState } from 'react'
import { Button, Chip, Field, Modal, Meter, cx } from '../ui'
import { api } from '../../lib/api'
import type { LiveFunction } from '../../lib/live'

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
  const [error, setError] = useState('')
  const stop = useRef(false)

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
    stop.current = false
    setProgress({ sent: 0, total, failed: 0 })

    for (let burst = 0; burst < bursts; burst += 1) {
      if (stop.current) break
      // Every request in a burst leaves together; that is what forces the pool
      // to widen instead of reusing one warm isolate.
      await Promise.all(
        Array.from({ length: concurrency }, () =>
          api
            .post(`/api/functions/${target}/test`, { body: payload })
            .then(() => setProgress((p) => (p ? { ...p, sent: p.sent + 1 } : p)))
            .catch(() =>
              setProgress((p) => (p ? { ...p, sent: p.sent + 1, failed: p.failed + 1 } : p)),
            ),
        ),
      )
      if (burst < bursts - 1 && interval > 0 && !stop.current) {
        await new Promise((resolve) => setTimeout(resolve, interval))
      }
    }
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
          ) : (
            <Button variant="primary" disabled={!target} onClick={start}>
              Send {total} request{total === 1 ? '' : 's'}
            </Button>
          )}
        </>
      }
    >
      <div className="grid gap-4.5">
        <div>
          <span className="mb-1.5 block text-[12.5px] text-ink-2">Function</span>
          <select
            value={target}
            disabled={running}
            onChange={(event) => setTarget(event.target.value)}
            className="h-10 w-full rounded-[9px] border border-line bg-bg px-3 text-sm text-ink outline-none focus:border-accent disabled:opacity-50"
          >
            {functions.map((fn) => (
              <option key={fn.id} value={fn.id}>
                /{fn.namespace}/{fn.name} · {fn.method}
              </option>
            ))}
          </select>
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
    </Modal>
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
