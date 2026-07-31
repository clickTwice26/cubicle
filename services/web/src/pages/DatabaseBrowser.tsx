import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { CodeEditor } from '../components/CodeEditor'
import {
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Database,
  Play,
  Plus,
  Search,
  Trash,
} from '../components/Icons'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Field,
  Modal,
  PageHeader,
  Skeleton,
  Tabs,
  cx,
  useToast,
} from '../components/ui'
import { formatBytes } from '../lib/format'
import {
  useDbOverview,
  useDbPage,
  useDbStructure,
  useDbTables,
  useDeleteRow,
  useInsertRow,
  useRunQuery,
  useUpdateRow,
  type Cell,
  type ColumnRef,
  type Row,
  type TableRef,
} from '../lib/database'

const DEFAULT_PAGE_SIZE = 50

type Tab = 'rows' | 'structure' | 'query'

const TABS: Tab[] = ['rows', 'structure', 'query']

export default function DatabaseBrowser() {
  const { data: tables, isLoading, error } = useDbTables()
  const { data: overview } = useDbOverview()
  const [params, setParams] = useSearchParams()

  // The whole view is addressable: which tab, which table, which page, the
  // search and the sort. Refreshing, linking and the back button all work.
  const tab = (TABS.find((value) => value === params.get('tab')) ?? 'rows') as Tab
  const tableParam = params.get('table')
  const selected =
    (tables ?? []).find((entry) => `${entry.schema}.${entry.name}` === tableParam) ??
    tables?.[0] ??
    null

  const setTab = (next: Tab) => {
    const updated = new URLSearchParams(params)
    if (next === 'rows') updated.delete('tab')
    else updated.set('tab', next)
    setParams(updated)
  }

  const setTable = (next: TableRef) => {
    const updated = new URLSearchParams(params)
    updated.set('table', `${next.schema}.${next.name}`)
    // A different table invalidates where you were in the old one.
    for (const key of ['page', 'q', 'sort', 'dir']) updated.delete(key)
    setParams(updated)
  }

  if (error) {
    return (
      <div className="px-5 py-7 sm:px-8">
        <PageHeader title="Database" />
        <EmptyState
          title="The database is not reachable"
          body={(error as Error).message}
          action={
            <Link to="/console/services/postgres">
              <Button>Back to PostgreSQL</Button>
            </Link>
          }
        />
      </div>
    )
  }

  return (
    // No max width: this page is a data grid, and every pixel it does not use
    // is a column the operator has to scroll for.
    <div className="px-5 py-7 sm:px-8">
      <Link
        to="/console/services/postgres"
        className="mb-3.5 inline-flex items-center gap-1.5 text-[13px] text-ink-2 transition hover:text-ink"
      >
        <ChevronLeft size={14} />
        PostgreSQL
      </Link>

      <PageHeader
        title="Database"
        subtitle={
          overview
            ? `${overview.database} · ${overview.server} · ${overview.tables} table${
                overview.tables === 1 ? '' : 's'
              } · ${formatBytes(overview.size_bytes)} · ${overview.connections} connection${
                overview.connections === 1 ? '' : 's'
              }`
            : ' '
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-4 border-b border-line">
        {tab === 'query' ? null : (
          <TablePicker
            tables={tables ?? []}
            loading={isLoading}
            selected={selected}
            onSelect={setTable}
          />
        )}
        <Tabs
          value={tab}
          onChange={setTab}
          className="ml-auto border-b-0"
          tabs={[
            { value: 'rows', label: 'Rows' },
            { value: 'structure', label: 'Structure' },
            { value: 'query', label: 'Query' },
          ]}
        />
      </div>

      {isLoading ? <Skeleton className="h-64 w-full" /> : null}
      {!isLoading && tab === 'rows' && selected ? <RowsTab table={selected} /> : null}
      {!isLoading && tab === 'structure' && selected ? <StructureTab table={selected} /> : null}
      {tab === 'query' ? <QueryTab /> : null}
      {!isLoading && !selected && tab !== 'query' ? (
        <EmptyState
          title="No tables yet"
          body="Create one from the query console, then it appears here."
          action={
            <Button variant="primary" onClick={() => setTab('query')}>
              Open the query console
            </Button>
          }
        />
      ) : null}
    </div>
  )
}

/** Table selection, as a dropdown rather than a column that eats the grid. */
function TablePicker({
  tables,
  loading,
  selected,
  onSelect,
}: {
  tables: TableRef[]
  loading: boolean
  selected: TableRef | null
  onSelect: (table: TableRef) => void
}) {
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState('')
  const container = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const close = (event: MouseEvent) => {
      if (!container.current?.contains(event.target as Node)) setOpen(false)
    }
    const escape = (event: KeyboardEvent) => event.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', escape)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', escape)
    }
  }, [open])

  const shown = useMemo(() => {
    const needle = filter.trim().toLowerCase()
    if (!needle) return tables
    return tables.filter((t) => `${t.schema}.${t.name}`.toLowerCase().includes(needle))
  }, [tables, filter])

  return (
    <div className="relative pb-2.5" ref={container}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={loading || tables.length === 0}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="flex h-10 min-w-[260px] items-center gap-2.5 rounded-[9px] border border-line-strong bg-panel px-3 text-left transition hover:bg-panel-2 disabled:opacity-55"
      >
        <Database size={15} className="flex-none text-ink-3" />
        <span className="min-w-0 flex-1">
          <span className="block truncate font-mono text-[13px] font-semibold">
            {selected ? `${selected.schema}.${selected.name}` : 'No table'}
          </span>
          {selected ? (
            <span className="block truncate text-[11px] text-ink-3">
              {selected.estimated_rows > 0
                ? `~${selected.estimated_rows.toLocaleString()} rows · `
                : ''}
              {formatBytes(selected.size_bytes)}
              {selected.kind === 'view' ? ' · view' : ''}
              {!selected.editable && selected.kind !== 'view' ? ' · no primary key' : ''}
            </span>
          ) : null}
        </span>
        <Badge>{tables.length}</Badge>
        <ChevronDown
          size={14}
          className={cx('flex-none text-ink-3 transition', open && 'rotate-180')}
        />
      </button>

      {open ? (
        <div
          role="listbox"
          className="animate-rise absolute top-full left-0 z-30 mt-1 w-[340px] overflow-hidden rounded-xl border border-line-strong bg-panel shadow-2xl"
        >
          {tables.length > 8 ? (
            <div className="border-b border-line p-2">
              <input
                autoFocus
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
                placeholder="Filter tables…"
                className="h-8 w-full rounded-lg border border-line bg-bg px-2.5 text-[12.5px] text-ink outline-none placeholder:text-ink-3 focus:border-accent"
              />
            </div>
          ) : null}
          <div className="max-h-[60vh] overflow-auto">
            {shown.map((t) => {
              const active = selected?.schema === t.schema && selected?.name === t.name
              return (
                <button
                  key={`${t.schema}.${t.name}`}
                  type="button"
                  role="option"
                  aria-selected={active}
                  onClick={() => {
                    onSelect(t)
                    setOpen(false)
                    setFilter('')
                  }}
                  className={cx(
                    'flex w-full items-center gap-2.5 px-3 py-2 text-left transition',
                    active ? 'bg-accent-soft' : 'hover:bg-panel-2',
                  )}
                >
                  <span className="w-3.5 flex-none text-ink">
                    {active ? <Check size={13} /> : null}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-mono text-[12.5px] font-semibold">
                      {t.name}
                    </span>
                    <span className="block truncate text-[11px] text-ink-3">
                      {t.schema} · {formatBytes(t.size_bytes)}
                      {t.kind === 'view' ? ' · view' : ''}
                    </span>
                  </span>
                </button>
              )
            })}
            {shown.length === 0 ? (
              <div className="px-3 py-6 text-center text-[12.5px] text-ink-3">
                Nothing matches that.
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  )
}

// ── rows ─────────────────────────────────────────────────────────────────────

const PAGE_SIZES = [25, 50, 100, 200]

function RowsTab({ table }: { table: TableRef }) {
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const [editing, setEditing] = useState<Row | null>(null)
  const [creating, setCreating] = useState(false)

  const page = Math.max(1, Number(params.get('page') ?? 1) || 1)
  const size = PAGE_SIZES.includes(Number(params.get('size')))
    ? Number(params.get('size'))
    : DEFAULT_PAGE_SIZE
  const search = params.get('q') ?? ''
  const orderBy = params.get('sort') ?? undefined
  const descending = params.get('dir') === 'desc'
  const [term, setTerm] = useState(search)

  useEffect(() => setTerm(search), [search])

  const patch = (changes: Record<string, string | null>) => {
    const updated = new URLSearchParams(params)
    for (const [key, value] of Object.entries(changes)) {
      if (value === null) updated.delete(key)
      else updated.set(key, value)
    }
    // Paging and sorting replace rather than stack — the back button should
    // leave the page, not walk back through every sort you tried.
    setParams(updated, { replace: true })
  }

  const { data, isFetching } = useDbPage({
    schema: table.schema,
    table: table.name,
    limit: size,
    offset: (page - 1) * size,
    orderBy,
    descending,
    search: search || undefined,
  })

  const remove = useDeleteRow(table.schema, table.name)
  const columns = data?.columns ?? []
  const pk = data?.primary_key ?? []
  const editable = Boolean(data?.editable)
  const pages = data ? Math.max(1, Math.ceil(data.total / size)) : 1

  const keyOf = (row: Row): Row => Object.fromEntries(pk.map((k) => [k, row[k]]))

  return (
    <>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <form
          className="flex items-center gap-2"
          onSubmit={(event) => {
            event.preventDefault()
            patch({ q: term.trim() || null, page: null })
          }}
        >
          <div className="flex h-8 items-center gap-2 rounded-lg border border-line bg-panel px-2.5">
            <Search size={14} className="text-ink-3" />
            <input
              value={term}
              onChange={(event) => setTerm(event.target.value)}
              placeholder="Search every column…"
              className="w-48 bg-transparent text-[12.5px] text-ink outline-none placeholder:text-ink-3"
            />
          </div>
          <Button size="sm" type="submit">
            Search
          </Button>
          {search ? (
            <Button size="sm" variant="ghost" onClick={() => patch({ q: null, page: null })}>
              Clear
            </Button>
          ) : null}
        </form>

        <div className="ml-auto flex items-center gap-2">
          <span className="font-mono text-[12px] text-ink-3">
            {data ? `${data.total.toLocaleString()} rows` : '…'}
            {isFetching ? ' · loading' : ''}
          </span>
          {editable ? (
            <Button
              size="sm"
              variant="primary"
              icon={<Plus size={13} />}
              onClick={() => setCreating(true)}
            >
              Add row
            </Button>
          ) : null}
        </div>
      </div>

      {!editable && data ? (
        <div className="mb-3 rounded-[10px] border border-line bg-panel-2 px-3.5 py-2.5 text-[12.5px] text-ink-2">
          {table.kind === 'view'
            ? 'This is a view — rows are read-only here.'
            : 'This table has no primary key, so a single row cannot be identified. Use the query console to change it.'}
        </div>
      ) : null}

      <Card className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-[12.5px]">
            <thead>
              <tr className="border-b border-line">
                {columns.map((c) => (
                  <th
                    key={c.name}
                    className="px-3.5 py-2.5 text-left font-semibold whitespace-nowrap text-ink-3"
                  >
                    <button
                      type="button"
                      onClick={() =>
                        patch({
                          sort: c.name,
                          dir: orderBy === c.name && !descending ? 'desc' : 'asc',
                          page: null,
                        })
                      }
                      className="inline-flex items-center gap-1.5 uppercase transition hover:text-ink"
                    >
                      {c.name}
                      {c.is_primary_key ? (
                        <span className="text-accent" title="primary key">
                          ●
                        </span>
                      ) : null}
                      {data?.order_by === c.name ? (
                        <span className="text-ink">{data.descending ? '↓' : '↑'}</span>
                      ) : null}
                    </button>
                  </th>
                ))}
                {editable ? <th className="w-20" /> : null}
              </tr>
            </thead>
            <tbody>
              {(data?.rows ?? []).map((row, index) => (
                <tr
                  key={index}
                  className={cx(
                    'border-b border-line last:border-b-0',
                    editable && 'cursor-pointer transition hover:bg-panel-2',
                  )}
                  onClick={editable ? () => setEditing(row) : undefined}
                >
                  {columns.map((c) => (
                    <td key={c.name} className="max-w-[280px] px-3.5 py-2.5 align-top">
                      <CellValue value={row[c.name]} />
                    </td>
                  ))}
                  {editable ? (
                    <td className="px-3.5 py-2.5 text-right">
                      <button
                        type="button"
                        title="Delete this row"
                        onClick={(event) => {
                          event.stopPropagation()
                          remove.mutate(
                            { key: keyOf(row) },
                            {
                              onSuccess: () => toast.push('Row deleted'),
                              onError: (error) => toast.push(error.message, 'err'),
                            },
                          )
                        }}
                        className="text-ink-3 transition hover:text-err"
                      >
                        <Trash size={14} />
                      </button>
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {data && data.rows.length === 0 ? (
          <div className="px-5 py-10 text-center text-[13px] text-ink-3">
            {search ? `Nothing matches “${search}”.` : 'This table is empty.'}
          </div>
        ) : null}

        {data ? (
          <Pagination
            page={page}
            pages={pages}
            size={size}
            total={data.total}
            from={data.total === 0 ? 0 : data.offset + 1}
            to={Math.min(data.offset + data.limit, data.total)}
            onPage={(next) => patch({ page: next === 1 ? null : String(next) })}
            onSize={(next) =>
              patch({ size: next === DEFAULT_PAGE_SIZE ? null : String(next), page: null })
            }
          />
        ) : null}
      </Card>

      <RowEditor
        table={table}
        columns={columns}
        primaryKey={pk}
        row={editing}
        open={Boolean(editing)}
        onClose={() => setEditing(null)}
      />
      <RowEditor
        table={table}
        columns={columns}
        primaryKey={pk}
        row={null}
        open={creating}
        onClose={() => setCreating(false)}
      />
    </>
  )
}

/** Always present, even on a single page — the page-size control lives here. */
function Pagination({
  page,
  pages,
  size,
  total,
  from,
  to,
  onPage,
  onSize,
}: {
  page: number
  pages: number
  size: number
  total: number
  from: number
  to: number
  onPage: (page: number) => void
  onSize: (size: number) => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 border-t border-line px-4 py-2.5 text-[12.5px] text-ink-2">
      <span className="flex items-center gap-1.5">
        <span className="text-ink-3">Rows per page</span>
        {PAGE_SIZES.map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => onSize(option)}
            className={cx(
              'rounded-md border px-2 py-0.5 font-mono text-[11.5px] transition',
              option === size
                ? 'border-accent bg-accent-soft text-ink'
                : 'border-line text-ink-3 hover:text-ink',
            )}
          >
            {option}
          </button>
        ))}
      </span>

      <span className="font-mono">
        {from.toLocaleString()}–{to.toLocaleString()} of {total.toLocaleString()}
      </span>

      <span className="ml-auto flex items-center gap-1.5">
        <Button
          size="sm"
          variant="ghost"
          disabled={page <= 1}
          onClick={() => onPage(1)}
          title="First page"
        >
          «
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={page <= 1}
          onClick={() => onPage(page - 1)}
          icon={<ChevronLeft size={13} />}
        >
          Previous
        </Button>
        <span className="px-2 font-mono whitespace-nowrap">
          Page {page.toLocaleString()} of {pages.toLocaleString()}
        </span>
        <Button
          size="sm"
          variant="ghost"
          disabled={page >= pages}
          onClick={() => onPage(page + 1)}
        >
          Next <ChevronRight size={13} />
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={page >= pages}
          onClick={() => onPage(pages)}
          title="Last page"
        >
          »
        </Button>
      </span>
    </div>
  )
}

function CellValue({ value }: { value: Cell }) {
  if (value === null)
    return <span className="font-mono text-[11.5px] tracking-wide text-ink-3">NULL</span>
  if (typeof value === 'boolean')
    return <span className="font-mono text-info">{String(value)}</span>
  const text = String(value)
  return (
    <span className="block truncate font-mono" title={text.length > 40 ? text : undefined}>
      {text}
    </span>
  )
}

// ── row editor ───────────────────────────────────────────────────────────────

function RowEditor({
  table,
  columns,
  primaryKey,
  row,
  open,
  onClose,
}: {
  table: TableRef
  columns: ColumnRef[]
  primaryKey: string[]
  row: Row | null
  open: boolean
  onClose: () => void
}) {
  const toast = useToast()
  const insert = useInsertRow(table.schema, table.name)
  const update = useUpdateRow(table.schema, table.name)
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [nulls, setNulls] = useState<Record<string, boolean>>({})

  const editingExisting = row !== null

  useEffect(() => {
    if (!open) return
    const next: Record<string, string> = {}
    const nullish: Record<string, boolean> = {}
    for (const c of columns) {
      const value = row?.[c.name]
      next[c.name] = value === null || value === undefined ? '' : String(value)
      nullish[c.name] = editingExisting ? value === null : false
    }
    setDraft(next)
    setNulls(nullish)
  }, [open, row, columns, editingExisting])

  // Only send what actually changed, so untouched defaults stay untouched.
  const payload = useMemo(() => {
    const values: Row = {}
    for (const c of columns) {
      if (editingExisting && primaryKey.includes(c.name)) continue
      const original = row?.[c.name]
      const wasNull = original === null || original === undefined
      if (nulls[c.name]) {
        if (!wasNull) values[c.name] = null
        continue
      }
      const text = draft[c.name] ?? ''
      if (editingExisting) {
        if (!wasNull && String(original) === text) continue
        if (wasNull && text === '') continue
      } else if (text === '') {
        continue
      }
      values[c.name] = coerce(text, c.data_type)
    }
    return values
  }, [columns, draft, nulls, row, editingExisting, primaryKey])

  const submit = () => {
    const done = {
      onSuccess: () => {
        toast.push(editingExisting ? 'Row updated' : 'Row inserted')
        onClose()
      },
      onError: (error: Error) => toast.push(error.message, 'err'),
    }
    if (editingExisting) {
      update.mutate(
        { key: Object.fromEntries(primaryKey.map((k) => [k, row![k]])), values: payload },
        done,
      )
    } else {
      insert.mutate({ values: payload }, done)
    }
  }

  const changed = Object.keys(payload).length

  return (
    <Modal
      open={open}
      onClose={onClose}
      width={620}
      title={editingExisting ? `Edit row in ${table.name}` : `New row in ${table.name}`}
      footer={
        <>
          <span className="mr-auto text-[12.5px] text-ink-3">
            {editingExisting
              ? changed
                ? `${changed} column${changed === 1 ? '' : 's'} changed`
                : 'nothing changed'
              : 'blank fields use the column default'}
          </span>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={insert.isPending || update.isPending}
            disabled={editingExisting && changed === 0}
            onClick={submit}
          >
            {editingExisting ? 'Save changes' : 'Insert row'}
          </Button>
        </>
      }
    >
      <div className="grid max-h-[55vh] gap-3.5 overflow-auto pr-1">
        {columns.map((c) => {
          const locked = editingExisting && primaryKey.includes(c.name)
          return (
            <div key={c.name}>
              <div className="mb-1.5 flex items-center gap-2">
                <span className="font-mono text-[12.5px] font-semibold">{c.name}</span>
                <span className="font-mono text-[11px] text-ink-3">{c.data_type}</span>
                {c.is_primary_key ? <Badge tone="accent">pk</Badge> : null}
                {!c.nullable ? <Badge tone="warn">required</Badge> : null}
                {c.nullable && !locked ? (
                  <button
                    type="button"
                    onClick={() => setNulls((n) => ({ ...n, [c.name]: !n[c.name] }))}
                    className={cx(
                      'ml-auto rounded-md border px-2 py-0.5 font-mono text-[10.5px] transition',
                      nulls[c.name]
                        ? 'border-accent bg-accent-soft text-ink'
                        : 'border-line text-ink-3 hover:text-ink',
                    )}
                  >
                    NULL
                  </button>
                ) : null}
              </div>
              <Field
                value={nulls[c.name] ? '' : (draft[c.name] ?? '')}
                disabled={locked || nulls[c.name]}
                placeholder={
                  locked
                    ? 'primary key — not editable'
                    : nulls[c.name]
                      ? 'NULL'
                      : (c.default ?? '')
                }
                onChange={(event) => setDraft((d) => ({ ...d, [c.name]: event.target.value }))}
              />
            </div>
          )
        })}
      </div>
    </Modal>
  )
}

/** Text from a form field into something Postgres will accept for this type. */
function coerce(text: string, dataType: string): Cell {
  const t = dataType.toLowerCase()
  if (t === 'boolean') return ['true', 't', '1', 'yes'].includes(text.trim().toLowerCase())
  if (/^(smallint|integer|bigint)$/.test(t)) {
    const n = Number(text)
    return Number.isFinite(n) ? Math.trunc(n) : text
  }
  if (/^(real|double precision)$/.test(t)) {
    const n = Number(text)
    return Number.isFinite(n) ? n : text
  }
  // numeric, json, dates, arrays and everything else go as text — Postgres
  // casts them, and its error message is better than anything guessed here.
  return text
}

// ── structure ────────────────────────────────────────────────────────────────

function StructureTab({ table }: { table: TableRef }) {
  const { data } = useDbStructure(table.schema, table.name)
  if (!data) return <Skeleton className="h-48 w-full" />

  return (
    <div className="grid gap-5">
      <Card className="overflow-hidden">
        <div className="grid grid-cols-[1.4fr_1.6fr_0.7fr_1.4fr] gap-3 border-b border-line px-5 py-3 text-[11.5px] font-semibold tracking-[0.04em] text-ink-3 uppercase">
          <span>Column</span>
          <span>Type</span>
          <span>Null</span>
          <span>Default</span>
        </div>
        {data.columns.map((c) => (
          <div
            key={c.name}
            className="grid grid-cols-[1.4fr_1.6fr_0.7fr_1.4fr] items-center gap-3 border-b border-line px-5 py-3 text-[13px] last:border-b-0"
          >
            <span className="flex items-center gap-2 font-mono font-semibold">
              {c.name}
              {c.is_primary_key ? <Badge tone="accent">pk</Badge> : null}
            </span>
            <span className="font-mono text-ink-2">{c.data_type}</span>
            <span className="text-ink-2">{c.nullable ? 'yes' : 'no'}</span>
            <span className="truncate font-mono text-[12px] text-ink-3">
              {c.default ?? '—'}
            </span>
          </div>
        ))}
      </Card>

      <Card className="overflow-hidden">
        <div className="border-b border-line px-5 py-3.5 text-sm font-semibold">Indexes</div>
        {data.indexes.length ? (
          data.indexes.map((i) => (
            <div key={i.name} className="border-b border-line px-5 py-3 last:border-b-0">
              <div className="flex items-center gap-2 text-[13px] font-semibold">
                <span className="font-mono">{i.name}</span>
                {i.primary ? <Badge tone="accent">primary</Badge> : null}
                {i.unique && !i.primary ? <Badge>unique</Badge> : null}
              </div>
              <div className="mt-1 font-mono text-[11.5px] break-all text-ink-3">
                {i.definition}
              </div>
            </div>
          ))
        ) : (
          <div className="px-5 py-6 text-center text-[13px] text-ink-3">No indexes.</div>
        )}
      </Card>
    </div>
  )
}

// ── query console ────────────────────────────────────────────────────────────

const SAMPLE = "select * from information_schema.tables\nwhere table_schema = 'public';"

function QueryTab() {
  const toast = useToast()
  const run = useRunQuery()
  const [sql, setSql] = useState(SAMPLE)
  const result = run.data

  const execute = () =>
    run.mutate(sql, { onError: (error) => toast.push(error.message, 'err') })

  return (
    <div className="grid gap-4">
      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 border-b border-line bg-panel-2 px-4 py-2.5">
          <span className="text-[11.5px] font-bold tracking-[0.05em] text-ink-3 uppercase">
            SQL
          </span>
          <span className="text-[12px] text-ink-3">
            runs against this cluster's managed database · 15s statement timeout
          </span>
          <Button
            size="sm"
            variant="primary"
            className="ml-auto"
            icon={<Play size={12} />}
            loading={run.isPending}
            onClick={execute}
          >
            Run
          </Button>
        </div>
        <CodeEditor value={sql} onChange={setSql} language="sql" minHeight={180} />
      </Card>

      {run.error ? (
        <Card className="border-err bg-err-bg px-4 py-3.5 font-mono text-[12.5px] leading-relaxed whitespace-pre-wrap">
          {(run.error as Error).message}
        </Card>
      ) : null}

      {result ? (
        <Card className="overflow-hidden">
          <div className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-2.5 text-[12.5px]">
            <span className="font-mono text-ok">
              {result.kind === 'command'
                ? (result.command ?? 'ok')
                : `${result.row_count.toLocaleString()} row${result.row_count === 1 ? '' : 's'}`}
            </span>
            <span className="font-mono text-ink-3">{result.duration_ms}ms</span>
            {result.truncated ? <Badge tone="warn">showing the first 500</Badge> : null}
          </div>
          {result.rows.length ? (
            <div className="max-h-[50vh] overflow-auto">
              <table className="w-full border-collapse text-[12.5px]">
                <thead className="sticky top-0 bg-panel">
                  <tr className="border-b border-line">
                    {result.columns.map((c) => (
                      <th
                        key={c}
                        className="px-3.5 py-2.5 text-left font-semibold whitespace-nowrap text-ink-3 uppercase"
                      >
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.rows.map((row, index) => (
                    <tr key={index} className="border-b border-line last:border-b-0">
                      {result.columns.map((c) => (
                        <td key={c} className="max-w-[320px] px-3.5 py-2 align-top">
                          <CellValue value={row[c]} />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : result.kind === 'rows' ? (
            <div className="px-5 py-8 text-center text-[13px] text-ink-3">
              No rows returned.
            </div>
          ) : null}
        </Card>
      ) : null}
    </div>
  )
}
