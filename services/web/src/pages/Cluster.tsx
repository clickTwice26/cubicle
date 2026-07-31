import { useState } from 'react'
import { Download, Plus, Server } from '../components/Icons'
import {
  Badge,
  Button,
  Card,
  CardHeader,
  Field,
  Meter,
  Modal,
  PAGE,
  PageHeader,
  Skeleton,
  StatusDot,
  useToast,
} from '../components/ui'
import { api } from '../lib/api'
import { useDrainNode, useMetering, useNodes } from '../lib/hooks'
import { formatMoney, statusTone } from '../lib/format'

export default function Cluster() {
  const toast = useToast()
  const { data: nodes, isLoading: nodesLoading, refetch } = useNodes()
  const { data: metering } = useMetering()
  const drain = useDrainNode()
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [host, setHost] = useState('tcp://')
  const [pool, setPool] = useState('general')
  const [saving, setSaving] = useState(false)

  const addNode = async () => {
    setSaving(true)
    try {
      await api.post('/api/cluster/nodes', { name, docker_host: host, pool })
      toast.push(`${name} joined the cluster`)
      setAdding(false)
      setName('')
      setHost('tcp://')
      await refetch()
    } catch (error) {
      toast.push((error as Error).message, 'err')
    } finally {
      setSaving(false)
    }
  }

  const windowLabel = metering
    ? `${new Date(metering.window_start).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} – ${new Date(
        new Date(metering.window_end).getTime() - 86_400_000,
      ).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`
    : ''

  return (
    <div className={PAGE}>
      <PageHeader
        title="Cluster & metering"
        subtitle={
          metering
            ? `${nodes?.length ?? 0} node${nodes?.length === 1 ? '' : 's'} · self-hosted · metering window ${windowLabel}`
            : ' '
        }
        action={
          <Button size="sm" icon={<Plus size={14} />} onClick={() => setAdding(true)}>
            Add node
          </Button>
        }
      />

      <div className="mb-5 grid gap-5 lg:grid-cols-[1.3fr_1fr]">
        <Card className="p-6">
          <div className="text-[13px] text-ink-2">Invocations this window</div>
          <div className="mt-1.5 mb-0.5 font-mono text-[42px] leading-none font-semibold tracking-[-0.03em]">
            {metering?.invocations_label ?? '—'}
          </div>
          <div className="text-[13px] text-ink-2">
            {metering ? `${metering.window_progress}% through window` : ''} ·{' '}
            <span className="text-ok">{metering?.gb_seconds_label ?? '0'} GB-s metered</span>
          </div>
          <Meter className="mt-4" value={metering?.window_progress ?? 0} />
        </Card>

        <Card className="flex flex-col justify-between p-6">
          <div className="mb-3 text-[13px] font-semibold">Metering export</div>
          <div className="flex items-center gap-3">
            <StatusDot tone="ok" />
            <span className="font-mono text-[13px]">prometheus · /metrics</span>
          </div>
          <div className="mt-3 text-xs leading-relaxed text-ink-3">
            Scrape it with no credentials from inside your network. Every series is derived from
            recorded invocations.
          </div>
          <a href="/api/cluster/metering/export.csv" className="mt-4">
            <Button className="w-full" icon={<Download size={14} />}>
              Export chargeback CSV
            </Button>
          </a>
        </Card>
      </div>

      <Card className="mb-5 overflow-hidden">
        <CardHeader title="Nodes" subtitle="Docker engines this control plane schedules onto" />
        <div className="hidden grid-cols-[1.3fr_0.9fr_1.6fr_1.6fr_0.9fr_auto] gap-3.5 border-b border-line px-5 py-3 text-[11.5px] font-semibold tracking-[0.04em] text-ink-3 uppercase md:grid">
          <span>Node</span>
          <span>Status</span>
          <span>CPU allocated</span>
          <span>Memory allocated</span>
          <span>Isolates</span>
          <span />
        </div>

        {nodesLoading ? (
          <div className="p-5">
            <Skeleton className="h-12 w-full" />
          </div>
        ) : (
          nodes?.map((node) => (
            <div
              key={node.id}
              className="grid grid-cols-1 items-center gap-3.5 border-b border-line px-5 py-3.5 text-[13px] last:border-b-0 md:grid-cols-[1.3fr_0.9fr_1.6fr_1.6fr_0.9fr_auto]"
            >
              <div>
                <div className="flex items-center gap-2 font-mono font-semibold">
                  {node.name}
                  {node.is_local ? <Badge>local</Badge> : null}
                </div>
                <div className="mt-0.5 text-[11.5px] text-ink-3">{node.spec}</div>
              </div>
              <span className="flex items-center gap-2 text-ink-2">
                <StatusDot tone={statusTone(node.status)} />
                {node.status}
              </span>
              <div>
                <div className="mb-1.5 font-mono text-xs text-ink-2">
                  {node.cpu_allocated_pct}%
                </div>
                <Meter value={node.cpu_allocated_pct} />
              </div>
              <div>
                <div className="mb-1.5 font-mono text-xs text-ink-2">{node.memory_label}</div>
                <Meter
                  value={node.memory_allocated_pct}
                  tone={node.memory_allocated_pct > 80 ? 'warn' : 'accent'}
                />
              </div>
              <span className="font-mono">{node.isolates}</span>
              <button
                type="button"
                className="text-right text-xs text-ink-3 transition hover:text-ink"
                onClick={() =>
                  drain.mutate(
                    { id: node.id, drain: node.schedulable },
                    {
                      onSuccess: () =>
                        toast.push(
                          node.schedulable ? `${node.name} draining` : `${node.name} resumed`,
                        ),
                    },
                  )
                }
              >
                {node.schedulable ? 'Drain' : 'Resume'}
              </button>
            </div>
          ))
        )}
        {nodes?.some((node) => node.last_error) ? (
          <div className="border-t border-line bg-err-bg px-5 py-3 text-[12.5px]">
            {nodes.find((node) => node.last_error)?.last_error}
          </div>
        ) : null}
      </Card>

      <div className="mb-5 grid gap-4 md:grid-cols-3">
        {[
          {
            label: 'Compute consumed',
            value: `${metering?.gb_seconds_label ?? '0'} GB-s`,
            rate: 'metered per invocation',
          },
          {
            label: 'Function storage',
            value: metering?.storage_label ?? '—',
            rate: 'version volumes and data services',
          },
          {
            label: 'Response egress',
            value: metering?.egress_label ?? '—',
            rate: 'measured response bodies',
          },
        ].map((item) => (
          <Card key={item.label} className="p-5">
            <div className="mb-2 text-[12.5px] text-ink-2">{item.label}</div>
            <div className="mb-1 font-mono text-[22px] font-semibold">{item.value}</div>
            <div className="font-mono text-xs text-ink-3">{item.rate}</div>
          </Card>
        ))}
      </div>

      {metering ? (
        <>
          <Card className="mb-5 overflow-hidden">
            <div className="flex flex-wrap items-end justify-between gap-5 border-b border-line px-5 pt-5 pb-4">
              <div className="max-w-[560px]">
                <div className="text-sm font-semibold">
                  What this workload would cost hosted
                </div>
                <div className="mt-1 text-[12.5px] leading-relaxed text-ink-2">
                  The same {metering.invocations_label} invocations, {metering.gb_seconds_label}{' '}
                  GB-s and {metering.egress_label} of responses, priced at each vendor's public
                  list rate.
                </div>
              </div>
              <div className="text-right">
                <div className="text-xs text-ink-2">Avoided this window vs AWS Lambda</div>
                <div className="font-mono text-3xl leading-tight font-semibold tracking-[-0.02em] text-ok">
                  {formatMoney(metering.cost.avoided_vs_aws)}
                </div>
                <div className="font-mono text-xs text-ink-3">
                  ≈ {formatMoney(metering.cost.avoided_vs_aws * 12)} / yr at this rate
                </div>
              </div>
            </div>

            <div className="hidden grid-cols-[1.5fr_0.8fr_0.8fr_0.8fr_0.9fr_0.9fr] gap-3.5 border-b border-line px-5 py-3 text-[11.5px] font-semibold tracking-[0.04em] text-ink-3 uppercase md:grid">
              <span>Platform</span>
              <span>Requests</span>
              <span>Compute</span>
              <span>Egress</span>
              <span className="text-right">Window</span>
              <span className="text-right">You save</span>
            </div>

            {metering.cost.rows.map((row) => (
              <div
                key={row.key}
                className="grid grid-cols-1 items-center gap-3.5 border-b border-line px-5 py-3.5 text-[13px] md:grid-cols-[1.5fr_0.8fr_0.8fr_0.8fr_0.9fr_0.9fr]"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2.5">
                    <span
                      className="h-2 w-2 flex-none rounded-[2px]"
                      style={{ background: row.colour }}
                    />
                    <span className="truncate font-semibold">{row.name}</span>
                  </div>
                  <div className="mt-2 h-1 overflow-hidden rounded-full bg-panel-3">
                    <div
                      className="h-full rounded-full"
                      style={{ width: `${row.bar}%`, background: row.colour }}
                    />
                  </div>
                </div>
                <span className="font-mono text-ink-2">
                  {row.requests ? formatMoney(row.requests) : '—'}
                </span>
                <span className="font-mono text-ink-2">{formatMoney(row.compute)}</span>
                <span className="font-mono text-ink-2">{formatMoney(row.egress)}</span>
                <span className="text-right font-mono font-semibold">
                  {formatMoney(row.total)}
                </span>
                <span
                  className="text-right font-mono"
                  style={{ color: row.saved === null ? 'var(--text-3)' : 'var(--ok)' }}
                >
                  {row.saved === null ? '—' : `+${formatMoney(row.saved)}`}
                </span>
              </div>
            ))}

            <div className="px-5 py-3.5 text-xs leading-relaxed text-ink-3">
              List prices as of {metering.cost.rates_as_of}, us-east equivalents, no
              committed-use discounts and no free tiers. The Cubicle line is marginal power draw
              only (${metering.cost.kwh_price}/kWh) — the nodes are hardware you already own, so
              capex, rack space and operator time are excluded. Egress inside your own network
              is free.
            </div>
          </Card>

          <Card className="overflow-hidden">
            <CardHeader
              title="Internal chargeback"
              subtitle="Showback by namespace, derived from recorded invocations"
              action={
                <a href="/api/cluster/metering/export.csv">
                  <Button size="sm">Export CSV</Button>
                </a>
              }
            />
            <div className="hidden grid-cols-[1.4fr_1.2fr_1.2fr] gap-3.5 border-b border-line px-5 py-3 text-[11.5px] font-semibold tracking-[0.04em] text-ink-3 uppercase md:grid">
              <span>Namespace</span>
              <span>Invocations</span>
              <span>GB-seconds</span>
            </div>
            {metering.namespaces.length ? (
              metering.namespaces.map((row) => (
                <div
                  key={row.name}
                  className="grid grid-cols-1 items-center gap-3.5 border-b border-line px-5 py-3.5 text-[13.5px] md:grid-cols-[1.4fr_1.2fr_1.2fr]"
                >
                  <span className="font-mono font-medium">{row.name}</span>
                  <span className="font-mono text-ink-2">{row.invocations_label}</span>
                  <span className="font-mono text-ink-2">{row.gb_seconds_label}</span>
                </div>
              ))
            ) : (
              <div className="px-5 py-8 text-center text-[13px] text-ink-3">
                Nothing metered in this window yet.
              </div>
            )}
          </Card>
        </>
      ) : null}

      <Modal
        open={adding}
        onClose={() => setAdding(false)}
        title="Add a node"
        footer={
          <>
            <Button variant="ghost" onClick={() => setAdding(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              loading={saving}
              disabled={!name.trim() || host.length < 8}
              onClick={addNode}
            >
              Join node
            </Button>
          </>
        }
      >
        <div className="grid gap-4">
          <div className="flex items-start gap-2.5 rounded-[10px] border border-line bg-panel-2 px-3.5 py-3 text-[12.5px] leading-relaxed text-ink-2">
            <Server size={16} className="mt-0.5 flex-none" />
            <span>
              A node is a Docker engine reachable from this control plane. Expose it over TLS
              and put the client certificates in{' '}
              <span className="font-mono">/var/lib/cubicle/certs</span> on this host.
            </span>
          </div>
          <Field
            label="Node name"
            value={name}
            placeholder="node-02"
            onChange={(event) => setName(event.target.value)}
          />
          <Field
            label="Docker host"
            value={host}
            placeholder="tcp://10.0.0.12:2376"
            onChange={(event) => setHost(event.target.value)}
          />
          <Field
            label="Pool"
            value={pool}
            placeholder="general"
            onChange={(event) => setPool(event.target.value)}
          />
        </div>
      </Modal>
    </div>
  )
}
