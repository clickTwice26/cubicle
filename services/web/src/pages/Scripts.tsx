import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { CodeEditor } from '../components/CodeEditor'
import { Play, Plus, Shield } from '../components/Icons'
import {
  Badge,
  Button,
  Card,
  CardHeader,
  Checkbox,
  CodeBlock,
  ConfirmButton,
  CopyButton,
  EmptyState,
  Field,
  MethodBadge,
  Modal,
  PAGE,
  PageHeader,
  Select,
  Skeleton,
  StatusDot,
  Tabs,
  cx,
  useToast,
} from '../components/ui'
import { useMe, useNodes } from '../lib/hooks'
import { relativeTime } from '../lib/format'
import {
  useCreateScript,
  useDeleteScript,
  useRunScript,
  useScript,
  useScriptRuns,
  useScripts,
  useScriptsStatus,
  useSetScriptsEnabled,
  useUpdateScript,
  type RunResult,
  type ScriptDetail,
  type ScriptInput,
  type ScriptSummary,
} from '../lib/scripts'

/** What a new script starts as — the contract, written out, rather than a
 *  blank page and a trip to the docs. */
const STARTERS: Record<string, string> = {
  python3: `import json
import os
import sys

# The request body arrives on stdin, exactly as it would if you piped it in.
payload = sys.stdin.read()

# Anything printed to stdout is the response. Print JSON and the caller gets
# JSON; print anything else and they get exactly those bytes.
print(json.dumps({
    "ok": True,
    "method": os.environ["CUBICLE_METHOD"],
    "hostname": os.uname().nodename,
    "received_bytes": len(payload),
}))
`,
  bash: `set -euo pipefail

# This is the machine itself — the same shell, the same paths, the same root.
echo "host:   $(hostname)"
echo "user:   $(whoami)"
echo "uptime: $(uptime -p 2>/dev/null || uptime)"
`,
  node: `let body = ''
process.stdin.on('data', (chunk) => (body += chunk))
process.stdin.on('end', () => {
  console.log(JSON.stringify({ ok: true, received: body.length }))
})
`,
}

const starterFor = (interpreter: string) => STARTERS[interpreter] ?? STARTERS.bash

/**
 * Programs that run on the machine, not in a container.
 *
 * The console's other half of a feature whose point is the URL — so the page
 * is arranged around the two things somebody actually does with one: write it
 * and watch it run. Everything that makes a script a script rather than a
 * function (which host, which interpreter, how long it may take) is one tab
 * away, because it is set once and then forgotten.
 */
export default function ScriptsPage() {
  const { data: me, isLoading: meLoading } = useMe()
  const owner = me?.role === 'owner'
  const { data: status, isLoading: statusLoading } = useScriptsStatus({ enabled: owner })

  if (meLoading)
    return (
      <PageShell>
        <Skeleton className="h-40 w-full" />
      </PageShell>
    )

  if (!owner)
    return (
      <PageShell>
        <EmptyState
          title="Owner access required"
          body="A script runs as root on the machine, so writing one asks for the owner role specifically rather than admin — the same as the terminal, for the same reason."
        />
      </PageShell>
    )

  if (statusLoading)
    return (
      <PageShell>
        <Skeleton className="h-40 w-full" />
      </PageShell>
    )

  if (!status?.enabled)
    return (
      <PageShell>
        <EnableCard />
      </PageShell>
    )

  return (
    <PageShell>
      <Workspace maxTimeout={status.max_timeout_s} interpreters={status.interpreters} />
    </PageShell>
  )
}

function PageShell({ children }: { children: ReactNode }) {
  return (
    <div className={PAGE}>
      <PageHeader
        title="Scripts"
        subtitle="Programs that run on the machine itself — no image, no container — behind a URL"
      />
      {children}
    </div>
  )
}

function EnableCard() {
  const toast = useToast()
  const setEnabled = useSetScriptsEnabled()

  return (
    <Card className="p-6">
      <div className="flex items-start gap-3.5">
        <span className="mt-0.5 grid h-9 w-9 flex-none place-items-center rounded-full border border-line bg-panel-2 text-ink-2">
          <Shield size={16} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[15px] font-semibold">Scripts are off</div>
          <p className="mt-1.5 max-w-[66ch] text-[13.5px] leading-relaxed text-ink-2">
            A script is a program that runs on the node&apos;s host as root — the host&apos;s
            own Python, its packages, its disk — started because an HTTP request arrived. That
            is a URL with the authority of a root shell behind it, which is a separate decision
            from turning on the terminal, and it is off until you make it.
          </p>
          <p className="mt-2.5 max-w-[66ch] text-[13.5px] leading-relaxed text-ink-2">
            Every script requires an API key by default. Turning that off for one is how you
            wire up a webhook, and it means exactly what it says.
          </p>
          <div className="mt-4">
            <Button
              variant="primary"
              loading={setEnabled.isPending}
              onClick={() =>
                setEnabled.mutate(true, {
                  onSuccess: () => toast.push('Scripts are on', 'ok'),
                  onError: (error) => toast.push(error.message, 'err'),
                })
              }
            >
              Turn on scripts
            </Button>
          </div>
        </div>
      </div>
    </Card>
  )
}

function Workspace({
  maxTimeout,
  interpreters,
}: {
  maxTimeout: number
  interpreters: { value: string; label: string }[]
}) {
  const { data, isLoading } = useScripts()
  const [selected, setSelected] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)

  const scripts = data?.scripts ?? []

  // Keep a selection that still exists, and select the first one on arrival so
  // the page is never a list next to an empty panel.
  useEffect(() => {
    if (scripts.length === 0) {
      setSelected(null)
      return
    }
    setSelected((current) =>
      current && scripts.some((s) => s.id === current) ? current : scripts[0].id,
    )
  }, [scripts])

  if (isLoading) return <Skeleton className="h-64 w-full" />

  if (scripts.length === 0)
    return (
      <>
        <EmptyState
          title="No scripts yet"
          body="A script is the thing you would otherwise have SSH'd in to run — a backup, a cache purge, a health check — given a URL that runs it."
          action={
            <Button
              variant="primary"
              icon={<Plus size={14} />}
              onClick={() => setCreating(true)}
            >
              New script
            </Button>
          }
        />
        <NewScriptModal
          open={creating}
          interpreters={interpreters}
          onClose={() => setCreating(false)}
          onCreated={setSelected}
        />
      </>
    )

  return (
    <div className="grid gap-5 lg:grid-cols-[300px_minmax(0,1fr)]">
      <div>
        <Card className="overflow-hidden">
          <CardHeader
            title="Scripts"
            action={
              <Button size="sm" icon={<Plus size={13} />} onClick={() => setCreating(true)}>
                New
              </Button>
            }
          />
          <div className="max-h-[70vh] overflow-y-auto">
            {scripts.map((script) => (
              <ScriptRow
                key={script.id}
                script={script}
                active={script.id === selected}
                onSelect={() => setSelected(script.id)}
              />
            ))}
          </div>
        </Card>
      </div>

      {selected ? (
        <ScriptEditor
          key={selected}
          scriptId={selected}
          maxTimeout={maxTimeout}
          interpreters={interpreters}
          onDeleted={() => setSelected(null)}
        />
      ) : null}

      <NewScriptModal
        open={creating}
        interpreters={interpreters}
        onClose={() => setCreating(false)}
        onCreated={setSelected}
      />
    </div>
  )
}

function ScriptRow({
  script,
  active,
  onSelect,
}: {
  script: ScriptSummary
  active: boolean
  onSelect: () => void
}) {
  const tone =
    script.status === 'paused'
      ? 'idle'
      : script.last_exit_code === null
        ? 'info'
        : script.last_exit_code === 0
          ? 'ok'
          : 'err'

  return (
    <button
      type="button"
      onClick={onSelect}
      className={cx(
        'flex w-full items-center gap-2.5 border-b border-line px-4 py-3 text-left transition last:border-b-0',
        active ? 'bg-accent-soft' : 'bg-transparent hover:bg-panel-2',
      )}
    >
      <StatusDot tone={tone} />
      <span className="min-w-0 flex-1">
        <span className="block truncate font-mono text-[13px] font-semibold">
          {script.name}
        </span>
        <span className="block truncate text-[12px] text-ink-3">
          {script.description || script.interpreter_label}
        </span>
      </span>
      {!script.auth_required ? <Badge tone="warn">public</Badge> : null}
    </button>
  )
}

type Tab = 'code' | 'settings' | 'env' | 'runs'

function ScriptEditor({
  scriptId,
  maxTimeout,
  interpreters,
  onDeleted,
}: {
  scriptId: string
  maxTimeout: number
  interpreters: { value: string; label: string }[]
  onDeleted: () => void
}) {
  const toast = useToast()
  const { data: script, isLoading } = useScript(scriptId)
  const update = useUpdateScript()
  const remove = useDeleteScript()
  const run = useRunScript()

  const [tab, setTab] = useState<Tab>('code')
  const [draft, setDraft] = useState<ScriptDetail | null>(null)
  const [envText, setEnvText] = useState('')
  const [requestBody, setRequestBody] = useState('')
  const [result, setResult] = useState<RunResult | null>(null)

  useEffect(() => {
    if (!script) return
    setDraft(script)
    setEnvText(
      Object.entries(script.env)
        .map(([key, value]) => `${key}=${value}`)
        .join('\n'),
    )
  }, [script])

  const dirty = useMemo(() => {
    if (!script || !draft) return false
    const envNow = Object.entries(script.env)
      .map(([k, v]) => `${k}=${v}`)
      .join('\n')
    return (
      draft.source !== script.source ||
      draft.interpreter !== script.interpreter ||
      draft.description !== script.description ||
      draft.working_dir !== script.working_dir ||
      draft.timeout_s !== script.timeout_s ||
      draft.method !== script.method ||
      draft.output_mode !== script.output_mode ||
      draft.auth_required !== script.auth_required ||
      draft.status !== script.status ||
      draft.node_id !== script.node_id ||
      envText.trim() !== envNow.trim()
    )
  }, [script, draft, envText])

  if (isLoading || !draft) return <Skeleton className="h-96 w-full" />

  const edit = (patch: Partial<ScriptDetail>) => setDraft({ ...draft, ...patch })

  const save = () => {
    let env: Record<string, string>
    try {
      env = parseEnv(envText)
    } catch (error) {
      toast.push((error as Error).message, 'err')
      return
    }
    const body: ScriptInput & { id: string } = {
      id: scriptId,
      description: draft.description,
      interpreter: draft.interpreter,
      source: draft.source,
      working_dir: draft.working_dir,
      timeout_s: draft.timeout_s,
      method: draft.method,
      output_mode: draft.output_mode,
      auth_required: draft.auth_required,
      status: draft.status,
      node_id: draft.node_id,
      env,
    }
    update.mutate(body, {
      onSuccess: () => toast.push('Saved'),
      onError: (error) => toast.push(error.message, 'err'),
    })
  }

  const execute = () => {
    setResult(null)
    run.mutate(
      { id: scriptId, body: requestBody },
      {
        onSuccess: (data) => {
          setResult(data)
          if (data.exit_code !== 0) toast.push(`Exited ${data.exit_code}`, 'err')
        },
        onError: (error) => toast.push(error.message, 'err'),
      },
    )
  }

  return (
    <div className="min-w-0">
      <Card className="mb-5 overflow-hidden">
        <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-4">
          <MethodBadge method={draft.method} />
          <span className="min-w-0 flex-1 basis-[240px]">
            <span className="block truncate font-mono text-[15px] font-semibold">
              {draft.name}
            </span>
            <span className="flex items-center gap-2 text-[12px] text-ink-3">
              <span className="truncate">{script?.url}</span>
              <CopyButton value={script?.url ?? ''} label="" className="flex-none" />
            </span>
          </span>
          {draft.status === 'paused' ? <Badge tone="warn">paused</Badge> : null}
          {!draft.auth_required ? <Badge tone="warn">no key required</Badge> : null}
          <Button
            variant="primary"
            icon={<Play size={13} />}
            loading={run.isPending}
            onClick={execute}
          >
            Run now
          </Button>
          <Button
            variant="secondary"
            disabled={!dirty}
            loading={update.isPending}
            onClick={save}
          >
            {dirty ? 'Save' : 'Saved'}
          </Button>
        </div>

        <Tabs
          className="px-5"
          value={tab}
          onChange={setTab}
          tabs={[
            { value: 'code', label: 'Code' },
            { value: 'settings', label: 'Settings' },
            { value: 'env', label: 'Environment' },
            { value: 'runs', label: 'Runs' },
          ]}
        />

        {tab === 'code' ? (
          <CodeTab
            draft={draft}
            onChange={(source) => edit({ source })}
            requestBody={requestBody}
            onRequestBody={setRequestBody}
          />
        ) : null}

        {tab === 'settings' ? (
          <SettingsTab
            draft={draft}
            maxTimeout={maxTimeout}
            interpreters={interpreters}
            onChange={edit}
            onDelete={() =>
              remove.mutate(scriptId, {
                onSuccess: () => {
                  toast.push('Script deleted')
                  onDeleted()
                },
                onError: (error) => toast.push(error.message, 'err'),
              })
            }
          />
        ) : null}

        {tab === 'env' ? <EnvTab value={envText} onChange={setEnvText} /> : null}

        {tab === 'runs' ? <RunsTab scriptId={scriptId} /> : null}
      </Card>

      {result ? <Result result={result} onDismiss={() => setResult(null)} /> : null}
    </div>
  )
}

function CodeTab({
  draft,
  onChange,
  requestBody,
  onRequestBody,
}: {
  draft: ScriptDetail
  onChange: (source: string) => void
  requestBody: string
  onRequestBody: (next: string) => void
}) {
  return (
    <div>
      <div className="border-b border-line">
        <CodeEditor
          value={draft.source}
          onChange={onChange}
          language={draft.interpreter === 'python3' ? 'python' : 'text'}
          minHeight={380}
        />
      </div>
      <div className="px-5 py-4">
        <label className="mb-1.5 block text-[12.5px] text-ink-2">
          Request body for &ldquo;Run now&rdquo;
        </label>
        <textarea
          value={requestBody}
          onChange={(event) => onRequestBody(event.target.value)}
          rows={3}
          spellCheck={false}
          placeholder='{"example": true}'
          className="w-full resize-y rounded-[9px] border border-line-strong bg-bg px-3 py-2.5 font-mono text-[13px] text-ink outline-none transition placeholder:text-ink-3 focus:border-accent"
        />
        <p className="mt-1.5 text-[12.5px] text-ink-3">
          Arrives on the script&apos;s stdin, the same as a real request&apos;s body would.
        </p>
      </div>
    </div>
  )
}

function SettingsTab({
  draft,
  maxTimeout,
  interpreters,
  onChange,
  onDelete,
}: {
  draft: ScriptDetail
  maxTimeout: number
  interpreters: { value: string; label: string }[]
  onChange: (patch: Partial<ScriptDetail>) => void
  onDelete: () => void
}) {
  const { data: nodes } = useNodes()
  const known = interpreters.some((i) => i.value === draft.interpreter)

  return (
    <div className="px-5 py-5">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          label="Description"
          mono={false}
          value={draft.description}
          maxLength={200}
          onChange={(event) => onChange({ description: event.target.value })}
          placeholder="What it does"
        />
        <Select
          label="Interpreter"
          value={known ? draft.interpreter : 'custom'}
          onChange={(event) =>
            onChange({
              interpreter: event.target.value === 'custom' ? '/usr/bin/' : event.target.value,
            })
          }
        >
          {interpreters.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
          <option value="custom">Another path on the host…</option>
        </Select>

        {!known ? (
          <Field
            label="Interpreter path"
            value={draft.interpreter}
            onChange={(event) => onChange({ interpreter: event.target.value })}
            hint="An absolute path on the host, with no arguments"
            className="sm:col-span-2"
          />
        ) : null}

        <Field
          label="Working directory"
          value={draft.working_dir}
          onChange={(event) => onChange({ working_dir: event.target.value })}
          placeholder="/srv/app"
          hint="Blank means the run's own temporary directory"
        />
        <Field
          label="Timeout (seconds)"
          type="number"
          min={1}
          max={maxTimeout}
          value={draft.timeout_s}
          onChange={(event) => onChange({ timeout_s: Number(event.target.value) })}
          hint={`Up to ${maxTimeout}. The host enforces it.`}
        />

        <Select
          label="Method"
          value={draft.method}
          onChange={(event) => onChange({ method: event.target.value })}
        >
          {['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].map((method) => (
            <option key={method} value={method}>
              {method}
            </option>
          ))}
        </Select>
        <Select
          label="Response"
          value={draft.output_mode}
          onChange={(event) => onChange({ output_mode: event.target.value as 'auto' })}
        >
          <option value="auto">Auto — JSON if it printed JSON</option>
          <option value="json">JSON only</option>
          <option value="text">Text always</option>
        </Select>

        <Select
          label="Node"
          value={draft.node_id ?? ''}
          onChange={(event) => onChange({ node_id: event.target.value || null })}
          hint="Which machine this runs on"
        >
          <option value="">This control plane&apos;s own host</option>
          {(nodes ?? []).map((node) => (
            <option key={node.id} value={node.id}>
              {node.name}
            </option>
          ))}
        </Select>
        <Select
          label="Status"
          value={draft.status}
          onChange={(event) => onChange({ status: event.target.value as 'active' })}
        >
          <option value="active">Active</option>
          <option value="paused">Paused — the URL answers 503</option>
        </Select>
      </div>

      <div className="mt-5 rounded-xl border border-line bg-panel-2 px-4 py-3.5">
        <Checkbox
          checked={draft.auth_required}
          onChange={(next) => onChange({ auth_required: next })}
          label="Require an API key"
        />
        <p className="mt-1.5 text-[12.5px] leading-relaxed text-ink-2">
          Turning this off is how a webhook reaches a script, and it means anyone who learns the
          URL can run this program as root on the machine. A failing run answers with its exit
          code and the tail of stderr, so do not print anything on a public script that you
          would not publish.
        </p>
      </div>

      <div className="mt-5 flex justify-end border-t border-line pt-4">
        <ConfirmButton
          as="button"
          label="Delete script"
          confirmLabel="Click again to delete"
          hint="Deletes the script and its run history"
          onConfirm={onDelete}
        />
      </div>
    </div>
  )
}

function EnvTab({ value, onChange }: { value: string; onChange: (next: string) => void }) {
  return (
    <div className="px-5 py-5">
      <label className="mb-1.5 block text-[12.5px] text-ink-2">One NAME=value per line</label>
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        rows={8}
        spellCheck={false}
        placeholder={'BACKUP_TARGET=/srv/backups\nAPI_TOKEN=…'}
        className="w-full resize-y rounded-[9px] border border-line-strong bg-bg px-3 py-2.5 font-mono text-[13px] text-ink outline-none transition placeholder:text-ink-3 focus:border-accent"
      />
      <p className="mt-2 max-w-[70ch] text-[12.5px] leading-relaxed text-ink-2">
        Stored envelope-encrypted and set on the process when it runs. Cubicle sets the{' '}
        <code className="font-mono">CUBICLE_*</code> variables itself —{' '}
        <code className="font-mono">CUBICLE_METHOD</code>,{' '}
        <code className="font-mono">CUBICLE_QUERY</code>,{' '}
        <code className="font-mono">CUBICLE_HEADERS</code>,{' '}
        <code className="font-mono">CUBICLE_RUN_ID</code> — so those names are reserved.
      </p>
    </div>
  )
}

function RunsTab({ scriptId }: { scriptId: string }) {
  const { data: runs, isLoading } = useScriptRuns(scriptId)
  const [open, setOpen] = useState<string | null>(null)

  if (isLoading) return <Skeleton className="m-5 h-40" />
  if (!runs || runs.length === 0)
    return <div className="px-5 py-8 text-center text-[13.5px] text-ink-3">No runs yet.</div>

  return (
    <div>
      {runs.map((entry) => (
        <div key={entry.id} className="border-b border-line last:border-b-0">
          <button
            type="button"
            onClick={() => setOpen(open === entry.id ? null : entry.id)}
            className="flex w-full items-center gap-3 px-5 py-3 text-left transition hover:bg-panel-2"
          >
            <StatusDot tone={entry.exit_code === 0 ? 'ok' : 'err'} />
            <span className="w-16 flex-none font-mono text-[12.5px]">
              exit {entry.exit_code}
            </span>
            <span className="w-20 flex-none font-mono text-[12.5px] text-ink-2">
              {(entry.duration_ms / 1000).toFixed(2)}s
            </span>
            <Badge>{entry.trigger}</Badge>
            <span className="min-w-0 flex-1 truncate text-right text-[12.5px] text-ink-3">
              {relativeTime(entry.ts)}
            </span>
          </button>
          {open === entry.id ? (
            <div className="space-y-3 px-5 pb-4">
              <Stream label="stdout" body={entry.stdout} />
              <Stream label="stderr" body={entry.stderr} />
              {entry.truncated ? (
                <p className="text-[12px] text-ink-3">Output was longer than the kept limit.</p>
              ) : null}
            </div>
          ) : null}
        </div>
      ))}
    </div>
  )
}

function Stream({ label, body }: { label: string; body: string }) {
  if (!body) return null
  return (
    <CodeBlock filename={label} copyValue={body}>
      {body}
    </CodeBlock>
  )
}

function Result({ result, onDismiss }: { result: RunResult; onDismiss: () => void }) {
  const ok = result.exit_code === 0
  return (
    <Card className="overflow-hidden">
      <CardHeader
        title={ok ? 'Ran successfully' : `Exited ${result.exit_code}`}
        subtitle={`${(result.duration_ms / 1000).toFixed(2)}s on ${result.node_name} · ${result.run_id}`}
        action={
          <div className="flex items-center gap-3">
            {result.timed_out ? <Badge tone="err">timed out</Badge> : null}
            <Badge tone={ok ? 'ok' : 'err'}>exit {result.exit_code}</Badge>
            <button
              type="button"
              onClick={onDismiss}
              className="text-[12.5px] text-ink-3 transition hover:text-ink"
            >
              Dismiss
            </button>
          </div>
        }
      />
      <div className="space-y-3 px-5 py-4">
        {!result.stdout && !result.stderr ? (
          <p className="text-[13.5px] text-ink-3">It printed nothing.</p>
        ) : null}
        <Stream label="stdout" body={result.stdout} />
        <Stream label="stderr" body={result.stderr} />
      </div>
    </Card>
  )
}

function NewScriptModal({
  open,
  interpreters,
  onClose,
  onCreated,
}: {
  open: boolean
  interpreters: { value: string; label: string }[]
  onClose: () => void
  onCreated: (id: string) => void
}) {
  const toast = useToast()
  const create = useCreateScript()
  const [name, setName] = useState('')
  const [interpreter, setInterpreter] = useState('python3')

  useEffect(() => {
    if (open) {
      setName('')
      setInterpreter('python3')
    }
  }, [open])

  const submit = () => {
    create.mutate(
      { name: name.trim().toLowerCase(), interpreter, source: starterFor(interpreter) },
      {
        onSuccess: (script) => {
          toast.push(`Created ${script.name}`, 'ok')
          onCreated(script.id)
          onClose()
        },
        onError: (error) => toast.push(error.message, 'err'),
      },
    )
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="New script"
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            loading={create.isPending}
            disabled={!name.trim()}
            onClick={submit}
          >
            Create
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field
          label="Name"
          value={name}
          autoFocus
          onChange={(event) => setName(event.target.value)}
          placeholder="nightly-backup"
          hint={
            name.trim() ? `Answers at /run/${name.trim().toLowerCase()}` : 'Becomes the URL'
          }
        />
        <Select
          label="Interpreter"
          value={interpreter}
          onChange={(event) => setInterpreter(event.target.value)}
          hint="Whatever is already installed on the host"
        >
          {interpreters.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </Select>
      </div>
    </Modal>
  )
}

/** `NAME=value` lines into an object, refusing what the API would refuse
 *  anyway — locally, so a typo is a message under the box and not a round
 *  trip. */
function parseEnv(text: string): Record<string, string> {
  const env: Record<string, string> = {}
  for (const raw of text.split('\n')) {
    const line = raw.trim()
    if (!line || line.startsWith('#')) continue
    const at = line.indexOf('=')
    if (at < 1) throw new Error(`"${line}" is not NAME=value.`)
    const key = line.slice(0, at).trim()
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(key))
      throw new Error(`"${key}" is not a variable name.`)
    if (key.startsWith('CUBICLE_')) throw new Error(`"${key}" is reserved by Cubicle.`)
    env[key] = line.slice(at + 1)
  }
  return env
}
