import { useEffect, useRef, useState } from 'react'
import { Badge, Button, Card, CardHeader, ConfirmButton, Spinner, cx, useToast } from './ui'
import {
  useCheckForUpdate,
  useMe,
  useStartUpdate,
  useUpdateProgress,
  useUpdateStatus,
} from '../lib/hooks'
import { relativeTime } from '../lib/format'

/**
 * Whether this instance is behind its branch, and catching it up.
 *
 * Super admin only: applying an update runs whatever is on that branch on the
 * host. The console is also one of the things being replaced, so once an update
 * starts this component expects to lose the API and treats that as progress
 * rather than failure.
 */

export function UpdateCard() {
  const toast = useToast()
  const { data: me } = useMe()
  const owner = me?.role === 'owner'

  const status = useUpdateStatus(owner)
  const check = useCheckForUpdate()
  const start = useStartUpdate()

  const [running, setRunning] = useState(false)
  const progress = useUpdateProgress(running)
  const wasRunning = useRef(false)

  // An update started in another tab — or before a reload — is still ours to
  // follow, so pick it up rather than showing a stale "up to date".
  useEffect(() => {
    if (progress.data?.state === 'running') setRunning(true)
  }, [progress.data?.state])

  useEffect(() => {
    if (!running) return
    if (progress.data?.state === 'running') wasRunning.current = true
    if (!wasRunning.current) return

    if (progress.data?.state === 'success') {
      setRunning(false)
      wasRunning.current = false
      toast.push('Updated — reload to pick up the new console')
    } else if (progress.data?.state === 'failed') {
      setRunning(false)
      wasRunning.current = false
      toast.push('The update failed. The log below says where.', 'err')
    }
  }, [running, progress.data?.state, toast])

  if (!owner) return null

  const data = status.data
  const logs = progress.data?.logs ?? ''
  const failed = !running && progress.data?.state === 'failed'
  const finished = !running && progress.data?.state === 'success'

  return (
    <Card className="mb-5 overflow-hidden">
      <CardHeader
        title="Updates"
        subtitle={
          data?.repo
            ? `Tracking ${data.repo} on ${data.branch}. Updating pulls that branch on the host and rebuilds every container.`
            : 'Whether this instance is running the newest commit on its branch.'
        }
        action={
          !running ? (
            <Button
              size="sm"
              loading={check.isPending || status.isLoading}
              onClick={() =>
                check.mutate(undefined, {
                  onSuccess: (next) =>
                    toast.push(next.available ? 'Update available' : 'Already up to date'),
                  onError: (error) => toast.push(error.message, 'err'),
                })
              }
            >
              Check now
            </Button>
          ) : null
        }
      />

      {running ? (
        <Running logs={logs} />
      ) : (
        <>
          <div className="grid gap-4 px-5 py-5 sm:grid-cols-2">
            <Version label="Running" sha={data?.current} />
            <Version
              label={data?.available ? 'Available' : 'Newest on the branch'}
              sha={data?.latest}
              highlight={data?.available}
            />
          </div>

          {data?.error ? (
            <div className="border-t border-line px-5 py-3 text-[12.5px] leading-relaxed text-err">
              {data.error}
            </div>
          ) : data?.available ? (
            <div className="border-t border-line px-5 py-4">
              <div className="text-[13px] font-semibold [overflow-wrap:anywhere]">
                {data.message}
              </div>
              <div className="mt-1 text-[12.5px] text-ink-3">
                {data.author}
                {data.date ? ` · ${relativeTime(data.date)}` : ''}
              </div>

              <div className="mt-3.5 flex flex-wrap items-center gap-3">
                <ConfirmButton
                  as="button"
                  label="Update now"
                  confirmLabel="Yes, rebuild and restart"
                  hint="Pulls the branch and rebuilds every container. The console will be unreachable for a minute or two."
                  onConfirm={() =>
                    start.mutate(undefined, {
                      onSuccess: () => setRunning(true),
                      onError: (error) => toast.push(error.message, 'err'),
                    })
                  }
                />
                <span className="text-[12px] text-ink-3">
                  Runs whatever is on {data.branch}. Nothing else is checked.
                </span>
              </div>
            </div>
          ) : (
            <div className="border-t border-line px-5 py-3 text-[12.5px] text-ink-2">
              <span className="font-semibold text-ink">Up to date.</span> Nothing newer has been
              pushed to {data?.branch || 'the branch'}.
            </div>
          )}

          {(failed || finished) && logs ? (
            <details className="border-t border-line" open={failed}>
              <summary className="cursor-pointer px-5 py-2.5 text-[12.5px] text-ink-2 select-none hover:text-ink">
                {failed ? 'What went wrong' : 'What the last update did'}
              </summary>
              <Log text={logs} />
            </details>
          ) : null}
        </>
      )}
    </Card>
  )
}

function Running({ logs }: { logs: string }) {
  return (
    <>
      <div className="flex items-center gap-3 border-b border-line bg-panel-2 px-5 py-3">
        <Spinner size={14} />
        <div className="min-w-0">
          <div className="text-[13px] font-semibold">Updating</div>
          <div className="text-[12.5px] text-ink-3">
            The console will stop answering while it rebuilds. This page keeps watching and picks
            the log back up when it returns.
          </div>
        </div>
      </div>
      <Log text={logs || 'Starting…'} />
    </>
  )
}

function Log({ text }: { text: string }) {
  const box = useRef<HTMLPreElement>(null)

  // Follow the tail, the way a terminal would.
  useEffect(() => {
    if (box.current) box.current.scrollTop = box.current.scrollHeight
  }, [text])

  return (
    <pre
      ref={box}
      className="max-h-64 overflow-auto bg-bg px-5 py-3 font-mono text-[12px] leading-relaxed whitespace-pre-wrap text-ink-2"
    >
      {text}
    </pre>
  )
}

function Version({
  label,
  sha,
  highlight,
}: {
  label: string
  sha?: string
  highlight?: boolean
}) {
  return (
    <div className="min-w-0">
      <div className="mb-1.5 flex items-center gap-2 text-[12.5px] text-ink-2">
        {label}
        {highlight ? <Badge tone="accent">new</Badge> : null}
      </div>
      <div
        className={cx(
          'font-mono text-[13.5px]',
          highlight ? 'font-semibold text-ink' : 'text-ink-2',
        )}
      >
        {sha ? sha.slice(0, 12) : '—'}
      </div>
    </div>
  )
}
