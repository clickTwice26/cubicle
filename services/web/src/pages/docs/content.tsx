import type { ReactNode } from 'react'

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
  <div className="mb-6 overflow-hidden rounded-xl border border-line bg-panel">
    {filename ? (
      <div className="border-b border-line px-3.5 py-2 font-mono text-[11.5px] text-ink-3">
        {filename}
      </div>
    ) : null}
    <pre className="m-0 overflow-x-auto px-4.5 py-4 font-mono text-[13px] leading-[1.75] text-ink">
      {children}
    </pre>
  </div>
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
    id: 'config',
    group: 'Reference',
    label: 'cubicle.toml',
    title: 'cubicle.toml',
    lede: 'Per-function configuration, kept next to the source and editable from either side.',
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

        {h2('options', 'Options')}
        {table(
          ['Key', 'Default', 'Notes'],
          [
            ['resources.memory_mb', '512', 'Hard cap. The isolate is killed on overrun.'],
            ['resources.timeout_s', '30', 'Wall clock per invocation, up to 900.'],
            [
              'resources.min_instances',
              '0',
              'Isolates kept resident. Above 0 removes cold starts at the cost of held memory.',
            ],
            ['resources.node_pool', '"general"', 'Schedules onto a labelled pool of nodes.'],
            [
              'context.access',
              '"read+write"',
              'read+write, read only, write only, or no access.',
            ],
            ['function.method', '"POST"', 'The single method this endpoint accepts.'],
          ],
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
            ['cubicle status', 'Control plane, node and isolate health.'],
            ['cubicle init <ns>/<name>', 'Scaffold a function directory locally.'],
            ['cubicle deploy', 'Bundle the current directory and deploy it.'],
            [
              'cubicle invoke <ns>/<name>',
              'Send a test event and print the response with timing.',
            ],
            ['cubicle logs [--follow]', 'Tail structured logs across functions.'],
            ['cubicle env set KEY=value', 'Write a cluster-wide variable.'],
            ['cubicle secrets set KEY', 'Create or rotate a per-function secret.'],
            ['cubicle ls', 'List namespaces and functions.'],
          ],
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
]
