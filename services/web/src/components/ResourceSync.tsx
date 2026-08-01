import { useState } from 'react'
import { Badge, Button, Card, CardHeader, Checkbox, ConfirmButton, cx, useToast } from './ui'
import { useMe, useReconcileApply, useReconcileScan } from '../lib/hooks'
import type { ReconcileFinding, ReconcileReport } from '../lib/types'

/**
 * What the database and the pool believe, against what Docker actually has.
 *
 * Scanning is explicit rather than automatic: it walks every engine, and an
 * operator who did not ask for it would not know why the page paused. Nothing
 * is ever fixed without being chosen — some fixes delete the only copy of
 * someone's data, so "tidy up for me" is not on offer.
 */

const SEVERITY: Record<string, { tone: 'err' | 'warn' | 'accent'; label: string }> = {
  error: { tone: 'err', label: 'breaking' },
  warn: { tone: 'warn', label: 'wasteful' },
  info: { tone: 'accent', label: 'noted' },
}

export function ResourceSync() {
  const toast = useToast()
  const { data: me } = useMe()
  const scan = useReconcileScan()
  const apply = useReconcileApply()

  const [report, setReport] = useState<ReconcileReport | null>(null)
  const [chosen, setChosen] = useState<Set<string>>(new Set())

  if (me?.role !== 'owner') return null

  const findings = report?.findings ?? []
  const actionable = findings.filter((f) => f.fix)
  const selected = actionable.filter((f) => chosen.has(f.id))
  const destructive = selected.filter((f) => f.destructive)

  function runScan() {
    scan.mutate(undefined, {
      onSuccess: (next) => {
        setReport(next)
        setChosen(new Set())
        toast.push(
          next.findings.length
            ? `${next.findings.length} thing${next.findings.length === 1 ? '' : 's'} out of sync`
            : 'Everything matches',
        )
      },
      onError: (error) => toast.push(error.message, 'err'),
    })
  }

  function runApply() {
    apply.mutate([...chosen], {
      onSuccess: (result) => {
        setReport(result.report)
        setChosen(new Set())
        const failed = result.failed.length
        toast.push(
          failed
            ? `Fixed ${result.applied.length}, ${failed} failed`
            : `Fixed ${result.applied.length}`,
          failed ? 'err' : undefined,
        )
        for (const failure of result.failed) toast.push(failure.error, 'err')
      },
      onError: (error) => toast.push(error.message, 'err'),
    })
  }

  function toggle(id: string) {
    setChosen((previous) => {
      const next = new Set(previous)
      if (!next.delete(id)) next.add(id)
      return next
    })
  }

  return (
    <Card className="mb-5 overflow-hidden">
      <CardHeader
        title="Resource sync"
        subtitle="Checks what the database and the warm pool believe against what Docker actually has, on every node."
        action={
          <Button size="sm" loading={scan.isPending} onClick={runScan}>
            {report ? 'Scan again' : 'Scan'}
          </Button>
        }
      />

      {!report ? (
        <div className="px-5 py-5 text-[12.5px] leading-relaxed text-ink-2">
          Nothing has been checked yet. A scan reads every node and changes nothing — it reports
          instances the pool still routes to that have died, containers left behind by a control
          plane that was killed mid-start, and volumes whose service was deleted. You choose what,
          if anything, to act on.
        </div>
      ) : findings.length === 0 ? (
        <div className="px-5 py-5 text-[13px] text-ink-2">
          <span className="font-semibold text-ink">Everything matches.</span> Every warm instance
          the pool routes to is running, every recorded service has its container, and no volume or
          container is left without an owner.
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 border-b border-line bg-panel-2 px-5 py-2.5 text-[12.5px] text-ink-2">
            {report.errors > 0 ? (
              <span>
                <span className="font-semibold text-err">{report.errors}</span> breaking something
                now
              </span>
            ) : null}
            {report.warnings > 0 ? (
              <span>
                <span className="font-semibold text-ink">{report.warnings}</span> wasting resources
              </span>
            ) : null}
            <span className="text-ink-3">
              {actionable.length} of {findings.length} can be fixed from here
            </span>
          </div>

          {findings.map((finding) => (
            <FindingRow
              key={finding.id}
              finding={finding}
              checked={chosen.has(finding.id)}
              onToggle={() => toggle(finding.id)}
            />
          ))}

          <div className="flex flex-wrap items-center gap-3 border-t border-line bg-panel-2 px-5 py-3">
            <button
              type="button"
              className="text-[12.5px] text-ink-2 underline-offset-2 hover:text-ink hover:underline"
              onClick={() =>
                setChosen(
                  new Set(actionable.filter((f) => !f.destructive).map((f) => f.id)),
                )
              }
            >
              Select everything safe
            </button>
            {chosen.size ? (
              <button
                type="button"
                className="text-[12.5px] text-ink-2 underline-offset-2 hover:text-ink hover:underline"
                onClick={() => setChosen(new Set())}
              >
                Clear
              </button>
            ) : null}

            <div className="ml-auto flex items-center gap-3">
              {destructive.length ? (
                <ConfirmButton
                  as="button"
                  label={`Fix ${selected.length} — deletes data`}
                  confirmLabel="Delete for real"
                  hint={`${destructive.length} of these destroy data that does not come back`}
                  onConfirm={runApply}
                />
              ) : (
                <Button
                  variant="primary"
                  size="sm"
                  disabled={!selected.length}
                  loading={apply.isPending}
                  onClick={runApply}
                >
                  {selected.length ? `Fix ${selected.length} selected` : 'Nothing selected'}
                </Button>
              )}
            </div>
          </div>
        </>
      )}
    </Card>
  )
}

function FindingRow({
  finding,
  checked,
  onToggle,
}: {
  finding: ReconcileFinding
  checked: boolean
  onToggle: () => void
}) {
  const severity = SEVERITY[finding.severity] ?? SEVERITY.info

  return (
    <div className="flex gap-3 border-b border-line px-5 py-3.5 last:border-b-0">
      <div className="pt-0.5">
        {finding.fix ? (
          <Checkbox checked={checked} onChange={onToggle} label="" />
        ) : (
          <span className="block w-4" />
        )}
      </div>

      <div className="min-w-0 flex-1 [overflow-wrap:anywhere]">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={severity.tone}>{severity.label}</Badge>
          {finding.cluster ? (
            <span className="font-mono text-[11.5px] text-ink-3">{finding.cluster}</span>
          ) : null}
          {finding.destructive ? <Badge tone="err">destroys data</Badge> : null}
        </div>

        <div className="mt-1.5 text-[13px] font-semibold">{finding.summary}</div>
        <div className="mt-1 text-[12.5px] leading-relaxed text-ink-2">{finding.detail}</div>

        <div
          className={cx(
            'mt-1.5 text-[12px]',
            finding.fix ? 'text-ink-3' : 'text-ink-3 italic',
          )}
        >
          {finding.fix ? `Fixing this will: ${finding.fix}.` : 'Nothing here can fix this for you.'}
        </div>
      </div>
    </div>
  )
}
