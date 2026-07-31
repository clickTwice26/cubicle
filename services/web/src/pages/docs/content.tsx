import type { ReactNode } from 'react'
import { CodeBlock } from './CodeBlock'

export interface DocPage {
  id: string
  group: string
  label: string
  title: string
  lede: string
  body: () => ReactNode
}

const h2 = (id: string, text: string) => (
  <h2
    id={id}
    className="mt-9 mb-3 scroll-mt-20 text-[21px] font-semibold tracking-[-0.02em] first:mt-0"
  >
    {text}
  </h2>
)

const p = (children: ReactNode) => (
  <p className="mb-4 text-[15px] leading-[1.7] text-ink-2">{children}</p>
)

const code = (children: ReactNode, filename?: string) => (
  <CodeBlock filename={filename}>{children}</CodeBlock>
)

const table = (head: string[], rows: ReactNode[][]) => (
  <div className="mb-6 overflow-hidden rounded-xl border border-line">
    <div
      className="grid gap-4 border-b border-line bg-panel-2 px-4 py-2.5 text-[11px] font-bold tracking-[0.05em] text-ink-3 uppercase"
      style={{ gridTemplateColumns: `repeat(${head.length}, minmax(0, 1fr))` }}
    >
      {head.map((cell) => (
        <span key={cell}>{cell}</span>
      ))}
    </div>
    {rows.map((row, index) => (
      <div
        key={index}
        className="grid items-baseline gap-4 border-b border-line px-4 py-3 text-[13.5px] last:border-b-0"
        style={{ gridTemplateColumns: `repeat(${head.length}, minmax(0, 1fr))` }}
      >
        {row.map((cell, cellIndex) => (
          <span
            key={cellIndex}
            className={cellIndex === 0 ? 'font-mono font-semibold' : 'text-ink-2'}
          >
            {cell}
          </span>
        ))}
      </div>
    ))}
  </div>
)

const note = (children: ReactNode) => (
  <div className="mb-6 rounded-xl border border-accent bg-accent-soft px-4 py-3.5 text-[13.5px] leading-relaxed">
    {children}
  </div>
)

const mono = (text: string) => <span className="font-mono text-[13.5px] text-ink">{text}</span>

export const DOCS: DocPage[] = [
  {
    id: 'install',
    group: 'Getting started',
    label: 'Installation',
    title: 'Installation',
    lede: 'Get a Cubicle cluster running on your own hardware — a laptop, one server, or several. No account, no licence check, no call home.',
    body: () => (
      <>
        {h2('requirements', 'Requirements')}
        {p(
          'Everything runs in Docker, including the isolates that execute your functions. The control plane needs the Docker socket so it can start them.',
        )}
        {table(
          ['What', 'Needs'],
          [
            ['Docker Engine', '24 or newer, with Compose v2'],
            ['CPU', '2 cores minimum, 8+ for a production pool'],
            ['Memory', '4 GB minimum — isolates are capped per function'],
            ['Disk', '20 GB for images, version volumes and the database'],
            ['Architectures', 'amd64 · arm64'],
          ],
        )}

        {h2('install', 'Install')}
        {p('One command builds the images, generates secrets and starts the stack.')}
        {code(
          <>
            <span className="text-ink-3">$</span> git clone
            https://github.com/clickTwice26/cubicle{'\n'}
            <span className="text-ink-3">$</span> cd cubicle{'\n'}
            <span className="text-ink-3">$</span> ./install.sh{'\n\n'}
            {'  '}▸ Generating .env{'\n'}
            {'  '}▸ Building images{'\n'}
            {'  '}▸ Starting the cluster{'\n'}
            {'  '}▸ Cubicle is up. Console http://localhost:7000
          </>,
        )}

        {h2('domain', 'With a domain')}
        {p(
          <>
            Point an A record at the machine and pass the hostname. Caddy obtains and renews a
            Let&apos;s Encrypt certificate on first request — there is nothing else to
            configure.
          </>,
        )}
        {code(
          <>
            <span className="text-ink-3">$</span> ./install.sh --domain fn.example.com \{'\n'}
            {'    '}--email ops@example.com
          </>,
        )}
        {note(
          <>
            <strong>Ports 80 and 443</strong> must reach the host for the ACME HTTP-01
            challenge. The installer sets those as the published ports automatically in domain
            mode. Add {mono('--staging')} while you are testing, so a misconfiguration does not
            burn the production rate limit.
          </>,
        )}

        {h2('verify', 'Verify')}
        {code(
          <>
            <span className="text-ink-3">$</span> curl -s localhost:7000/healthz | jq{'\n\n'}
            {'{'}
            {'\n'}
            {'  '}
            <span className="text-ok">&quot;status&quot;</span>:{' '}
            <span className="text-ok">&quot;ok&quot;</span>,{'\n'}
            {'  '}
            <span className="text-ok">&quot;checks&quot;</span>: {'{'}{' '}
            <span className="text-ok">&quot;database&quot;</span>:{' '}
            <span className="text-warn">true</span>,{' '}
            <span className="text-ok">&quot;redis&quot;</span>:{' '}
            <span className="text-warn">true</span>,{' '}
            <span className="text-ok">&quot;docker&quot;</span>:{' '}
            <span className="text-warn">true</span> {'}'}
            {'\n'}
            {'}'}
          </>,
        )}
        {p(
          'Then open the console. The first screen is setup: you name the cluster and choose the administrator password there. That password is the only credential on the instance.',
        )}
        {note(
          <>
            The installer checks the port before claiming it and picks another if it is taken,
            printing whichever it used. On macOS this matters: AirPlay Receiver holds port 7000
            by default.
          </>,
        )}
      </>
    ),
  },
  {
    id: 'quickstart',
    group: 'Getting started',
    label: 'Quickstart',
    title: 'Quickstart',
    lede: 'Namespace, function, deploy, invoke — about two minutes once the console is up.',
    body: () => (
      <>
        {h2('group', '1 · Create a namespace')}
        {p(
          <>
            In <strong>Function playground</strong>, create a group. Its slug becomes the
            namespace, and every function under it is served at{' '}
            {mono('https://<host>/<cluster>/<namespace>/<function>')}.
          </>,
        )}

        {h2('write', '2 · Write the handler')}
        {p(
          'A new function is scaffolded with a working example. The handler takes a request and a session context, and returns anything JSON-serialisable.',
        )}
        {code(
          <>
            <span className="text-info">from</span> cubicle_context{' '}
            <span className="text-info">import</span> Request, Context, env{'\n\n'}
            <span className="text-info">def</span>{' '}
            <span className="rounded bg-accent-soft px-1">handler</span>(req: Request, ctx:
            Context):{'\n'}
            {'    '}order = req.json()[<span className="text-ok">&quot;orderId&quot;</span>]
            {'\n'}
            {'    '}ctx.set(<span className="text-ok">&quot;last_order&quot;</span>, order)
            {'\n'}
            {'    '}
            <span className="text-info">return</span> {'{'}
            <span className="text-ok">&quot;ok&quot;</span>:{' '}
            <span className="text-warn">True</span>,{' '}
            <span className="text-ok">&quot;order&quot;</span>: order{'}'}
          </>,
          'handler.py',
        )}

        {h2('deploy', '3 · Deploy')}
        {p(
          <>
            <strong>Save &amp; deploy</strong> creates an immutable version: the source is
            written into a fresh volume, dependencies from {mono('requirements.txt')} are
            installed into it, and the new version takes over once the build succeeds. A failed
            build leaves the running version untouched.
          </>,
        )}

        {h2('invoke', '4 · Invoke')}
        {code(
          <>
            <span className="text-ink-3">$</span> curl -X POST
            http://localhost:7000/prod-cluster/payments/create-charge \{'\n'}
            {'    '}-H <span className="text-ok">&apos;Authorization: Bearer cbcl_…&apos;</span>{' '}
            \{'\n'}
            {'    '}-H <span className="text-ok">&apos;X-Cubicle-Session: sess_demo&apos;</span>{' '}
            \{'\n'}
            {'    '}-d <span className="text-ok">&apos;{'{"amount": 4200}'}&apos;</span>
            {'\n\n'}
            {'{'}
            <span className="text-ok">&quot;ok&quot;</span>:{' '}
            <span className="text-warn">true</span>
            {'}'}
          </>,
        )}
        {note(
          <>
            <strong>Cold starts.</strong> The first request after an idle period starts a
            container; that takes a few hundred milliseconds. Every request after it reuses the
            warm isolate. Set warm instances above zero in a function&apos;s settings to keep
            one resident for latency-critical paths — the response header{' '}
            {mono('X-Cubicle-Cold-Start')} tells you which kind you got.
          </>,
        )}
      </>
    ),
  },
  {
    id: 'functions',
    group: 'Guides',
    label: 'Writing functions',
    title: 'Writing functions',
    lede: 'The handler contract, the objects it receives, and the limits it runs under.',
    body: () => (
      <>
        {h2('signature', 'Handler signature')}
        {p(
          <>
            Export one callable named {mono('handler')}. It receives a {mono('Request')} and a{' '}
            {mono('Context')}. A single-argument handler works too, and a request also behaves
            like a plain mapping, so {mono('event["body"]')} is valid.
          </>,
        )}
        {code(
          <>
            <span className="text-info">def</span> handler(req, ctx):{'\n'}
            {'    '}
            <span className="text-info">return</span> {'{'}
            <span className="text-ok">&quot;statusCode&quot;</span>:{' '}
            <span className="text-warn">200</span>,{' '}
            <span className="text-ok">&quot;body&quot;</span>: {'{'}
            <span className="text-ok">&quot;ok&quot;</span>:{' '}
            <span className="text-warn">True</span>
            {'}}'}
          </>,
          'handler.py',
        )}
        {p(
          <>
            Return a dict with {mono('statusCode')} to control the response, or return any
            JSON-serialisable value and it is sent with a 200.
          </>,
        )}

        {h2('request', 'The request object')}
        {table(
          ['Attribute', 'Description'],
          [
            ['req.json()', 'Parsed JSON body, or {} when there is none'],
            ['req.text()', 'Raw body as text'],
            ['req.headers', 'Lower-cased request headers; hop-by-hop headers are stripped'],
            ['req.method', 'HTTP method'],
            ['req.query', 'Parsed query string'],
            ['req.session_id', 'Value of X-Cubicle-Session, generated if absent'],
            ['req.request_id', 'Correlation id, echoed in X-Cubicle-Request-Id'],
          ],
        )}

        {h2('context', 'Session context')}
        {p(
          <>
            {mono('ctx')} is a small store shared by every function in the namespace, keyed by
            the {mono('X-Cubicle-Session')} header and expiring after 30 minutes. What a
            function may do with it is set per function; a read-only function that calls{' '}
            {mono('ctx.set()')} raises rather than silently dropping the write.
          </>,
        )}
        {code(
          <>
            actor = ctx.get(<span className="text-ok">&quot;actor&quot;</span>) or {'{}'}
            {'\n'}
            ctx.set(<span className="text-ok">&quot;actor&quot;</span>, {'{'}
            <span className="text-ok">&quot;id&quot;</span>:{' '}
            <span className="text-ok">&quot;usr_9f2c&quot;</span>
            {'}'}){'\n'}
            ctx.delete(<span className="text-ok">&quot;cart&quot;</span>)
          </>,
        )}

        {h2('limits', 'Execution limits')}
        {p(
          <>
            Defaults are 512 MB and a 30 second timeout, both settable per function. The isolate
            runs unprivileged with a read-only root filesystem, all capabilities dropped and{' '}
            {mono('no-new-privileges')} set. {mono('/tmp')} is a 64 MB tmpfs and is the only
            writable path — it is discarded when the isolate is reclaimed, so use the database
            or an object store for anything durable.
          </>,
        )}
        {p(
          'A handler that exceeds its timeout gets a 504 and its isolate is destroyed, since a runaway thread cannot be reclaimed any other way.',
        )}
        {p(
          <>
            One isolate serves one request at a time, so a handler never runs concurrently with
            itself and does not need to be thread-safe. How many run in parallel, and how long
            they stick around, is covered in <strong>Scaling and concurrency</strong>.
          </>,
        )}
      </>
    ),
  },
  {
    id: 'secrets',
    group: 'Guides',
    label: 'Env & secrets',
    title: 'Env and secrets',
    lede: 'Cluster-wide configuration and per-function secrets, encrypted at rest and resolved at invocation.',
    body: () => (
      <>
        {h2('env', 'Global env')}
        {p(
          <>
            One store per cluster, readable from any namespace. Values are fetched at invocation
            time, so changing one in the console applies on the next request with no redeploy.
          </>,
        )}
        {code(
          <>
            <span className="text-info">from</span> cubicle_context{' '}
            <span className="text-info">import</span> env{'\n\n'}
            base = env.get(<span className="text-ok">&quot;PAYMENTS_API_BASE&quot;</span>){'\n'}
            pool = env.get_int(<span className="text-ok">&quot;DB_POOL_SIZE&quot;</span>,{' '}
            <span className="text-warn">10</span>){'\n'}
            key{'  '}= env.require(
            <span className="text-ok">&quot;STRIPE_SECRET_KEY&quot;</span>)
          </>,
        )}

        {h2('crypto', 'How secrets are stored')}
        {p(
          'Every secret gets its own random 256-bit data key. That key encrypts the value with AES-256-GCM and is itself wrapped with a key derived from the cluster root key. The database only ever holds wrapped material, so a database dump on its own reveals nothing.',
        )}
        {note(
          <>
            <strong>Back up CUBICLE_MASTER_KEY.</strong> It lives in your {mono('.env')} and
            never leaves the machine. Lose it and every stored secret is unrecoverable — that is
            the intended property, not a bug.
          </>,
        )}

        {h2('function', 'Per-function secrets')}
        {p(
          <>
            A function&apos;s own secrets live on its <strong>Secrets</strong> tab and are
            merged over the global env for that function only. Both arrive in the isolate&apos;s
            memory with the invocation and are never written to its filesystem or to the log
            pipeline.
          </>,
        )}
      </>
    ),
  },
  {
    id: 'services',
    group: 'Guides',
    label: 'Data services',
    title: 'Data services',
    lede: 'PostgreSQL and Redis provisioned on the same cluster, wired into every function.',
    body: () => (
      <>
        {h2('create', 'Create an instance')}
        {p(
          <>
            Nothing runs until you create it. Pick a version and a size under{' '}
            <strong>Data services</strong>, and the control plane starts a container on the
            function network with a generated password stored envelope-encrypted.
          </>,
        )}

        {h2('browse', 'Browsing and editing the data')}
        {p(
          <>
            <strong>Browse data</strong> on the PostgreSQL page opens a database manager: tables
            with their sizes, paginated rows with sorting and a search across every column, an
            editor for inserting, changing and deleting rows, the structure of each table, and a
            SQL console.
          </>,
        )}
        {note(
          <>
            Row editing needs a primary key — without one a single row cannot be identified, so
            those tables are read-only in the grid and you use the console instead. The console
            itself is unrestricted, including DDL: it is your database. What bounds it is the
            admin role, a 15 second statement timeout and a 500 row cap on results.
          </>,
        )}

        {h2('lifecycle', 'Stop, recreate, destroy')}
        {table(
          ['Action', 'Effect'],
          [
            ['Stop', 'Stops the container. The volume, the password and the data all stay.'],
            [
              'Recreate',
              'Rebuilds the container from the current spec, reusing the same volume and password. A restart, not a reset — use it when a running container predates a change to how they are created.',
            ],
            [
              'Destroy',
              'Removes the container and, unless you keep the volume, the data with it. It asks you to type the service name first.',
            ],
          ],
        )}

        {h2('use', 'Using them from a function')}
        {p(
          <>
            Connection details are handed to the isolate per invocation, so there is no secret
            to copy and nothing to configure. {mono('available')} is False when the operator has
            not created the service or has stopped it.
          </>,
        )}
        {code(
          <>
            <span className="text-info">from</span> cubicle_db{' '}
            <span className="text-info">import</span> postgres, redis{'\n\n'}
            <span className="text-info">with</span> postgres.session(){' '}
            <span className="text-info">as</span> db:{'\n'}
            {'    '}db.execute({'\n'}
            {'        '}
            <span className="text-ok">
              &quot;insert into orders (ref, amount) values (:ref, :amount)&quot;
            </span>
            ,{'\n'}
            {'        '}ref=<span className="text-ok">&quot;ord_8fk2&quot;</span>, amount=
            <span className="text-warn">4200</span>,{'\n'}
            {'    '}){'\n'}
            {'    '}rows = db.execute(
            <span className="text-ok">&quot;select * from orders limit 10&quot;</span>
            ).fetchall(){'\n\n'}
            redis.setex(<span className="text-ok">&quot;seen&quot;</span>,{' '}
            <span className="text-warn">300</span>,{' '}
            <span className="text-ok">&quot;1&quot;</span>)
          </>,
        )}
        {p(
          <>
            Named parameters are rewritten for the driver, so {mono(':name')} is the portable
            way to bind values. Anything not wrapped is reachable through {mono('redis.client')}
            .
          </>,
        )}
      </>
    ),
  },
  {
    id: 'clusters',
    group: 'Guides',
    label: 'Clusters',
    title: 'Clusters',
    lede: 'One instance, several isolated scheduling domains — production and staging on the same hardware, sharing nothing.',
    body: () => (
      <>
        {h2('what', 'What a cluster owns')}
        {p(
          'A cluster has its own namespaces, functions, configuration store, data services, nodes and metrics. Nothing crosses the boundary, so two clusters can both hold a namespace called payments and a variable called DATABASE_URL without colliding.',
        )}
        {table(
          ['Scoped to a cluster', 'Shared by the instance'],
          [
            ['Namespaces and functions', 'User accounts and roles'],
            ['Global env and secrets', 'The administrator password'],
            ['PostgreSQL and Redis', 'The root encryption key'],
            ['Nodes and scheduling', 'The edge and its certificates'],
            ['Invocations, logs, metering', 'The instance version'],
          ],
        )}

        {h2('create', 'Creating one')}
        {p(
          <>
            Use the switcher at the top of the sidebar, or <strong>Settings → Clusters</strong>.
            A cluster is a row plus the local engine registered against it — it costs nothing
            until you deploy into it, which is what makes a throwaway preview cluster
            reasonable.
          </>,
        )}
        {code(
          <>
            <span className="text-ink-3">$</span> cubicle clusters{'\n\n'}
            {'  '}CLUSTER{'       '}NAME{'          '}BASE URL{'\n'}
            {'  '}* prod-cluster{'  '}Production{'    '}https://fn.example.com/{'\n'}
            {'    '}staging{'       '}Staging{'       '}https://fn.example.com/staging/
          </>,
        )}

        {h2('addressing', 'How a request finds its cluster')}
        {p('Every endpoint names its cluster. There are two ways to do that:')}
        {table(
          ['Rule', 'Example'],
          [
            [
              'A hostname pointed at the cluster',
              'https://staging.example.com/payments/charge',
            ],
            ['The cluster slug in the path', 'https://example.com/staging/payments/charge'],
          ],
        )}
        {note(
          <>
            <strong>There is no unqualified form.</strong> A bare{' '}
            {mono('/<namespace>/<function>')} is refused with a 404 naming the clusters that do
            hold it — every cluster could own that namespace, and if the default one answered,
            changing the default would quietly change what an existing URL addressed. A cluster
            with its own hostname is the exception: the host already identifies it, so the slug
            leaves the path.
          </>,
        )}

        {h2('clients', 'Console and CLI')}
        {p(
          <>
            The console sends the active cluster on every request and remembers your choice
            between sessions. The CLI takes {mono('--cluster <slug>')}, reads{' '}
            {mono('CUBICLE_CLUSTER')}, or falls back to the default.
          </>,
        )}
        {code(
          <>
            <span className="text-ink-3">$</span> cubicle --cluster staging deploy{'\n'}
            <span className="text-ink-3">$</span> cubicle --cluster staging logs --follow{'\n'}
            <span className="text-ink-3">$</span> CUBICLE_CLUSTER=staging cubicle ls
          </>,
        )}

        {h2('deleting', 'Deleting one')}
        {p(
          'Deleting a cluster stops its isolates, destroys its data services and removes its namespaces, functions and history. The default cluster cannot be deleted — make another one the default first — and the instance always keeps at least one.',
        )}
      </>
    ),
  },
  {
    id: 'scaling',
    group: 'Guides',
    label: 'Scaling & concurrency',
    title: 'Scaling and concurrency',
    lede: 'How many containers your function gets, who decides, and when they go away again.',
    body: () => (
      <>
        {h2('model', 'One request per isolate')}
        {p(
          <>
            An isolate is a container running one function version. It serves exactly one
            request at a time — the control plane marks it busy and will not hand it a second.
            Concurrency therefore comes from having more isolates, not from threads inside one.
          </>,
        )}
        {p(
          <>
            That is the whole scheduling model, and it is why your handler does not need to be
            thread-safe: nothing else is running in it.
          </>,
        )}

        {h2('bounds', 'The two numbers that matter')}
        {table(
          ['Setting', 'Default', 'What it does'],
          [
            [
              'Warm instances',
              '0',
              'Isolates kept resident even with no traffic. Above zero there is no cold start, at the cost of memory held permanently.',
            ],
            [
              'Max instances',
              '4',
              'Ceiling on concurrent isolates. Past it a request waits for a free one rather than starting another container.',
            ],
          ],
        )}
        {p(
          <>
            Both live on a function&apos;s <strong>Settings</strong> tab. Max instances is what
            stops one busy function from taking a whole node: with it at 4 and a 128 MB
            function, that endpoint can never hold more than 512 MB however hard it is hit.
          </>,
        )}
        {note(
          <>
            The instance-wide {mono('CUBICLE_ISOLATE_MAX_PER_FUNCTION')} (8) is a hard ceiling
            over the per-function setting. A function may restrain the platform, never overrule
            it. Raise the instance limit first if you need a function above it.
          </>,
        )}

        {h2('queue', 'What happens at the ceiling')}
        {p(
          <>
            Requests beyond the ceiling do not fail — they wait for an isolate to free up, for
            as long as the function&apos;s timeout allows. Only if nothing frees up in that
            window do they get a {mono('503')} naming the limit they hit.
          </>,
        )}
        {p(
          <>
            So max instances trades latency for memory. Ten simultaneous requests against a cap
            of 2 all succeed; five of them just queue.
          </>,
        )}

        {h2('spread', 'Work is spread, not stacked')}
        {p(
          <>
            When several isolates are warm, an incoming request goes to the one that has served
            the fewest so far. Load converges on an even split rather than piling onto whichever
            container happened to start first — 60 sequential requests across five isolates land
            close to 12 each.
          </>,
        )}

        {h2('down', 'Coming back down')}
        {p(
          'A pool that grew during a burst gives the containers back in two stages, on separate timers.',
        )}
        {table(
          ['Stage', 'Setting', 'Behaviour'],
          [
            [
              'Shed the surplus',
              'CUBICLE_ISOLATE_SCALEDOWN_WINDOW (60 s)',
              'Once concurrency has not been seen for this long, the reconcile loop reclaims one isolate per pass while the pool is wider than recent demand.',
            ],
            [
              'Go cold',
              'CUBICLE_ISOLATE_IDLE_TTL (900 s)',
              'The last isolate is reclaimed after this much idleness. The function then costs nothing but a database row.',
            ],
          ],
        )}
        {p(
          <>
            Two timers rather than one because they answer different questions. Spreading work
            evenly keeps every isolate&apos;s last-used timestamp fresh, so idle time alone
            would never shrink a pool that grew during a spike — eight isolates each taking an
            eighth of the traffic all look busy enough to keep.
          </>,
        )}
        {p(
          <>
            The reconcile loop runs every {mono('CUBICLE_RECONCILE_INTERVAL')} seconds (30), so
            a pool of six drains to one in roughly two and a half minutes of quiet.
          </>,
        )}

        {h2('cold', 'Cold starts')}
        {p(
          <>
            A cold start is container create, start and agent readiness — a few hundred
            milliseconds for a small function, longer if {mono('requirements.txt')} pulled in
            something heavy. Warm invocations are 2–5 ms of platform overhead on top of your
            handler.
          </>,
        )}
        {p(
          <>
            Every response carries {mono('X-Cubicle-Cold-Start')}, so you can tell which kind
            you got without guessing. Set warm instances above zero on latency-critical paths.
          </>,
        )}
        {note(
          <>
            A cold start is <strong>not</strong> billed as compute when the isolate fails to
            become ready — a {mono('503')} never reached your handler, so it records no
            GB-seconds.
          </>,
        )}
      </>
    ),
  },
  {
    id: 'observability',
    group: 'Guides',
    label: 'Observability',
    title: 'Observability',
    lede: 'Watching the cluster work: the live activity stream, logs, metrics and Prometheus.',
    body: () => (
      <>
        {h2('live', 'Live activity')}
        {p(
          <>
            <strong>Live activity</strong> streams the runtime&apos;s own events over
            server-sent events and animates them: requests travelling from the edge through the
            router to a function, isolates appearing while they boot, pulsing while they serve
            and shrinking away when the pool reclaims them.
          </>,
        )}
        {p(
          'It is the fastest way to see what the scheduler is actually doing — whether a burst is fanning out or queueing at the ceiling, which isolates are carrying the load, how long cold starts really take.',
        )}
        {table(
          ['Panel', 'Shows'],
          [
            ['Request path', 'Each function, its warm and busy isolates, and its ceiling.'],
            ['Invocations / second', 'Throughput over the last minute.'],
            ['Latency', 'Recent durations on a log scale — cold starts are the outliers.'],
            ['Isolates', 'Every container, its state, request count and memory.'],
            ['Event stream', 'The raw events, newest first.'],
          ],
        )}
        {p(
          <>
            <strong>Send traffic</strong> generates load so an idle cluster has something to
            show: choose a function, how many requests go out at once, how many times to repeat,
            and how long to wait between rounds. Requests at once is the interesting one — it is
            what makes the pool widen instead of reusing a single isolate.
          </>,
        )}
        {note(
          <>
            Those are real invocations through the real endpoint. They are recorded, metered and
            logged like any other request, so do not point the generator at something with side
            effects you would not want repeated.
          </>,
        )}

        {h2('logs', 'Logs')}
        {p(
          <>
            Anything your handler prints, plus control-plane events, lands in{' '}
            <strong>Logs &amp; monitoring</strong> — filterable by level, function and free
            text, paginated, and tailing live while you are on the newest page. Logs are kept
            for 14 days and then pruned.
          </>,
        )}
        {code(
          <>
            <span className="text-ink-3">$</span> cubicle logs --follow{'\n'}
            <span className="text-ink-3">$</span> cubicle logs --function create-charge
          </>,
        )}

        {h2('function', 'Per-function detail')}
        {p(
          <>
            A function&apos;s own page carries its invocation count, p50/p90/p95/p99, error
            rate, cold-start rate, metered GB-seconds, its version history with build times, and
            its recent log lines.
          </>,
        )}

        {h2('prometheus', 'Prometheus')}
        {p(
          <>
            {mono('/metrics')} is a standard Prometheus endpoint. Scrape it directly; it needs
            no authentication and carries no request payloads.
          </>,
        )}
        {table(
          ['Metric', 'Type', 'Labels'],
          [
            ['cubicle_invocations_total', 'counter', 'namespace, function, status'],
            ['cubicle_invocation_duration_seconds', 'histogram', 'namespace, function'],
            ['cubicle_cold_starts_total', 'counter', 'namespace, function'],
            ['cubicle_builds_total', 'counter', 'result'],
            ['cubicle_warm_isolates', 'gauge', '—'],
            ['cubicle_gb_seconds_total', 'counter', 'namespace, function'],
          ],
        )}

        {h2('health', 'Health')}
        {p(
          <>
            {mono('/healthz')} reports the database, Redis and Docker engine separately, so a
            failing check names what is wrong rather than returning a bare 500. It is what the
            container healthcheck and any external monitor should watch.
          </>,
        )}
      </>
    ),
  },
  {
    id: 'config',
    group: 'Reference',
    label: 'cubicle.toml',
    title: 'cubicle.toml',
    lede: 'The manifest that ties a source directory to a deployed function.',
    body: () => (
      <>
        {h2('example', 'Example')}
        {code(
          <>
            <span className="text-ink-3">[function]</span>
            {'\n'}
            name{'       '}= <span className="text-ok">&quot;create-charge&quot;</span>
            {'\n'}
            namespace{'  '}= <span className="text-ok">&quot;payments&quot;</span>
            {'\n'}
            runtime{'    '}= <span className="text-ok">&quot;python3.12&quot;</span>
            {'\n'}
            entrypoint = <span className="text-ok">&quot;handler.handler&quot;</span>
            {'\n'}
            method{'     '}= <span className="text-ok">&quot;POST&quot;</span>
            {'\n\n'}
            <span className="text-ink-3">[resources]</span>
            {'\n'}
            memory_mb{'     '}= <span className="text-warn">512</span>
            {'\n'}
            timeout_s{'     '}= <span className="text-warn">30</span>
            {'\n'}
            min_instances = <span className="text-warn">0</span>
            {'\n'}
            max_instances = <span className="text-warn">4</span>
            {'\n'}
            node_pool{'     '}= <span className="text-ok">&quot;general&quot;</span>
            {'\n\n'}
            <span className="text-ink-3">[context]</span>
            {'\n'}
            access = <span className="text-ok">&quot;read+write&quot;</span>
            {'\n'}
            header = <span className="text-ok">&quot;X-Cubicle-Session&quot;</span>
            {'\n'}
            ttl{'    '}= <span className="text-ok">&quot;30m&quot;</span>
          </>,
          'cubicle.toml',
        )}

        {h2('what', 'What it is read for')}
        {p(
          <>
            {mono('cubicle deploy')} reads exactly two keys from this file:{' '}
            {mono('function.namespace')} and {mono('function.name')}. They are how a directory
            on your machine finds the function it belongs to, so that deploying is {mono('cd')}{' '}
            and one command with no arguments.
          </>,
        )}
        {note(
          <>
            <strong>The remaining sections are a record, not a control.</strong> They are
            written by {mono('cubicle init')} to reflect the function&apos;s settings at that
            moment, and they ship with the bundle so the deployed source is self-describing —
            but the control plane does not apply them. Changing {mono('memory_mb')} here does
            not change the memory the function runs with.
          </>,
        )}
        {p(
          <>
            Resource settings are owned by the function itself, on its <strong>Settings</strong>{' '}
            tab or through {mono('PATCH /api/functions/{id}')}. That is deliberate: an old
            checkout redeploying a stale manifest would otherwise silently roll back a limit
            someone raised in the console.
          </>,
        )}

        {h2('options', 'Fields')}
        {table(
          ['Key', 'Read by deploy', 'Notes'],
          [
            ['function.namespace', 'yes', 'Which namespace to deploy into. Required.'],
            ['function.name', 'yes', 'Which function. Required, and it must already exist.'],
            ['function.runtime', 'no', 'Mirrors the interpreter the function is set to use.'],
            ['function.method', 'no', 'Mirrors the method the endpoint accepts.'],
            ['resources.*', 'no', 'Mirrors memory, timeout, warm instances and node pool.'],
            ['context.*', 'no', 'Mirrors the session context access mode and TTL.'],
          ],
        )}

        {h2('bundle', 'What gets deployed')}
        {p(
          <>
            A deploy sends four files and nothing else: {mono('handler.py')} (required),{' '}
            {mono('requirements.txt')}, {mono('cubicle.toml')} and {mono('README.md')}. Anything
            else in the directory is ignored, so a virtualenv or a test folder sitting next to
            the handler costs nothing.
          </>,
        )}
      </>
    ),
  },
  {
    id: 'cli',
    group: 'Reference',
    label: 'CLI',
    title: 'CLI reference',
    lede: 'Every console action is available from the terminal — the console is a client of the same API.',
    body: () => (
      <>
        {h2('install', 'Install')}
        {code(
          <>
            <span className="text-ink-3">$</span> pipx install ./cli{'\n'}
            <span className="text-ink-3">$</span> cubicle login http://localhost:7000{'\n'}
            <span className="text-ink-3">?</span> token:{' '}
            <span className="text-ink-3">cbcl_••••</span>
            {'\n'}
            {'  '}
            <span className="text-ok">authenticated</span> · prod-cluster
          </>,
        )}
        {p(
          <>
            Credentials are written to {mono('~/.cubicle/config.toml')}. Create tokens under{' '}
            <strong>Settings → API keys</strong>; setup issues the first one for you.
          </>,
        )}

        {h2('commands', 'Commands')}
        {table(
          ['Command', 'Description'],
          [
            ['cubicle login <url>', 'Authenticate and store the profile.'],
            ['cubicle clusters', 'List the clusters on this instance.'],
            ['cubicle status', 'Control plane, node and isolate health.'],
            ['cubicle ls', 'List namespaces and functions.'],
            ['cubicle init <ns>/<name>', 'Scaffold a function directory locally.'],
            ['cubicle deploy [dir]', 'Bundle a directory and deploy it.'],
            [
              'cubicle invoke <ns>/<name>',
              'Send a test event and print the response with timing.',
            ],
            ['cubicle logs [--follow]', 'Show or follow structured logs.'],
            ['cubicle env ls | set KEY=value | rm KEY', 'Cluster-wide configuration.'],
            ['cubicle secrets ls | set KEY | rm KEY', 'Per-function secrets.'],
          ],
        )}
        {p(
          <>
            Every command takes {mono('--cluster <slug>')}, and each of them honours{' '}
            {mono('CUBICLE_CLUSTER')} when it is not given.
          </>,
        )}

        {h2('api', 'HTTP API')}
        {p(
          <>
            The full OpenAPI document is served at {mono('/api/openapi.json')} with a browsable
            UI at {mono('/api/docs')}. Authenticate with {mono('Authorization: Bearer cbcl_…')}.
          </>,
        )}
      </>
    ),
  },
  {
    id: 'access',
    group: 'Reference',
    label: 'Access & API keys',
    title: 'Access and API keys',
    lede: 'Who can do what, and how machines authenticate.',
    body: () => (
      <>
        {h2('sessions', 'Signing in')}
        {p(
          <>
            There is no registration. Setup creates a single administrator and its password, and
            that account can add more users afterwards. A browser session is an opaque token
            held in Redis and sent as an httpOnly cookie — nothing about the session lives in
            the token itself, so signing out revokes it server-side.
          </>,
        )}
        {p(
          <>
            Passwords are hashed with Argon2id. Repeated failures against one account are rate
            limited.
          </>,
        )}

        {h2('roles', 'Roles')}
        {table(
          ['Role', 'Can'],
          [
            ['readonly', 'View everything: functions, logs, metrics, configuration keys.'],
            ['developer', 'Everything above, plus create, edit, deploy and delete functions.'],
            ['admin', 'Everything above, plus data services, nodes, API keys and settings.'],
            ['owner', 'Everything above, plus deleting clusters and users.'],
          ],
        )}

        {h2('keys', 'API keys')}
        {p(
          <>
            Machines authenticate with a bearer token from <strong>Settings → API keys</strong>.
            A key is shown once, at creation; only an HMAC of it is stored, so a database dump
            does not yield usable credentials and a lost key can only be replaced, never
            recovered.
          </>,
        )}
        {code(
          <>
            <span className="text-ink-3">$</span> curl
            https://fn.example.com/prod-cluster/payments/create-charge \{'\n'}
            {'    '}-H <span className="text-ok">&apos;Authorization: Bearer cbcl_…&apos;</span>{' '}
            \{'\n'}
            {'    '}-d <span className="text-ok">&apos;{'{"amount": 4200}'}&apos;</span>
          </>,
        )}
        {p(
          <>
            A key may be scoped to one cluster or left instance-wide. Revoking takes effect on
            the next request.
          </>,
        )}

        {h2('public', 'Public endpoints')}
        {p(
          <>
            A function requires a key by default. Turning off{' '}
            <strong>Require an API key</strong> makes the endpoint public, which is what you
            want for an inbound webhook whose sender cannot carry your credentials — verify the
            provider&apos;s own signature inside the handler instead.
          </>,
        )}

        {h2('http', 'The HTTP API')}
        {p(
          <>
            The console is a client of the same API you have. The full OpenAPI document is at{' '}
            {mono('/api/openapi.json')}, with a browsable UI at {mono('/api/docs')}. Every
            cluster-scoped endpoint takes the cluster from an {mono('X-Cubicle-Cluster')}{' '}
            header, a {mono('?cluster=')} parameter, or the key&apos;s own scope.
          </>,
        )}
      </>
    ),
  },
  {
    id: 'troubleshooting',
    group: 'Reference',
    label: 'Troubleshooting',
    title: 'Troubleshooting',
    lede: 'What the common failures look like and what actually causes them.',
    body: () => (
      <>
        {h2('responses', 'Responses from an endpoint')}
        {table(
          ['You see', 'Cause'],
          [
            [
              '404 not_found',
              'No function at that path in that cluster. The response names the clusters that do hold it.',
            ],
            [
              '401 unauthorized',
              'The function requires an API key and none was sent, or the key was revoked.',
            ],
            [
              '405 method_not_allowed',
              'A function accepts one method. The Allow header says which.',
            ],
            [
              '503 not_deployed',
              'The function has never built successfully. Check the build log on its Code tab.',
            ],
            [
              '503 isolate_unavailable',
              'The container never became ready — usually a dependency that fails at import. Its output is in the logs.',
            ],
            [
              '504',
              'The handler exceeded its timeout. Its isolate is destroyed, since a runaway thread cannot be reclaimed any other way.',
            ],
            ['502 invocation_failed', 'The handler raised. The traceback is in the logs.'],
          ],
        )}

        {h2('builds', 'Builds')}
        {p(
          <>
            A failed build never replaces the running version — the deploy is rejected and
            traffic keeps going to the last good one. The full build log is on the
            function&apos;s <strong>Code</strong> tab.
          </>,
        )}
        {p(
          <>
            Builds run in a container with no network restrictions of their own, so a private
            index needs its credentials in {mono('requirements.txt')} the usual pip way, and a
            dependency that needs a compiler will fail unless the runtime image has one.
          </>,
        )}

        {h2('cold', 'Everything feels slow')}
        {p(
          <>
            Check the cold-start rate on the dashboard. If it is high, traffic is arriving
            spread further apart than {mono('CUBICLE_ISOLATE_IDLE_TTL')} and every request is
            paying for a container start — set warm instances to 1. If latency is high but cold
            starts are not, the handler itself is the cost, and the per-function latency chart
            will show it.
          </>,
        )}

        {h2('platform', 'Platform')}
        {table(
          ['Symptom', 'Cause'],
          [
            [
              'Console loads, nothing works',
              'Check /healthz — it reports database, Redis and Docker separately.',
            ],
            [
              'docker: false',
              'The api container lost the Docker socket. Nothing can be built or invoked until it is back.',
            ],
            [
              'Isolates vanish after a restart',
              'Expected on a version change: adopt keeps only isolates whose version is still current.',
            ],
            [
              '"root key changed" instead of a secret',
              'CUBICLE_MASTER_KEY is not the one that encrypted it. Restore the original .env; there is no recovery path.',
            ],
            [
              'Port already in use',
              'Something else holds the port. On macOS, AirPlay Receiver holds 7000 — the installer detects this and picks another.',
            ],
          ],
        )}

        {h2('reset', 'Starting over')}
        {p(
          <>
            {mono('docker compose down -v')} removes the containers and every volume, including
            the control-plane database and any managed PostgreSQL. It is a complete reset with
            no confirmation, so be sure that is what you want.
          </>,
        )}
      </>
    ),
  },
]
