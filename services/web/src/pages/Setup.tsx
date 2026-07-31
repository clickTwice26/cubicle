import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Logo, ThemeToggle } from '../components/Layout'
import { Bolt, Check, Info } from '../components/Icons'
import { Button, Card, Chip, CodeBlock, CopyButton, Field, Spinner, cx } from '../components/ui'
import { api, subscribe } from '../lib/api'
import { useJoinableNodes, useSetupStatus } from '../lib/hooks'
import { slugify } from '../lib/format'
import type { ProvisionStep } from '../lib/types'

const STEPS = ['Administrator', 'Cluster', 'Nodes', 'Review'] as const

const KMS_OPTIONS = [
  {
    value: 'file',
    label: 'file',
    hint: 'Root key from the instance environment. The default.',
  },
  {
    value: 'vault',
    label: 'vault',
    hint: 'HashiCorp Vault transit — needs CUBICLE_VAULT_* set.',
  },
  { value: 'kms', label: 'cloud KMS', hint: 'AWS/GCP KMS or KMIP — needs CUBICLE_KMS_* set.' },
  { value: 'pkcs11', label: 'HSM', hint: 'PKCS#11 device — needs CUBICLE_PKCS11_* set.' },
]

export default function Setup() {
  const navigate = useNavigate()
  const { data: status } = useSetupStatus()
  const { data: nodes, isLoading: nodesLoading, error: nodesError } = useJoinableNodes()

  const [step, setStep] = useState(0)
  const [adminName, setAdminName] = useState('')
  const [adminEmail, setAdminEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [clusterName, setClusterName] = useState('prod-cluster')
  const [ingressDomain, setIngressDomain] = useState('')
  const [dataDir, setDataDir] = useState('/var/lib/cubicle')
  const [kms, setKms] = useState('file')
  const [selected, setSelected] = useState<string[]>([])

  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [provisioning, setProvisioning] = useState(false)
  const [steps, setSteps] = useState<ProvisionStep[]>([])
  const [cliToken, setCliToken] = useState<string | null>(null)

  useEffect(() => {
    if (status?.setup_complete && !provisioning) navigate('/console', { replace: true })
  }, [status?.setup_complete, provisioning, navigate])

  useEffect(() => {
    if (status?.domain && !ingressDomain) setIngressDomain(status.domain)
  }, [status?.domain, ingressDomain])

  useEffect(() => {
    if (nodes && selected.length === 0) setSelected(nodes.map((node) => node.name))
  }, [nodes, selected.length])

  const passwordProblem = useMemo(() => {
    if (!password) return null
    if (password.length < 12) return 'Use at least 12 characters.'
    const classes = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((re) => re.test(password))
    if (classes.length < 3)
      return 'Mix at least three of: lower case, upper case, digits, symbols.'
    if (confirm && password !== confirm) return 'The two passwords do not match.'
    return null
  }, [password, confirm])

  const stepValid = [
    Boolean(
      adminName.trim() && adminEmail.includes('@') && password && !passwordProblem && confirm,
    ),
    Boolean(slugify(clusterName)),
    selected.length > 0,
    true,
  ][step]

  const complete =
    steps.length > 0 && steps.every((s) => s.status === 'done' || s.status === 'failed')
  const failed = steps.some((s) => s.status === 'failed')

  async function submit() {
    setSubmitting(true)
    setError(null)
    try {
      const result = await api.post<{ cli_token: string }>('/api/setup', {
        admin_name: adminName.trim(),
        admin_email: adminEmail.trim(),
        password,
        cluster_name: slugify(clusterName),
        ingress_domain: ingressDomain.trim() || 'localhost',
        data_dir: dataDir.trim(),
        kms_backend: kms,
        nodes: selected,
      })
      setCliToken(result.cli_token)
      setProvisioning(true)
      const stop = subscribe<{ steps: ProvisionStep[]; complete: boolean }>(
        '/api/setup/progress',
        (payload) => {
          setSteps(payload.steps)
          if (payload.complete) stop()
        },
      )
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : 'Setup failed.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen flex-col bg-bg text-ink">
      <header className="border-b border-line">
        <div className="mx-auto flex h-[62px] max-w-[860px] items-center gap-3 px-6 sm:px-8">
          <Link to="/">
            <Logo size={26} />
          </Link>
          <span className="rounded-full border border-line px-2.5 py-0.5 font-mono text-xs text-ink-3">
            first run
          </span>
          <div className="ml-auto flex items-center gap-3">
            <Link to="/docs/install" className="text-[13.5px] text-ink-2 hover:text-ink">
              Docs
            </Link>
            <ThemeToggle />
          </div>
        </div>
      </header>

      <div className="mx-auto w-full max-w-[860px] flex-1 px-6 pt-11 pb-16 sm:px-8">
        {provisioning ? (
          <Provisioning
            steps={steps}
            complete={complete}
            failed={failed}
            clusterName={slugify(clusterName)}
            nodeCount={selected.length}
            cliToken={cliToken}
            onFinish={() => navigate('/console')}
          />
        ) : (
          <>
            <h1 className="m-0 mb-2 text-[32px] font-semibold tracking-[-0.03em]">
              Create your cluster
            </h1>
            <p className="m-0 mb-8 max-w-[560px] text-base leading-relaxed text-ink-2 text-pretty">
              Cubicle needs a cluster before it can schedule functions. This takes about a
              minute. There is no registration — the password you choose here is the only
              account on this instance.
            </p>

            <ol className="mb-8 flex list-none flex-wrap items-center gap-3 p-0">
              {STEPS.map((label, index) => (
                <li key={label} className="flex min-w-[130px] flex-1 items-center gap-2.5">
                  <span
                    className={cx(
                      'grid h-6 w-6 flex-none place-items-center rounded-full font-mono text-xs font-semibold',
                      index <= step
                        ? 'bg-accent text-accent-ink'
                        : 'border border-line bg-panel-2 text-ink-3',
                    )}
                  >
                    {index < step ? <Check size={12} /> : index + 1}
                  </span>
                  <span
                    className={cx(
                      'text-[13.5px] whitespace-nowrap',
                      index === step ? 'font-semibold text-ink' : '',
                      index < step ? 'text-ink' : index > step ? 'text-ink-3' : '',
                    )}
                  >
                    {label}
                  </span>
                  <span className="h-px flex-1 bg-[var(--border)]" />
                </li>
              ))}
            </ol>

            {step === 0 ? (
              <Card className="mb-5 p-6">
                <div className="text-[15.5px] font-semibold">Administrator</div>
                <div className="mt-1 mb-5 text-[13.5px] text-ink-2">
                  This account owns the cluster. Store the password somewhere safe — nothing on
                  this instance can email you a reset link.
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field
                    label="Name"
                    mono={false}
                    value={adminName}
                    autoComplete="name"
                    placeholder="Jordan Diaz"
                    onChange={(event) => setAdminName(event.target.value)}
                  />
                  <Field
                    label="Email"
                    value={adminEmail}
                    type="email"
                    autoComplete="username"
                    placeholder="you@internal.corp"
                    onChange={(event) => setAdminEmail(event.target.value)}
                  />
                  <Field
                    label="Password"
                    mono={false}
                    type="password"
                    value={password}
                    autoComplete="new-password"
                    onChange={(event) => setPassword(event.target.value)}
                    error={password && passwordProblem ? passwordProblem : null}
                    hint="At least 12 characters, three character classes."
                  />
                  <Field
                    label="Confirm password"
                    mono={false}
                    type="password"
                    value={confirm}
                    autoComplete="new-password"
                    onChange={(event) => setConfirm(event.target.value)}
                  />
                </div>
              </Card>
            ) : null}

            {step === 1 ? (
              <Card className="mb-5 p-6">
                <div className="text-[15.5px] font-semibold">Cluster basics</div>
                <div className="mt-1 mb-5 text-[13.5px] text-ink-2">
                  Written to the control plane on first boot. All of it is editable later in
                  Settings.
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field
                    label="Cluster name"
                    value={clusterName}
                    onChange={(event) => setClusterName(event.target.value)}
                    hint={slugify(clusterName) || 'lower-case, hyphens'}
                  />
                  <Field
                    label="Ingress domain"
                    value={ingressDomain}
                    placeholder="localhost"
                    onChange={(event) => setIngressDomain(event.target.value)}
                    hint={`functions resolve at ${(ingressDomain || 'localhost').replace(/^\*\./, '')}/<namespace>/<function>`}
                  />
                  <Field
                    label="Data directory"
                    value={dataDir}
                    onChange={(event) => setDataDir(event.target.value)}
                  />
                  <div>
                    <span className="mb-1.5 block text-[12.5px] text-ink-2">
                      Secrets backend
                    </span>
                    <div className="flex flex-wrap gap-2">
                      {KMS_OPTIONS.map((option) => (
                        <Chip
                          key={option.value}
                          active={kms === option.value}
                          title={option.hint}
                          onClick={() => setKms(option.value)}
                        >
                          {option.label}
                        </Chip>
                      ))}
                    </div>
                    <div className="mt-2 text-xs text-ink-3">
                      {KMS_OPTIONS.find((option) => option.value === kms)?.hint}
                    </div>
                  </div>
                </div>
              </Card>
            ) : null}

            {step === 2 ? (
              <Card className="mb-4 overflow-hidden">
                <div className="px-6 pt-5 pb-4">
                  <div className="text-[15.5px] font-semibold">Nodes</div>
                  <div className="mt-1 text-[13.5px] text-ink-2">
                    A node is a Docker engine Cubicle may schedule isolates onto. The engine
                    this control plane runs on is detected automatically — a single-node cluster
                    is perfectly valid. More engines can be added later in Settings.
                  </div>
                </div>

                {nodesError ? (
                  <div className="mx-6 mb-5 rounded-[10px] border border-err bg-err-bg px-4 py-3 text-[13px]">
                    {(nodesError as Error).message}
                  </div>
                ) : null}

                <div className="grid grid-cols-[auto_1.4fr_1.6fr_0.8fr] gap-3.5 border-y border-line px-6 py-3 text-[11px] font-bold tracking-[0.05em] text-ink-3 uppercase">
                  <span className="w-[18px]" />
                  <span>Node</span>
                  <span>Capacity</span>
                  <span>Status</span>
                </div>

                {nodesLoading ? (
                  <div className="px-6 py-6 text-[13px] text-ink-2">
                    <Spinner size={14} /> Detecting engines…
                  </div>
                ) : (
                  (nodes ?? []).map((node) => {
                    const on = selected.includes(node.name)
                    return (
                      <button
                        key={node.name}
                        type="button"
                        onClick={() =>
                          setSelected((current) =>
                            on
                              ? current.length === 1
                                ? current
                                : current.filter((name) => name !== node.name)
                              : [...current, node.name],
                          )
                        }
                        className="grid w-full grid-cols-[auto_1.4fr_1.6fr_0.8fr] items-center gap-3.5 border-b border-line px-6 py-3.5 text-left text-[13.5px] transition hover:bg-panel-2"
                      >
                        <span
                          className={cx(
                            'grid h-[18px] w-[18px] place-items-center rounded-[5px] border',
                            on
                              ? 'border-accent bg-accent text-accent-ink'
                              : 'border-line-strong',
                          )}
                        >
                          {on ? <Check size={11} /> : null}
                        </span>
                        <span className="font-mono font-semibold">{node.name}</span>
                        <span className="font-mono text-[12.5px] text-ink-2">{node.spec}</span>
                        <span className="flex items-center gap-1.5 text-[12.5px] text-ink-2">
                          <span className="h-[7px] w-[7px] rounded-full bg-ok" />
                          {node.status}
                        </span>
                      </button>
                    )
                  })
                )}

                <div className="px-6 py-3 text-[13px] text-ink-3">
                  {selected.length} selected · isolates are scheduled only onto selected nodes
                </div>
              </Card>
            ) : null}

            {step === 3 ? (
              <Card className="mb-5 overflow-hidden">
                <div className="border-b border-line px-6 pt-5 pb-4">
                  <div className="text-[15.5px] font-semibold">Review</div>
                  <div className="mt-1 text-[13.5px] text-ink-2">
                    Creating the cluster writes state to disk and starts the scheduler. Nothing
                    leaves your network.
                  </div>
                </div>
                {[
                  ['Administrator', `${adminName} · ${adminEmail}`],
                  ['Cluster name', slugify(clusterName)],
                  ['Ingress domain', ingressDomain || 'localhost'],
                  ['Data directory', dataDir],
                  ['Secrets backend', kms],
                  ['Nodes', selected.join(' · ') || '—'],
                  ['Runtimes', 'python3.12 · python3.11'],
                ].map(([key, value]) => (
                  <div
                    key={key}
                    className="grid grid-cols-[minmax(140px,200px)_minmax(0,1fr)] gap-4 border-b border-line px-6 py-3 text-[13.5px]"
                  >
                    <span className="text-ink-2">{key}</span>
                    <span className="truncate font-mono">{value}</span>
                  </div>
                ))}
              </Card>
            ) : null}

            {error ? (
              <div className="mb-4 rounded-[10px] border border-err bg-err-bg px-4 py-3 text-[13px]">
                {error}
              </div>
            ) : null}

            <div className="flex items-center justify-between gap-3">
              <Button
                variant="ghost"
                size="lg"
                onClick={() => setStep((s) => Math.max(0, s - 1))}
                style={{ visibility: step > 0 ? 'visible' : 'hidden' }}
              >
                Back
              </Button>
              {step < STEPS.length - 1 ? (
                <Button
                  variant="primary"
                  size="lg"
                  disabled={!stepValid}
                  onClick={() => setStep((s) => s + 1)}
                >
                  Continue
                </Button>
              ) : (
                <Button
                  variant="primary"
                  size="lg"
                  loading={submitting}
                  onClick={submit}
                  icon={<Bolt size={15} />}
                >
                  Create cluster
                </Button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function Provisioning({
  steps,
  complete,
  failed,
  clusterName,
  nodeCount,
  cliToken,
  onFinish,
}: {
  steps: ProvisionStep[]
  complete: boolean
  failed: boolean
  clusterName: string
  nodeCount: number
  cliToken: string | null
  onFinish: () => void
}) {
  return (
    <>
      <h1 className="m-0 mb-2 text-[32px] font-semibold tracking-[-0.03em]">
        {complete ? 'Cluster created' : 'Creating cluster…'}
      </h1>
      <p className="m-0 mb-8 text-base leading-relaxed text-ink-2">
        {complete
          ? 'The scheduler is accepting work. Deploy a function whenever you are ready.'
          : 'Bootstrapping the control plane on your hardware. This usually takes under a minute.'}
      </p>

      <Card className="mb-6 overflow-hidden">
        {(steps.length ? steps : PLACEHOLDER).map((step) => (
          <div
            key={step.id}
            className="flex items-center gap-3.5 border-b border-line px-5 py-4 last:border-b-0"
          >
            <span
              className={cx(
                'grid h-5 w-5 flex-none place-items-center rounded-full text-[11px] font-bold',
                step.status === 'done'
                  ? 'bg-accent text-accent-ink'
                  : step.status === 'failed'
                    ? 'border-2 border-err text-err'
                    : step.status === 'running'
                      ? 'animate-pulse-dot border-2 border-accent'
                      : 'border border-line-strong',
              )}
            >
              {step.status === 'done' ? <Check size={11} /> : null}
            </span>
            <span
              className={cx(
                'flex-1 text-[13.5px]',
                step.status === 'pending' ? 'text-ink-3' : 'text-ink',
              )}
            >
              {step.label}
            </span>
            <span
              className={cx(
                'font-mono text-xs',
                step.status === 'failed' ? 'text-err' : 'text-ink-3',
              )}
            >
              {step.status === 'running' ? 'running' : step.meta}
            </span>
          </div>
        ))}
      </Card>

      {cliToken ? (
        <div className="mb-6">
          <div className="mb-2 flex items-center gap-2 text-[13.5px] font-semibold">
            <Info size={15} /> Your CLI token — shown once
          </div>
          <CodeBlock filename="~/.cubicle/config.toml" copyValue={cliToken}>
            {cliToken}
          </CodeBlock>
          <div className="mt-2 text-xs text-ink-3">
            Use it with <span className="font-mono">cubicle login</span>. You can always create
            another in Settings → API keys. <CopyButton value={cliToken} label="Copy token" />
          </div>
        </div>
      ) : null}

      {complete ? (
        <div
          className={cx(
            'flex flex-wrap items-center gap-4 rounded-xl border px-5 py-4',
            failed ? 'border-warn bg-warn-bg' : 'border-accent bg-accent-soft',
          )}
        >
          <div className="min-w-0 flex-1">
            <div className="mb-1 text-[14.5px] font-semibold">
              {failed ? `${clusterName} is up, with one warning` : `${clusterName} is ready`}
            </div>
            <div className="font-mono text-[13px] text-ink-2">
              {nodeCount} node{nodeCount === 1 ? '' : 's'} · scheduler warm
              {failed ? ' · check the failed step above' : ''}
            </div>
          </div>
          <Button variant="primary" onClick={onFinish}>
            Open console
          </Button>
        </div>
      ) : null}
    </>
  )
}

const PLACEHOLDER: ProvisionStep[] = [
  {
    id: 'keys',
    label: 'Generating cluster keys and the CLI deploy token',
    meta: '',
    status: 'running',
  },
  { id: 'control', label: 'Writing control plane configuration', meta: '', status: 'pending' },
  { id: 'nodes', label: 'Registering nodes', meta: '', status: 'pending' },
  { id: 'ingress', label: 'Configuring ingress and routing', meta: '', status: 'pending' },
  { id: 'runtimes', label: 'Warming runtime snapshots', meta: '', status: 'pending' },
]
