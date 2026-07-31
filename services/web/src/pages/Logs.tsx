import { useEffect, useMemo, useRef, useState } from 'react'
import { Card, Chip, EmptyState, PageHeader, Skeleton, cx } from '../components/ui'
import { subscribe } from '../lib/api'
import { useLogs } from '../lib/hooks'
import { levelColour } from '../lib/format'
import type { LogLine } from '../lib/types'

const LEVELS = [
  { value: 'all', label: 'All' },
  { value: 'INFO', label: 'Info' },
  { value: 'WARN', label: 'Warn' },
  { value: 'ERROR', label: 'Error' },
]

export default function Logs() {
  const [level, setLevel] = useState('all')
  const [search, setSearch] = useState('')
  const [live, setLive] = useState<LogLine[]>([])
  const [connected, setConnected] = useState(false)
  const { data: history, isLoading } = useLogs(level)
  const seen = useRef(new Set<string>())

  useEffect(() => {
    setLive([])
    seen.current = new Set()
    const stop = subscribe<Omit<LogLine, 'id'>[]>(
      `/api/logs/stream?level=${level}`,
      (entries) => {
        setConnected(true)
        setLive((current) =>
          [
            ...entries.map((entry, index) => ({
              ...entry,
              id: `live-${entry.ts}-${index}-${Math.random().toString(16).slice(2, 8)}`,
            })),
            ...current,
          ].slice(0, 300),
        )
      },
      () => setConnected(false),
    )
    return stop
  }, [level])

  const lines = useMemo(() => {
    const combined = [...live, ...(history ?? [])].filter((line) => {
      if (!seen.current.has(line.id)) seen.current.add(line.id)
      if (!search) return true
      const needle = search.toLowerCase()
      return (
        line.message.toLowerCase().includes(needle) ||
        line.function_name.toLowerCase().includes(needle)
      )
    })
    return combined.slice(0, 300)
  }, [live, history, search])

  return (
    <div className="mx-auto max-w-[1240px] px-5 py-7 sm:px-8">
      <PageHeader
        title="Logs & monitoring"
        subtitle={
          <>
            Streaming across every function ·{' '}
            <span style={{ color: connected ? 'var(--ok)' : 'var(--text-3)' }}>
              {connected ? 'live' : 'connecting…'}
            </span>
          </>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        {LEVELS.map((option) => (
          <Chip
            key={option.value}
            active={level === option.value}
            onClick={() => setLevel(option.value)}
          >
            {option.label}
          </Chip>
        ))}
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Filter messages…"
          className="h-8 w-full max-w-[260px] rounded-lg border border-line bg-panel px-3 text-[12.5px] text-ink outline-none placeholder:text-ink-3 focus:border-accent sm:w-auto"
        />
        <div className="ml-auto flex items-center gap-2 text-[12.5px] text-ink-2">
          <span
            className={cx('h-[7px] w-[7px] rounded-full', connected && 'animate-pulse-dot')}
            style={{ background: connected ? 'var(--ok)' : 'var(--text-3)' }}
          />
          Tailing
        </div>
      </div>

      {isLoading ? (
        <Skeleton className="h-72 w-full" />
      ) : lines.length ? (
        <Card className="overflow-hidden font-mono text-[12.5px]">
          {lines.map((line) => (
            <div
              key={line.id}
              className="flex items-baseline gap-3.5 border-b border-line px-4.5 py-2.5 transition last:border-b-0 hover:bg-panel-2"
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
        </Card>
      ) : (
        <EmptyState
          title="Nothing logged yet"
          body="Invoke a function and its output shows up here as it happens."
        />
      )}
    </div>
  )
}
