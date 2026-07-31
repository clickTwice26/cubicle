import { Link, useNavigate } from 'react-router-dom'
import { Logo, ThemeToggle } from '../components/Layout'
import { ArrowRight, Bolt, Github, Lock, Meter } from '../components/Icons'
import { Button, Card } from '../components/ui'
import { useSetupStatus } from '../lib/hooks'

const RUNTIME_TAGS = ['Docker', 'Docker Compose', 'systemd', 'Bare metal', 'Air-gapped']

const FEATURES = [
  {
    icon: Bolt,
    title: 'Warm isolates, scale to zero',
    body: 'Each function version runs in its own container, kept warm between requests and reclaimed when it goes idle. Warm invocations are a local HTTP hop; an idle function costs nothing but a database row.',
  },
  {
    icon: Lock,
    title: 'Envelope-encrypted secrets',
    body: 'Every secret gets its own data key, wrapped by a root key that never leaves your machine. The database only ever holds sealed material, and values are injected per invocation — never written to disk.',
  },
  {
    icon: Meter,
    title: 'Per-invocation metering',
    body: 'Every invocation is timed, attributed to a namespace and written down. Export to Prometheus for internal chargeback. No external billing pipe, because there is no bill.',
  },
]

const INSTALLS = [
  {
    title: 'One command',
    subtitle: 'Local, batteries included',
    code: '$ git clone …/cubicle && cd cubicle\n$ ./install.sh',
    note: 'Console at localhost:7000',
  },
  {
    title: 'With a domain',
    subtitle: 'Automatic HTTPS on first boot',
    code: '$ ./install.sh \\\n    --domain fn.example.com \\\n    --email ops@example.com',
    note: 'Certificate issued and renewed for you',
  },
  {
    title: 'Compose',
    subtitle: 'Drop into existing infrastructure',
    code: '$ docker compose up -d\n$ docker compose logs -f api',
    note: 'Five containers, one network, no agents',
  },
]

const STATS = [
  { value: 'Apache-2.0', label: 'Permissive license' },
  { value: '3.12 · 3.11', label: 'Python runtimes' },
  { value: '1', label: 'Command to install' },
  { value: '0', label: 'Telemetry calls home' },
]

export default function Landing() {
  const navigate = useNavigate()
  const { data: status } = useSetupStatus()

  const enter = () => navigate(status?.setup_complete ? '/console' : '/setup')

  return (
    <div className="max-w-full overflow-hidden">
      <div className="sticky top-0 z-20 border-b border-line backdrop-blur-[12px] [background:color-mix(in_srgb,var(--bg)_82%,transparent)]">
        <div className="mx-auto flex h-16 max-w-[1180px] items-center justify-between px-6 sm:px-8">
          <div className="flex items-center gap-9">
            <Logo />
            <div className="hidden gap-6 text-sm text-ink-2 md:flex">
              <Link to="/docs" className="transition hover:text-ink">
                Docs
              </Link>
              <Link to="/docs/functions" className="transition hover:text-ink">
                Runtimes
              </Link>
              <Link to="/docs/install" className="transition hover:text-ink">
                Self-hosting
              </Link>
              <Link to="/docs/cli" className="transition hover:text-ink">
                CLI
              </Link>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <ThemeToggle className="h-[34px] w-[34px]" />
            <span className="hidden h-[34px] items-center gap-2 rounded-lg border border-line px-3 text-[13px] text-ink-2 sm:flex">
              <Github size={14} />
              <span className="font-mono">Apache-2.0</span>
            </span>
            <Button variant="primary" onClick={enter} className="h-9 px-4 text-[13.5px]">
              {status?.setup_complete ? 'Open console' : 'Start setup'}
            </Button>
          </div>
        </div>
      </div>

      <section className="mx-auto max-w-[1180px] px-6 pt-16 pb-10 text-center sm:px-8 sm:pt-24">
        <div className="mb-7 inline-flex items-center gap-2 rounded-full border border-line px-3.5 py-1.5 text-[12.5px] text-ink-2">
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-ok" />v
          {status?.version ?? '1.0.0'} · Apache-2.0 · no vendor, no bill
        </div>
        <h1 className="mx-auto max-w-[820px] text-[clamp(2.5rem,7vw,3.75rem)] leading-[1.03] font-bold tracking-[-0.035em] text-balance">
          Serverless.
          <br />
          On your own metal.
        </h1>
        <p className="mx-auto mt-5 max-w-[620px] text-[19px] leading-[1.55] text-ink-2 text-pretty">
          Cubicle is an open-source functions platform you run yourself. Your hardware, your
          data, no account anywhere. Python 3.12 and 3.11, warm isolates with scale-to-zero, and
          per-invocation metering that stays inside your network.
        </p>
        <div className="mt-8 flex flex-wrap justify-center gap-3">
          <Button variant="primary" size="lg" onClick={enter} icon={<ArrowRight size={16} />}>
            {status?.setup_complete ? 'Open the console' : 'Set up this instance'}
          </Button>
          <Link to="/docs/install">
            <Button variant="secondary" size="lg">
              Read the install guide
            </Button>
          </Link>
        </div>

        <Card className="mx-auto mt-14 max-w-[760px] overflow-hidden text-left shadow-card">
          <div className="flex items-center gap-2.5 border-b border-line px-4.5 py-3.5">
            <span className="h-2.5 w-2.5 rounded-full bg-[var(--border-strong)]" />
            <span className="h-2.5 w-2.5 rounded-full bg-[var(--border-strong)]" />
            <span className="h-2.5 w-2.5 rounded-full bg-[var(--border-strong)]" />
            <span className="ml-2 font-mono text-[12.5px] text-ink-3">handler.py</span>
            <span className="ml-auto font-mono text-xs text-ok">● deployed</span>
          </div>
          <pre className="m-0 overflow-x-auto px-5 py-5 font-mono text-[13.5px] leading-[1.75]">
            <span className="text-ink-3"># scheduled onto the node pool you chose</span>
            {'\n'}
            <span className="text-info">from</span> cubicle_context{' '}
            <span className="text-info">import</span> Request, Context, env{'\n'}
            {'\n'}
            <span className="text-info">def</span>{' '}
            <span className="rounded bg-accent-soft px-1 text-accent-ink">handler</span>(req:
            Request, ctx: Context):{'\n'}
            {'    '}body = req.json(){'\n'}
            {'    '}ctx.set(<span className="text-ok">"actor"</span>, body[
            <span className="text-ok">"user"</span>]){'\n'}
            {'    '}
            <span className="text-info">return</span> {'{'}
            <span className="text-ok">"ok"</span>: <span className="text-warn">True</span>
            {'}'}
          </pre>
          <div className="flex flex-wrap items-center gap-3.5 border-t border-line px-4.5 py-3 font-mono text-xs text-ink-2">
            <span>$ cubicle deploy</span>
            <span className="text-ink-3">→</span>
            <span className="text-ok">https://your-host/payments/create-charge</span>
          </div>
        </Card>

        <div className="mt-8 flex flex-wrap justify-center gap-2.5">
          {RUNTIME_TAGS.map((tag) => (
            <span
              key={tag}
              className="rounded-full border border-line px-3.5 py-1.5 text-[12.5px] text-ink-2"
            >
              {tag}
            </span>
          ))}
        </div>
      </section>

      <section className="mx-auto max-w-[1180px] px-6 py-16 sm:px-8">
        <div className="grid gap-5 md:grid-cols-3">
          {FEATURES.map(({ icon: Icon, title, body }) => (
            <Card key={title} className="p-6">
              <div className="mb-4 grid h-[38px] w-[38px] place-items-center rounded-[10px] bg-accent-soft text-ink">
                <Icon size={19} />
              </div>
              <h3 className="m-0 mb-2 text-[16.5px] tracking-[-0.01em]">{title}</h3>
              <p className="m-0 text-sm leading-relaxed text-ink-2">{body}</p>
            </Card>
          ))}
        </div>
      </section>

      <section className="mx-auto max-w-[1180px] px-6 pt-6 pb-12 sm:px-8">
        <h2 className="m-0 mb-2 text-center text-[34px] tracking-[-0.03em]">
          Free forever. Yours to run.
        </h2>
        <p className="mx-auto mb-10 max-w-[620px] text-center text-base text-ink-2 text-pretty">
          Apache-2.0, no open-core bait, no seat limits. Everything ships in this repository —
          the control plane, the console, the runtimes and the CLI.
        </p>

        <div className="mx-auto grid max-w-[1000px] gap-5 md:grid-cols-3">
          {INSTALLS.map((install) => (
            <Card key={install.title} className="flex min-w-0 flex-col gap-3.5 p-6">
              <div>
                <div className="text-[15.5px] font-semibold tracking-[-0.01em]">
                  {install.title}
                </div>
                <div className="mt-1 text-[13px] text-ink-2">{install.subtitle}</div>
              </div>
              <pre className="m-0 overflow-x-auto rounded-[10px] border border-line bg-bg px-3.5 py-3 font-mono text-[12.5px] leading-[1.7]">
                {install.code}
              </pre>
              <div className="mt-auto text-[12.5px] text-ink-3">{install.note}</div>
            </Card>
          ))}
        </div>

        <Card className="mx-auto mt-5 grid max-w-[1000px] grid-cols-2 gap-5 px-7 py-6 md:grid-cols-4">
          {STATS.map((stat) => (
            <div key={stat.label}>
              <div className="font-mono text-2xl font-semibold tracking-[-0.02em]">
                {stat.value}
              </div>
              <div className="mt-1.5 text-[12.5px] text-ink-2">{stat.label}</div>
            </div>
          ))}
        </Card>
      </section>

      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-[1180px] flex-wrap items-center justify-between gap-4 px-6 py-8 text-[13px] text-ink-3 sm:px-8">
          <div className="flex items-center gap-2.5 text-ink-2">
            <Logo size={22} label={false} />
            Cubicle — open source, Apache-2.0
          </div>
          <div className="flex gap-5">
            <Link to="/docs" className="transition hover:text-ink">
              Docs
            </Link>
            <Link to="/docs/cli" className="transition hover:text-ink">
              CLI
            </Link>
            <Link to="/docs/secrets" className="transition hover:text-ink">
              Security
            </Link>
          </div>
        </div>
      </footer>
    </div>
  )
}
