import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search } from '../components/Icons'
import {
  Badge,
  Button,
  Card,
  CodeBlock,
  EmptyState,
  Field,
  Modal,
  PAGE,
  PageHeader,
  Skeleton,
  cx,
  useToast,
} from '../components/ui'
import {
  useGroups,
  useInstallFromMarketplace,
  useMarketplace,
  useMarketplacePackage,
} from '../lib/hooks'
import type { MarketplaceListing } from '../lib/types'

/**
 * Functions other people published, and installing one into a namespace.
 *
 * The whole source is fetched and shown before anything is created, because
 * installing runs a stranger's code on your cluster with whatever that
 * namespace can reach. A function is one readable file — a better position
 * than most package managers put you in — so the console makes reading it the
 * step before installing rather than an option afterwards.
 */
export default function Marketplace() {
  const [query, setQuery] = useState('')
  const [opened, setOpened] = useState<MarketplaceListing | null>(null)

  const { data, isLoading, error, refetch, isFetching } = useMarketplace('')

  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase()
    const all = data?.packages ?? []
    if (!needle) return all
    return all.filter((entry) =>
      [entry.name, entry.slug, entry.summary, entry.author, ...entry.tags]
        .join(' ')
        .toLowerCase()
        .includes(needle),
    )
  }, [data, query])

  return (
    <div className={PAGE}>
      <PageHeader
        title="Marketplace"
        subtitle="Functions published by the community. Read one, then install it into a namespace of yours."
      />

      <Card className="mb-5 flex flex-wrap items-center gap-3 px-4 py-3">
        <span className="relative min-w-[220px] flex-1">
          <span className="absolute top-1/2 left-3 -translate-y-1/2 text-ink-3">
            <Search size={15} />
          </span>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search by name, tag or author…"
            className="h-10 w-full rounded-[9px] border border-line bg-bg pr-3 pl-9 text-sm text-ink outline-none transition placeholder:text-ink-3 focus:border-accent"
          />
        </span>
        <Button size="sm" loading={isFetching} onClick={() => void refetch()}>
          Refresh
        </Button>
      </Card>

      {error ? (
        <Card className="mb-5 px-5 py-4 text-[12.5px] leading-relaxed text-err">
          {error.message}
        </Card>
      ) : null}

      {isLoading ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 3 }).map((_, index) => (
            <Skeleton key={index} className="h-36 w-full" />
          ))}
        </div>
      ) : matches.length ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {matches.map((entry) => (
            <Listing key={entry.slug} entry={entry} onOpen={() => setOpened(entry)} />
          ))}
        </div>
      ) : (
        <Card className="p-5">
          <EmptyState
            title={query ? 'Nothing matches that' : 'This registry lists nothing'}
            body={
              query
                ? 'Try a different name, tag or author.'
                : 'A registry is a JSON index at a URL. This one is empty, or is not a registry.'
            }
          />
        </Card>
      )}

      {data ? (
        <div className="mt-5 text-[12px] text-ink-3 [overflow-wrap:anywhere]">
          Reading {data.registry}
          {data.is_default ? '' : ' (custom registry)'}
        </div>
      ) : null}

      <PackageModal listing={opened} onClose={() => setOpened(null)} />
    </div>
  )
}

function Listing({ entry, onOpen }: { entry: MarketplaceListing; onOpen: () => void }) {
  return (
    <Card className="flex flex-col gap-3 p-4.5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[14px] font-semibold [overflow-wrap:anywhere]">{entry.name}</div>
          <div className="mt-0.5 font-mono text-[11.5px] text-ink-3">
            {entry.author || 'unattributed'}
            {entry.version ? ` · v${entry.version}` : ''}
          </div>
        </div>
        <Badge tone={entry.runtime_installed ? 'accent' : 'warn'}>
          {entry.language || entry.runtime}
        </Badge>
      </div>

      <p className="m-0 flex-1 text-[12.5px] leading-relaxed text-ink-2">
        {entry.summary || 'No description.'}
      </p>

      {entry.tags.length ? (
        <div className="flex flex-wrap gap-1.5">
          {entry.tags.map((tag) => (
            <span
              key={tag}
              className="rounded-full border border-line px-2 py-0.5 text-[11px] text-ink-3"
            >
              {tag}
            </span>
          ))}
        </div>
      ) : null}

      <Button size="sm" onClick={onOpen} disabled={!entry.url}>
        {entry.runtime_installed ? 'Read and install' : 'Read'}
      </Button>
    </Card>
  )
}

/**
 * The package in full: what it needs, then its source, then install.
 *
 * The order is the point. Nothing here installs before the source has been on
 * screen, and the environment it wants is listed rather than set — an
 * installer that writes your secrets for you is a bad idea however convenient.
 */
function PackageModal({
  listing,
  onClose,
}: {
  listing: MarketplaceListing | null
  onClose: () => void
}) {
  const toast = useToast()
  const navigate = useNavigate()
  const { data: groups } = useGroups()
  const { data: pkg, isLoading, error } = useMarketplacePackage(listing?.url ?? null)
  const install = useInstallFromMarketplace()

  const [group, setGroup] = useState('')
  const [name, setName] = useState('')
  const [file, setFile] = useState<string | null>(null)

  const target = group || groups?.[0]?.id || ''
  const files = pkg ? Object.keys(pkg.files) : []
  const showing = file && files.includes(file) ? file : files[0]

  const run = () => {
    if (!pkg || !target) return
    install.mutate(
      { url: pkg.source_url, group_id: target, name: name.trim() || undefined },
      {
        onSuccess: (created) => {
          toast.push(`${created.name} installed`, 'ok', 'building')
          onClose()
          navigate(`/console/playground/${created.group_id}/${created.id}`)
        },
        onError: (err) => toast.push(err.message, 'err'),
      },
    )
  }

  return (
    <Modal
      open={Boolean(listing)}
      onClose={onClose}
      title={pkg?.name || listing?.name || 'Package'}
      width={760}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={install.isPending}
            disabled={!pkg || !pkg.runtime_installed || !target}
            onClick={run}
          >
            Install into {groups?.find((g) => g.id === target)?.ns ?? 'a namespace'}
          </Button>
        </>
      }
    >
      {isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : error ? (
        <div className="text-[12.5px] leading-relaxed text-err">{error.message}</div>
      ) : pkg ? (
        <div className="grid gap-4.5">
          <p className="m-0 text-[13px] leading-relaxed text-ink-2">{pkg.summary}</p>

          <div className="flex flex-wrap gap-2 text-[12px]">
            <Badge>{pkg.runtime_label}</Badge>
            <Badge>{pkg.method}</Badge>
            <Badge>{pkg.function_type}</Badge>
            <Badge>{pkg.memory_mb} MB</Badge>
            <Badge>{pkg.timeout_s}s timeout</Badge>
            {pkg.license ? <Badge>{pkg.license}</Badge> : null}
          </div>

          {!pkg.runtime_installed ? (
            <div className="rounded-[9px] border border-warn bg-panel-2 px-3.5 py-3 text-[12.5px] leading-relaxed text-ink-2">
              This needs <span className="font-semibold text-ink">{pkg.runtime_label}</span>,
              which is not installed here. Install it in Settings → Runtimes, then come back.
            </div>
          ) : null}

          {pkg.env.length ? (
            <div>
              <div className="mb-2 text-[12.5px] font-semibold">
                Needs these in Global env
              </div>
              <div className="rounded-[9px] border border-line">
                {pkg.env.map((item) => (
                  <div
                    key={item.key}
                    className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-line px-3.5 py-2.5 last:border-b-0"
                  >
                    <span className="font-mono text-[12.5px] font-semibold">{item.key}</span>
                    {item.required ? <Badge tone="warn">required</Badge> : null}
                    <span className="min-w-0 flex-1 text-[12px] text-ink-3">
                      {item.description}
                    </span>
                  </div>
                ))}
              </div>
              <div className="mt-1.5 text-[12px] text-ink-3">
                Listed by the author, never set for you. Add them yourself before invoking.
              </div>
            </div>
          ) : null}

          <div>
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <span className="text-[12.5px] font-semibold">Source</span>
              <span className="text-[12px] text-ink-3">
                — installing runs this on your cluster. Read it first.
              </span>
            </div>
            <div className="mb-2 flex flex-wrap gap-1.5">
              {files.map((entry) => (
                <button
                  key={entry}
                  type="button"
                  onClick={() => setFile(entry)}
                  className={cx(
                    'rounded-full border px-2.5 py-1 font-mono text-[11.5px] transition',
                    showing === entry
                      ? 'border-accent bg-accent-soft font-semibold text-ink'
                      : 'border-line text-ink-2 hover:text-ink',
                  )}
                >
                  {entry}
                </button>
              ))}
            </div>
            {showing ? (
              <div className="max-h-72 overflow-auto rounded-[9px] border border-line">
                <CodeBlock>{pkg.files[showing]}</CodeBlock>
              </div>
            ) : null}
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <span className="mb-1.5 block text-[12.5px] text-ink-2">Install into</span>
              <select
                value={target}
                onChange={(event) => setGroup(event.target.value)}
                className="h-10 w-full rounded-[9px] border border-line bg-bg px-3 font-mono text-[13.5px] text-ink outline-none transition focus:border-accent"
              >
                {(groups ?? []).map((entry) => (
                  <option key={entry.id} value={entry.id}>
                    {entry.ns}
                  </option>
                ))}
              </select>
            </div>
            <Field
              label="Name it"
              value={name}
              placeholder={pkg.slug}
              onChange={(event) => setName(event.target.value)}
              hint="Defaults to the package's own name."
            />
          </div>

          {pkg.readme ? (
            <details>
              <summary className="cursor-pointer text-[12.5px] text-ink-2 select-none hover:text-ink">
                What the author says
              </summary>
              <p className="mt-2 mb-0 text-[12.5px] leading-relaxed whitespace-pre-wrap text-ink-2">
                {pkg.readme}
              </p>
            </details>
          ) : null}
        </div>
      ) : null}
    </Modal>
  )
}
