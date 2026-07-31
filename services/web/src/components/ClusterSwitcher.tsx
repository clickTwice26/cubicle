import { useEffect, useRef, useState } from 'react'
import { Check, ChevronDown, Plus, Server } from './Icons'
import { Button, Card, Field, Modal, cx, useToast } from './ui'
import { activeCluster } from '../lib/cluster'
import { useClusters, useCreateCluster, useInstance, useSwitchCluster } from '../lib/hooks'
import { slugify } from '../lib/format'

/**
 * The sidebar chip, made real: it names the cluster the console is pointed at
 * and switches between them. With one cluster it stays out of the way.
 */
export function ClusterSwitcher() {
  const { data: instance } = useInstance()
  const { data: clusters } = useClusters()
  const switchCluster = useSwitchCluster()
  const [open, setOpen] = useState(false)
  const [creating, setCreating] = useState(false)
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

  const current = activeCluster()
  const list = clusters ?? []

  return (
    <div className="relative px-3 pb-2.5" ref={container}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="flex w-full items-center gap-2.5 rounded-[9px] border border-line px-2.5 py-2 text-left transition hover:bg-panel-2"
      >
        <span className="grid h-5 w-5 flex-none place-items-center rounded-[5px] border border-accent bg-accent-soft">
          <span className="h-[7px] w-[7px] rounded-full bg-ok" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] leading-tight font-semibold">
            {instance?.cluster_name ?? '—'}
          </span>
          <span className="block truncate font-mono text-[11.5px] text-ink-3">
            {instance
              ? `${instance.is_default ? 'default' : instance.cluster_slug} · v${instance.version}`
              : 'self-hosted'}
          </span>
        </span>
        <ChevronDown
          size={14}
          className={cx('flex-none text-ink-3 transition', open && 'rotate-180')}
        />
      </button>

      {open ? (
        <div
          role="listbox"
          className="animate-rise absolute inset-x-3 top-full z-30 mt-1 overflow-hidden rounded-xl border border-line-strong bg-panel shadow-2xl"
        >
          <div className="px-3 py-2 text-[11px] font-bold tracking-[0.06em] text-ink-3 uppercase">
            Clusters
          </div>
          <div className="max-h-64 overflow-auto">
            {list.map((cluster) => {
              const selected = current
                ? current === cluster.slug || current === cluster.id
                : cluster.is_default
              return (
                <button
                  key={cluster.id}
                  type="button"
                  role="option"
                  aria-selected={selected}
                  onClick={() => {
                    switchCluster(cluster.is_default ? null : cluster.slug)
                    setOpen(false)
                  }}
                  className={cx(
                    'flex w-full items-center gap-2.5 px-3 py-2 text-left transition hover:bg-panel-2',
                    selected && 'bg-accent-soft',
                  )}
                >
                  <span className="w-3.5 flex-none text-ink">
                    {selected ? <Check size={13} /> : null}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] font-semibold">
                      {cluster.name}
                    </span>
                    <span className="block truncate font-mono text-[11px] text-ink-3">
                      {cluster.namespace_count} ns · {cluster.function_count} fn ·{' '}
                      {cluster.node_count} node{cluster.node_count === 1 ? '' : 's'}
                    </span>
                  </span>
                  {cluster.is_default ? (
                    <span className="flex-none rounded-full border border-line px-1.5 py-px text-[10px] text-ink-3">
                      default
                    </span>
                  ) : null}
                </button>
              )
            })}
          </div>
          <button
            type="button"
            onClick={() => {
              setOpen(false)
              setCreating(true)
            }}
            className="flex w-full items-center gap-2.5 border-t border-line px-3 py-2.5 text-left text-[13px] font-semibold transition hover:bg-panel-2"
          >
            <Plus size={14} />
            New cluster
          </button>
        </div>
      ) : null}

      <NewClusterModal open={creating} onClose={() => setCreating(false)} />
    </div>
  )
}

export function NewClusterModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const toast = useToast()
  const create = useCreateCluster()
  const switchCluster = useSwitchCluster()
  const [name, setName] = useState('')
  const [domain, setDomain] = useState('')
  const [description, setDescription] = useState('')

  const slug = slugify(name)

  const submit = () =>
    create.mutate(
      {
        name: name.trim(),
        slug,
        ingress_domain: domain.trim(),
        description: description.trim(),
      },
      {
        onSuccess: (cluster) => {
          toast.push(`${cluster.name} created`)
          switchCluster(cluster.slug)
          onClose()
          setName('')
          setDomain('')
          setDescription('')
        },
        onError: (error) => toast.push(error.message, 'err'),
      },
    )

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="New cluster"
      width={520}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={create.isPending}
            disabled={!slug}
            onClick={submit}
          >
            Create cluster
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        <div className="flex items-start gap-2.5 rounded-[10px] border border-line bg-panel-2 px-3.5 py-3 text-[12.5px] leading-relaxed text-ink-2">
          <Server size={16} className="mt-0.5 flex-none" />
          <span>
            A cluster has its own namespaces, configuration, data services and metrics. Nothing
            crosses between them. It costs nothing until you deploy into it.
          </span>
        </div>

        <Field
          label="Name"
          mono={false}
          autoFocus
          value={name}
          placeholder="Staging"
          onChange={(event) => setName(event.target.value)}
          hint={slug ? `slug: ${slug}` : 'lower-case, hyphens'}
        />
        <Field
          label="Ingress domain (optional)"
          value={domain}
          placeholder="staging.example.com"
          onChange={(event) => setDomain(event.target.value)}
          hint={
            domain.trim()
              ? `https://${domain.trim()}/<namespace>/<function>`
              : `…/${slug || 'slug'}/<namespace>/<function>`
          }
        />
        <Field
          label="Description (optional)"
          mono={false}
          value={description}
          placeholder="Pre-production checks"
          onChange={(event) => setDescription(event.target.value)}
        />

        <Card className="bg-panel-2 px-3.5 py-3 text-[12.5px] leading-relaxed text-ink-2">
          Functions in this cluster are always addressed under its slug. Give it a domain
          instead and the edge routes that hostname straight here, dropping the slug from the
          path — you will need DNS pointing at this machine, and a certificate is issued on the
          first request.
        </Card>
      </div>
    </Modal>
  )
}
