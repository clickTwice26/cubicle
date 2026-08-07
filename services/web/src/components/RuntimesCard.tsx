import { Badge, Button, Card, CardHeader, ConfirmButton, Spinner, useToast } from './ui'
import { useInstallRuntime,
  useRebuildRuntime, useMe, useRuntimes, useUninstallRuntime } from '../lib/hooks'
import type { RuntimeInfo } from '../lib/types'

/**
 * The languages this instance can run.
 *
 * Python and JavaScript ship with it. The rest are listed but not installed:
 * their image is built here on demand, because each one has to carry the
 * Cubicle agent and there is no registry to pull a finished one from. Mostly
 * that build is the base image downloading.
 */
export function RuntimesCard() {
  const toast = useToast()
  const { data: me } = useMe()
  const { data: runtimes, isLoading } = useRuntimes()
  const install = useInstallRuntime()
  const rebuild = useRebuildRuntime()
  const uninstall = useUninstallRuntime()

  const owner = me?.role === 'owner'

  // Grouped by language, installed first — the question is usually "can I write
  // this in JavaScript", not "is node20 here".
  const groups = new Map<string, RuntimeInfo[]>()
  for (const entry of runtimes ?? []) {
    groups.set(entry.language, [...(groups.get(entry.language) ?? []), entry])
  }
  for (const list of groups.values()) {
    list.sort((a, b) => Number(b.installed) - Number(a.installed) || a.label.localeCompare(b.label))
  }

  const ready = (runtimes ?? []).filter((entry) => entry.installed).length

  return (
    <Card className="mb-5 overflow-hidden">
      <CardHeader
        title="Runtimes"
        subtitle={
          owner
            ? 'Python and JavaScript ship with Cubicle. The rest download and build on this node when you install them.'
            : 'The languages functions on this instance can be written in.'
        }
        action={
          <span className="text-[12.5px] text-ink-3">
            {isLoading ? '' : `${ready} of ${(runtimes ?? []).length} installed`}
          </span>
        }
      />

      {[...groups.entries()].map(([language, list]) => (
        <div key={language}>
          <div className="border-b border-line bg-panel-2 px-5 py-2 text-[11px] font-bold tracking-[0.06em] text-ink-3 uppercase">
            {language}
          </div>
          {list.map((entry) => (
            <Row
              key={entry.key}
              entry={entry}
              owner={owner}
              busy={
                (install.isPending && install.variables === entry.key) ||
                (rebuild.isPending && rebuild.variables === entry.key)
              }
              onInstall={() =>
                install.mutate(entry.key, {
                  onSuccess: () => toast.push(`${entry.label} installed`),
                  onError: (error) => toast.push(error.message, 'err'),
                })
              }
              onRebuild={() =>
                rebuild.mutate(entry.key, {
                  onSuccess: () => toast.push(`${entry.label} rebuilt`),
                  onError: (error) => toast.push(error.message, 'err'),
                })
              }
              onRemove={() =>
                uninstall.mutate(entry.key, {
                  onSuccess: () => toast.push(`${entry.label} removed`),
                  onError: (error) => toast.push(error.message, 'err'),
                })
              }
            />
          ))}
        </div>
      ))}

      <div className="border-t border-line bg-panel-2 px-5 py-3 text-[12.5px] leading-relaxed text-ink-2">
        Installing builds the runtime's image on this node — mostly the time it takes to pull the
        base image. A runtime cannot be removed while a function is still written in it.
      </div>
    </Card>
  )
}

function Row({
  entry,
  owner,
  busy,
  onInstall,
  onRebuild,
  onRemove,
}: {
  entry: RuntimeInfo
  owner: boolean
  busy: boolean
  onInstall: () => void
  onRebuild: () => void
  onRemove: () => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-3.5 last:border-b-0">
      <div className="min-w-0 flex-1 basis-[220px]">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[13.5px] font-semibold">{entry.label}</span>
          {entry.builtin ? <Badge>built in</Badge> : null}
          {entry.installed ? (
            <Badge tone="accent">installed</Badge>
          ) : (
            <Badge tone="warn">not installed</Badge>
          )}
          {entry.functions > 0 ? (
            <span className="text-[12px] text-ink-3">
              {entry.functions} function{entry.functions === 1 ? '' : 's'}
            </span>
          ) : null}
        </div>
        <div className="mt-1 text-[12.5px] text-ink-2">{entry.summary}</div>
        <div className="mt-1 truncate font-mono text-[11px] text-ink-3">
          {entry.entry_file} · {entry.deps_file} · {entry.installed ? entry.image : entry.base_image}
        </div>
      </div>

      {owner ? (
        <div className="flex flex-none items-center gap-2">
          {busy ? (
            <span className="flex items-center gap-2 text-[12.5px] text-ink-2">
              <Spinner size={13} />
              building…
            </span>
          ) : entry.installed ? (
            <span className="flex flex-wrap items-center gap-2">
              {/* The agent lives in the image, so an update that changes it
                  leaves every isolate on the old one until this runs. A
                  built-in could not be rebuilt at all before: Remove refuses
                  one that ships with Cubicle, and Install saw it was there. */}
              <ConfirmButton
                as="button"
                label="Rebuild"
                confirmLabel="Rebuild now"
                hint="Builds the image again from the current agent. Running instances keep serving until they are next replaced."
                onConfirm={onRebuild}
              />
              {entry.builtin ? (
                <span className="text-[12.5px] text-ink-3">ships with Cubicle</span>
              ) : (
                <ConfirmButton
                  as="button"
                  label="Remove"
                  confirmLabel="Confirm"
                  hint="Frees the disk the image uses. Install it again at any time."
                  onConfirm={onRemove}
                />
              )}
            </span>
          ) : (
            <Button size="sm" variant="primary" onClick={onInstall}>
              Install
            </Button>
          )}
        </div>
      ) : null}
    </div>
  )
}
