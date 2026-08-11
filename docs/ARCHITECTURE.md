# Architecture

This page explains how Cubicle is put together and why each part is where it is.
It assumes you have read the summary in the [index](README.md).

## The containers

A default install runs five containers, on three networks.

| Container | What it does | Networks |
| --- | --- | --- |
| `caddy` | Terminates TLS, serves the console, routes function URLs to the control plane | `edge` |
| `web` | The compiled React console, served as static files | `edge` |
| `api` | The control plane: HTTP API, scheduler, isolate pool, invocation router | `edge`, `core`, `fn` |
| `postgres` | Every record the platform keeps | `core` |
| `redis` | Sessions, login throttling, live event fan-out, setup progress | `core` |

Only `caddy` publishes ports to the host. The control plane is not directly
reachable from outside; everything arrives through the proxy.

The three networks exist to keep things apart:

- `edge` carries public traffic to the proxy, the console and the API.
- `core` carries the control plane's own state. Postgres and Redis are here and
  nowhere else, so a function cannot reach them.
- `fn` carries function traffic. Isolates and managed data services live here.
  The control plane joins it so it can reach an isolate directly.

## The control plane

`services/api/` is a FastAPI application with async SQLAlchemy over Postgres.
It owns four responsibilities that are easier to keep together than apart:

**The HTTP API.** Everything the console and the CLI do goes through it. There
is no privileged back channel: the CLI is a client of the same endpoints the
browser calls.

**The isolate pool.** `cubicle/runtime/pool.py` decides when a container starts,
which one serves a request, and when one is taken back. See
[the isolate lifecycle](#the-isolate-lifecycle) below.

**The invocation router.** `cubicle/routers/invoke.py` receives a request for a
function URL, finds or starts an isolate, forwards the request to it, and
returns the response.

**The scheduler.** Cron triggers fire here, which is why a schedule survives a
console being closed.

The control plane mounts the Docker socket. It has to: starting a container is
the whole job. The consequence is stated plainly in [the security model](security.md).

## Runtimes

A runtime is an image that serves two endpoints, `GET /healthz` and
`POST /invoke`, plus two facts about the language: what the entry file is called
and how dependencies are declared.

| Key | Language | Entry file | Dependencies |
| --- | --- | --- | --- |
| `python313`, `python312`, `python311`, `python310` | Python | `handler.py` | `requirements.txt` |
| `node22`, `node20`, `node18` | JavaScript | `handler.js` | `package.json` |

Python 3.12 and Node 18 ship with the instance. The rest are defined but not
installed, and are built on demand from Settings or with `cubicle runtimes
install`. Building rather than pulling is deliberate: the agent has to be inside
the image, and there is no public registry of Cubicle runtime images to pull
one from. It also means a runtime installs onto whichever node needs it,
including a remote engine reached over TCP.

Nothing in the control plane knows one language from another. Everything it
needs is in the runtime record, which is why adding a language does not touch
the scheduler, the pool or the router.

## A deploy, end to end

1. The client sends the bundle: the entry file, the dependency file, and
   optionally `cubicle.toml` and `README.md`. The API checks the file names
   against the function's runtime, so a `handler.py` sent to a Node function is
   refused by name rather than failing later in the build.
2. A new version row is written with status `building`.
3. A build container installs the dependencies into a volume that will be
   mounted read only at `/srv`.
4. If the build succeeds the version becomes the one that serves traffic, and
   isolates running the previous version are marked stale and reclaimed.
5. If it fails the version keeps the build log, and the previous version carries
   on serving. A failed deploy never takes a working function down.

## An invocation, end to end

1. Caddy matches the function URL shape and rewrites it onto `/api/invoke`.
2. The router resolves the cluster, the namespace and the function.
3. If the function requires authentication, the credential is checked here.
4. The pool is asked for an isolate. If a warm one is free it is used. If not,
   see the next section.
5. The request is forwarded to the isolate's agent, which calls the handler.
6. The response comes back, the isolate is released, and the invocation is
   recorded with its duration and whether it was a cold start.

## The isolate lifecycle

An isolate moves through five states.

**Starting.** A container is created and the pool waits for its health check. If
it never becomes ready it is given up on after thirty seconds and removed.

**Ready.** Warm and idle, waiting for work.

**Busy.** Serving one request. An isolate serves one request at a time, which is
why concurrency is a function of how many isolates may run.

**Adopted.** After the control plane restarts it finds containers it started
before. One that answers a health check and runs the current version is adopted
back into the pool rather than replaced, so a restart does not cause a wave of
cold starts.

**Removed.** A container in Ready is taken back in four cases: it has been idle
longer than the idle limit and the function does not require one to stay alive;
there are more containers than recent traffic needs; a newer version has been
deployed; or the function was deleted, paused, or had its memory or timeout
changed. The first two are what scale to zero means here.

### Waiting versus starting

Room in the pool is not by itself a reason to start a container. A burst of
short requests makes every isolate momentarily busy, and answering that with a
cold start gives the caller a four hundred millisecond wait for a five
millisecond handler, then leaves the cluster carrying a container it did not
need.

The pool keeps two rolling means per function version: how long a request
occupies an isolate, and what a cold start actually costs on that node. Before
starting a container it asks whether a busy one will be free sooner than a new
one could boot. If so it waits. If not it starts one.

Three bounds keep that honest. A function with no measurement yet starts
immediately, so behaviour on a cold pool is unchanged. A single wait is capped
at 250 ms. And once a request has waited as long as a boot would have taken it
stops waiting and starts a container, so a saturated pool still grows.

## Data model

The tables worth knowing about:

- `instance` holds the single row that says whether setup is complete.
- `cluster` is a tenant. Functions, nodes, services, logs and env vars all carry
  a cluster id.
- `user`, `api_key` and the cluster access grants decide who may reach what.
- `group` is a namespace. `function` belongs to a group.
- `function_version` holds the files and the build log for one deploy. The
  function points at the version currently serving.
- `trigger` is a cron schedule attached to a function.
- `managed_service` is a Postgres or Redis container the platform runs for a
  cluster.
- `log_entry` and the invocation records are what the console's logs and metrics
  pages read.

## Where the code lives

```
services/api/cubicle/
  routers/      one module per HTTP surface
  runtime/      pool, builder, invoker, scheduler, data services, reconcile
  deps.py       authentication and authorisation dependencies
  clusters.py   how a request is bound to a cluster
  crypto.py     envelope encryption for stored secrets
  security.py   passwords, sessions, API keys
  runtimes.py   the runtime registry
  schemas.py    every request and response shape
services/web/   the React console
services/runtime/ the agent that runs inside each isolate
cli/            the command line client
deploy/         Caddy configuration
```
