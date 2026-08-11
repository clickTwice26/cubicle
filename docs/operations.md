# Operations

What to do after the install works, and what to look at when it does not.

## Daily checks

```bash
cubicle status
```

Control plane version, database, Docker, node health, how many isolates are
warm, the ingress URL and the cluster's ceilings. If Docker reports down,
nothing will run: the control plane cannot start containers.

```bash
curl -s localhost:28080/healthz
```

The same three checks without a credential, which is what a monitor should poll.

## Logs

```bash
cubicle logs --follow
cubicle logs --level ERROR --limit 200
```

Logs carry the function that produced them, the level, the message and the
duration. The console's Logs page pages through the same data and pauses the
tail when you leave the newest page, so you can read something without it
scrolling away.

Handler output goes here too. `print` and `console.log` are captured.

## Metrics

`/metrics` serves Prometheus format. Point your scraper at it, but read
[the security model](security.md) first: it currently has no authentication.

Per function, `cubicle metrics <ns>/<fn>` reports latency percentiles, error
rate and cold start rate over a window. The console's overview shows the same
across the cluster, with an invocations chart.

## Metering

```bash
cubicle metering
```

This month's usage for the cluster: invocations, compute time and storage. The
console can export it as CSV from the Cluster page.

## When record and reality disagree

The database records which containers should exist. Docker holds the ones that
do. They drift when a container is removed by hand, when the daemon restarts
under the control plane, or when something crashes mid operation.

```bash
cubicle reconcile
```

This reports the disagreements without changing anything. Read it, then:

```bash
cubicle reconcile apply
```

The console has the same under Resource sync.

## Scaling a function

A function serves one request per isolate at a time, and `max_instances`
defaults to 1. That default is right for something invoked occasionally and
wrong for anything under load.

```bash
cubicle scale payments/create-charge --max 8
```

Raising `min_instances` above zero keeps isolates warm, which defeats cold
starts and costs memory continuously. Use it for a function whose latency
matters and leave it at zero for everything else.

Memory and CPU move together: raising `memory_mb` raises the CPU share.

## Cold starts

A cold start is a container being created and its runtime loading, typically a
few hundred milliseconds. Three things reduce them:

- `min_instances` above zero, which removes them for the warm copies.
- A longer `idle_timeout_s`, so an isolate survives a quiet period.
- Leaving the pool alone. It measures how long requests take and how long boots
  take, and waits for a busy isolate rather than starting a new one when waiting
  is faster. See [the architecture](architecture.md#waiting-versus-starting).

`cubicle metrics` reports the cold start rate, which is the number to watch
rather than any individual slow request.

## Upgrading

```bash
cubicle update
```

Reports whether the branch has moved on. `cubicle update apply` applies it, and
the console's update card does the same with progress.

After an upgrade, rebuild runtime images so isolates get the current agent:

```bash
cubicle runtimes rebuild python312
```

## Backups

Two things need backing up and neither is automatic.

**`.env`**, because it holds `CUBICLE_MASTER_KEY`. Without that key every stored
secret and environment value is unrecoverable. Nothing else can decrypt them.

**The Postgres volume**, which holds every function, every version and every
log:

```bash
docker exec cubicle-postgres-1 pg_dump -U cubicle cubicle > cubicle-backup.sql
```

Managed data services are separate containers and need their own dump. See
[Data services](data-services.md#backups).

## Common failures

**A function returns 502.** The isolate did not answer. Check `cubicle instances
<ns>/<fn>` for whether anything is running and `cubicle logs --level ERROR` for
why it stopped. A handler that exceeds `timeout_s` is killed and reported this
way.

**A deploy fails.** The build log is printed. The previous version keeps
serving, so the function is not down. Most failures are a dependency that will
not install.

**Everything is slow under load.** Check `max_instances`. One isolate serves one
request at a time.

**A runtime is missing.** `cubicle runtimes` shows what is installed.
Installing builds an image and takes minutes.

**Setup will not complete.** The wizard reports which step failed. A failure at
the runtimes step usually means the images were never built: run
`docker compose up -d --build`.
