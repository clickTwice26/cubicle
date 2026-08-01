import { useEffect, useState } from 'react'
import { Check, Plus } from '../components/Icons'
import {
  Badge,
  Button,
  Card,
  CardHeader,
  CodeBlock,
  ConfirmButton,
  Field,
  Modal,
  PAGE,
  PageHeader,
  Skeleton,
  useToast,
} from '../components/ui'
import { NewClusterModal } from '../components/ClusterSwitcher'
import { activeCluster } from '../lib/cluster'
import { useAiStatus, useTestAi, useUpdateAiSettings } from '../lib/ai'
import {
  useApiKeys,
  useClusters,
  useDeleteCluster,
  useSetDefaultCluster,
  useSwitchCluster,
  useChangePassword,
  useCreateApiKey,
  useCreateUser,
  useDeleteUser,
  useInstance,
  useMe,
  useRevokeApiKey,
  useUpdateInstance,
  useUpdateUser,
  useUsers,
} from '../lib/hooks'
import { formatDate, relativeTime } from '../lib/format'
import type { Role } from '../lib/types'

const ROLES: Role[] = ['owner', 'admin', 'developer', 'readonly']

export default function Settings() {
  return (
    <div className={PAGE}>
      <PageHeader title="Settings" />
      <ClustersCard />
      <InstanceCard />
      <AssistantCard />
      <PasswordCard />
      <ApiKeysCard />
      <UsersCard />
    </div>
  )
}

function ClustersCard() {
  const toast = useToast()
  const { data: clusters } = useClusters()
  const setDefault = useSetDefaultCluster()
  const remove = useDeleteCluster()
  const switchCluster = useSwitchCluster()
  const [creating, setCreating] = useState(false)
  const current = activeCluster()

  return (
    <Card className="mb-5 overflow-hidden">
      <CardHeader
        title="Clusters"
        subtitle="Each has its own namespaces, configuration, data services and metrics"
        action={
          <Button size="sm" icon={<Plus size={13} />} onClick={() => setCreating(true)}>
            New cluster
          </Button>
        }
      />
      {(clusters ?? []).map((cluster) => {
        const selected = current
          ? current === cluster.slug || current === cluster.id
          : cluster.is_default
        return (
          <div
            key={cluster.id}
            className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-3.5 last:border-b-0"
          >
            <span className="w-4 flex-none text-ink">
              {selected ? <Check size={14} /> : null}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 text-[13.5px] font-semibold">
                {cluster.name}
                {cluster.is_default ? <Badge>default</Badge> : null}
              </div>
              <div className="truncate font-mono text-[11.5px] text-ink-3">
                {cluster.base_url} · {cluster.namespace_count} ns · {cluster.function_count} fn
              </div>
            </div>
            <div className="flex flex-none flex-wrap items-center gap-2">
              {!selected ? (
                <Button
                  size="sm"
                  onClick={() => switchCluster(cluster.is_default ? null : cluster.slug)}
                >
                  Switch to
                </Button>
              ) : (
                <span className="rounded-lg border border-accent bg-accent-soft px-3 py-1.5 text-[12.5px] font-semibold">
                  Active
                </span>
              )}
              {!cluster.is_default ? (
                <>
                  <Button
                    size="sm"
                    variant="ghost"
                    loading={setDefault.isPending}
                    onClick={() =>
                      setDefault.mutate(cluster.slug, {
                        onSuccess: () => toast.push(`${cluster.name} is now the default`),
                        onError: (error) => toast.push(error.message, 'err'),
                      })
                    }
                  >
                    Make default
                  </Button>
                  <ConfirmButton
                    as="button"
                    label="Delete"
                    confirmLabel="Confirm"
                    hint="Deletes this cluster's functions, data services and history"
                    onConfirm={() =>
                      remove.mutate(cluster.slug, {
                        onSuccess: () => {
                          toast.push(`${cluster.name} deleted`)
                          if (selected) switchCluster(null)
                        },
                        onError: (error) => toast.push(error.message, 'err'),
                      })
                    }
                  />
                </>
              ) : null}
            </div>
          </div>
        )
      })}
      <NewClusterModal open={creating} onClose={() => setCreating(false)} />
    </Card>
  )
}

/**
 * Cubicle AI — the one place a provider key is entered.
 *
 * The key is write-only from here on: it is stored envelope-encrypted like every
 * other secret and only ever comes back as a masked hint, so this card can show
 * that a key exists without being able to show what it is.
 */
function AssistantCard() {
  const toast = useToast()
  const { data: status } = useAiStatus()
  const update = useUpdateAiSettings()
  const test = useTestAi()

  const [key, setKey] = useState('')
  const [model, setModel] = useState('')
  const [baseUrl, setBaseUrl] = useState('')

  useEffect(() => {
    if (!status) return
    setModel(status.model)
    setBaseUrl(status.base_url)
  }, [status])

  if (!status) return <Skeleton className="mb-5 h-40 w-full" />

  const dirty = key.trim().length > 0 || model !== status.model || baseUrl !== status.base_url

  const save = () =>
    update.mutate(
      {
        ...(key.trim() ? { api_key: key.trim() } : {}),
        model: model.trim(),
        base_url: baseUrl.trim(),
      },
      {
        onSuccess: () => {
          setKey('')
          toast.push('Cubicle AI updated')
        },
        onError: (error) => toast.push(error.message, 'err'),
      },
    )

  return (
    <Card className="mb-5 overflow-hidden">
      <CardHeader
        title="Cubicle AI"
        subtitle="The code assistant in the function editor — the only part of Cubicle that talks to anything off this machine"
        action={
          status.enabled ? <Badge tone="accent">on</Badge> : <Badge tone="warn">off</Badge>
        }
      />

      <div className="grid gap-4 px-5 py-5">
        <Field
          label="API key"
          type="password"
          autoComplete="off"
          value={key}
          placeholder={
            status.key_hint
              ? `stored · ${status.key_hint}${
                  status.key_source === 'environment' ? ' (from the environment)' : ''
                }`
              : 'sk-…'
          }
          onChange={(event) => setKey(event.target.value)}
          hint="Stored envelope-encrypted, like every other secret here. It is never shown again."
        />
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="Model"
            value={model}
            placeholder="gpt-4.1-mini"
            onChange={(event) => setModel(event.target.value)}
            hint="These are single-file handlers — a small model is cheaper and quicker."
          />
          <Field
            label="Base URL"
            value={baseUrl}
            placeholder="https://api.openai.com/v1"
            onChange={(event) => setBaseUrl(event.target.value)}
            hint="Any OpenAI-compatible endpoint. Point it at a local server and nothing leaves your network."
          />
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          <Button
            variant="primary"
            size="sm"
            loading={update.isPending}
            disabled={!dirty}
            onClick={save}
          >
            Save
          </Button>
          <Button
            size="sm"
            loading={test.isPending}
            disabled={!status.enabled}
            onClick={() =>
              test.mutate(undefined, {
                onSuccess: (result) =>
                  toast.push(`${result.model} answered`, 'ok', `${result.duration_ms}ms`),
                onError: (error) => toast.push(error.message, 'err'),
              })
            }
          >
            Test connection
          </Button>
          {status.key_source === 'console' ? (
            <ConfirmButton
              label="Remove key"
              confirmLabel="Click again to remove"
              onConfirm={() =>
                update.mutate(
                  { api_key: '' },
                  {
                    onSuccess: () => toast.push('Key removed — the assistant is off'),
                    onError: (error) => toast.push(error.message, 'err'),
                  },
                )
              }
            />
          ) : null}
          <span className="ml-auto text-[12.5px] text-ink-3">
            Secret and env <strong>values</strong> are never sent — only their names.
          </span>
        </div>
      </div>
    </Card>
  )
}

function InstanceCard() {
  const toast = useToast()
  const { data: instance } = useInstance()
  const update = useUpdateInstance()
  const [form, setForm] = useState({
    cluster_name: '',
    ingress_domain: '',
    data_dir: '',
    default_node_pool: '',
  })

  useEffect(() => {
    if (instance)
      setForm({
        cluster_name: instance.cluster_name,
        ingress_domain: instance.ingress_domain,
        data_dir: instance.data_dir,
        default_node_pool: instance.default_node_pool,
      })
  }, [instance])

  if (!instance) return <Skeleton className="mb-5 h-56 w-full" />

  return (
    <Card className="mb-5 p-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="text-[15px] font-semibold">
          {instance.cluster_name}
          <span className="ml-2 font-mono text-[12px] font-normal text-ink-3">
            {instance.cluster_slug}
          </span>
        </div>
        <div className="flex items-center gap-2.5 text-[12.5px] text-ink-2">
          <span className="font-mono">v{instance.version}</span>
          <Badge tone={instance.tls ? 'ok' : 'neutral'}>
            {instance.tls ? 'HTTPS' : 'HTTP (local)'}
          </Badge>
          <Badge>{instance.kms_backend}</Badge>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          label="Cluster name"
          value={form.cluster_name}
          onChange={(event) => setForm({ ...form, cluster_name: event.target.value })}
        />
        <Field
          label="Ingress domain"
          value={form.ingress_domain}
          onChange={(event) => setForm({ ...form, ingress_domain: event.target.value })}
          hint={`${instance.base_url.replace(/\/$/, '')}/<namespace>/<function>`}
        />
        <Field
          label="Default node pool"
          value={form.default_node_pool}
          onChange={(event) => setForm({ ...form, default_node_pool: event.target.value })}
        />
        <Field
          label="Data directory"
          value={form.data_dir}
          onChange={(event) => setForm({ ...form, data_dir: event.target.value })}
        />
      </div>

      <div className="mt-4 flex items-center gap-3">
        <Button
          variant="primary"
          loading={update.isPending}
          onClick={() =>
            update.mutate(form, {
              onSuccess: () => toast.push('Instance updated'),
              onError: (error) => toast.push(error.message, 'err'),
            })
          }
        >
          Save changes
        </Button>
        <span className="text-xs text-ink-3">
          Changing the ingress domain affects the URLs shown here; the certificate itself
          follows CUBICLE_DOMAIN in your .env.
        </span>
      </div>
    </Card>
  )
}

function PasswordCard() {
  const toast = useToast()
  const change = useChangePassword()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')

  return (
    <Card className="mb-5 p-6">
      <div className="mb-1 text-[15px] font-semibold">Your password</div>
      <div className="mb-5 text-[13.5px] text-ink-2">
        Changing it signs out every other session immediately.
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          label="Current password"
          type="password"
          mono={false}
          value={current}
          autoComplete="current-password"
          onChange={(event) => setCurrent(event.target.value)}
        />
        <Field
          label="New password"
          type="password"
          mono={false}
          value={next}
          autoComplete="new-password"
          onChange={(event) => setNext(event.target.value)}
          hint="At least 12 characters, three character classes."
        />
      </div>
      <Button
        className="mt-4"
        loading={change.isPending}
        disabled={!current || next.length < 12}
        onClick={() =>
          change.mutate(
            { current_password: current, new_password: next },
            {
              onSuccess: () => {
                toast.push('Password changed')
                setCurrent('')
                setNext('')
              },
              onError: (error) => toast.push(error.message, 'err'),
            },
          )
        }
      >
        Change password
      </Button>
    </Card>
  )
}

function ApiKeysCard() {
  const toast = useToast()
  const { data: keys } = useApiKeys()
  const create = useCreateApiKey()
  const revoke = useRevokeApiKey()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [issued, setIssued] = useState<string | null>(null)

  return (
    <Card className="mb-5 overflow-hidden">
      <CardHeader
        title="API keys"
        subtitle="Used by the CLI, CI, and any endpoint that requires authentication"
        action={
          <Button
            size="sm"
            variant="primary"
            icon={<Plus size={13} />}
            onClick={() => setOpen(true)}
          >
            Create key
          </Button>
        }
      />
      <div className="hidden grid-cols-[1.2fr_1.5fr_1fr_0.8fr_auto] gap-3.5 border-b border-line px-5 py-3 text-[11.5px] font-semibold tracking-[0.04em] text-ink-3 uppercase md:grid">
        <span>Name</span>
        <span>Token</span>
        <span>Created</span>
        <span>Last used</span>
        <span />
      </div>
      {keys?.length ? (
        keys.map((key) => (
          <div
            key={key.id}
            className="grid grid-cols-1 items-center gap-3.5 border-b border-line px-5 py-3.5 text-[13px] last:border-b-0 md:grid-cols-[1.2fr_1.5fr_1fr_0.8fr_auto]"
          >
            <span className="font-semibold">{key.name}</span>
            <span className="font-mono text-ink-2">{key.prefix}••••</span>
            <span className="text-ink-2">{formatDate(key.created_at)}</span>
            <span className="text-ink-2">{relativeTime(key.last_used_at)}</span>
            <span className="flex justify-end">
              <ConfirmButton
                label="Revoke"
                confirmLabel="Confirm"
                onConfirm={() =>
                  revoke.mutate(key.id, { onSuccess: () => toast.push('Key revoked') })
                }
              />
            </span>
          </div>
        ))
      ) : (
        <div className="px-5 py-8 text-center text-[13px] text-ink-3">No API keys yet.</div>
      )}

      <Modal
        open={open}
        onClose={() => {
          setOpen(false)
          setIssued(null)
        }}
        title={issued ? 'Copy your key now' : 'Create API key'}
        width={520}
        footer={
          issued ? (
            <Button
              variant="primary"
              onClick={() => {
                setOpen(false)
                setIssued(null)
                setName('')
              }}
            >
              Done
            </Button>
          ) : (
            <>
              <Button variant="ghost" onClick={() => setOpen(false)}>
                Cancel
              </Button>
              <Button
                variant="primary"
                loading={create.isPending}
                disabled={!name.trim()}
                onClick={() =>
                  create.mutate(
                    { name: name.trim(), scope: 'admin' },
                    {
                      onSuccess: (key) => setIssued(key.token ?? null),
                      onError: (error) => toast.push(error.message, 'err'),
                    },
                  )
                }
              >
                Create key
              </Button>
            </>
          )
        }
      >
        {issued ? (
          <div className="grid gap-3">
            <CodeBlock copyValue={issued} filename="token">
              {issued}
            </CodeBlock>
            <p className="m-0 text-xs leading-relaxed text-ink-3">
              This is the only time the full token is shown — only a hash is stored. Use it with{' '}
              <span className="font-mono">cubicle login</span> or as a Bearer token.
            </p>
          </div>
        ) : (
          <Field
            label="Name"
            mono={false}
            autoFocus
            value={name}
            placeholder="ci-github-actions"
            onChange={(event) => setName(event.target.value)}
          />
        )}
      </Modal>
    </Card>
  )
}

function UsersCard() {
  const toast = useToast()
  const { data: users } = useUsers()
  const { data: me } = useMe()
  const create = useCreateUser()
  const update = useUpdateUser()
  const remove = useDeleteUser()
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ name: '', email: '', password: '', role: 'developer' })

  return (
    <Card className="overflow-hidden">
      <CardHeader
        title="Users"
        subtitle="Local accounts. There is no registration — accounts are created here."
        action={
          <Button size="sm" icon={<Plus size={13} />} onClick={() => setOpen(true)}>
            Add user
          </Button>
        }
      />
      {users?.map((user) => (
        <div
          key={user.id}
          className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-3.5 last:border-b-0"
        >
          <span className="grid h-8 w-8 flex-none place-items-center rounded-full bg-panel-3 text-xs font-semibold text-ink-2">
            {user.initials}
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-[13.5px] font-semibold">
              {user.name}
              {user.id === me?.id ? <span className="ml-2 text-xs text-ink-3">you</span> : null}
            </div>
            <div className="truncate text-xs text-ink-3">{user.email}</div>
          </div>
          <select
            value={user.role}
            disabled={user.id === me?.id}
            onChange={(event) =>
              update.mutate(
                { id: user.id, role: event.target.value },
                {
                  onSuccess: () => toast.push('Role updated'),
                  onError: (error) => toast.push(error.message, 'err'),
                },
              )
            }
            className="rounded-full border border-line bg-panel-2 px-3 py-1 text-xs text-ink-2 disabled:opacity-60"
          >
            {ROLES.map((role) => (
              <option key={role} value={role}>
                {role}
              </option>
            ))}
          </select>
          {user.id !== me?.id ? (
            <ConfirmButton
              label="Remove"
              confirmLabel="Confirm"
              onConfirm={() =>
                remove.mutate(user.id, {
                  onSuccess: () => toast.push('User removed'),
                  onError: (error) => toast.push(error.message, 'err'),
                })
              }
            />
          ) : null}
        </div>
      ))}

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Add user"
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              loading={create.isPending}
              disabled={!form.email.includes('@') || form.password.length < 12}
              onClick={() =>
                create.mutate(form, {
                  onSuccess: () => {
                    toast.push('User created')
                    setOpen(false)
                    setForm({ name: '', email: '', password: '', role: 'developer' })
                  },
                  onError: (error) => toast.push(error.message, 'err'),
                })
              }
            >
              Create user
            </Button>
          </>
        }
      >
        <div className="grid gap-4">
          <Field
            label="Name"
            mono={false}
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
          />
          <Field
            label="Email"
            type="email"
            value={form.email}
            onChange={(event) => setForm({ ...form, email: event.target.value })}
          />
          <Field
            label="Temporary password"
            type="password"
            mono={false}
            value={form.password}
            onChange={(event) => setForm({ ...form, password: event.target.value })}
            hint="At least 12 characters. Ask them to change it after signing in."
          />
          <div>
            <span className="mb-1.5 block text-[12.5px] text-ink-2">Role</span>
            <div className="flex flex-wrap gap-2">
              {ROLES.filter((role) => role !== 'owner').map((role) => (
                <button
                  key={role}
                  type="button"
                  onClick={() => setForm({ ...form, role })}
                  className={
                    form.role === role
                      ? 'rounded-lg border border-accent bg-accent-soft px-3 py-1.5 text-[12.5px]'
                      : 'rounded-lg border border-line px-3 py-1.5 text-[12.5px] text-ink-2'
                  }
                >
                  {role}
                </button>
              ))}
            </div>
          </div>
        </div>
      </Modal>
    </Card>
  )
}
