# How Cubicle works

A complete description of the platform: who uses it, what the pieces are, and
exactly what happens on a request. Every diagram here is drawn from the code —
where a number appears it is the real default, and the file that implements the
behaviour is linked.

**Contents**

1. [At a glance](#1-at-a-glance)
2. [Actors and use cases](#2-actors-and-use-cases)
3. [Deployment view](#3-deployment-view)
4. [Data model](#4-data-model)
5. [Sequence — first-run setup](#5-sequence--first-run-setup)
6. [Sequence — deploying a function](#6-sequence--deploying-a-function)
7. [Sequence — invoking a function](#7-sequence--invoking-a-function)
8. [Activity — the request pipeline](#8-activity--the-request-pipeline)
9. [Activity — isolate lifecycle](#9-activity--isolate-lifecycle)
10. [Activity — finding the cluster](#10-activity--finding-the-cluster)
11. [The reconcile loop](#11-the-reconcile-loop)
12. [Trust boundaries](#12-trust-boundaries)
13. [Failure modes](#13-failure-modes)
14. [Where things live](#14-where-things-live)

---

## 1. At a glance

Cubicle runs Python functions on hardware you own. A function is source code
plus a resource envelope; the platform builds it into an immutable version,
starts a container to serve it, keeps that container warm between requests, and
reclaims it when it goes idle.

Five long-lived containers make up an instance:

| Container | Role |
| --- | --- |
| `caddy` | TLS termination, ACME, routing. The only thing bound to a host port. |
| `web` | The console — a static React bundle. |
| `api` | Control plane: API, scheduler, isolate pool, builder. Holds the Docker socket. |
| `postgres` | All durable state. |
| `redis` | Sessions, the session context store, the live log channel. |

Plus containers the control plane creates on demand: one **isolate** per warm
function version, and optionally a managed PostgreSQL and Redis per cluster.

An instance holds one or more **clusters**. A cluster is an isolated scheduling
domain — its own namespaces, configuration, data services, nodes and metrics.
Nothing crosses the boundary.

```
instance
└── cluster (prod-cluster)
    ├── node-01                          a Docker engine
    ├── namespace (payments)
    │   └── function (create-charge)
    │       └── version 3  →  volume  →  isolate ×N
    ├── env store
    └── PostgreSQL, Redis
```

---

## 2. Actors and use cases

Who touches the system, and what for. Boxes are use cases; edges are "this
actor does this".

```mermaid
flowchart LR
    Operator([Operator<br/>owner / admin])
    Developer([Developer])
    Caller([Caller<br/>webhook, service, browser])
    CI([CI pipeline])
    Engine([Docker Engine])
    ACME([Let's Encrypt])

    subgraph Cubicle[" Cubicle instance "]
        direction TB

        subgraph Setup[" First run "]
            U1["Choose the admin password"]
            U2["Name the first cluster"]
            U3["Select schedulable nodes"]
        end

        subgraph Admin[" Administration "]
            U4["Create and switch clusters"]
            U5["Add nodes, drain a node"]
            U6["Manage users and roles"]
            U7["Issue and revoke API keys"]
            U8["Provision PostgreSQL / Redis"]
        end

        subgraph Build[" Building "]
            U9["Create a namespace"]
            U10["Create a function"]
            U11["Edit source, deploy a version"]
            U12["Set global env and secrets"]
            U13["Test invoke from the console"]
        end

        subgraph Observe[" Observing "]
            U14["Read dashboard metrics"]
            U15["Tail logs live"]
            U16["Review metering and chargeback"]
            U17["Scrape Prometheus"]
        end

        U18["Invoke a function over HTTP"]
    end

    Operator --> U1 & U2 & U3
    Operator --> U4 & U5 & U6 & U7 & U8
    Operator --> U16

    Developer --> U9 & U10 & U11 & U12 & U13
    Developer --> U14 & U15

    CI --> U11
    CI --> U18

    Caller --> U18

    U18 -.->|starts isolates| Engine
    U8 -.->|starts service containers| Engine
    U11 -.->|builds in a container| Engine
    U17 -.->|/metrics| Observe
    ACME -.->|issues certificates| Cubicle
```

**Roles** gate the administration column. `readonly` < `developer` < `admin` <
`owner`; deleting a cluster or a user requires `owner`, provisioning a data
service requires `admin`, deploying requires `developer`.
See [`deps.py`](../services/api/cubicle/deps.py).

---

## 3. Deployment view

Containers, the networks that join them, and what crosses each boundary.

```mermaid
flowchart TB
    client([Internet / LAN])

    subgraph host[" Docker host "]
        subgraph edge[" network: cubicle_edge "]
            caddy["caddy<br/><i>:80 :443 published</i>"]
            web["web<br/><i>static console</i>"]
            api["api<br/><i>control plane, scheduler,<br/>isolate pool, builder</i>"]
        end

        subgraph core[" network: cubicle_core — not published "]
            pg[("postgres<br/><i>control-plane state</i>")]
            rd[("redis<br/><i>sessions, ctx, log bus</i>")]
        end

        subgraph fn[" network: cubicle_fn — not published "]
            iso1["isolate<br/><i>fn A v3</i>"]
            iso2["isolate<br/><i>fn B v1</i>"]
            svcpg[("managed<br/>PostgreSQL")]
            svcrd[("managed<br/>Redis")]
        end

        sock{{"/var/run/docker.sock"}}
        vol[["version volumes<br/><i>cubicle-fn-…-vN</i>"]]
    end

    client -->|"HTTPS"| caddy
    caddy -->|"/ , /console, /docs"| web
    caddy -->|"/api/*, /healthz, /metrics"| api
    caddy -->|"/&lt;cluster&gt;/&lt;ns&gt;/&lt;fn&gt;<br/>rewritten to /api/invoke/…"| api

    api --> pg
    api --> rd
    api -->|"POST /invoke"| iso1
    api -->|"POST /invoke"| iso2
    api -.->|"create, start, remove"| sock
    sock -.-> iso1 & iso2 & svcpg & svcrd

    iso1 -.->|"read-only"| vol
    iso2 -.->|"read-only"| vol
    iso1 --> svcpg & svcrd
```

Notes that matter:

- **Only `caddy` is published.** Isolates and data services are reachable from
  the control plane and from each other, never from the host.
- **The `api` container holds the Docker socket.** That is how it starts
  isolates, and it is the instance's trust boundary — see
  [§12](#12-trust-boundaries).
- **Function code never travels on a shared filesystem.** Each version gets its
  own Docker volume, mounted read-only, so an isolate cannot see another
  function's source.

---

## 4. Data model

Everything durable lives in one PostgreSQL database.
See [`models.py`](../services/api/cubicle/models.py).

```mermaid
erDiagram
    INSTANCE ||--o{ CLUSTER : "hosts"
    INSTANCE ||--o{ USER : "has"

    CLUSTER ||--o{ NODE : "schedules onto"
    CLUSTER ||--o{ GROUP : "owns"
    CLUSTER ||--o{ ENV_VAR : "owns"
    CLUSTER ||--o{ MANAGED_SERVICE : "owns"
    CLUSTER ||--o{ INVOCATION : "records"
    CLUSTER ||--o{ LOG_ENTRY : "records"
    CLUSTER ||--o{ API_KEY : "may scope"

    GROUP ||--o{ FUNCTION : "contains"
    FUNCTION ||--o{ FUNCTION_VERSION : "has"
    FUNCTION ||--o{ FUNCTION_SECRET : "has"
    FUNCTION ||--o{ INVOCATION : "produces"
    FUNCTION ||--|| FUNCTION_VERSION : "current"

    USER ||--o{ API_KEY : "created"

    INSTANCE {
        int id PK "always 1"
        bool setup_complete
        string version
    }
    CLUSTER {
        uuid id PK
        string slug UK
        string ingress_domain "empty means path-addressed"
        bool is_default
        string kms_backend
    }
    NODE {
        uuid id PK
        string name "unique per cluster"
        string docker_host
        string pool
        bool schedulable
    }
    GROUP {
        uuid id PK
        string ns "unique per cluster"
    }
    FUNCTION {
        uuid id PK
        string name "unique per group"
        string method
        string runtime
        string ctx_access "rw r w none"
        int memory_mb
        int timeout_s
        int min_instances
        bool auth_required
    }
    FUNCTION_VERSION {
        uuid id PK
        int number
        jsonb files
        string status "pending building ready failed"
        text build_log
    }
    ENV_VAR {
        uuid id PK
        string key "unique per cluster"
        text value_ciphertext
        bool is_secret
    }
    INVOCATION {
        uuid id PK
        float duration_ms
        int status_code
        bool cold
        float gb_seconds
        bigint egress_bytes
    }
```

Two constraints carry a lot of weight:

- `ns` is unique **per cluster**, not globally. Two clusters may both own
  `payments`.
- `FUNCTION.current_version_id` is what serves traffic. Building a new version
  does not touch it until the build succeeds — that is the atomic swap.

---

## 5. Sequence — first-run setup

There is no registration. The first person to open the console creates the only
account. See [`routers/setup.py`](../services/api/cubicle/routers/setup.py).

```mermaid
sequenceDiagram
    autonumber
    actor Op as Operator
    participant Web as Console
    participant API as Control plane
    participant PG as PostgreSQL
    participant RD as Redis
    participant DK as Docker Engine

    Op->>Web: open the instance
    Web->>API: GET /api/setup/status
    API-->>Web: setup_complete = false
    Web-->>Op: show the wizard

    Web->>API: GET /api/setup/nodes
    API->>DK: engine info
    DK-->>API: CPUs, memory, arch, version
    API-->>Web: the engine it can already see

    Op->>Web: name, email, password, cluster, nodes
    Web->>API: POST /api/setup

    API->>API: check password policy
    Note over API: argon2id hash — the plaintext<br/>is never stored or logged

    rect rgb(24,28,20)
        Note over API,PG: step 1 — credentials
        API->>PG: INSERT user (owner)
        API->>PG: INSERT api_key (first CLI token)
    end

    rect rgb(24,28,20)
        Note over API,PG: step 2 — the first cluster
        API->>PG: INSERT cluster (is_default = true)
        API->>PG: UPDATE instance SET setup_complete = true
    end

    API->>RD: create session
    API-->>Web: Set-Cookie + the CLI token, shown once
    Note over API: the rest runs in the background<br/>while the wizard animates

    par background provisioning
        API->>DK: register the local engine as node-01
        API->>PG: INSERT node
        API->>RD: progress: nodes done
        API->>DK: ensure the cubicle_fn network
        API->>RD: progress: ingress done
        API->>DK: are the runtime images present?
        API->>RD: progress: runtimes done
    and the wizard watches
        Web->>API: GET /api/setup/progress (SSE)
        API-->>Web: step events until complete
    end

    Web-->>Op: cluster ready — open the console
```

If a runtime image is missing the step is marked **failed** rather than silently
skipped, because nothing will deploy without it.

---

## 6. Sequence — deploying a function

A deploy produces an immutable version. The running version keeps serving until
the new one is proven good.
See [`runtime/builder.py`](../services/api/cubicle/runtime/builder.py) and
[`routers/functions.py`](../services/api/cubicle/routers/functions.py).

```mermaid
sequenceDiagram
    autonumber
    actor Dev as Developer
    participant Web as Console / CLI
    participant API as Control plane
    participant PG as PostgreSQL
    participant DK as Docker Engine
    participant BC as Build container
    participant Pool as Isolate pool

    Dev->>Web: Save & deploy
    Web->>API: POST /api/functions/{id}/deploy {files}

    API->>API: validate — handler.py required,<br/>known filenames, bundle under 2 MB
    API->>PG: INSERT function_version (number+1, status=building)
    API-->>Web: 202-style: version is building

    API->>DK: remove any stale volume for this version
    API->>DK: create volume cubicle-fn-{fn}-v{n}
    API->>DK: create container from the runtime image,<br/>volume mounted rw at /srv, command = sleep
    API->>BC: start
    API->>BC: put_archive(/srv, source tarball)
    Note over BC: copying into a *running* container<br/>lands inside the mounted volume

    API->>BC: exec mkdir -p /srv/.deps && chmod -R a+rX /srv

    alt requirements.txt has real entries
        API->>BC: exec pip install -r requirements.txt -t /srv/.deps
        BC-->>API: exit code + output (tail kept as the build log)
    else nothing declared
        Note over API,BC: skipped — most functions need no build step
    end

    API->>BC: exec chmod -R a+rX /srv
    API->>DK: remove the build container

    alt build succeeded
        API->>PG: version.status = ready, deployed_at = now
        API->>PG: function.current_version_id = this version
        Note over API: the swap — from here, new requests<br/>resolve to the new version
        API->>Pool: drain isolates of the previous version
        API->>PG: INSERT log_entry "deployed version N"
    else build failed
        API->>PG: version.status = failed, build_log = output
        Note over API: current_version_id untouched —<br/>the running version is unaffected
        API->>PG: INSERT log_entry "build failed"
    end

    Web->>API: GET /api/functions/{id} (polling)
    API-->>Web: version_status + build_log
    Web-->>Dev: deployed, or the build log to read
```

**Why a volume and not a bind mount.** The volume is created on the node that
will run the function, so this works identically for the local engine and for a
remote one over TCP. Nothing depends on a shared host path.

---

## 7. Sequence — invoking a function

### 7a. Cold start

No warm isolate exists, so one is created. Measured at ~400 ms on a 2-core
machine.

```mermaid
sequenceDiagram
    autonumber
    actor C as Caller
    participant CA as Caddy
    participant API as Control plane
    participant PG as PostgreSQL
    participant RD as Redis
    participant DK as Docker Engine
    participant IS as Isolate agent

    C->>CA: POST /prod-cluster/payments/create-charge
    CA->>API: rewritten to /api/invoke/…

    API->>PG: resolve cluster, namespace, function
    API->>API: guards — paused? method? auth? version ready?
    API->>PG: read the current version

    API->>RD: read session context for this namespace
    API->>PG: read env vars + function secrets
    Note over API: decrypted in memory only

    API->>API: pool.acquire — no idle isolate, room to grow

    rect rgb(32,26,20)
        Note over API,IS: cold start
        API->>DK: run container<br/>image = runtime, volume ro at /srv,<br/>mem/cpu capped, read-only rootfs,<br/>caps dropped, user 65532
        DK-->>API: container id + IP on cubicle_fn
        loop until ready, 30 s budget
            API->>IS: GET /healthz
            IS-->>API: ready = false (still importing)
        end
        Note over IS: import handler.py once,<br/>keep the callable in memory
        IS-->>API: ready = true
    end

    API->>IS: POST /invoke {event, env, secrets, ctx, service URLs}
    IS->>IS: run handler on a worker thread
    IS-->>API: {status_code, body, logs, context_writes}

    API->>RD: merge context writes, append the write log
    API->>API: release the isolate back to the pool
    API-->>CA: response + X-Cubicle-Cold-Start: 1
    CA-->>C: response

    par recorded out of band
        API->>PG: INSERT invocation (duration, gb_seconds, egress)
        API->>PG: INSERT log entries
        API->>RD: PUBLISH to the live log channel
    end
```

### 7b. Warm

The same request when an isolate already exists — 2–5 ms of platform overhead.

```mermaid
sequenceDiagram
    autonumber
    actor C as Caller
    participant CA as Caddy
    participant API as Control plane
    participant RD as Redis
    participant IS as Isolate agent

    C->>CA: POST /prod-cluster/payments/create-charge
    CA->>API: /api/invoke/…
    API->>API: resolve + guards (cached env, 1 Redis GET)
    API->>RD: read session context
    API->>API: pool.acquire — idle isolate found, mark busy
    API->>IS: POST /invoke (keep-alive connection)
    Note over IS: module already imported —<br/>this is a Python function call
    IS-->>API: response
    API->>RD: apply context writes
    API-->>CA: X-Cubicle-Cold-Start: 0
    CA-->>C: response
```

The whole difference is the boxed section in 7a. Nothing is spawned per
invocation in either path.

---

## 8. Activity — the request pipeline

Every decision an invocation passes through, in order.
See [`routers/invoke.py`](../services/api/cubicle/routers/invoke.py).

```mermaid
flowchart TD
    A([Request arrives at Caddy]) --> B{"Path matches<br/>a console route?"}
    B -->|yes| B1[Serve the console] --> Z([Done])
    B -->|no| C{"Path looks like<br/>an invocation?"}
    C -->|no| C1[404 from the edge] --> Z
    C -->|yes| D[Rewrite to /api/invoke and forward]

    D --> E{"Resolve the cluster"}
    E -->|"no cluster named"| E1["404 cluster_required<br/>listing paths that would work"] --> Z
    E -->|resolved| F{"Function exists<br/>in this cluster?"}

    F -->|no| F1[404 not_found] --> Z
    F -->|yes| G{"Function paused?"}
    G -->|yes| G1[503 paused] --> Z
    G -->|no| H{"HTTP method<br/>matches?"}
    H -->|no| H1["405 with an Allow header"] --> Z
    H -->|yes| I{"auth_required<br/>and no valid key<br/>or session?"}
    I -->|yes| I1[401 unauthorized] --> Z
    I -->|no| J{"A version with<br/>status = ready?"}
    J -->|no| J1[503 not_deployed] --> Z
    J -->|yes| K{"Body under 6 MB?"}
    K -->|no| K1[413 too large] --> Z
    K -->|yes| L{"JSON body parses?"}
    L -->|no| L1[400 bad_request] --> Z
    L -->|yes| M[Pick a node in the function's pool]

    M --> N["Gather the payload:<br/>event, cluster env, function secrets,<br/>session context, data-service URLs"]
    N --> O{"pool.acquire"}

    O -->|"idle isolate"| P[Mark busy — warm]
    O -->|"room to grow"| Q[Cold start a container]
    O -->|"at the ceiling"| R{"Wait for a free one<br/>within the deadline"}
    R -->|freed| P
    R -->|"deadline passed"| R1[503 isolate_unavailable] --> Y

    Q -->|"never became ready"| Q1["Destroy it, log its output"] --> R1
    Q -->|ready| P

    P --> S[POST /invoke to the agent]
    S --> T{"Handler finished<br/>within timeout_s?"}
    T -->|no| T1["504 — destroy the isolate,<br/>a hung thread cannot be reclaimed"] --> Y
    T -->|yes| U{"Context access<br/>allows writing?"}
    U -->|yes| V[Merge writes into Redis, append the write log]
    U -->|no| W[Record the keys that were read]
    V --> X[Release the isolate as healthy]
    W --> X

    X --> Y["Record: invocation row, log rows,<br/>publish to the live channel,<br/>bump Prometheus counters"]
    Y --> Z
```

**Metering is honest about failures.** A 502 or 503 never reached the handler,
so it is recorded but charged `0` GB-seconds — billing a customer for a platform
failure would make the metering page a lie.
See [`runtime/invoker.py`](../services/api/cubicle/runtime/invoker.py).

---

## 9. Activity — isolate lifecycle

```mermaid
stateDiagram-v2
    [*] --> Starting: first request for a version

    Starting --> Ready: agent reports ready
    Starting --> Removed: not ready within 30 s

    Ready --> Busy: acquired for a request
    Busy --> Ready: released healthy
    Busy --> Removed: released unhealthy — timeout,<br/>transport error, agent crash

    Ready --> Removed: idle past CUBICLE_ISOLATE_IDLE_TTL<br/>and above min_instances
    Ready --> Removed: pool wider than recent peak concurrency
    Ready --> Removed: its version stopped being current
    Ready --> Removed: function deleted, paused,<br/>or its limits changed

    Ready --> Adopted: control plane restarted
    Adopted --> Ready: healthz passes and the version is still current
    Adopted --> Removed: stale version, or unreachable

    Removed --> [*]
```

Four properties fall out of this:

- **Scale to zero, in two stages.** The reconcile loop runs every 30 s. Once a
  function has been quiet for `CUBICLE_ISOLATE_SCALEDOWN_WINDOW` (60 s) it gives
  back the isolates a burst created, one per pass; the last one goes when it has
  been idle for `CUBICLE_ISOLATE_IDLE_TTL` (900 s), and the function then costs
  nothing but a database row. Verified: a 20-request burst against a cap of 6
  went 6 → 1 in 2.5 minutes.
- **Restarts stay warm.** Shutdown deliberately leaves isolates running; on the
  way back up `adopt` re-attaches to the ones whose version is still current and
  removes the rest. Verified: a request straight after a control-plane restart
  returned `X-Cubicle-Cold-Start: 0`.
- **Concurrency is isolates, not threads.** The control plane marks an isolate
  busy and will not give it a second request; parallelism comes from starting
  more of them, up to the function's own **max instances** (default 4) and never
  past the instance-wide `CUBICLE_ISOLATE_MAX_PER_FUNCTION` (8). At the ceiling a
  request waits for a free isolate rather than starting another container, which
  is what stops one busy function from taking a whole node. Verified: with the
  cap at 2, twenty-four concurrent requests ran on exactly two isolates.
- **Work is spread, not stacked.** `acquire` takes the *least-used* idle
  isolate, so traffic converges on an even split rather than piling onto
  whichever one happens to be first in the list — 60 sequential requests across
  five isolates landed 21/21/22/22/21. Spreading load keeps every isolate's
  last-used timestamp fresh, so idle-TTL alone would never shrink a pool that
  grew during a burst; the reconcile loop also trims one isolate per pass while
  the pool is wider than the concurrency seen in the last scale-down window.

---

## 10. Activity — finding the cluster

Every endpoint names its cluster. There is no unqualified form, because if the
default cluster answered a bare path, promoting a different default would
quietly change what an existing URL addressed.
See [`clusters.py`](../services/api/cubicle/clusters.py).

```mermaid
flowchart TD
    A([Incoming invocation]) --> B{"Does the Host header match<br/>a cluster's ingress_domain?"}
    B -->|yes| C["That cluster.<br/>Path is /&lt;ns&gt;/&lt;fn&gt; — the host<br/>already identifies it"]
    B -->|no| D{"Is the path<br/>/&lt;slug&gt;/&lt;ns&gt;/&lt;fn&gt;<br/>with a known slug?"}
    D -->|yes| E["That cluster"]
    D -->|no| F["404 cluster_required.<br/>The body lists the qualified paths<br/>that would resolve"]

    C --> G([Serve])
    E --> G

    subgraph api[" API and console requests "]
        H([Console or CLI request]) --> I{"X-Cubicle-Cluster header,<br/>or ?cluster= for SSE?"}
        I -->|present| J["That cluster — 404 if unknown"]
        I -->|absent| K["The default cluster,<br/>so single-cluster installs<br/>never think about this"]
    end
```

---

## 11. The reconcile loop

One background task in the control plane, every
`CUBICLE_RECONCILE_INTERVAL` (30 s).
See [`main.py`](../services/api/cubicle/main.py).

```mermaid
flowchart LR
    A([Every 30 s]) --> B["Read min_instances<br/>for every function"]
    B --> C["Reap isolates idle past the TTL,<br/>keeping each function's floor"]
    C --> D["Publish the warm-isolate gauge"]
    D --> E["Delete log entries older<br/>than 14 days"]
    E --> F["Keep the last 10 versions per function,<br/>drop older rows and their volumes"]
    F --> A
```

The loop swallows its own exceptions and keeps running — a transient Docker
error must not stop reaping forever.

---

## 12. Trust boundaries

```mermaid
flowchart TB
    subgraph untrusted[" Untrusted "]
        req([Request bodies, headers])
        code([Function source])
    end

    subgraph edgez[" Edge — authenticated "]
        caddy[Caddy]
        api["Control plane<br/><b>holds the Docker socket</b>"]
    end

    subgraph sandbox[" Sandbox — unprivileged "]
        iso["Isolate<br/>read-only rootfs, caps dropped,<br/>no-new-privileges, pids 256,<br/>memory and CPU capped,<br/>uid 65532, tmpfs /tmp only"]
    end

    subgraph secrets[" Secrets "]
        root["CUBICLE_MASTER_KEY<br/><i>.env, never in the database</i>"]
        db[("Ciphertext only")]
    end

    req --> caddy --> api
    code --> api
    api -->|"payload per invocation"| iso
    api --> db
    root -.->|"HKDF, in memory"| api
    iso -.->|"cannot reach"| root
    iso -.->|"cannot reach"| db
```

What this buys, and what it does not:

- **Secrets at rest.** Each secret gets its own AES-256-GCM data key, wrapped by
  a key derived from `CUBICLE_MASTER_KEY` via HKDF. The database holds only
  sealed material, bound to its record — a ciphertext moved to another key will
  not decrypt. Values reach an isolate in the invocation payload and are never
  written to its filesystem or the log pipeline.
  See [`crypto.py`](../services/api/cubicle/crypto.py).
- **Isolate containment.** Unprivileged user, read-only root filesystem, all
  capabilities dropped, `no-new-privileges`, a pids limit, memory and swap
  capped equal, CPU scaled to the memory setting, and a 64 MB tmpfs as the only
  writable path.
- **The honest caveat.** Containers are not a hard multi-tenant boundary. If you
  run genuinely untrusted third-party code, put clusters on separate hosts.
- **The Docker socket is the crown jewel.** The `api` container can create
  containers on the host, which is equivalent to root there. Treat access to it
  accordingly, and do not expose the API to an untrusted network without the
  edge in front of it.

---

## 13. Failure modes

| What happens | What the platform does | What you see |
| --- | --- | --- |
| Build fails (bad `requirements.txt`) | New version marked `failed`; `current_version_id` untouched | Running version keeps serving; the build log is on the function |
| Handler raises | Traceback captured into the log pipeline | `500` with the exception message; the isolate stays warm |
| Handler exceeds `timeout_s` | Agent returns `504`; control plane destroys the isolate | `504`; next request cold-starts |
| Isolate never becomes ready | Container removed, its output logged | `503 isolate_unavailable`; not metered |
| All 8 isolates busy | Waits for one to free within the deadline | `503` only if the deadline passes |
| Control plane restarts | Isolates left running, then adopted | Requests stay warm across the restart |
| Docker engine unreachable | Node marked `down`; `/healthz` reports `docker: false` | Console loads and explains, rather than erroring blankly |
| Node drained | Removed from scheduling; existing isolates keep serving | New isolates land elsewhere |
| `CUBICLE_MASTER_KEY` changed or lost | Every secret becomes undecryptable | Explicit "root key changed" in place of the value — by design |
| A data service container predates a change to how they are created | **Recreate** rebuilds it from the current spec, reusing the volume and the stored password | A restart; the data, credentials and connection string are unchanged |

---

## 14. Where things live

```
services/api/cubicle/
  main.py              app wiring, health, /metrics, reconcile loop
  clusters.py          cluster resolution and URL construction
  deps.py              auth, roles, the active-cluster dependency
  crypto.py            envelope encryption
  security.py          argon2 passwords, Redis sessions, API keys
  models.py            the whole schema
  analytics.py         every aggregate the console shows
  pricing.py           the hosted-cost comparison
  templates.py         what a new function is scaffolded with
  runtime/
    engine.py          Docker clients, one per node
    builder.py         deploy-time build into a version volume
    pool.py            isolate lifecycle, acquire/release, adoption
    invoker.py         the invocation path and its recording
    nodes.py           node registry and scheduling
    services.py        managed PostgreSQL and Redis
  routers/             one module per surface

services/runtime/
  agent.py             the in-isolate HTTP agent (standard library only)
  sdk/cubicle_context  Request, Context, env
  sdk/cubicle_db       postgres, redis

services/web/src/      the console
cli/                   the cubicle command
deploy/caddy/          edge configuration
```

---

**Related reading.** [README](../README.md) for installing and operating an
instance; the console's own **Docs** section for writing functions, secrets,
`cubicle.toml` and the CLI.
