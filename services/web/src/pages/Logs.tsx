import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Refresh } from '../components/Icons'
import {
  Badge,
  Button,
  Card,
  Chip,
  EmptyState,
  PAGE,
  PAGE_SIZES,
  PageHeader,
  Pagination,
  Select,
  Skeleton,
  cx,
} from '../components/ui'
import { api, subscribe } from '../lib/api'
import { useActiveCluster } from '../lib/cluster'
import { useQuery } from '@tanstack/react-query'
import { levelColour } from '../lib/format'
import type { LogLine } from '../lib/types'

const LEVELS = [
  { value: 'all', label: 'All' },
  { value: 'INFO', label: 'Info' },
  { value: 'WARN', label: 'Warn' },
  { value: 'ERROR', label: 'Error' },
]

const DEFAULT_SIZE = 100
/** How many live lines to hold before the oldest are dropped. */
const LIVE_BUFFER = 400

interface LogPage {
  items: LogLine[]
  total: number
  limit: number
  offset: number
}

export default function Logs() {
  const [params, setParams] = useSearchParams()
  const scope = useActiveCluster()

  const level = LEVELS.some((l) => l.value === params.get('level'))
    ? params.get('level')!
    : 'all'
  const fn = params.get('fn') ?? ''
  const search = params.get('q') ?? ''
  const page = Math.max(1, Number(params.get('page') ?? 1) || 1)
  const size = PAGE_SIZES.includes(Number(params.get('size')))
    ? Number(params.get('size'))
    : DEFAULT_SIZE

  const [term, setTerm] = useState(search)
  useEffect(() => setTerm(search), [search])

  const patch = useCallback(
    (changes: Record<string, string | null>, push = false) => {
      const updated = new URLSearchParams(params)
      for (const [key, value] of Object.entries(changes)) {
        if (value === null || value === '') updated.delete(key)
        else updated.set(key, value)
      }
      setParams(updated, { replace: !push })
    },
    [params, setParams],
  )

  // Live tail belongs to the newest page. Anywhere else it would be prepending
  // rows to a page whose position in the log has already moved on, so it is
  // paused and says so.
  const live = page === 1

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ['logs', level, fn, search, page, size, scope],
    queryFn: () => {
      const query = new URLSearchParams({
        level,
        limit: String(size),
        offset: String((page - 1) * size),
      })
      if (fn) query.set('function', fn)
      if (search) query.set('search', search)
      return api.get<LogPage>(`/api/logs?${query}`)
    },
    placeholderData: (previous) => previous,
  })

  const { data: functions } = useQuery({
    queryKey: ['log-functions', scope],
    queryFn: () => api.get<string[]>('/api/logs/functions'),
    staleTime: 60_000,
  })

  const [streamed, setStreamed] = useState<LogLine[]>([])
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    setStreamed([])
    if (!live) {
      setConnected(false)
      return
    }
    const stop = subscribe<Omit<LogLine, 'id'>[]>(
      `/api/logs/stream?level=${level}`,
      (entries) => {
        setConnected(true)
        const matching = entries.filter((entry) => {
          if (fn && entry.function_name !== fn) return false
          if (search && !entry.message.toLowerCase().includes(search.toLowerCase()))
            return false
          return true
        })
        if (matching.length === 0) return
        setStreamed((current) =>
          [
            ...matching.map((entry, index) => ({
              ...entry,
              id: `live-${entry.ts}-${index}-${Math.random().toString(16).slice(2, 8)}`,
            })),
            ...current,
          ].slice(0, LIVE_BUFFER),
        )
      },
      () => setConnected(false),
    )
    return stop
  }, [live, level, fn, search, scope])

  // Live lines sit above the fetched page; the page itself is never reordered.
  // Each carries a generated id, so no de-duplication against the page is
  // needed — a line that arrives on the stream is one the page predates.
  const lines = useMemo(
    () => (live ? [...streamed, ...(data?.items ?? [])] : (data?.items ?? [])),
    [live, streamed, data],
  )

  const total = (data?.total ?? 0) + (live ? streamed.length : 0)
  const pages = data ? Math.max(1, Math.ceil(data.total / size)) : 1

  return (
    <div className={PAGE}>
      <PageHeader
        title="Logs & monitoring"
        subtitle={
          <>
            Handler output and control-plane events ·{' '}
            {live ? (
              <span style={{ color: connected ? 'var(--ok)' : 'var(--text-3)' }}>
                {connected ? 'live' : 'connecting…'}
              </span>
            ) : (
              <span className="text-warn">paused — viewing older entries</span>
            )}
          </>
        }
        action={
          <Button
            size="sm"
            icon={<Refresh size={14} />}
            loading={isFetching}
            onClick={() => refetch()}
          >
            Refresh
          </Button>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        {LEVELS.map((option) => (
          <Chip
            key={option.value}
            active={level === option.value}
            onClick={() =>
              patch({ level: option.value === 'all' ? null : option.value, page: null })
            }
          >
            {option.label}
          </Chip>
        ))}

        {functions?.length ? (
          <Select
            size="sm"
            mono={false}
            selectClassName="border-line bg-panel text-ink-2"
            value={fn}
            onChange={(event) => patch({ fn: event.target.value || null, page: null })}
          >
            <option value="">All functions</option>
            {functions.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </Select>
        ) : null}

        <form
          onSubmit={(event) => {
            event.preventDefault()
            patch({ q: term.trim() || null, page: null })
          }}
          className="flex items-center gap-2"
        >
          <input
            value={term}
            onChange={(event) => setTerm(event.target.value)}
            placeholder="Filter messages…"
            className="h-8 w-full max-w-[240px] rounded-lg border border-line bg-panel px-3 text-[12.5px] text-ink outline-none placeholder:text-ink-3 focus:border-accent"
          />
          <Button size="sm" type="submit">
            Search
          </Button>
          {search || fn ? (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => patch({ q: null, fn: null, page: null })}
            >
              Clear
            </Button>
          ) : null}
        </form>

        <div className="ml-auto flex items-center gap-2 text-[12.5px] text-ink-2">
          <span
            className={cx(
              'h-[7px] w-[7px] rounded-full',
              live && connected && 'animate-pulse-dot',
            )}
            style={{ background: live && connected ? 'var(--ok)' : 'var(--text-3)' }}
          />
          {live ? 'Tailing' : 'Paused'}
        </div>
      </div>

      {isLoading ? (
        <Skeleton className="h-72 w-full" />
      ) : lines.length ? (
        <Card className="overflow-hidden font-mono text-[12.5px]">
          {lines.map((line, index) => (
            <div
              key={line.id}
              className={cx(
                'flex items-baseline gap-3.5 border-b border-line px-4.5 py-2.5 transition last:border-b-0 hover:bg-panel-2',
                live && index < streamed.length && 'bg-accent-soft/40',
              )}
            >
              <span className="flex-none text-ink-3">{line.time}</span>
              <span
                className="w-[46px] flex-none font-semibold"
                style={{ color: levelColour(line.level) }}
              >
                {line.level}
              </span>
              <span className="hidden w-[150px] flex-none truncate text-ink-2 sm:block">
                {line.function_name}
              </span>
              <span className="flex-1 break-words text-ink">{line.message}</span>
              <span className="flex-none text-ink-3">{line.duration ?? ''}</span>
            </div>
          ))}

          {data ? (
            <Pagination
              page={page}
              pages={pages}
              size={size}
              total={total}
              from={data.total === 0 ? 0 : data.offset + 1}
              to={Math.min(data.offset + data.limit, data.total)}
              onPage={(next) => patch({ page: next === 1 ? null : String(next) })}
              onSize={(next) =>
                patch({ size: next === DEFAULT_SIZE ? null : String(next), page: null })
              }
              note={
                live && streamed.length ? (
                  <Badge tone="accent">+{streamed.length} live</Badge>
                ) : !live ? (
                  <Button size="sm" variant="ghost" onClick={() => patch({ page: null })}>
                    Jump to live
                  </Button>
                ) : null
              }
            />
          ) : null}
        </Card>
      ) : (
        <EmptyState
          title={
            search || fn || level !== 'all'
              ? 'Nothing matches those filters'
              : 'Nothing logged yet'
          }
          body={
            search || fn || level !== 'all'
              ? 'Widen the filters, or clear them to see everything.'
              : 'Invoke a function and its output shows up here as it happens.'
          }
          action={
            search || fn || level !== 'all' ? (
              <Button onClick={() => patch({ q: null, fn: null, level: null, page: null })}>
                Clear filters
              </Button>
            ) : undefined
          }
        />
      )}
    </div>
  )
}
