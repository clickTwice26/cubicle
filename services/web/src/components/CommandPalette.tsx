import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Bars,
  Bolt,
  Book,
  Database,
  Globe,
  Grid,
  Layers,
  Lines,
  Search,
  Server,
  Sliders,
  Terminal,
} from './Icons'
import { cx } from './ui'
import { useClusters, useFunctions, useGroups, useServices } from '../lib/hooks'
import { useSwitchCluster } from '../lib/hooks'
import { activeCluster } from '../lib/cluster'
import { DOCS } from '../pages/docs/content'

/**
 * One search box for the whole console.
 *
 * Everything addressable is in here — functions, namespaces, every console
 * page, the data services, the docs, and the clusters you can switch to. It
 * is built from queries the console already holds, so opening it costs
 * nothing and typing filters cached data rather than hitting the API on every
 * keystroke.
 *
 * Free text that matches nothing is still useful: it falls through to a log
 * search, which is the thing people are usually looking for when they type
 * something the platform has never heard of.
 */

type Kind = 'Function' | 'Namespace' | 'Page' | 'Data service' | 'Cluster' | 'Docs' | 'Search'

interface Item {
  id: string
  kind: Kind
  label: string
  hint?: string
  icon: (props: { size?: number; className?: string }) => React.ReactElement
  run: () => void
  /** Ranked ahead of everything else when the query is empty. */
  weight?: number
}

const PAGES: { label: string; to: string; hint: string; icon: Item['icon'] }[] = [
  { label: 'Overview', to: '/console', hint: 'Dashboard', icon: Grid },
  {
    label: 'Live activity',
    to: '/console/live',
    hint: 'Streaming requests and isolates',
    icon: Bolt,
  },
  {
    label: 'Function playground',
    to: '/console/playground',
    hint: 'Namespaces and functions',
    icon: Terminal,
  },
  { label: 'Global env', to: '/console/env', hint: 'Cluster-wide configuration', icon: Globe },
  {
    label: 'Logs & monitoring',
    to: '/console/logs',
    hint: 'Filter and tail logs',
    icon: Lines,
  },
  {
    label: 'Cluster & metering',
    to: '/console/cluster',
    hint: 'Nodes, isolates, GB-seconds',
    icon: Bars,
  },
  {
    label: 'Settings',
    to: '/console/settings',
    hint: 'Users, API keys, clusters',
    icon: Sliders,
  },
  {
    label: 'Browse data',
    to: '/console/services/postgres/data',
    hint: 'Rows, structure and SQL',
    icon: Database,
  },
  {
    label: 'Browse keys',
    to: '/console/services/redis/data',
    hint: 'Redis keys, values and commands',
    icon: Layers,
  },
]

/** Subsequence match, so "crch" finds "create-charge". */
function score(query: string, text: string): number {
  const q = query.toLowerCase()
  const t = text.toLowerCase()
  if (!q) return 1
  const exact = t.indexOf(q)
  if (exact === 0) return 1000
  if (exact > 0) return 600 - exact
  let i = 0
  let hits = 0
  for (const character of t) {
    if (character === q[i]) {
      i += 1
      hits += 1
      if (i === q.length) break
    }
  }
  return i === q.length ? 100 + hits : 0
}

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate()
  const switchCluster = useSwitchCluster()
  const { data: functions } = useFunctions()
  const { data: groups } = useGroups()
  const { data: services } = useServices()
  const { data: clusters } = useClusters()

  const [query, setQuery] = useState('')
  const [cursor, setCursor] = useState(0)
  const input = useRef<HTMLInputElement>(null)
  const list = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    setQuery('')
    setCursor(0)
    // The frame delay lets the dialog paint before it steals focus, which
    // stops the page behind it jumping on open.
    const id = requestAnimationFrame(() => input.current?.focus())
    return () => cancelAnimationFrame(id)
  }, [open])

  const items = useMemo<Item[]>(() => {
    const go = (to: string) => () => {
      navigate(to)
      onClose()
    }
    const all: Item[] = []

    for (const fn of functions ?? []) {
      all.push({
        id: `fn:${fn.id}`,
        kind: 'Function',
        label: `${fn.namespace}/${fn.name}`,
        hint: `${fn.method} · ${fn.runtime_label}`,
        icon: Bolt,
        weight: 3,
        run: go(`/console/playground/${fn.group_id}/${fn.id}`),
      })
    }
    for (const group of groups ?? []) {
      all.push({
        id: `ns:${group.id}`,
        kind: 'Namespace',
        label: group.ns,
        hint: `${group.function_count} function${group.function_count === 1 ? '' : 's'}`,
        icon: Terminal,
        weight: 2,
        run: go(`/console/playground/${group.id}`),
      })
    }
    for (const page of PAGES) {
      all.push({
        id: `page:${page.to}`,
        kind: 'Page',
        label: page.label,
        hint: page.hint,
        icon: page.icon,
        weight: 4,
        run: go(page.to),
      })
    }
    for (const service of services ?? []) {
      all.push({
        id: `svc:${service.kind}`,
        kind: 'Data service',
        label: service.kind === 'postgres' ? 'PostgreSQL' : 'Redis',
        hint: service.created ? service.status : 'not created',
        icon: service.kind === 'postgres' ? Database : Layers,
        run: go(`/console/services/${service.kind}`),
      })
    }
    const current = activeCluster()
    for (const cluster of clusters ?? []) {
      const selected = current ? current === cluster.slug : cluster.is_default
      if (selected) continue
      all.push({
        id: `cl:${cluster.id}`,
        kind: 'Cluster',
        label: `Switch to ${cluster.name}`,
        hint: `${cluster.function_count} fn · ${cluster.node_count} node${cluster.node_count === 1 ? '' : 's'}`,
        icon: Server,
        run: () => {
          switchCluster(cluster.is_default ? null : cluster.slug)
          onClose()
        },
      })
    }
    for (const doc of DOCS) {
      all.push({
        id: `doc:${doc.id}`,
        kind: 'Docs',
        label: doc.title,
        hint: doc.lede.slice(0, 68),
        icon: Book,
        run: () => {
          window.location.href = `/docs/${doc.id}`
        },
      })
    }
    return all
  }, [functions, groups, services, clusters, navigate, onClose, switchCluster])

  const results = useMemo(() => {
    const q = query.trim()
    const ranked = items
      .map((item) => ({
        item,
        rank: Math.max(score(q, item.label), score(q, item.hint ?? '') * 0.5),
      }))
      .filter((row) => row.rank > 0)
      .sort((a, b) => b.rank - a.rank || (b.item.weight ?? 0) - (a.item.weight ?? 0))
      .slice(0, 40)
      .map((row) => row.item)

    // Anything typed is also a log query — usually what someone means when the
    // console has never heard of the string they pasted in.
    if (q) {
      ranked.push({
        id: 'search:logs',
        kind: 'Search',
        label: `Search logs for “${q}”`,
        icon: Search,
        run: () => {
          navigate(`/console/logs?q=${encodeURIComponent(q)}`)
          onClose()
        },
      })
    }
    return ranked
  }, [items, query, navigate, onClose])

  useEffect(() => setCursor(0), [query])

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose()
      } else if (event.key === 'ArrowDown') {
        event.preventDefault()
        setCursor((n) => Math.min(n + 1, results.length - 1))
      } else if (event.key === 'ArrowUp') {
        event.preventDefault()
        setCursor((n) => Math.max(n - 1, 0))
      } else if (event.key === 'Enter') {
        event.preventDefault()
        results[cursor]?.run()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, results, cursor, onClose])

  useEffect(() => {
    list.current?.querySelector('[data-active="true"]')?.scrollIntoView({ block: 'nearest' })
  }, [cursor])

  if (!open) return null

  let lastKind: Kind | null = null

  return (
    <div
      className="fixed inset-0 z-50 flex justify-center bg-black/45 px-4 pt-[12vh] backdrop-blur-[2px]"
      role="dialog"
      aria-modal="true"
      aria-label="Search"
      onMouseDown={(event) => event.target === event.currentTarget && onClose()}
    >
      <div className="animate-rise h-fit w-full max-w-[600px] overflow-hidden rounded-2xl border border-line-strong bg-panel shadow-2xl">
        <div className="flex items-center gap-3 border-b border-line px-4">
          <Search size={17} className="flex-none text-ink-3" />
          <input
            ref={input}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search functions, namespaces, pages, docs…"
            // The global :focus-visible ring is suppressed here: this input is
            // the whole point of the dialog and takes focus on open, so an
            // accent box around it marks nothing and only adds noise.
            className="h-[52px] w-full border-0 bg-transparent text-[15px] text-ink outline-none placeholder:text-ink-3 focus:outline-none focus-visible:outline-none"
          />
          <kbd className="flex-none rounded-[5px] border border-line px-1.5 py-px font-mono text-[11px] text-ink-3">
            esc
          </kbd>
        </div>

        <div ref={list} className="max-h-[52vh] overflow-y-auto py-1.5">
          {results.length === 0 ? (
            <div className="px-4 py-8 text-center text-[13px] text-ink-3">
              Nothing matches that.
            </div>
          ) : (
            results.map((item, index) => {
              const header = item.kind !== lastKind ? item.kind : null
              lastKind = item.kind
              const Icon = item.icon
              return (
                <div key={item.id}>
                  {header ? (
                    <div className="px-4 pt-2.5 pb-1 text-[11px] font-bold tracking-[0.05em] text-ink-3 uppercase">
                      {header}
                    </div>
                  ) : null}
                  <button
                    type="button"
                    data-active={index === cursor}
                    onMouseMove={() => setCursor(index)}
                    onClick={item.run}
                    className={cx(
                      'flex w-full items-center gap-3 px-4 py-2 text-left transition',
                      index === cursor ? 'bg-accent-soft' : 'hover:bg-panel-2',
                    )}
                  >
                    <Icon size={16} className="flex-none text-ink-2" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13.5px] font-semibold">
                        {item.label}
                      </span>
                      {item.hint ? (
                        <span className="block truncate text-[12px] text-ink-3">
                          {item.hint}
                        </span>
                      ) : null}
                    </span>
                    {index === cursor ? (
                      <kbd className="flex-none rounded-[5px] border border-line px-1.5 py-px font-mono text-[10.5px] text-ink-3">
                        ↵
                      </kbd>
                    ) : null}
                  </button>
                </div>
              )
            })
          )}
        </div>

        <div className="flex items-center gap-4 border-t border-line px-4 py-2 font-mono text-[11px] text-ink-3">
          <span>↑↓ move</span>
          <span>↵ open</span>
          <span className="ml-auto">
            {results.length} result{results.length === 1 ? '' : 's'}
          </span>
        </div>
      </div>
    </div>
  )
}
