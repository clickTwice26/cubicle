import { useState, useEffect, useRef } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Logo, ThemeToggle } from '../components/Layout'

function AnimatedFeature() {
  const WORDS = [
    'zero cloud bills or telemetry',
    'instant warm isolate hits',
    'full hardware ownership',
    'zero vendor lock-in',
  ]
  const [index, setIndex] = useState(0)

  useEffect(() => {
    const timer = setInterval(() => {
      setIndex((i) => (i + 1) % WORDS.length)
    }, 2800)
    return () => clearInterval(timer)
  }, [])

  return (
    <span key={index} className="inline-block animate-word-up font-semibold text-ink underline decoration-accent/50 underline-offset-4">
      {WORDS[index]}
    </span>
  )
}
import {
  ArrowRight,
  Check,
  Copy,
  Github,
  Zap,
  Shield,
  Terminal,
  CheckCircle,
  XCircle,
  ChevronDown,
  ArrowUpRight,
  Database,
  Refresh,
  Lock,
  Activity,
} from '../components/Icons'
import { Button, Card, cx } from '../components/ui'
import { Reveal, CountUp } from '../components/landing/Motion'
import { FlowStrip } from '../components/landing/FlowStrip'
import { useSetupStatus } from '../lib/hooks'

/** Hard facts, grouped. Every line is a fact with a number or name. */
const SPEC: { group: string; rows: [string, string][] }[] = [
  {
    group: 'Runtime',
    rows: [
      ['Languages', 'Python 3.10–3.13, Node 18/20/22'],
      ['Custom Runtimes', 'Built on node when installed from Settings'],
      ['Isolation', 'One container per function version'],
      ['Concurrency', 'One request per container isolate'],
      ['Smallest instance', '32 MB — agent holds 18 MB'],
      ['Filesystem', 'Read-only, 64 MB tmpfs at /tmp'],
      ['Privileges', 'Unprivileged, all Linux capabilities dropped'],
    ],
  },
  {
    group: 'Scheduling',
    rows: [
      ['Ceiling', 'Per function cap, hard cluster limit above it'],
      ['At ceiling', 'Requests queue gracefully, zero drops'],
      ['Distribution', 'Least-used warm container takes request'],
      ['Triggers', 'HTTP REST, or cron schedule in any timezone'],
      ['Scale down', '60s burst shedding, custom kill timer'],
      ['Idle cost', 'One database row in cluster state'],
    ],
  },
  {
    group: 'Storage',
    rows: [
      ['Managed', 'PostgreSQL 16, Redis 7 (per cluster)'],
      ['Wiring', 'Auto-injected per invocation, zero string config'],
      ['Browsing', 'Rows, structure & SQL in cluster console'],
      ['Secrets', 'AES-256-GCM, per-record data key'],
      ['Passwords', 'Argon2id hashing'],
    ],
  },
  {
    group: 'Operations',
    rows: [
      ['Install', '1 command, 5 containers, 3 networks'],
      ['TLS', 'Let’s Encrypt auto-provision or custom proxy'],
      ['Upgrades', '1-click pull branch & hot-rebuild'],
      ['Metrics', 'Prometheus endpoint at /metrics'],
      ['Live view', 'Real-time streamed requests & isolates'],
      ['Drift Detection', 'Scans Docker state against cluster spec'],
      ['Telemetry', 'Zero (100% air-gapped ready)'],
    ],
  },
]

const COMMAND_OPTIONS = [
  {
    id: 'script',
    label: 'Install Script',
    command: 'git clone https://github.com/clickTwice26/cubicle && cd cubicle && ./install.sh',
    sub: 'Recommended for single-node Linux or macOS servers',
  },
  {
    id: 'docker',
    label: 'Docker Compose',
    command: 'curl -fsSL https://raw.githubusercontent.com/clickTwice26/cubicle/main/docker-compose.yml | docker compose -f - up -d',
    sub: 'Launch instantly on any container engine',
  },
  {
    id: 'curl',
    label: 'One-Liner',
    command: 'curl -fsSL https://cubicle.dev/install.sh | bash',
    sub: 'Quick setup script for clean Ubuntu / Debian host',
  },
]

function CommandBox() {
  const [activeTab, setActiveTab] = useState(0)
  const [copied, setCopied] = useState(false)
  const current = COMMAND_OPTIONS[activeTab]

  const handleCopy = () => {
    void navigator.clipboard?.writeText(current.command)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1600)
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-line bg-panel text-left shadow-card">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line bg-panel-2 px-4 py-2.5">
        <div className="flex items-center gap-1.5">
          <div className="h-2.5 w-2.5 rounded-full bg-err/60" />
          <div className="h-2.5 w-2.5 rounded-full bg-warn/60" />
          <div className="h-2.5 w-2.5 rounded-full bg-ok/60" />
          <span className="ml-2 font-mono text-[11.5px] text-ink-3">terminal</span>
        </div>
        <div className="flex items-center gap-1">
          {COMMAND_OPTIONS.map((opt, i) => (
            <button
              key={opt.id}
              onClick={() => setActiveTab(i)}
              className={cx(
                'rounded-md px-2.5 py-1 font-mono text-[11.5px] transition select-none',
                activeTab === i
                  ? 'bg-panel text-ink font-medium shadow-xs border border-line'
                  : 'text-ink-3 hover:text-ink',
              )}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 px-4 py-3.5">
        <div className="flex items-center gap-3 min-w-0 flex-1">
          <span className="font-mono text-[13px] text-accent font-bold select-none">$</span>
          <span className="font-mono text-[12.5px] sm:text-[13px] text-ink truncate">
            {current.command}
          </span>
        </div>
        <button
          type="button"
          onClick={handleCopy}
          className={cx(
            'flex flex-none items-center justify-center gap-1.5 rounded-lg border px-3 py-1.5 font-mono text-[12px] font-medium transition select-none',
            copied
              ? 'border-ok bg-ok-bg text-ok'
              : 'border-line bg-panel-2 text-ink-2 hover:border-line-strong hover:text-ink',
          )}
        >
          {copied ? <Check size={14} /> : <Copy size={14} />}
          <span>{copied ? 'Copied' : 'Copy'}</span>
        </button>
      </div>
      <div className="border-t border-line bg-panel-2/50 px-4 py-2 text-[11.5px] font-mono text-ink-3">
        {current.sub}
      </div>
    </div>
  )
}

function CodePlayground() {
  const [lang, setLang] = useState<'py' | 'js' | 'ts' | 'toml'>('py')

  return (
    <Card className="overflow-hidden shadow-card border border-line">
      <div className="flex flex-wrap items-center justify-between border-b border-line bg-panel-2 px-4 py-2.5">
        <div className="flex items-center gap-2 font-mono text-[12px]">
          <span className="text-ink font-medium">
            {lang === 'py' && 'handler.py'}
            {lang === 'js' && 'handler.js'}
            {lang === 'ts' && 'handler.ts'}
            {lang === 'toml' && 'cubicle.toml'}
          </span>
          <span className="rounded bg-ok-bg px-2 py-0.5 text-[10.5px] text-ok font-medium">
            deployed · v4
          </span>
        </div>
        <div className="flex items-center gap-1 font-mono text-[11.5px]">
          {(['py', 'js', 'ts', 'toml'] as const).map((t) => (
            <button
              key={t}
              onClick={() => setLang(t)}
              className={cx(
                'rounded px-2.5 py-1 transition select-none',
                lang === t
                  ? 'bg-panel text-ink font-semibold border border-line'
                  : 'text-ink-3 hover:text-ink',
              )}
            >
              {t.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      <pre className="m-0 overflow-x-auto p-4 font-mono text-[12.5px] leading-[1.8]">
        {lang === 'py' && (
          <>
            <span className="text-info">from</span> cubicle_context{' '}
            <span className="text-info">import</span> Request, Context{'\n'}
            <span className="text-info">from</span> cubicle_db{' '}
            <span className="text-info">import</span> postgres, redis{'\n\n'}
            <span className="text-info">def</span>{' '}
            <span className="rounded bg-accent-soft px-1 text-accent-ink font-bold">handler</span>
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
              &quot;insert into orders (ref, total) values (:ref, :total)&quot;
            </span>
            ,{'\n'}
            {'            '}ref=order[<span className="text-ok">&quot;ref&quot;</span>], total=order[
            <span className="text-ok">&quot;total&quot;</span>],{'\n'}
            {'        '}){'\n\n'}
            {'    '}redis.incr(<span className="text-ok">&quot;stats:orders_count&quot;</span>){'\n'}
            {'    '}
            <span className="text-info">return</span> {'{'}
            <span className="text-ok">&quot;ok&quot;</span>: <span className="text-warn">True</span>,{' '}
            <span className="text-ok">&quot;ref&quot;</span>: order[
            <span className="text-ok">&quot;ref&quot;</span>]
            {'}'}, <span className="text-warn">201</span>
          </>
        )}

        {lang === 'js' && (
          <>
            <span className="text-info">import</span> {'{'} postgres, redis {'}'}{' '}
            <span className="text-info">from</span> <span className="text-ok">&apos;cubicle/db&apos;</span>
            {'\n\n'}
            <span className="text-info">export async function</span>{' '}
            <span className="rounded bg-accent-soft px-1 text-accent-ink font-bold">handler</span>(req, ctx) {'{'}
            {'\n'}
            {'  '}const order = await req.json(){'\n'}
            {'  '}ctx.set(<span className="text-ok">&apos;actor&apos;</span>, order.user){'\n\n'}
            {'  '}await postgres.query({'\n'}
            {'    '}
            <span className="text-ok">&apos;INSERT INTO orders (ref, total) VALUES ($1, $2)&apos;</span>,{'\n'}
            {'    '}[order.ref, order.total]{'\n'}
            {'  '}){'\n\n'}
            {'  '}await redis.incr(<span className="text-ok">&apos;stats:orders_count&apos;</span>){'\n'}
            {'  '}<span className="text-info">return</span> {'{'} statusCode: <span className="text-warn">201</span>, body: {'{'} ok: <span className="text-warn">true</span>, ref: order.ref {'}'} {'}'}{'\n'}
            {'}'}
          </>
        )}

        {lang === 'ts' && (
          <>
            <span className="text-info">import type</span> {'{'} Request, Context, HandlerResult {'}'}{' '}
            <span className="text-info">from</span> <span className="text-ok">&apos;cubicle/types&apos;</span>
            {'\n'}
            <span className="text-info">import</span> {'{'} postgres, redis {'}'}{' '}
            <span className="text-info">from</span> <span className="text-ok">&apos;cubicle/db&apos;</span>
            {'\n\n'}
            <span className="text-info">interface</span> OrderPayload {'{'} user: string; ref: string; total: number {'}'}
            {'\n\n'}
            <span className="text-info">export async function</span>{' '}
            <span className="rounded bg-accent-soft px-1 text-accent-ink font-bold">handler</span>(
            req: Request&lt;OrderPayload&gt;, ctx: Context): Promise&lt;HandlerResult&gt; {'{'}
            {'\n'}
            {'  '}const {'{'} user, ref, total {'}'} = await req.json(){'\n'}
            {'  '}ctx.set(<span className="text-ok">&apos;actor&apos;</span>, user){'\n\n'}
            {'  '}await postgres.query(<span className="text-ok">&apos;INSERT INTO orders (ref, total) VALUES ($1, $2)&apos;</span>, [ref, total]){'\n'}
            {'  '}await redis.incr(<span className="text-ok">&apos;stats:orders_count&apos;</span>){'\n'}
            {'  '}<span className="text-info">return</span> {'{'} statusCode: <span className="text-warn">201</span>, body: {'{'} ok: <span className="text-warn">true</span>, ref {'}'} {'}'}{'\n'}
            {'}'}
          </>
        )}

        {lang === 'toml' && (
          <>
            <span className="text-info">[function]</span>{'\n'}
            name = <span className="text-ok">&quot;create-charge&quot;</span>{'\n'}
            runtime = <span className="text-ok">&quot;python3.12&quot;</span>{'\n'}
            memory_mb = <span className="text-warn">128</span>{'\n'}
            timeout_sec = <span className="text-warn">30</span>{'\n'}
            concurrency = <span className="text-warn">1</span>{'\n\n'}
            <span className="text-info">[triggers.http]</span>{'\n'}
            path = <span className="text-ok">&quot;/api/v1/charge&quot;</span>{'\n'}
            method = <span className="text-ok">&quot;POST&quot;</span>{'\n\n'}
            <span className="text-info">[storage]</span>{'\n'}
            postgres = <span className="text-warn">true</span>{'\n'}
            redis = <span className="text-warn">true</span>
          </>
        )}
      </pre>

      <div className="border-t border-line bg-panel-2 px-4 py-3 font-mono text-[11.5px] leading-[1.7] text-ink-3 flex items-center justify-between">
        <span>Postgres & Redis context auto-injected. Zero connection strings needed.</span>
        <span className="hidden sm:inline-block text-ink-2 font-medium">Memory & timeout isolated</span>
      </div>
    </Card>
  )
}

function FaqSection() {
  const [openIndex, setOpenIndex] = useState<number | null>(0)

  const FAQS = [
    {
      q: 'What server hardware is required to run Cubicle?',
      a: 'Any Linux machine (Ubuntu, Debian, RHEL) or Mac running Docker. Minimum requirements are 1 vCPU and 1 GB RAM. Cubicle runs lightweight 32 MB container isolates.',
    },
    {
      q: 'How does Cubicle eliminate cold starts?',
      a: 'Cubicle maintains a pool of pre-warmed container isolates. Incoming requests hit warm containers in under 1ms. When traffic decreases, idle containers scale down automatically.',
    },
    {
      q: 'Are PostgreSQL and Redis included out of the box?',
      a: 'Yes. Cubicle manages containerized PostgreSQL 16 and Redis 7 directly inside your cluster. Credentials and connection pools are auto-wired into function execution context.',
    },
    {
      q: 'Is there any telemetry or cloud tracking?',
      a: 'Zero. Cubicle makes no third-party calls, collects no usage stats, and requires no account. It is 100% self-contained and suitable for air-gapped production environments.',
    },
  ]

  return (
    <div className="grid gap-3">
      {FAQS.map((faq, i) => {
        const isOpen = openIndex === i
        return (
          <Reveal delay={i * 80} key={faq.q}>
            <div
              className="overflow-hidden rounded-xl border border-line bg-panel transition hover:border-line-strong"
            >
              <button
                type="button"
                onClick={() => setOpenIndex(isOpen ? null : i)}
                className="flex w-full items-center justify-between px-5 py-4 text-left font-medium text-[15px] text-ink"
              >
                <span>{faq.q}</span>
                <ChevronDown
                  size={18}
                  className={cx('flex-none text-ink-3 transition-transform duration-200', isOpen && 'rotate-180 text-accent')}
                />
              </button>
              {isOpen && (
                <div className="border-t border-line/60 bg-panel-2/40 px-5 py-4 text-[14px] leading-relaxed text-ink-2">
                  {faq.a}
                </div>
              )}
            </div>
          </Reveal>
        )
      })}
    </div>
  )
}

function Navbar({ status }: { status: any }) {
  const navigate = useNavigate()
  const enter = () => navigate(status?.setup_complete ? '/console' : '/setup')
  const [scrolled, setScrolled] = useState(false)

  useEffect(() => {
    const handleScroll = () => setScrolled(window.scrollY > 15)
    window.addEventListener('scroll', handleScroll, { passive: true })
    handleScroll()
    return () => window.removeEventListener('scroll', handleScroll)
  }, [])

  return (
    <header
      className={cx(
        'fixed top-0 left-0 right-0 z-50 transition-all duration-300 ease-out',
        scrolled
          ? 'bg-bg/85 backdrop-blur-md border-b border-line shadow-sm py-2'
          : 'bg-transparent border-transparent py-5'
      )}
    >
      <div className="mx-auto flex h-[42px] max-w-[1080px] items-center justify-between px-5 sm:px-8">
        <div className="flex items-center gap-8 animate-fade-in-down" style={{ animationDelay: '0ms' }}>
          <Logo />
          <nav className="hidden md:flex items-center gap-7">
            <a href="https://github.com/clickTwice26/cubicle" target="_blank" rel="noreferrer" className="relative text-[13.5px] font-medium text-ink-2 transition-colors hover:text-ink group">
              Open Source
              <span className="absolute -bottom-1 left-0 w-0 h-[2px] bg-accent transition-all duration-300 ease-out group-hover:w-full rounded-full" />
            </a>
            <Link to="/docs" className="relative text-[13.5px] font-medium text-ink-2 transition-colors hover:text-ink group">
              Documentation
              <span className="absolute -bottom-1 left-0 w-0 h-[2px] bg-accent transition-all duration-300 ease-out group-hover:w-full rounded-full" />
            </Link>
          </nav>
        </div>
        <div className="flex items-center gap-3 animate-fade-in-down" style={{ animationDelay: '100ms' }}>
          <ThemeToggle className="h-[34px] w-[34px] hover:bg-panel-2 rounded-lg transition-colors" />
          <a
            href="https://github.com/clickTwice26/cubicle"
            target="_blank"
            rel="noreferrer"
            className="hidden h-[34px] items-center gap-2 rounded-lg border border-line px-3 text-[13px] font-medium text-ink-2 transition-all hover:text-ink hover:border-line-strong hover:bg-panel-2 sm:flex"
          >
            <Github size={14} />
            <span className="font-mono">Apache-2.0</span>
          </a>
          <Button variant="primary" onClick={enter} className="h-9 px-4 text-[13.5px] font-medium shadow-xs transition-transform hover:scale-[1.02] active:scale-[0.98]">
            {status?.setup_complete ? 'Open console' : 'Start setup'}
          </Button>
        </div>
      </div>
    </header>
  )
}

export default function Landing() {
  const navigate = useNavigate()
  const { data: status } = useSetupStatus()

  const enter = () => navigate(status?.setup_complete ? '/console' : '/setup')

  return (
    <div className="relative min-h-screen max-w-full overflow-hidden bg-bg text-ink font-sans">
      {/* Background ambient glow & grid pattern */}
      <div className="hero-glow-bg" />
      <div className="pointer-events-none absolute inset-0 bg-grid-pattern opacity-[0.035]" />

      {/* Navbar */}
      <Navbar status={status} />

      {/* Hero Section */}
      <section className="relative z-10 mx-auto max-w-[1080px] px-5 pt-28 pb-12 text-center sm:px-8 sm:pt-36">
        <Reveal className="flex flex-col items-center text-center">
          <h1 className="hero-stagger-1 m-0 max-w-[820px] text-[clamp(2.3rem,5.8vw,3.8rem)] leading-[1.08] font-extrabold tracking-[-0.035em] text-balance mx-auto">
            <span className="relative inline-block px-4 py-1.5 mr-2 -mt-2 rounded-2xl bg-accent-soft text-accent-ink border border-accent/40 shadow-[0_0_30px_color-mix(in_srgb,var(--accent)_35%,transparent)] rotate-[-3deg] hover:rotate-[-1deg] transition-transform duration-300 overflow-hidden align-middle cursor-default">
              <span className="relative z-10">Free</span>
              <div className="absolute top-0 left-[-100%] w-[100%] h-full bg-[linear-gradient(90deg,transparent_0%,rgba(255,255,255,0.6)_50%,transparent_100%)] animate-[cubicle-shimmer_3s_infinite_ease-in-out]" />
            </span>
            Function-as-a-Service on servers you already own.
          </h1>

          <p className="hero-stagger-2 mt-5 max-w-[650px] text-[17.5px] leading-[1.65] text-ink-2 mx-auto">
            Cubicle runs Python and JavaScript functions in warm container isolates on your hardware with <AnimatedFeature />.
          </p>

          <div className="hero-stagger-3 mt-8 w-full max-w-[680px] mx-auto">
            <CommandBox />
          </div>

          <div className="hero-stagger-4 mt-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-center">
            <Button
              variant="primary"
              onClick={enter}
              icon={<ArrowRight size={15} />}
              className="w-full justify-center sm:w-auto px-5 py-2.5 text-[14px] font-medium shadow-sm"
            >
              {status?.setup_complete ? 'Open the console' : 'Set up your Free FaaS'}
            </Button>
            <Link to="/docs/install" className="w-full sm:w-auto">
              <Button variant="secondary" className="w-full justify-center sm:w-auto px-5 py-2.5 text-[14px]">
                Install guide
              </Button>
            </Link>
            <span className="mt-1 text-[12.5px] font-mono text-ink-3 sm:mt-0 sm:ml-3">
              100% Open Source · Apache-2.0
            </span>
          </div>

          {/* Key metrics strip */}
          <div className="mt-12 grid w-full grid-cols-2 gap-4 border-t border-line/60 pt-8 text-center sm:grid-cols-4">
            <div className="flex flex-col items-center gap-1">
              <span className="text-2xl font-bold font-mono text-ink tracking-tight">0 ms</span>
              <span className="text-[13px] text-ink-3">Cold-start pool hit</span>
            </div>
            <div className="flex flex-col items-center gap-1">
              <span className="text-2xl font-bold font-mono text-ink tracking-tight">32 MB</span>
              <span className="text-[13px] text-ink-3">Min container footprint</span>
            </div>
            <div className="flex flex-col items-center gap-1">
              <span className="text-2xl font-bold font-mono text-ink tracking-tight">100%</span>
              <span className="text-[13px] text-ink-3">Private & air-gapped</span>
            </div>
            <div className="flex flex-col items-center gap-1">
              <span className="text-2xl font-bold font-mono text-ink tracking-tight">1 Cmd</span>
              <span className="text-[13px] text-ink-3">Zero-config deployment</span>
            </div>
          </div>
        </Reveal>
      </section>

      {/* Comparison Section */}
      <section className="relative z-10 mx-auto max-w-[1080px] px-5 pb-16 sm:px-8">
        <Reveal delay={60}>
          <ComparisonTable />
        </Reveal>
        <CostComparisonChart />
      </section>

      {/* Live Activity Visualizer */}
      <section className="relative z-10 mx-auto max-w-[1080px] px-5 pb-16 sm:px-8">
        <Reveal delay={80}>
          <div className="mb-4 flex items-center justify-between">
            <div className="flex items-center gap-2 text-[14px] font-semibold tracking-tight text-ink">
              <Activity size={16} className="text-accent" />
              <span>Real-time Execution Architecture</span>
            </div>
            <span className="font-mono text-[12px] text-ink-3 hidden sm:inline">
              Isolated Micro-Containers
            </span>
          </div>
          <FlowStrip />
        </Reveal>
      </section>

      {/* Feature Highlights Grid */}
      <section className="relative z-10 border-t border-line bg-panel-2/40 py-16">
        <div className="mx-auto max-w-[1080px] px-5 sm:px-8">
          <Reveal>
            <div className="max-w-[600px] mb-12">
              <h2 className="m-0 text-[clamp(1.6rem,3.2vw,2.2rem)] font-bold tracking-[-0.03em]">
                Built for operators who want control.
              </h2>
              <p className="mt-3 text-[15.5px] leading-relaxed text-ink-2">
                No monthly usage invoices, no arbitrary rate limits, and no black-box cloud infrastructure.
              </p>
            </div>
          </Reveal>

          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            <Reveal delay={50}>
              <div className="hover-glow rounded-2xl border border-line bg-panel p-6">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-soft text-accent-ink mb-4">
                  <Zap size={20} />
                </div>
                <h3 className="m-0 text-[16px] font-bold text-ink">Zero Cold Starts</h3>
                <p className="mt-2 text-[13.5px] leading-relaxed text-ink-2">
                  Pre-warmed isolate pools keep your functions responsive on every request without leaving high idle memory usage.
                </p>
              </div>
            </Reveal>

            <Reveal delay={100}>
              <div className="hover-glow rounded-2xl border border-line bg-panel p-6">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-soft text-accent-ink mb-4">
                  <Database size={20} />
                </div>
                <h3 className="m-0 text-[16px] font-bold text-ink">Auto-Wired Postgres & Redis</h3>
                <p className="mt-2 text-[13.5px] leading-relaxed text-ink-2">
                  Managed database instances ship with your cluster. Connections are injected directly into your invocation context.
                </p>
              </div>
            </Reveal>

            <Reveal delay={150}>
              <div className="hover-glow rounded-2xl border border-line bg-panel p-6">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-soft text-accent-ink mb-4">
                  <Shield size={20} />
                </div>
                <h3 className="m-0 text-[16px] font-bold text-ink">100% Private & Air-Gapped</h3>
                <p className="mt-2 text-[13.5px] leading-relaxed text-ink-2">
                  Zero telemetry or call-home metrics. All code execution, data storage, and logs remain strictly on your server disk.
                </p>
              </div>
            </Reveal>

            <Reveal delay={200}>
              <div className="hover-glow rounded-2xl border border-line bg-panel p-6">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-soft text-accent-ink mb-4">
                  <Terminal size={20} />
                </div>
                <h3 className="m-0 text-[16px] font-bold text-ink">Declarative Specs</h3>
                <p className="mt-2 text-[13.5px] leading-relaxed text-ink-2">
                  Configure memory allocations, concurrency caps, and cron schedules using a simple, human-readable <span className="font-mono text-[12px] text-ink font-semibold">cubicle.toml</span> file.
                </p>
              </div>
            </Reveal>

            <Reveal delay={250}>
              <div className="hover-glow rounded-2xl border border-line bg-panel p-6">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-soft text-accent-ink mb-4">
                  <Lock size={20} />
                </div>
                <h3 className="m-0 text-[16px] font-bold text-ink">Auto-TLS Edge Proxy</h3>
                <p className="mt-2 text-[13.5px] leading-relaxed text-ink-2">
                  Built-in Caddy edge proxy automatically manages SSL certificates via Let’s Encrypt for all your custom HTTP domains.
                </p>
              </div>
            </Reveal>

            <Reveal delay={300}>
              <div className="hover-glow rounded-2xl border border-line bg-panel p-6">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-soft text-accent-ink mb-4">
                  <Refresh size={20} />
                </div>
                <h3 className="m-0 text-[16px] font-bold text-ink">One-Click Hot Upgrades</h3>
                <p className="mt-2 text-[13.5px] leading-relaxed text-ink-2">
                  Update Cubicle seamlessly from the web console. The system pulls git updates and rebuilds without dropping active requests.
                </p>
              </div>
            </Reveal>
          </div>
        </div>
      </section>

      {/* Code Section */}
      <section className="relative z-10 border-b border-line bg-panel-2/70 py-16">
        <div className="mx-auto grid max-w-[1080px] gap-10 px-5 sm:px-8 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)] lg:items-center">
          <Reveal>
            <div className="inline-flex items-center gap-2 rounded-md bg-accent-soft px-2.5 py-1 font-mono text-[12px] font-semibold text-accent-ink mb-3">
              Developer-First API
            </div>
            <h2 className="m-0 text-[clamp(1.6rem,3.2vw,2.2rem)] font-bold tracking-[-0.03em]">
              One file, one handler.
            </h2>
            <p className="mt-3.5 mb-0 text-[15px] leading-[1.7] text-ink-2">
              Memory, execution timeouts, and concurrency are defined as function metadata, not boilerplate code. Databases arrive automatically with every invocation.
            </p>
            <div className="mt-6 space-y-2 font-mono text-[13px] text-ink-2">
              <div className="flex items-center gap-2">
                <CheckCircle size={15} className="text-ok" />
                <span>Standard HTTP request & response contracts</span>
              </div>
              <div className="flex items-center gap-2">
                <CheckCircle size={15} className="text-ok" />
                <span>Native Python & Node.js ecosystem packages</span>
              </div>
              <div className="flex items-center gap-2">
                <CheckCircle size={15} className="text-ok" />
                <span>Zero vendor lock-in or proprietary SDKs</span>
              </div>
            </div>
          </Reveal>

          <Reveal delay={100}>
            <CodePlayground />
          </Reveal>
        </div>
      </section>

      {/* Hardware Specs Section */}
      <section className="relative z-10 mx-auto max-w-[1080px] px-5 py-16 sm:px-8">
        <Reveal>
          <div className="flex items-center gap-2 text-[12.5px] font-mono font-semibold tracking-wider text-accent uppercase mb-2">
            Technical Specification
          </div>
          <h2 className="m-0 text-[clamp(1.6rem,3vw,2.2rem)] font-bold tracking-[-0.03em]">
            Engineered for performance
          </h2>
          <p className="mt-2 mb-10 max-w-[580px] text-[15px] text-ink-2">
            Hard facts and exact specs. Every value can be monitored live or tuned in your cluster settings.
          </p>
        </Reveal>

        <div className="grid gap-x-10 gap-y-9 sm:grid-cols-2">
          {SPEC.map((section, index) => (
            <Reveal key={section.group} delay={(index % 2) * 70}>
              <div className="mb-3.5 border-b border-line pb-2.5 text-[12px] font-bold tracking-[0.06em] text-ink font-mono uppercase flex items-center justify-between">
                <span>{section.group}</span>
                <span className="h-1.5 w-1.5 rounded-full bg-accent" />
              </div>
              <dl className="m-0 grid gap-3">
                {section.rows.map(([term, value]) => (
                  <div key={term} className="grid grid-cols-[130px_minmax(0,1fr)] gap-3 items-baseline">
                    <dt className="text-[13px] font-mono text-ink-3">{term}</dt>
                    <dd className="m-0 text-[13.5px] font-medium text-ink">{value}</dd>
                  </div>
                ))}
              </dl>
            </Reveal>
          ))}
        </div>
      </section>

      {/* FAQ Section */}
      <section className="relative z-10 border-t border-line bg-panel-2/30 py-16">
        <div className="mx-auto max-w-[780px] px-5 sm:px-8">
          <Reveal>
            <div className="text-center mb-10">
              <h2 className="m-0 text-[clamp(1.6rem,3vw,2.2rem)] font-bold tracking-[-0.03em]">
                Frequently Asked Questions
              </h2>
              <p className="mt-2 text-[15px] text-ink-2">
                Everything you need to know about running Cubicle on your server.
              </p>
            </div>
            <FaqSection />
          </Reveal>
        </div>
      </section>

      {/* Final CTA Banner */}
      <section className="relative z-10 mx-auto max-w-[1080px] px-5 py-16 sm:px-8">
        <Reveal>
          <div className="relative overflow-hidden rounded-3xl border border-line bg-panel p-8 sm:p-12 text-center shadow-card hover-glow">
            <div className="hero-glow-bg opacity-70" />
            <div className="relative z-10 max-w-[640px] mx-auto">
              <h2 className="m-0 text-[clamp(1.8rem,3.5vw,2.5rem)] font-bold tracking-[-0.035em]">
                Ready to take back control of your FaaS?
              </h2>
              <p className="mt-3 text-[16px] text-ink-2">
                Deploy Cubicle on your server in under two minutes with a single command.
              </p>
              <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-3">
                <Button
                  variant="primary"
                  onClick={enter}
                  icon={<ArrowRight size={16} />}
                  className="w-full sm:w-auto px-6 py-3 text-[14.5px] font-semibold"
                >
                  {status?.setup_complete ? 'Open Console' : 'Start Setup Now'}
                </Button>
                <a
                  href="https://github.com/clickTwice26/cubicle"
                  target="_blank"
                  rel="noreferrer"
                  className="w-full sm:w-auto"
                >
                  <Button variant="secondary" icon={<Github size={16} />} className="w-full sm:w-auto px-5 py-3 text-[14.5px]">
                    Star on GitHub
                  </Button>
                </a>
              </div>
            </div>
          </div>
        </Reveal>
      </section>

      {/* Footer */}
      <footer className="relative z-10 border-t border-line bg-panel">
        <div className="mx-auto flex max-w-[1080px] flex-col gap-6 px-5 py-10 text-[13px] sm:flex-row sm:items-center sm:px-8">
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center gap-2.5 text-ink font-semibold">
              <Logo size={22} label={false} />
              <span>Cubicle</span>
              <span className="font-mono text-[11px] rounded bg-panel-2 border border-line px-2 py-0.5 text-ink-2">
                Apache-2.0
              </span>
            </div>
            <span className="text-[12.5px] text-ink-3">
              Self-hosted serverless engine. Zero telemetry, 100% private.
            </span>
          </div>
          <div className="flex flex-wrap gap-x-6 gap-y-2 text-ink-2 font-medium sm:ml-auto">
            <Link to="/docs/install" className="transition hover:text-ink">
              Install Guide
            </Link>
            <Link to="/docs/functions" className="transition hover:text-ink">
              Writing Functions
            </Link>
            <Link to="/docs/scaling" className="transition hover:text-ink">
              Scaling & Limits
            </Link>
            <Link to="/docs/cli" className="transition hover:text-ink">
              CLI Reference
            </Link>
            <a
              href="https://github.com/clickTwice26/cubicle"
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 transition hover:text-ink"
            >
              <span>GitHub</span>
              <ArrowUpRight size={13} />
            </a>
          </div>
        </div>
      </footer>
    </div>
  )
}

/** Comparison component with checkmarks and visual status indicators. */
const RIVALS = ['AWS Lambda', 'Azure Functions', 'Google Cloud Run', 'DigitalOcean']

const COMPARISON_ROWS: {
  label: string
  cubicle: string
  rivals: string[]
  isBoolean?: boolean
}[] = [
  {
    label: 'Hosting Location',
    cubicle: 'Hardware you control',
    rivals: ["Amazon Cloud", "Microsoft Cloud", "Google Cloud", "DigitalOcean Cloud"],
  },
  {
    label: 'Request Pricing',
    cubicle: '$0 / Free (Your machine)',
    rivals: ['$0.20 per 1M req', '$0.20 per 1M req', '$0.40 per 1M req', '$0.000016 / sec'],
  },
  {
    label: 'Data Sovereignty',
    cubicle: 'Your local disk',
    rivals: ['Vendor cloud region', 'Vendor cloud region', 'Vendor cloud region', 'Vendor cloud region'],
  },
  {
    label: 'Managed Postgres & Redis',
    cubicle: 'Built-in (Auto-wired)',
    rivals: ['Separate paid service', 'Separate paid service', 'Separate paid service', 'Separate paid service'],
  },
  {
    label: 'Account & Credit Card',
    cubicle: 'None required',
    rivals: ['Required', 'Required', 'Required', 'Required'],
  },
  {
    label: 'Air-Gapped Operation',
    cubicle: 'Yes (100% offline)',
    rivals: ['No', 'No', 'No', 'No'],
  },
  {
    label: 'Telemetry & Tracking',
    cubicle: 'Zero telemetry',
    rivals: ['Required', 'Required', 'Required', 'Required'],
  },
  {
    label: 'Licence',
    cubicle: 'Apache-2.0 Open Source',
    rivals: ['Proprietary TOS', 'Proprietary TOS', 'Proprietary TOS', 'Proprietary TOS'],
  },
]

function ComparisonTable() {
  return (
    <Card className="mx-auto mt-5 max-w-[1000px] overflow-hidden border border-line shadow-card">
      <div className="border-b border-line bg-panel-2 px-5 py-5 sm:px-7">
        <div className="text-[17px] font-bold tracking-[-0.01em]">
          How Cubicle compares to managed cloud platforms
        </div>
        <div className="mt-1 text-[13.5px] text-ink-2">
          Structural differences — total control vs. third-party dependencies.
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[740px] border-collapse text-left">
          <thead>
            <tr className="border-b border-line bg-panel">
              <th className="sticky left-0 z-10 bg-panel px-5 py-3.5 text-[11.5px] font-bold tracking-[0.05em] text-ink-3 uppercase sm:px-7" />
              <th className="bg-accent-soft/80 px-4 py-3.5 text-[13.5px] font-bold whitespace-nowrap text-accent-ink border-x border-accent/20">
                ⚡ Cubicle
              </th>
              {RIVALS.map((name) => (
                <th
                  key={name}
                  className="px-4 py-3.5 text-[12.5px] font-semibold whitespace-nowrap text-ink-2"
                >
                  {name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {COMPARISON_ROWS.map((row, index) => (
              <Reveal as="tr" delay={index * 60} key={row.label} className="border-b border-line last:border-b-0 hover:bg-panel-2/30 transition-colors">
                <th
                  scope="row"
                  className="sticky left-0 z-10 bg-panel px-5 py-3.5 text-[13px] font-medium whitespace-nowrap text-ink sm:px-7"
                >
                  {row.label}
                </th>
                <td className="bg-accent-soft/30 px-4 py-3.5 text-[13px] font-bold text-ink border-x border-accent/15">
                  <div className="flex items-center gap-1.5">
                    <CheckCircle size={15} className="text-ok flex-none" />
                    <span>{row.cubicle}</span>
                  </div>
                </td>
                {row.rivals.map((value, i) => (
                  <td key={RIVALS[i]} className="px-4 py-3.5 text-[13px] text-ink-2">
                    <div className="flex items-center gap-1.5">
                      {value === 'Required' || value === 'No' || value.includes('Proprietary') ? (
                        <XCircle size={14} className="text-err/70 flex-none" />
                      ) : null}
                      <span>{value}</span>
                    </div>
                  </td>
                ))}
              </Reveal>
            ))}
          </tbody>
        </table>
      </div>

      <div className="border-t border-line bg-panel-2/70 px-5 py-4 text-[13px] leading-relaxed text-ink-2 sm:px-7">
        <span className="font-semibold text-ink">When to choose cloud FaaS:</span> If you need multi-region edge nodes across 50 countries or auto-scaling to tens of millions of concurrent requests. <span className="font-semibold text-ink">When to choose Cubicle:</span> When you want full hardware ownership, zero usage bills, absolute data privacy, and zero telemetry.
      </div>
    </Card>
  )
}

function CostComparisonChart() {
  const [shown, setShown] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setShown(true)
        observer.disconnect()
      }
    }, { threshold: 0.25 })
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  const data = [
    { name: 'Managed Edge (Vercel, Netlify)', cost: 150, width: '100%', color: 'bg-err/70', desc: '100M req + 1TB egress' },
    { name: 'Google Cloud Run', cost: 95, width: '63%', color: 'bg-ink-3/50', desc: '100M req + 1TB egress' },
    { name: 'AWS Lambda', cost: 65, width: '43%', color: 'bg-ink-3/50', desc: '100M req + 1TB egress' },
    { name: 'Cubicle', cost: 0, width: '4%', color: 'bg-accent text-accent-ink', desc: 'Bring your own hardware' },
  ]

  return (
    <div ref={ref}>
      <Card className="mx-auto mt-6 max-w-[1000px] border border-line shadow-card overflow-hidden bg-panel p-6 sm:p-8 hover-glow transition-all">
        <div className="mb-8">
          <h3 className="m-0 text-[18px] font-bold tracking-tight text-ink">Monthly Cost at Scale</h3>
          <p className="mt-1 text-[14px] text-ink-2">Estimated base cost for 100M requests and 1TB of egress bandwidth.</p>
        </div>
      <div className="grid gap-6">
        {data.map((item, i) => (
          <div key={item.name} className="relative">
            <div className="mb-2 flex items-center justify-between text-[13px] font-medium">
              <div className="flex items-center gap-2">
                <span className="text-ink">{item.name}</span>
                <span className="hidden text-ink-3 sm:inline-block">— {item.desc}</span>
              </div>
              <div className="font-mono font-bold text-ink tracking-tight flex items-center">
                <span>$</span>
                {shown ? <CountUp to={item.cost} duration={1400} /> : 0}
                <span className="text-ink-3 text-[11px] ml-1">/mo</span>
              </div>
            </div>
            <div className="h-[22px] w-full overflow-hidden rounded-[4px] bg-panel-2/60 relative">
              <div 
                className={cx("h-full transition-all duration-[1400ms] ease-out flex items-center px-2", item.color)}
                style={{ 
                  width: shown ? item.width : '0%', 
                  transitionDelay: `${i * 150}ms`
                }}
              >
                {item.cost === 0 && shown && (
                  <span className="text-[10.5px] font-bold tracking-wider uppercase ml-1 animate-fade-in-down" style={{ animationDelay: '800ms' }}>
                    Free
                  </span>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </Card>
    </div>
  )
}
