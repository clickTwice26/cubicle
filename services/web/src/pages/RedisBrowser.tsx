import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ChevronLeft, Play, Plus, Search, Trash } from '../components/Icons'
import {
  Badge,
  Button,
  Card,
  Chip,
  ConfirmButton,
  EmptyState,
  Field,
  Modal,
  PAGE,
  PageHeader,
  Skeleton,
  Tabs,
  cx,
  useToast,
} from '../components/ui'
import { formatBytes } from '../lib/format'
import {
  formatTtl,
  useDeleteRedisEntry,
  useDeleteRedisKey,
  useRedisKeys,
  useRedisOverview,
  useRedisValue,
  useRunRedisCommand,
  useSetRedisTtl,
  useWriteRedisKey,
  type Entry,
  type KeyRef,
  type RedisType,
} from '../lib/redis'

const PAGE_SIZE = 50
const TYPES: RedisType[] = ['string', 'hash', 'list', 'set', 'zset', 'stream']
const CREATABLE: RedisType[] = ['string', 'hash', 'list', 'set', 'zset']

type Tab = 'keys' | 'command'

/**
 * The Redis half of the data browser.
 *
 * Deliberately the same shape as the PostgreSQL one — a browse tab and a
 * console tab over the cluster's own managed instance — but it pages the way
 * Redis does. SCAN has no page numbers, so the cursors visited are kept in a
 * stack: forward pushes the cursor Redis handed back, back pops it.
 */
export default function RedisBrowser() {
  const [params, setParams] = useSearchParams()
  const { data: overview, error } = useRedisOverview()

  const tab: Tab = params.get('tab') === 'command' ? 'command' : 'keys'
  const setTab = (next: Tab) => {
    const updated = new URLSearchParams(params)
    if (next === 'keys') updated.delete('tab')
    else updated.set('tab', next)
    setParams(updated)
  }

  if (error) {
    return (
      <div className={PAGE}>
        <PageHeader title="Keys" />
        <EmptyState
          title="Redis is not reachable"
          body={(error as Error).message}
          action={
            <Link to="/console/services/redis">
              <Button>Back to Redis</Button>
            </Link>
          }
        />
      </div>
    )
  }

  return (
    <div className={PAGE}>
      <Link
        to="/console/services/redis"
        className="mb-3.5 inline-flex items-center gap-1.5 text-[13px] text-ink-2 transition hover:text-ink"
      >
        <ChevronLeft size={14} />
        Redis
      </Link>

      <PageHeader
        title="Keys"
        subtitle={
          overview
            ? `${overview.server} · ${overview.keys.toLocaleString()} key${
                overview.keys === 1 ? '' : 's'
              } · ${formatBytes(overview.used_memory)}${
                overview.max_memory ? ` / ${formatBytes(overview.max_memory)}` : ''
              } · ${overview.eviction}${
                overview.hit_rate === null
                  ? ''
                  : ` · ${Math.round(overview.hit_rate * 100)}% hit rate`
              }`
            : ' '
        }
      />

      <Tabs
        value={tab}
        onChange={setTab}
        className="mb-4"
        tabs={[
          { value: 'keys', label: 'Keys' },
          { value: 'command', label: 'Command' },
        ]}
      />

      {tab === 'keys' ? <KeysTab /> : <CommandTab />}
    </div>
  )
}

// ── keys ─────────────────────────────────────────────────────────────────────

function KeysTab() {
  const [params, setParams] = useSearchParams()
  const match = params.get('q') ?? ''
  const type = (TYPES.find((value) => value === params.get('type')) ?? null) as RedisType | null
  const selected = params.get('key')

  const [term, setTerm] = useState(match)
  const [cursors, setCursors] = useState<number[]>([0])
  const [creating, setCreating] = useState(false)

  useEffect(() => setTerm(match), [match])
  // A different filter starts the scan over — an old cursor means nothing
  // against a new MATCH.
  useEffect(() => setCursors([0]), [match, type])

  const cursor = cursors[cursors.length - 1]
  const { data, isFetching } = useRedisKeys({ cursor, match, type, limit: PAGE_SIZE })

  const patch = (changes: Record<string, string | null>) => {
    const updated = new URLSearchParams(params)
    for (const [key, value] of Object.entries(changes)) {
      if (value === null) updated.delete(key)
      else updated.set(key, value)
    }
    setParams(updated, { replace: true })
  }

  return (
    <>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <form
          className="flex items-center gap-2"
          onSubmit={(event) => {
            event.preventDefault()
            patch({ q: term.trim() || null })
          }}
        >
          <div className="flex h-8 items-center gap-2 rounded-lg border border-line bg-panel px-2.5">
            <Search size={14} className="text-ink-3" />
            <input
              value={term}
              onChange={(event) => setTerm(event.target.value)}
              placeholder="session:* or a word…"
              className="w-52 bg-transparent font-mono text-[12.5px] text-ink outline-none placeholder:text-ink-3"
            />
          </div>
          <Button size="sm" type="submit">
            Scan
          </Button>
          {match ? (
            <Button size="sm" variant="ghost" onClick={() => patch({ q: null })}>
              Clear
            </Button>
          ) : null}
        </form>

        <div className="flex flex-wrap items-center gap-1.5">
          <Chip active={type === null} onClick={() => patch({ type: null })}>
            all
          </Chip>
          {TYPES.map((value) => (
            <Chip key={value} active={type === value} onClick={() => patch({ type: value })}>
              {value}
            </Chip>
          ))}
        </div>

        <div className="ml-auto flex items-center gap-2">
          <span className="font-mono text-[12px] text-ink-3">
            {data ? `${data.total.toLocaleString()} keys in db0` : '…'}
            {isFetching ? ' · scanning' : ''}
          </span>
          <Button
            size="sm"
            variant="primary"
            icon={<Plus size={13} />}
            onClick={() => setCreating(true)}
          >
            New key
          </Button>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)] lg:items-start">
        <Card className="overflow-hidden">
          <div className="grid grid-cols-[minmax(0,1fr)_64px_84px] gap-3 border-b border-line px-4 py-2.5 text-[11.5px] font-semibold tracking-[0.04em] text-ink-3 uppercase">
            <span>Key</span>
            <span>Type</span>
            <span className="text-right">TTL</span>
          </div>
          <div className="max-h-[58vh] overflow-y-auto">
            {(data?.keys ?? []).map((entry) => (
              <KeyRow
                key={entry.key}
                entry={entry}
                active={entry.key === selected}
                onSelect={() => patch({ key: entry.key })}
              />
            ))}
            {data && data.keys.length === 0 ? (
              <div className="px-4 py-10 text-center text-[13px] text-ink-3">
                {match || type
                  ? 'No keys on this page match. SCAN walks the keyspace in slices — try the next page.'
                  : 'This database is empty.'}
              </div>
            ) : null}
            {!data ? <Skeleton className="m-4 h-40" /> : null}
          </div>

          <div className="flex items-center gap-2 border-t border-line px-4 py-2.5">
            <span className="font-mono text-[11.5px] text-ink-3">
              {data?.keys.length ?? 0} on this page
            </span>
            <div className="ml-auto flex items-center gap-2">
              <Button
                size="sm"
                variant="ghost"
                disabled={cursors.length === 1}
                onClick={() => setCursors((stack) => stack.slice(0, -1))}
              >
                Back
              </Button>
              <Button
                size="sm"
                disabled={!data?.next_cursor}
                onClick={() =>
                  setCursors((stack) => (data?.next_cursor ? [...stack, data.next_cursor] : stack))
                }
              >
                Next
              </Button>
            </div>
          </div>
        </Card>

        {selected ? (
          <ValuePanel keyName={selected} onGone={() => patch({ key: null })} />
        ) : (
          <EmptyState
            title="No key selected"
            body="Pick one on the left to read or change what is in it."
          />
        )}
      </div>

      <KeyEditor
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={(key) => patch({ key })}
      />
    </>
  )
}

function KeyRow({
  entry,
  active,
  onSelect,
}: {
  entry: KeyRef
  active: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cx(
        'grid w-full grid-cols-[minmax(0,1fr)_64px_84px] items-center gap-3 border-b border-line px-4 py-2.5 text-left transition last:border-b-0',
        active ? 'bg-accent-soft' : 'hover:bg-panel-2',
      )}
    >
      <span className="min-w-0">
        <span className="block truncate font-mono text-[12.5px] font-semibold">{entry.key}</span>
        <span className="block truncate text-[11px] text-ink-3">
          {entry.length === null ? '' : `${entry.length.toLocaleString()} ${unit(entry)}`}
          {entry.size_bytes ? ` · ${formatBytes(entry.size_bytes)}` : ''}
        </span>
      </span>
      <span>
        <Badge>{entry.type}</Badge>
      </span>
      <span
        className={cx(
          'text-right font-mono text-[11.5px]',
          entry.ttl >= 0 ? 'text-warn' : 'text-ink-3',
        )}
      >
        {entry.ttl < 0 ? '—' : formatTtl(entry.ttl)}
      </span>
    </button>
  )
}

function unit(entry: KeyRef): string {
  if (entry.type === 'string') return entry.length === 1 ? 'char' : 'chars'
  if (entry.type === 'hash') return entry.length === 1 ? 'field' : 'fields'
  return entry.length === 1 ? 'item' : 'items'
}

// ── one key ──────────────────────────────────────────────────────────────────

function ValuePanel({ keyName, onGone }: { keyName: string; onGone: () => void }) {
  const toast = useToast()
  const [cursor, setCursor] = useState(0)
  const { data, isFetching } = useRedisValue(keyName, cursor, PAGE_SIZE)
  const write = useWriteRedisKey()
  const removeKey = useDeleteRedisKey()
  const removeEntry = useDeleteRedisEntry()
  const expire = useSetRedisTtl()

  const [draft, setDraft] = useState('')
  const [editing, setEditing] = useState<Entry | null>(null)
  const [adding, setAdding] = useState(false)

  useEffect(() => setCursor(0), [keyName])
  useEffect(() => {
    if (data?.type === 'string') setDraft(data.value ?? '')
  }, [data?.value, data?.type])

  if (!data) return <Skeleton className="h-64 w-full" />

  const isString = data.type === 'string'
  const dirty = isString && draft !== (data.value ?? '')

  const saveString = () =>
    write.mutate(
      { key: keyName, value: draft },
      {
        onSuccess: () => toast.push('Value saved'),
        onError: (error) => toast.push(error.message, 'err'),
      },
    )

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center gap-2.5 border-b border-line px-4 py-3">
        <Badge tone="accent">{data.type}</Badge>
        <span className="min-w-0 flex-1 truncate font-mono text-[13px] font-semibold">
          {keyName}
        </span>
        <span className="font-mono text-[11.5px] text-ink-3">
          {data.total.toLocaleString()} {isString ? 'chars' : 'entries'}
          {isFetching ? ' · loading' : ''}
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-2.5 border-b border-line bg-panel-2 px-4 py-2.5">
        <span className="text-[11.5px] font-bold tracking-[0.05em] text-ink-3 uppercase">
          TTL
        </span>
        <span className="font-mono text-[12.5px]">{formatTtl(data.ttl)}</span>
        <TtlControl
          pending={expire.isPending}
          onSet={(seconds) =>
            expire.mutate(
              { key: keyName, ttl: seconds },
              {
                onSuccess: () =>
                  toast.push(seconds < 0 ? 'Expiry removed' : `Expires in ${formatTtl(seconds)}`),
                onError: (error) => toast.push(error.message, 'err'),
              },
            )
          }
        />
        <div className="ml-auto flex items-center gap-2">
          {!isString && data.editable ? (
            <Button size="sm" icon={<Plus size={13} />} onClick={() => setAdding(true)}>
              Add entry
            </Button>
          ) : null}
          <ConfirmButton
            as="button"
            label="Delete key"
            confirmLabel="Click again to delete"
            onConfirm={() =>
              removeKey.mutate(
                { key: keyName },
                {
                  onSuccess: () => {
                    toast.push(`${keyName} deleted`)
                    onGone()
                  },
                  onError: (error) => toast.push(error.message, 'err'),
                },
              )
            }
          />
        </div>
      </div>

      {isString ? (
        <div className="p-4">
          <textarea
            value={draft}
            spellCheck={false}
            onChange={(event) => setDraft(event.target.value)}
            className="h-64 w-full resize-y rounded-[10px] border border-line-strong bg-bg p-3 font-mono text-[12.5px] leading-relaxed text-ink outline-none focus:border-accent"
          />
          {data.truncated ? (
            <div className="mt-2 text-[12px] text-warn">
              Showing the first 64 KB. Saving would replace the whole value, so this one is
              read-only — use the command console for the rest.
            </div>
          ) : null}
          <div className="mt-3 flex items-center gap-2">
            <Button
              variant="primary"
              size="sm"
              loading={write.isPending}
              disabled={!dirty || data.truncated}
              onClick={saveString}
            >
              Save
            </Button>
            {dirty && !data.truncated ? (
              <Button size="sm" variant="ghost" onClick={() => setDraft(data.value ?? '')}>
                Revert
              </Button>
            ) : null}
          </div>
        </div>
      ) : (
        <>
          <div className="max-h-[52vh] overflow-auto">
            <table className="w-full border-collapse text-[12.5px]">
              <thead className="sticky top-0 bg-panel">
                <tr className="border-b border-line">
                  <th className="w-[34%] px-4 py-2.5 text-left font-semibold text-ink-3 uppercase">
                    {label(data.type)}
                  </th>
                  <th className="px-4 py-2.5 text-left font-semibold text-ink-3 uppercase">
                    Value
                  </th>
                  <th className="w-16" />
                </tr>
              </thead>
              <tbody>
                {data.entries.map((entry, index) => (
                  <tr
                    key={`${entry.field ?? ''}:${index}`}
                    className={cx(
                      'border-b border-line last:border-b-0',
                      data.editable && 'cursor-pointer transition hover:bg-panel-2',
                    )}
                    onClick={data.editable ? () => setEditing(entry) : undefined}
                  >
                    <td className="max-w-[220px] px-4 py-2 align-top">
                      <span className="block truncate font-mono">
                        {entry.field ?? render(entry.value)}
                      </span>
                      {entry.score !== undefined ? (
                        <span className="font-mono text-[11px] text-ink-3">
                          score {entry.score}
                        </span>
                      ) : null}
                    </td>
                    <td className="max-w-[320px] px-4 py-2 align-top">
                      <span className="block truncate font-mono text-ink-2">
                        {render(entry.value)}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-right">
                      {data.editable ? (
                        <button
                          type="button"
                          title="Remove this entry"
                          onClick={(event) => {
                            event.stopPropagation()
                            removeEntry.mutate(
                              { key: keyName, field: entry.field ?? String(entry.value ?? '') },
                              {
                                onSuccess: () => toast.push('Entry removed'),
                                onError: (error) => toast.push(error.message, 'err'),
                              },
                            )
                          }}
                          className="text-ink-3 transition hover:text-err"
                        >
                          <Trash size={14} />
                        </button>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data.entries.length === 0 ? (
              <div className="px-4 py-10 text-center text-[13px] text-ink-3">
                Nothing on this page.
              </div>
            ) : null}
          </div>

          <div className="flex items-center gap-2 border-t border-line px-4 py-2.5">
            <span className="font-mono text-[11.5px] text-ink-3">
              {data.entries.length} shown of {data.total.toLocaleString()}
            </span>
            <div className="ml-auto flex items-center gap-2">
              <Button size="sm" variant="ghost" disabled={cursor === 0} onClick={() => setCursor(0)}>
                Start
              </Button>
              <Button
                size="sm"
                disabled={data.next_cursor === null}
                onClick={() => setCursor(data.next_cursor ?? cursor)}
              >
                Next
              </Button>
            </div>
          </div>
        </>
      )}

      <EntryEditor
        open={Boolean(editing) || adding}
        onClose={() => {
          setEditing(null)
          setAdding(false)
        }}
        keyName={keyName}
        type={data.type}
        entry={editing}
      />
    </Card>
  )
}

function label(type: RedisType): string {
  if (type === 'hash') return 'Field'
  if (type === 'list') return 'Index'
  if (type === 'zset') return 'Member'
  if (type === 'stream') return 'Id'
  return 'Member'
}

function render(value: Entry['value']): string {
  if (value === null) return ''
  if (typeof value === 'string') return value
  return JSON.stringify(value)
}

/** Expiry as a few plain choices, because nobody wants to type 86400. */
function TtlControl({ pending, onSet }: { pending: boolean; onSet: (seconds: number) => void }) {
  const CHOICES: { label: string; seconds: number }[] = [
    { label: '5m', seconds: 300 },
    { label: '1h', seconds: 3600 },
    { label: '1d', seconds: 86400 },
    { label: 'never', seconds: -1 },
  ]
  return (
    <span className="flex items-center gap-1.5">
      {CHOICES.map((choice) => (
        <button
          key={choice.label}
          type="button"
          disabled={pending}
          onClick={() => onSet(choice.seconds)}
          className="rounded-md border border-line px-2 py-0.5 font-mono text-[10.5px] text-ink-3 transition hover:border-line-strong hover:text-ink disabled:opacity-50"
        >
          {choice.label}
        </button>
      ))}
    </span>
  )
}

// ── editors ──────────────────────────────────────────────────────────────────

function EntryEditor({
  open,
  onClose,
  keyName,
  type,
  entry,
}: {
  open: boolean
  onClose: () => void
  keyName: string
  type: RedisType
  entry: Entry | null
}) {
  const toast = useToast()
  const write = useWriteRedisKey()
  const [field, setField] = useState('')
  const [value, setValue] = useState('')
  const [score, setScore] = useState('0')

  useEffect(() => {
    if (!open) return
    setField(entry?.field ?? '')
    setValue(render(entry?.value ?? null))
    setScore(entry?.score !== undefined ? String(entry.score) : '0')
  }, [open, entry, type])

  const needsField = type === 'hash'
  const editing = entry !== null

  const submit = () =>
    write.mutate(
      {
        key: keyName,
        value,
        // What identifies the entry being replaced: a hash field, a list index,
        // or — for a set, which has no slots — the old member itself. Adding
        // rather than editing identifies nothing.
        field: type === 'hash' ? field : editing ? (entry?.field ?? render(entry?.value)) : null,
        score: type === 'zset' ? Number(score) || 0 : null,
      },
      {
        onSuccess: () => {
          toast.push(editing ? 'Entry updated' : 'Entry added')
          onClose()
        },
        onError: (error) => toast.push(error.message, 'err'),
      },
    )

  return (
    <Modal
      open={open}
      onClose={onClose}
      width={560}
      title={editing ? `Edit ${label(type).toLowerCase()} in ${keyName}` : `Add to ${keyName}`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={write.isPending}
            disabled={(needsField && !field.trim()) || (!value.trim() && type !== 'hash')}
            onClick={submit}
          >
            {editing ? 'Save' : 'Add'}
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        {needsField ? (
          <Field
            label="Field"
            value={field}
            autoFocus
            disabled={editing}
            placeholder="user:name"
            onChange={(event) => setField(event.target.value)}
          />
        ) : null}
        {type === 'list' && editing ? (
          <Field label="Index" value={entry?.field ?? ''} disabled />
        ) : null}
        {type === 'zset' ? (
          <Field
            label="Score"
            value={score}
            placeholder="0"
            onChange={(event) => setScore(event.target.value)}
          />
        ) : null}
        <div>
          <span className="mb-1.5 block text-[12.5px] text-ink-2">Value</span>
          <textarea
            value={value}
            autoFocus={!needsField}
            spellCheck={false}
            onChange={(event) => setValue(event.target.value)}
            className="h-40 w-full resize-y rounded-[9px] border border-line-strong bg-bg p-3 font-mono text-[12.5px] text-ink outline-none focus:border-accent"
          />
        </div>
      </div>
    </Modal>
  )
}

function KeyEditor({
  open,
  onClose,
  onCreated,
}: {
  open: boolean
  onClose: () => void
  onCreated: (key: string) => void
}) {
  const toast = useToast()
  const write = useWriteRedisKey()
  const [name, setName] = useState('')
  const [type, setType] = useState<RedisType>('string')
  const [field, setField] = useState('')
  const [value, setValue] = useState('')
  const [ttl, setTtl] = useState('')

  useEffect(() => {
    if (!open) return
    setName('')
    setType('string')
    setField('')
    setValue('')
    setTtl('')
  }, [open])

  const submit = () =>
    write.mutate(
      {
        key: name.trim(),
        type,
        value,
        field: type === 'hash' ? field.trim() : null,
        score: type === 'zset' ? 0 : null,
        ttl: ttl.trim() ? Number(ttl) : undefined,
      },
      {
        onSuccess: () => {
          toast.push(`${name.trim()} created`)
          onCreated(name.trim())
          onClose()
        },
        onError: (error) => toast.push(error.message, 'err'),
      },
    )

  return (
    <Modal
      open={open}
      onClose={onClose}
      width={560}
      title="New key"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={write.isPending}
            disabled={!name.trim() || (type === 'hash' && !field.trim())}
            onClick={submit}
          >
            Create key
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        <Field
          label="Key"
          value={name}
          autoFocus
          placeholder="session:42"
          onChange={(event) => setName(event.target.value)}
        />
        <div>
          <span className="mb-2 block text-[12.5px] text-ink-2">Type</span>
          <div className="flex flex-wrap gap-2">
            {CREATABLE.map((option) => (
              <Chip key={option} active={type === option} onClick={() => setType(option)}>
                {option}
              </Chip>
            ))}
          </div>
        </div>
        {type === 'hash' ? (
          <Field
            label="First field"
            value={field}
            placeholder="name"
            onChange={(event) => setField(event.target.value)}
          />
        ) : null}
        <div>
          <span className="mb-1.5 block text-[12.5px] text-ink-2">
            {type === 'string' ? 'Value' : 'First value'}
          </span>
          <textarea
            value={value}
            spellCheck={false}
            onChange={(event) => setValue(event.target.value)}
            className="h-28 w-full resize-y rounded-[9px] border border-line-strong bg-bg p-3 font-mono text-[12.5px] text-ink outline-none focus:border-accent"
          />
        </div>
        <Field
          label="TTL in seconds (optional)"
          value={ttl}
          placeholder="3600"
          onChange={(event) => setTtl(event.target.value.replace(/[^\d]/g, ''))}
          hint="Left blank the key never expires."
        />
      </div>
    </Modal>
  )
}

// ── command console ──────────────────────────────────────────────────────────

const SUGGESTIONS = ['INFO keyspace', 'DBSIZE', 'CONFIG GET maxmemory-policy', 'SCAN 0 COUNT 20']

function CommandTab() {
  const toast = useToast()
  const run = useRunRedisCommand()
  const [command, setCommand] = useState('DBSIZE')
  const [history, setHistory] = useState<string[]>([])

  const execute = () => {
    const statement = command.trim()
    if (!statement) return
    run.mutate(statement, {
      onSuccess: () => setHistory((past) => [statement, ...past.filter((c) => c !== statement)].slice(0, 8)),
      onError: (error) => toast.push(error.message, 'err'),
    })
  }

  const result = run.data
  const lines = useMemo(() => {
    if (!result) return []
    const { value } = result
    if (Array.isArray(value)) return value.map((item) => stringify(item))
    if (value && typeof value === 'object') {
      return Object.entries(value as Record<string, unknown>).map(
        ([k, v]) => `${k}: ${stringify(v)}`,
      )
    }
    return [stringify(value)]
  }, [result])

  return (
    <div className="grid gap-4">
      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 border-b border-line bg-panel-2 px-4 py-2.5">
          <span className="text-[11.5px] font-bold tracking-[0.05em] text-ink-3 uppercase">
            Redis
          </span>
          <span className="text-[12px] text-ink-3">
            runs against this cluster's managed instance · blocking commands are refused
          </span>
        </div>
        <form
          className="flex items-center gap-2 px-4 py-3"
          onSubmit={(event) => {
            event.preventDefault()
            execute()
          }}
        >
          <span className="font-mono text-[13px] text-ink-3">&gt;</span>
          <input
            value={command}
            autoFocus
            spellCheck={false}
            onChange={(event) => setCommand(event.target.value)}
            placeholder="GET session:42"
            className="min-w-0 flex-1 bg-transparent font-mono text-[13px] text-ink outline-none placeholder:text-ink-3"
          />
          <Button
            size="sm"
            variant="primary"
            type="submit"
            icon={<Play size={12} />}
            loading={run.isPending}
          >
            Run
          </Button>
        </form>
        <div className="flex flex-wrap items-center gap-1.5 border-t border-line px-4 py-2.5">
          {(history.length ? history : SUGGESTIONS).map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => setCommand(item)}
              className="rounded-md border border-line px-2 py-0.5 font-mono text-[11px] text-ink-3 transition hover:border-line-strong hover:text-ink"
            >
              {item}
            </button>
          ))}
        </div>
      </Card>

      {run.error ? (
        <Card className="border-err bg-err-bg px-4 py-3.5 font-mono text-[12.5px] leading-relaxed whitespace-pre-wrap">
          {(run.error as Error).message}
        </Card>
      ) : null}

      {result ? (
        <Card className="overflow-hidden">
          <div className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-2.5 text-[12.5px]">
            <span className="font-mono text-ok">{result.command}</span>
            <span className="font-mono text-ink-3">{result.duration_ms}ms</span>
            {result.truncated ? <Badge tone="warn">showing the first 500</Badge> : null}
          </div>
          <pre className="m-0 max-h-[50vh] overflow-auto px-4 py-3.5 font-mono text-[12.5px] leading-[1.7] whitespace-pre-wrap">
            {lines.length ? lines.join('\n') : '(empty)'}
          </pre>
        </Card>
      ) : (
        <EmptyState
          title="Nothing run yet"
          body={
            <>
              Anything <span className="font-mono">redis-cli</span> takes works here, including
              writes.
            </>
          }
        />
      )}
    </div>
  )
}

function stringify(value: unknown): string {
  if (value === null || value === undefined) return '(nil)'
  if (typeof value === 'string') return value
  return JSON.stringify(value)
}
