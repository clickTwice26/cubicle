import { Link, useNavigate } from 'react-router-dom'
import { Logo, ThemeToggle } from '../components/Layout'
import {
  ArrowRight,
  Bars,
  Bolt,
  Database,
  Github,
  Globe,
  Layers,
  Lines,
  Lock,
  Meter,
  Server,
  Table,
  Terminal,
} from '../components/Icons'
import { Button, Card } from '../components/ui'
import { Reveal } from '../components/landing/Motion'
import { FlowStrip } from '../components/landing/FlowStrip'
import { useSetupStatus } from '../lib/hooks'

const RUNTIME_TAGS = ['Docker', 'Docker Compose', 'Bare metal', 'Air-gapped', 'arm64 · amd64']

const FEATURES = [
  {
    icon: Bolt,
    title: 'Warm isolates, scale to zero',
    body: 'Every function version runs in its own container, kept warm between requests and reclaimed when demand drops. A warm invocation is a local HTTP hop; an idle function costs nothing but a database row.',
  },
  {
    icon: Meter,
    title: 'Concurrency you control',
    body: 'One request per isolate, so a handler never races itself. Set the ceiling per function and a busy endpoint can never take the whole node — past the limit requests wait for a free isolate instead of starting another container.',
  },
  {
    icon: Layers,
    title: 'Clusters that share nothing',
    body: 'Production and staging on one machine, with separate namespaces, configuration, data services, nodes and metrics. Two clusters can both own a payments namespace and a DATABASE_URL without colliding.',
  },
  {
    icon: Bars,
    title: 'Live activity, actually live',
    body: 'A streaming dashboard that animates the runtime as it works: requests crossing the edge, isolates booting, the pool widening under load and narrowing again. Not a poll that happens to land nearby.',
  },
  {
    icon: Database,
    title: 'PostgreSQL and Redis, managed',
    body: 'Provision either one per cluster and it is wired into every function — no connection string to copy. Browse and edit the data from the console, with a SQL console when the grid is not enough.',
  },
  {
    icon: Lock,
    title: 'Envelope-encrypted secrets',
    body: 'Every secret gets its own data key, wrapped by a root key that never leaves your machine. The database only ever holds sealed material, and values reach the isolate in memory — never on its disk, never in a log.',
  },
  {
    icon: Server,
    title: 'Atomic deploys',
    body: 'A deploy builds into a fresh volume and only takes over once it succeeds. A failed build leaves the running version serving, so a bad requirements.txt is an error message rather than an outage.',
  },
  {
    icon: Globe,
    title: 'HTTPS on first boot',
    body: 'Give the installer a domain and Caddy obtains and renews the certificate itself. No reverse proxy to configure, no cron job to forget, nothing to renew by hand.',
  },
]

const CONSOLE = [
  {
    icon: Bars,
    title: 'Live activity',
    body: 'Requests and isolates, animated as they happen.',
  },
  {
    icon: Terminal,
    title: 'Playground',
    body: 'Editor, request runner and settings per function.',
  },
  { icon: Globe, title: 'Global env', body: 'Cluster-wide values, resolved at invocation.' },
  {
    icon: Lines,
    title: 'Logs',
    body: 'Filtered, paginated, tailing live from the newest page.',
  },
  {
    icon: Meter,
    title: 'Metering',
    body: 'GB-seconds per namespace, and a Prometheus endpoint.',
  },
  {
    icon: Table,
    title: 'Data browser',
    body: 'Rows, structure and SQL against managed Postgres.',
  },
]

const STEPS = [
  {
    n: '01',
    title: 'Install',
    body: 'One command builds the images, generates every secret and starts five containers. No account, no licence check, nothing phoning home.',
  },
  {
    n: '02',
    title: 'Write',
    body: 'A function is a handler, a requirements file and a resource envelope. Edit it in the console or deploy a directory from your terminal.',
  },
  {
    n: '03',
    title: 'Deploy',
    body: 'The source is built into an immutable version on its own volume. The running version keeps serving until the new one is ready.',
  },
  {
    n: '04',
    title: 'Watch',
    body: 'Every invocation is timed, attributed and recorded. Watch it live, tail the logs, or scrape the metrics into whatever you already run.',
  },
]

const INSTALLS = [
  {
    title: 'One command',
    subtitle: 'Local, batteries included',
    code: '$ git clone …/cubicle && cd cubicle\n$ ./install.sh',
    note: 'Finds a free port and prints it',
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
    note: 'Five containers, three networks, no agents',
  },
]

export default function Landing() {
  const navigate = useNavigate()
  const { data: status } = useSetupStatus()

  const enter = () => navigate(status?.setup_complete ? '/console' : '/setup')
  const cta = status?.setup_complete ? 'Open the console' : 'Set up this instance'

  return (
    <div className="max-w-full overflow-hidden">
      <header className="sticky top-0 z-20 border-b border-line backdrop-blur-[12px] [background:color-mix(in_srgb,var(--bg)_82%,transparent)]">
        <div className="mx-auto flex h-16 max-w-[1180px] items-center justify-between px-6 sm:px-8">
          <div className="flex items-center gap-9">
            <Logo />
            <nav className="flex gap-6 text-sm text-ink-2">
              <Link to="/docs" className="transition hover:text-ink">
                Docs
              </Link>
            </nav>
          </div>
          <div className="flex items-center gap-3">
            <ThemeToggle className="h-[34px] w-[34px]" />
            <a
              href="https://github.com/clickTwice26/cubicle"
              target="_blank"
              rel="noreferrer"
              className="hidden h-[34px] items-center gap-2 rounded-lg border border-line px-3 text-[13px] text-ink-2 transition hover:text-ink sm:flex"
            >
              <Github size={14} />
              <span className="font-mono">Apache-2.0</span>
            </a>
            <Button variant="primary" onClick={enter} className="h-9 px-4 text-[13.5px]">
              {status?.setup_complete ? 'Open console' : 'Start setup'}
            </Button>
          </div>
        </div>
      </header>

      {/* ── hero ─────────────────────────────────────────────────────────── */}
      <section className="relative mx-auto max-w-[1180px] px-5 pt-12 pb-12 text-center sm:px-8 sm:pt-24">
        {/* Ambient wash behind the headline. Decorative, so it drifts slowly
            and disappears entirely under prefers-reduced-motion. */}
        <div
          aria-hidden
          className="animate-drift pointer-events-none absolute top-[-18%] left-1/2 -z-10 h-[520px] w-[820px] max-w-[130vw] -translate-x-1/2 rounded-full opacity-[0.22] blur-[90px]"
          style={{
            background: 'radial-gradient(closest-side, var(--accent), transparent 72%)',
          }}
        />

        <Reveal>

          <h1 className="mx-auto max-w-[840px] text-[clamp(2.05rem,7vw,3.9rem)] leading-[1.03] font-bold tracking-[-0.035em] text-balance">
            Serverless.
            <br />
            On your own metal.
          </h1>
          <p className="mx-auto mt-5 max-w-[660px] text-[16.5px] leading-[1.55] text-ink-2 text-pretty sm:text-[19px]">
            Cubicle is an open-source functions platform you run yourself. Python 3.12 and 3.11,
            warm isolates with scale-to-zero, managed Postgres and Redis, several isolated
            clusters on one machine — and a live view of all of it. Your hardware, your data, no
            account anywhere.
          </p>
          {/* Stacked and full width on a phone: a thumb should not have to
              aim at a centred pill. Side by side from sm up. */}
          <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:justify-center">
            <Button
              variant="primary"
              size="lg"
              onClick={enter}
              icon={<ArrowRight size={16} />}
              className="w-full justify-center sm:w-auto"
            >
              {cta}
            </Button>
            <Link to="/docs/install" className="w-full sm:w-auto">
              <Button variant="secondary" size="lg" className="w-full justify-center sm:w-auto">
                Read the install guide
              </Button>
            </Link>
          </div>
        </Reveal>

        <Reveal delay={120} className="mx-auto mt-14 max-w-[880px]">
          <FlowStrip />
        </Reveal>

        <Reveal delay={200}>
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
        </Reveal>
      </section>

      {/* ── the function ─────────────────────────────────────────────────── */}
      <section className="mx-auto max-w-[1180px] px-5 py-10 sm:px-8">
        <div className="grid grid-cols-1 items-center gap-8 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
          <Reveal>
            <h2 className="m-0 text-[clamp(1.75rem,3.4vw,2.3rem)] tracking-[-0.03em] text-balance">
              A function is a handler and an envelope.
            </h2>
            <p className="mt-4 mb-0 text-[16px] leading-[1.7] text-ink-2 text-pretty">
              Export one callable. It receives the request and a session context shared across
              the namespace, and returns anything JSON-serialisable. Memory, timeout,
              concurrency and context access are settings on the function, not decisions baked
              into your code.
            </p>
            <ul className="mt-5 mb-0 grid gap-2.5 p-0 text-[14.5px] text-ink-2">
              {[
                'Global env resolves at invocation — change a value, no redeploy',
                'Managed Postgres and Redis handed to the isolate per request',
                'Read-only root filesystem, all capabilities dropped, unprivileged',
                'X-Cubicle-Cold-Start tells you which kind of invocation you got',
              ].map((line) => (
                <li key={line} className="flex items-start gap-2.5 list-none">
                  <span className="mt-[7px] h-1.5 w-1.5 flex-none rounded-full bg-accent" />
                  {line}
                </li>
              ))}
            </ul>
          </Reveal>

          <Reveal delay={120}>
            <Card className="overflow-hidden text-left shadow-card">
              <div className="flex items-center gap-2.5 border-b border-line px-4.5 py-3.5">
                <span className="h-2.5 w-2.5 rounded-full bg-[var(--border-strong)]" />
                <span className="h-2.5 w-2.5 rounded-full bg-[var(--border-strong)]" />
                <span className="h-2.5 w-2.5 rounded-full bg-[var(--border-strong)]" />
                <span className="ml-2 font-mono text-[12.5px] text-ink-3">handler.py</span>
                <span className="ml-auto font-mono text-xs text-ok">● deployed</span>
              </div>
              <pre className="m-0 overflow-x-auto px-5 py-5 font-mono text-[13.5px] leading-[1.75]">
                <span className="text-info">from</span> cubicle_context{' '}
                <span className="text-info">import</span> Request, Context, env{'\n'}
                <span className="text-info">from</span> cubicle_db{' '}
                <span className="text-info">import</span> postgres{'\n'}
                {'\n'}
                <span className="text-info">def</span>{' '}
                <span className="rounded bg-accent-soft px-1 text-accent-ink">handler</span>
                (req: Request, ctx: Context):{'\n'}
                {'    '}body = req.json(){'\n'}
                {'    '}ctx.set(<span className="text-ok">&quot;actor&quot;</span>, body[
                <span className="text-ok">&quot;user&quot;</span>]){'\n'}
                {'\n'}
                {'    '}
                <span className="text-info">with</span> postgres.session(){' '}
                <span className="text-info">as</span> db:{'\n'}
                {'        '}db.execute({'\n'}
                {'            '}
                <span className="text-ok">
                  &quot;insert into charges (amount) values (:amount)&quot;
                </span>
                ,{'\n'}
                {'            '}amount=body[<span className="text-ok">&quot;amount&quot;</span>
                ],
                {'\n'}
                {'        '}){'\n'}
                {'\n'}
                {'    '}
                <span className="text-info">return</span> {'{'}
                <span className="text-ok">&quot;ok&quot;</span>:{' '}
                <span className="text-warn">True</span>
                {'}'}
              </pre>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-line px-4.5 py-3 font-mono text-[11px] break-all text-ink-2 sm:text-xs">
                <span>$ cubicle deploy</span>
                <span className="text-ink-3">→</span>
                <span className="min-w-0 break-all text-ok">
                  built v4 · https://your-host/prod/payments/create-charge
                </span>
                <span className="animate-blink ml-auto text-accent">▍</span>
              </div>
            </Card>
          </Reveal>
        </div>
      </section>

      {/* ── features ─────────────────────────────────────────────────────── */}
      <section className="mx-auto max-w-[1180px] px-5 py-16 sm:px-8">
        <Reveal>
          <h2 className="m-0 mb-2 text-center text-[clamp(1.9rem,4vw,2.4rem)] tracking-[-0.03em]">
            Everything a platform needs, nothing it does not.
          </h2>
          <p className="mx-auto mb-10 max-w-[640px] text-center text-[16px] text-ink-2 text-pretty">
            Not a demo you outgrow. Isolation, scheduling, storage, secrets, observability and
            multi-tenancy — all of it in the repository, all of it running on your own machine.
          </p>
        </Reveal>

        <div className="grid grid-cols-1 gap-5 md:grid-cols-2 lg:grid-cols-4">
          {FEATURES.map(({ icon: Icon, title, body }, index) => (
            <Reveal key={title} delay={(index % 4) * 80}>
              <Card className="h-full p-6 transition-transform duration-300 hover:-translate-y-1">
                <div className="mb-4 grid h-[38px] w-[38px] place-items-center rounded-[10px] bg-accent-soft text-ink">
                  <Icon size={19} />
                </div>
                <h3 className="m-0 mb-2 text-[16px] tracking-[-0.01em]">{title}</h3>
                <p className="m-0 text-[13.5px] leading-relaxed text-ink-2">{body}</p>
              </Card>
            </Reveal>
          ))}
        </div>
      </section>

      {/* ── the console ──────────────────────────────────────────────────── */}
      <section className="border-y border-line bg-panel-2">
        <div className="mx-auto max-w-[1180px] px-5 py-16 sm:px-8">
          <Reveal>
            <h2 className="m-0 mb-2 text-[clamp(1.75rem,3.4vw,2.2rem)] tracking-[-0.03em]">
              A console you would actually use.
            </h2>
            <p className="mb-10 max-w-[620px] text-[16px] text-ink-2 text-pretty">
              Every screen is a client of the same HTTP API you have. Nothing in the console is
              privileged, and nothing is only available there.
            </p>
          </Reveal>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {CONSOLE.map(({ icon: Icon, title, body }, index) => (
              <Reveal key={title} delay={(index % 3) * 80}>
                <div className="flex h-full items-start gap-3.5 rounded-xl border border-line bg-panel px-4.5 py-4">
                  <span className="mt-0.5 grid h-[30px] w-[30px] flex-none place-items-center rounded-[9px] bg-accent-soft">
                    <Icon size={15} />
                  </span>
                  <div className="min-w-0">
                    <div className="text-[14.5px] font-semibold">{title}</div>
                    <div className="mt-1 text-[13px] leading-relaxed text-ink-2">{body}</div>
                  </div>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ── how it works ─────────────────────────────────────────────────── */}
      <section className="mx-auto max-w-[1180px] px-5 py-16 sm:px-8">
        <Reveal>
          <h2 className="m-0 mb-10 text-center text-[clamp(1.75rem,3.4vw,2.2rem)] tracking-[-0.03em]">
            Four steps, then it is running.
          </h2>
        </Reveal>
        <div className="grid grid-cols-1 gap-5 md:grid-cols-2 lg:grid-cols-4">
          {STEPS.map((step, index) => (
            <Reveal key={step.n} delay={index * 90}>
              <div className="relative h-full rounded-xl border border-line bg-panel p-6">
                <span className="font-mono text-[13px] font-bold text-accent">{step.n}</span>
                <h3 className="mt-2.5 mb-2 text-[16.5px] tracking-[-0.01em]">{step.title}</h3>
                <p className="m-0 text-[13.5px] leading-relaxed text-ink-2">{step.body}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </section>

      {/* ── install ──────────────────────────────────────────────────────── */}
      <section className="mx-auto max-w-[1180px] px-5 pt-6 pb-12 sm:px-8">
        <Reveal>
          <h2 className="m-0 mb-2 text-center text-[clamp(1.9rem,4vw,2.4rem)] tracking-[-0.03em]">
            Free forever. Yours to run.
          </h2>
          <p className="mx-auto mb-10 max-w-[620px] text-center text-base text-ink-2 text-pretty">
            Apache-2.0, no open-core bait, no seat limits. Everything ships in this repository —
            the control plane, the console, the runtimes, the CLI and the docs.
          </p>
        </Reveal>

        <div className="mx-auto grid max-w-[1000px] grid-cols-1 gap-5 md:grid-cols-3">
          {INSTALLS.map((install, index) => (
            <Reveal key={install.title} delay={index * 90}>
              <Card className="flex h-full min-w-0 flex-col gap-3.5 p-6">
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
            </Reveal>
          ))}
        </div>

        <Reveal delay={120}>
          <Comparison />
        </Reveal>
      </section>

      {/* ── closing ──────────────────────────────────────────────────────── */}
      <section className="mx-auto max-w-[1180px] px-5 pb-20 sm:px-8">
        <Reveal>
          <Card className="relative overflow-hidden px-7 py-12 text-center">
            <div
              aria-hidden
              className="animate-drift pointer-events-none absolute top-[-60%] left-1/2 h-[300px] w-[600px] max-w-[120vw] -translate-x-1/2 rounded-full opacity-[0.18] blur-[70px]"
              style={{
                background: 'radial-gradient(closest-side, var(--accent), transparent 70%)',
              }}
            />
            <h2 className="relative m-0 text-[clamp(1.6rem,3.2vw,2.1rem)] tracking-[-0.03em]">
              Run it in the next five minutes.
            </h2>
            <p className="relative mx-auto mt-3 mb-7 max-w-[520px] text-[15.5px] text-ink-2 text-pretty">
              One command, five containers, and a console waiting on a port it picked for you.
            </p>
            <div className="relative flex flex-wrap justify-center gap-3">
              <Button
                variant="primary"
                size="lg"
                onClick={enter}
                icon={<ArrowRight size={16} />}
              >
                {cta}
              </Button>
              <Link to="/docs">
                <Button variant="secondary" size="lg">
                  Browse the docs
                </Button>
              </Link>
            </div>
          </Card>
        </Reveal>
      </section>

      <footer className="border-t border-line">
        <div className="mx-auto grid max-w-[1180px] gap-8 px-6 py-10 sm:px-8 md:grid-cols-[1.4fr_1fr_1fr_1fr]">
          <div>
            <Logo size={22} />
            <p className="mt-3 mb-0 max-w-[280px] text-[13px] leading-relaxed text-ink-3">
              An open-source functions platform for hardware you own. Apache-2.0.
            </p>
          </div>
          <FooterColumn
            title="Start"
            links={[
              ['Installation', '/docs/install'],
              ['Quickstart', '/docs/quickstart'],
              ['Writing functions', '/docs/functions'],
            ]}
          />
          <FooterColumn
            title="Operate"
            links={[
              ['Scaling', '/docs/scaling'],
              ['Observability', '/docs/observability'],
              ['Clusters', '/docs/clusters'],
              ['Troubleshooting', '/docs/troubleshooting'],
            ]}
          />
          <FooterColumn
            title="Reference"
            links={[
              ['CLI', '/docs/cli'],
              ['cubicle.toml', '/docs/config'],
              ['Access & API keys', '/docs/access'],
              ['Env & secrets', '/docs/secrets'],
            ]}
          />
        </div>
        <div className="border-t border-line">
          <div className="mx-auto max-w-[1180px] px-5 py-5 text-[12.5px] text-ink-3 sm:px-8">
            Cubicle — self-hosted, no telemetry, no account.
          </div>
        </div>
      </footer>
    </div>
  )
}

/**
 * Cubicle against the managed platforms.
 *
 * Every row is a structural difference that does not move with a price list —
 * where the code runs, who holds the data, whether you can run it at all
 * without an account. No latency figures and no dollar amounts, because those
 * change monthly and a stale number is worse than none.
 *
 * The note underneath is deliberate: a comparison that claims to win on every
 * row is marketing, and nobody believes it.
 */
const RIVALS = ['AWS Lambda', 'Azure Functions', 'Google Cloud Run', 'DigitalOcean Functions']

const ROWS: { label: string; cubicle: string; rivals: string | string[] }[] = [
  {
    label: 'Runs on',
    cubicle: 'Hardware you own',
    rivals: ["Amazon's", "Microsoft's", "Google's", "DigitalOcean's"],
  },
  {
    label: 'What a request costs',
    cubicle: 'Nothing — it is your machine',
    rivals: 'Per request and GB-second',
  },
  { label: 'Where the data sits', cubicle: 'Your disk', rivals: 'A region you pick' },
  { label: 'Account needed', cubicle: 'None', rivals: 'Yes, with a card' },
  { label: 'Can you run it yourself', cubicle: 'That is the point', rivals: 'No' },
  { label: 'Works air-gapped', cubicle: 'Yes', rivals: 'No' },
  {
    label: 'Postgres and Redis',
    cubicle: 'In the same box, one click',
    rivals: 'A separate billable service',
  },
  { label: 'Licence', cubicle: 'Apache-2.0', rivals: 'Terms of service' },
]

function Comparison() {
  return (
    <Card className="mx-auto mt-5 max-w-[1000px] overflow-hidden">
      <div className="border-b border-line px-5 py-4 sm:px-7">
        <div className="text-[15.5px] font-semibold tracking-[-0.01em]">
          How that differs from the managed platforms
        </div>
        <div className="mt-1 text-[13px] text-ink-2">
          Structural differences only — no prices or latency numbers, because those go stale.
        </div>
      </div>

      {/* A five-column table cannot fit a phone, so it scrolls sideways and
          the label column stays put while it does. */}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] border-collapse text-left">
          <thead>
            <tr className="border-b border-line">
              <th className="sticky left-0 z-10 bg-panel px-5 py-3 text-[11.5px] font-bold tracking-[0.05em] text-ink-3 uppercase sm:px-7" />
              <th className="bg-accent-soft px-4 py-3 text-[13px] font-semibold whitespace-nowrap text-ink">
                Cubicle
              </th>
              {RIVALS.map((name) => (
                <th
                  key={name}
                  className="px-4 py-3 text-[12.5px] font-medium whitespace-nowrap text-ink-2"
                >
                  {name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ROWS.map((row) => {
              const cells = Array.isArray(row.rivals)
                ? row.rivals
                : RIVALS.map(() => row.rivals as string)
              return (
                <tr key={row.label} className="border-b border-line last:border-b-0">
                  <th
                    scope="row"
                    className="sticky left-0 z-10 bg-panel px-5 py-3 text-[13px] font-medium whitespace-nowrap text-ink-2 sm:px-7"
                  >
                    {row.label}
                  </th>
                  <td className="bg-accent-soft/50 px-4 py-3 text-[13px] font-semibold text-ink">
                    {row.cubicle}
                  </td>
                  {cells.map((value, index) => (
                    <td key={RIVALS[index]} className="px-4 py-3 text-[13px] text-ink-2">
                      {value}
                    </td>
                  ))}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div className="border-t border-line bg-panel-2 px-5 py-4 text-[13px] leading-relaxed text-ink-2 sm:px-7">
        <span className="font-semibold text-ink">What they do that Cubicle does not.</span> Edge
        locations on every continent, capacity you could not exhaust if you tried, and someone
        else awake when it breaks at 3am. If you need those, use them. Cubicle is for the case
        where you would rather own the machine.
      </div>
    </Card>
  )
}


function FooterColumn({ title, links }: { title: string; links: [string, string][] }) {
  return (
    <div>
      <div className="mb-3 text-[12px] font-bold tracking-[0.05em] text-ink-3 uppercase">
        {title}
      </div>
      <div className="grid gap-2 text-[13.5px] text-ink-2">
        {links.map(([label, href]) => (
          <Link
            key={href}
            to={href}
            className="-mx-2 rounded-md px-2 py-2 transition hover:bg-panel-2 hover:text-ink sm:mx-0 sm:px-0 sm:py-0.5 sm:hover:bg-transparent"
          >
            {label}
          </Link>
        ))}
      </div>
    </div>
  )
}
