import { useState } from 'react'
import {
  Badge,
  Button,
  Card,
  ConfirmButton,
  EmptyState,
  Select,
  Skeleton,
  cx,
  useToast,
} from './ui'
import {
  useCreateTrigger,
  useDeleteTrigger,
  useRunTrigger,
  useSchedulePreview,
  useTriggers,
  useUpdateTrigger,
} from '../lib/hooks'
import { relativeTime } from '../lib/format'
import type { FunctionDetail, Trigger } from '../lib/types'

/**
 * The ways a function runs other than someone calling it.
 *
 * Schedules only, for now. The panel is built around cron because that is what
 * is stored and what the scheduler reads, but nobody should have to write cron
 * to get a daily job: the presets compose the expression, the field accepts one
 * directly, and the server says in English what it read and when it will fire.
 */

const PRESETS = [
  { label: 'Every 5 minutes', cron: '*/5 * * * *' },
  { label: 'Every 15 minutes', cron: '*/15 * * * *' },
  { label: 'Hourly', cron: '0 * * * *' },
  { label: 'Daily at 09:00', cron: '0 9 * * *' },
  { label: 'Daily at midnight', cron: '0 0 * * *' },
  { label: 'Mondays at 09:00', cron: '0 9 * * 1' },
]

/** What the browser thinks it is, so a schedule defaults to the operator's clock. */
const LOCAL_ZONE = (() => {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  } catch {
    return 'UTC'
  }
})()

const ZONES = Array.from(new Set(['UTC', LOCAL_ZONE]))

export function TriggerPanel({ fn }: { fn: FunctionDetail }) {
  const { data: triggers, isLoading } = useTriggers(fn.id)
  const independent = fn.function_type === 'independent'

  return (
    <div className="grid gap-5">
      {!independent ? <DependentNotice name={fn.name} /> : null}

      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-line px-5 py-3.5">
          <div className="text-sm font-semibold">Schedules</div>
          <div className="text-[11.5px] text-ink-3">
            Runs with no request body, on the cluster, whether or not anyone is watching
          </div>
        </div>

        {isLoading ? (
          <div className="space-y-3 p-5">
            {Array.from({ length: 2 }).map((_, index) => (
              <Skeleton key={index} className="h-14 w-full" />
            ))}
          </div>
        ) : triggers?.length ? (
          triggers.map((trigger) => (
            <TriggerRow key={trigger.id} functionId={fn.id} trigger={trigger} />
          ))
        ) : (
          <div className="p-5">
            <EmptyState
              title="No schedules"
              body={
                independent
                  ? 'Add one below and this function will run on its own.'
                  : 'Mark this function independent first — a schedule has no request body to send.'
              }
            />
          </div>
        )}
      </Card>

      {independent ? <NewSchedule fn={fn} /> : null}
    </div>
  )
}

function DependentNotice({ name }: { name: string }) {
  return (
    <Card className="border-warn px-5 py-4">
      <div className="text-[13px] font-semibold">This function cannot be scheduled</div>
      <p className="mt-1.5 mb-0 text-[12.5px] leading-relaxed text-ink-2">
        <span className="font-mono">{name}</span> is marked <b>dependent</b>, meaning it expects a
        request body. A schedule has none to send, so it would be invoked with nothing and fail on
        a timer. Mark it <b>independent</b> in Settings if it does not read its input.
      </p>
    </Card>
  )
}

function TriggerRow({ functionId, trigger }: { functionId: string; trigger: Trigger }) {
  const toast = useToast()
  const update = useUpdateTrigger(functionId)
  const runNow = useRunTrigger(functionId)
  const remove = useDeleteTrigger(functionId)

  const tone =
    trigger.last_status === 'failed' ? 'err' : trigger.last_status === 'ok' ? 'accent' : undefined

  return (
    <div className="border-b border-line px-5 py-4 last:border-b-0">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <div className="min-w-0 flex-1 basis-[220px]">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[13.5px] font-semibold">{trigger.description}</span>
            {!trigger.enabled ? <Badge>paused</Badge> : null}
            {trigger.last_status ? <Badge tone={tone}>{trigger.last_status}</Badge> : null}
          </div>
          <div className="mt-1 font-mono text-[11.5px] text-ink-3">
            {trigger.cron} · {trigger.timezone}
          </div>
        </div>

        <div className="flex flex-none flex-wrap items-center gap-2">
          <Button
            size="sm"
            loading={runNow.isPending}
            onClick={() =>
              runNow.mutate(trigger.id, {
                onSuccess: () => toast.push('Ran once'),
                onError: (error) => toast.push(error.message, 'err'),
              })
            }
          >
            Run now
          </Button>
          <Button
            size="sm"
            variant="ghost"
            loading={update.isPending}
            onClick={() =>
              update.mutate(
                { id: trigger.id, enabled: !trigger.enabled },
                { onError: (error) => toast.push(error.message, 'err') },
              )
            }
          >
            {trigger.enabled ? 'Pause' : 'Resume'}
          </Button>
          <ConfirmButton
            as="button"
            label="Delete"
            confirmLabel="Confirm"
            onConfirm={() =>
              remove.mutate(trigger.id, {
                onSuccess: () => toast.push('Schedule deleted'),
                onError: (error) => toast.push(error.message, 'err'),
              })
            }
          />
        </div>
      </div>

      <div className="mt-2.5 flex flex-wrap gap-x-5 gap-y-1 text-[12px] text-ink-3">
        <span>
          Next:{' '}
          <span className="text-ink-2">
            {trigger.next_run_at ? relativeTime(trigger.next_run_at) : 'not scheduled'}
          </span>
        </span>
        <span>
          Last:{' '}
          <span className="text-ink-2">
            {trigger.last_run_at ? relativeTime(trigger.last_run_at) : 'never'}
          </span>
        </span>
        <span>
          Runs: <span className="text-ink-2">{trigger.run_count}</span>
        </span>
      </div>

      {trigger.last_error ? (
        <div className="mt-2 rounded-[8px] border border-line bg-panel-2 px-3 py-2 font-mono text-[11.5px] text-err [overflow-wrap:anywhere]">
          {trigger.last_error}
        </div>
      ) : null}
    </div>
  )
}

function NewSchedule({ fn }: { fn: FunctionDetail }) {
  const toast = useToast()
  const create = useCreateTrigger(fn.id)
  const [cron, setCron] = useState('0 9 * * *')
  const [timezone, setTimezone] = useState(LOCAL_ZONE)

  const { data: preview } = useSchedulePreview(fn.id, cron, timezone)

  return (
    <Card className="overflow-hidden">
      <div className="border-b border-line px-5 py-3.5 text-sm font-semibold">Add a schedule</div>

      <div className="grid gap-4 px-5 py-5">
        <div>
          <span className="mb-2 block text-[12.5px] text-ink-2">Start from</span>
          <div className="flex flex-wrap gap-1.5">
            {PRESETS.map((preset) => (
              <button
                key={preset.cron}
                type="button"
                onClick={() => setCron(preset.cron)}
                className={cx(
                  'rounded-full border px-2.5 py-1 text-[12px] transition',
                  cron === preset.cron
                    ? 'border-accent bg-accent-soft font-semibold text-ink'
                    : 'border-line text-ink-2 hover:border-line-strong hover:text-ink',
                )}
              >
                {preset.label}
              </button>
            ))}
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-[1fr_auto]">
          <div>
            <span className="mb-1.5 block text-[12.5px] text-ink-2">Cron expression</span>
            <input
              value={cron}
              onChange={(event) => setCron(event.target.value)}
              spellCheck={false}
              className={cx(
                'h-10 w-full rounded-[9px] border bg-bg px-3 font-mono text-[13.5px] text-ink outline-none transition',
                preview && !preview.valid ? 'border-err' : 'border-line-strong focus:border-accent',
              )}
            />
            <div className="mt-1.5 text-[12px] text-ink-3">
              minute · hour · day of month · month · day of week
            </div>
          </div>

          <div>
            <Select
              label="Timezone"
              value={timezone}
              onChange={(event) => setTimezone(event.target.value)}
            >
              {ZONES.map((entry) => (
                <option key={entry} value={entry}>
                  {entry}
                </option>
              ))}
            </Select>
          </div>
        </div>

        {/* Read back from the server, not guessed at in the browser: the thing
            that will actually run it is the thing that should say when. */}
        {preview ? (
          preview.valid ? (
            <div className="rounded-[9px] border border-line bg-panel-2 px-3.5 py-3">
              <div className="text-[13px] font-semibold">{preview.description}</div>
              <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 font-mono text-[11.5px] text-ink-3">
                {preview.upcoming.slice(0, 3).map((when) => (
                  <span key={when}>{new Date(when).toLocaleString()}</span>
                ))}
              </div>
            </div>
          ) : (
            <div className="rounded-[9px] border border-err px-3.5 py-3 text-[12.5px] text-err">
              {preview.error}
            </div>
          )
        ) : null}
      </div>

      <div className="flex items-center justify-end border-t border-line px-5 py-3">
        <Button
          variant="primary"
          size="sm"
          loading={create.isPending}
          disabled={!preview?.valid}
          onClick={() =>
            create.mutate(
              { cron: cron.trim(), timezone },
              {
                onSuccess: () => toast.push('Schedule added'),
                onError: (error) => toast.push(error.message, 'err'),
              },
            )
          }
        >
          Add schedule
        </Button>
      </div>
    </Card>
  )
}
