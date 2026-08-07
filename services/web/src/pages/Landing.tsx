import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Logo, ThemeToggle } from '../components/Layout'
import { ArrowRight, Check, Copy, Github } from '../components/Icons'
import { Button, Card, cx } from '../components/ui'
import { Reveal } from '../components/landing/Motion'
import { FlowStrip } from '../components/landing/FlowStrip'
import { useSetupStatus } from '../lib/hooks'

/**
 * The landing page.
 *
 * Written as a spec sheet rather than a brochure. Every line is a fact with a
 * number or a name in it; where there is no number, the line is cut. Long
 * feature paragraphs read as filler to the audience for this — people who run
 * their own servers — and they are the first thing that makes a page look
 * generated.
 */

/** Hard facts, grouped. No adjectives that a benchmark could contradict. */
const SPEC: { group: string; rows: [string, string][] }[] = [
  {
    group: 'Runtime',
    rows: [
      ['Languages', 'Python 3.10–3.13, Node 18/20/22'],
      ['More of them', 'Built on the node when you install one, from Settings'],
      ['Isolation', 'One container per function version'],
      ['Concurrency', 'One request per container'],
      ['Smallest instance', '32 MB — the agent holds 18 of it'],
      ['Filesystem', 'Read-only, 64 MB tmpfs at /tmp'],
      ['Privileges', 'Unprivileged, all capabilities dropped'],
    ],
  },
  {
    group: 'Scheduling',
    rows: [
      ['Ceiling', 'Per function, and a hard cap per cluster above it'],
      ['At the ceiling', 'Requests queue, they do not fail'],
      ['Distribution', 'Least-used container takes the request'],
      ['Triggers', 'HTTP, or a cron schedule in any timezone'],
      ['Scale down', '60 s to shed a burst, then a kill time you set'],
      ['Idle cost', 'One database row'],
    ],
  },
  {
    group: 'Storage',
    rows: [
      ['Managed', 'PostgreSQL 16, Redis 7, per cluster'],
      ['Wiring', 'Injected per invocation, no connection string'],
      ['Browsing', 'Rows, structure and SQL in the console'],
      ['Secrets', 'AES-256-GCM, per-record data key'],
      ['Passwords', 'Argon2id'],
    ],
  },
  {
    group: 'Operations',
    rows: [
      ['Install', 'One command, 5 containers, 3 networks'],
      ['TLS', 'Let’s Encrypt on first boot, or your own proxy'],
      ['Upgrades', 'One press — it pulls the branch and rebuilds itself'],
      ['Metrics', 'Prometheus at /metrics'],
      ['Live view', 'Every request and container, streamed'],
      ['Drift', 'Scans what Docker has against what it believes'],
      ['Telemetry', 'None'],
    ],
  },
]

const INSTALL =
  'git clone https://github.com/clickTwice26/cubicle && cd cubicle && ./install.sh'

function CopyLine({ value }: { value: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      type="button"
      onClick={() => {
        void navigator.clipboard?.writeText(value)
        setCopied(true)
        window.setTimeout(() => setCopied(false), 1600)
      }}
      className="group flex w-full items-center gap-3 rounded-xl border border-line bg-panel px-4 py-3 text-left transition hover:border-line-strong"
    >
      <span className="flex-none font-mono text-[13px] text-ink-3 select-none">$</span>
      <span className="min-w-0 flex-1 truncate font-mono text-[13px] text-ink">{value}</span>
      <span
        className={cx(
          'flex-none transition',
          copied ? 'text-ok' : 'text-ink-3 group-hover:text-ink',
        )}
      >
        {copied ? <Check size={14} /> : <Copy size={14} />}
      </span>
    </button>
  )
}

export default function Landing() {
  const navigate = useNavigate()
  const { data: status } = useSetupStatus()

  const enter = () => navigate(status?.setup_complete ? '/console' : '/setup')

  return (
    <div className="max-w-full overflow-hidden">
      <header className="sticky top-0 z-20 border-b border-line backdrop-blur-[12px] [background:color-mix(in_srgb,var(--bg)_82%,transparent)]">
        <div className="mx-auto flex h-16 max-w-[1080px] items-center justify-between px-5 sm:px-8">
          <div className="flex items-center gap-8">
            <Logo />
            <Link to="/docs" className="text-sm text-ink-2 transition hover:text-ink">
              Docs
            </Link>
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
      <section className="mx-auto max-w-[1080px] px-5 pt-14 pb-10 sm:px-8 sm:pt-20">
        <Reveal>
          <h1 className="m-0 max-w-[760px] text-[clamp(2.1rem,6vw,3.4rem)] leading-[1.05] font-bold tracking-[-0.035em] text-balance">
            Python and JavaScript functions on a server you already own.
          </h1>
          <p className="mt-5 max-w-[560px] text-[17px] leading-[1.6] text-ink-2">
            Cubicle builds each function into its own container, keeps it warm between requests
            and reclaims it when traffic stops. No account, no bill, nothing leaves the machine.
          </p>

          <div className="mt-7 max-w-[640px]">
            <CopyLine value={INSTALL} />
          </div>

          <div className="mt-4 flex flex-col gap-2.5 sm:flex-row sm:items-center">
            <Button
              variant="primary"
              onClick={enter}
              icon={<ArrowRight size={15} />}
              className="w-full justify-center sm:w-auto"
            >
              {status?.setup_complete ? 'Open the console' : 'Set up this instance'}
            </Button>
            <Link to="/docs/install" className="w-full sm:w-auto">
              <Button variant="secondary" className="w-full justify-center sm:w-auto">
                Install guide
              </Button>
            </Link>
            <span className="mt-1 text-[12.5px] text-ink-3 sm:mt-0 sm:ml-2">
              Apache-2.0 · v{status?.version ?? '1.0.0'}
            </span>
          </div>
        </Reveal>
      </section>

      {/* ── the product, moving ──────────────────────────────────────────── */}
      <section className="mx-auto max-w-[1080px] px-5 pb-14 sm:px-8">
        <Reveal delay={80}>
          <FlowStrip />
        </Reveal>
      </section>

      {/* ── the handler ──────────────────────────────────────────────────── */}
      <section className="border-y border-line bg-panel-2">
        <div className="mx-auto grid max-w-[1080px] gap-8 px-5 py-14 sm:px-8 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)] lg:items-center">
          <Reveal>
            <h2 className="m-0 text-[clamp(1.5rem,3vw,1.9rem)] tracking-[-0.03em]">
              One file, one callable.
            </h2>
            <p className="mt-3.5 mb-0 text-[15px] leading-[1.7] text-ink-2">
              Memory, timeout and concurrency are settings on the function, not decisions in
              your code. Postgres and Redis arrive with the request.
            </p>
            <div className="mt-5 grid gap-1.5 font-mono text-[12.5px] text-ink-3">
              <span>handler.py</span>
              <span>requirements.txt</span>
              <span>cubicle.toml</span>
            </div>
          </Reveal>

          <Reveal delay={100}>
            <Card className="overflow-hidden shadow-card">
              <div className="flex items-center gap-2 border-b border-line px-4 py-2.5 font-mono text-[11.5px] text-ink-3">
                handler.py
                <span className="ml-auto text-ok">deployed · v4</span>
              </div>
              <pre className="m-0 overflow-x-auto px-4 py-4 font-mono text-[12.5px] leading-[1.8]">
                <span className="text-info">from</span> cubicle_context{' '}
                <span className="text-info">import</span> Request, Context{'\n'}
                <span className="text-info">from</span> cubicle_db{' '}
                <span className="text-info">import</span> postgres{'\n\n'}
                <span className="text-info">def</span>{' '}
                <span className="rounded bg-accent-soft px-1 text-accent-ink">handler</span>
                (req: Request, ctx: Context):{'\n'}
                {'    '}order = req.json(){'\n'}
                {'    '}ctx.set(<span className="text-ok">&quot;actor&quot;</span>, order[
                <span className="text-ok">&quot;user&quot;</span>]){'\n\n'}
                {'    '}
                <span className="text-info">with</span> postgres.session(){' '}
                <span className="text-info">as</span> db:{'\n'}
                {'        '}db.execute({'\n'}
                {'            '}
                <span className="text-ok">
                  &quot;insert into orders (ref) values (:ref)&quot;
                </span>
                ,{'\n'}
                {'            '}ref=order[<span className="text-ok">&quot;ref&quot;</span>],
                {'\n'}
                {'        '}){'\n\n'}
                {'    '}
                <span className="text-info">return</span> {'{'}
                <span className="text-ok">&quot;ok&quot;</span>:{' '}
                <span className="text-warn">True</span>
                {'}'}, <span className="text-warn">201</span>
              </pre>

              {/* The same contract in the other language that ships. Two lines
                  rather than a second styled block: the point is that the shape
                  does not change, not to show the whole file twice. */}
              <div className="border-t border-line px-4 py-3 font-mono text-[11.5px] leading-[1.8] text-ink-3">
                <span className="text-ink-2">handler.js</span> — same contract, same context:
                {'\n'}
                <span className="text-info">export function</span>{' '}
                <span className="text-ink-2">handler</span>(req, ctx) {'{'}{' '}
                <span className="text-info">return</span> {'{'} statusCode:{' '}
                <span className="text-warn">201</span>, body: {'{'} ok:{' '}
                <span className="text-warn">true</span> {'}'} {'}'} {'}'}
              </div>
            </Card>
          </Reveal>
        </div>
      </section>

      {/* ── the spec sheet ───────────────────────────────────────────────── */}
      <section className="mx-auto max-w-[1080px] px-5 py-14 sm:px-8">
        <Reveal>
          <h2 className="m-0 mb-1.5 text-[clamp(1.5rem,3vw,1.9rem)] tracking-[-0.03em]">
            What it actually does
          </h2>
          <p className="mb-8 max-w-[560px] text-[15px] text-ink-2">
            Defaults, not aspirations. Every one of these is a value you can change or a
            behaviour you can watch happen.
          </p>
        </Reveal>

        <div className="grid gap-x-10 gap-y-9 sm:grid-cols-2">
          {SPEC.map((section, index) => (
            <Reveal key={section.group} delay={(index % 2) * 70}>
              <div className="mb-3 border-b border-line pb-2 text-[11.5px] font-bold tracking-[0.06em] text-ink-3 uppercase">
                {section.group}
              </div>
              <dl className="m-0 grid gap-2.5">
                {section.rows.map(([term, value]) => (
                  <div key={term} className="grid grid-cols-[112px_minmax(0,1fr)] gap-3">
                    <dt className="text-[13px] text-ink-3">{term}</dt>
                    <dd className="m-0 text-[13.5px] text-ink">{value}</dd>
                  </div>
                ))}
              </dl>
            </Reveal>
          ))}
        </div>
      </section>

      {/* ── comparison ───────────────────────────────────────────────────── */}
      <section className="mx-auto max-w-[1080px] px-5 pb-16 sm:px-8">
        <Reveal>
          <Comparison />
        </Reveal>
      </section>

      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-[1080px] flex-col gap-5 px-5 py-8 text-[13px] sm:flex-row sm:items-center sm:px-8">
          <div className="flex items-center gap-2.5 text-ink-2">
            <Logo size={20} label={false} />
            Cubicle · Apache-2.0 · no telemetry
          </div>
          <div className="flex flex-wrap gap-x-5 gap-y-2 text-ink-3 sm:ml-auto">
            <Link to="/docs/install" className="transition hover:text-ink">
              Install
            </Link>
            <Link to="/docs/functions" className="transition hover:text-ink">
              Writing functions
            </Link>
            <Link to="/docs/scaling" className="transition hover:text-ink">
              Scaling
            </Link>
            <Link to="/docs/cli" className="transition hover:text-ink">
              CLI
            </Link>
            <a
              href="https://github.com/clickTwice26/cubicle"
              target="_blank"
              rel="noreferrer"
              className="transition hover:text-ink"
            >
              Source
            </a>
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
  {
    label: 'Adding a language',
    cubicle: 'Install the runtime, or write one',
    rivals: 'Wait for the vendor',
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
