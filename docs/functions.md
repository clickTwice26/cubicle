# Writing functions

A function is one file exporting one entry point, plus a dependency file and a
little configuration. There is no framework to learn and no application object
to construct.

## The shape of a handler

Python:

```python
from cubicle_context import Request, Context, env
from cubicle_db import postgres, redis


def handler(req: Request, ctx: Context):
    body = req.json()
    return {"ok": True, "received": body}
```

JavaScript:

```javascript
export async function handler(req, ctx) {
  const body = await req.json()
  return { ok: true, received: body }
}
```

Return a dictionary or object and it is sent as JSON with status 200. Return a
tuple or an explicit response to control the status code and headers.

## The request

`req` carries the method, the path, the query, the headers and the body.
`req.json()` parses a JSON body, and the raw bytes are available for anything
else. Binary request and response bodies are carried through intact, so a
function can accept an upload or return an image.

`req.session_id` is the value of the `X-Cubicle-Session` header, if the caller
sent one. It is what ties a series of calls together.

## The context

`ctx` is a key value store scoped to a session and shared by every function in
the same namespace, for as long as that session lives. It exists so a group of
functions can pass state between themselves without inventing a store for it.

Each function declares what it may do with the context: read and write, read
only, write only, or no access at all. A function with no access cannot see what
its neighbours have written.

## Cluster environment

`env` reads the cluster wide store, which the console and `cubicle env` write.
Values resolve at invocation time, so changing one does not need a redeploy.

Mark a value as secret and it is encrypted at rest and masked everywhere in the
console. Function specific secrets live separately, under the function itself,
and are set with `cubicle secrets`.

## Data services

`postgres` and `redis` are already connected if the cluster has those services
running. Both expose `.available`, so a handler can work whether or not they are
there:

```python
if postgres.available:
    with postgres.session() as db:
        db.execute("insert into orders (amount) values (:amount)", amount=42)
```

Queries take bound parameters. See [Data services](data-services.md) for
creating them.

## Configuration

`cubicle.toml` sits next to the handler and is read on deploy:

```toml
[function]
namespace = "payments"
name = "create-charge"
runtime = "python3.12"
method = "POST"
memory_mb = 128
timeout_s = 30
max_instances = 4
```

| Setting | Meaning | Bounds |
| --- | --- | --- |
| `memory_mb` | Hard memory limit on the container | 32 to 8192 |
| `timeout_s` | The request is killed after this | 1 to 900 |
| `max_instances` | How many isolates may serve at once | 1 to 32 |
| `min_instances` | How many stay warm, defeating cold starts | 0 to 20 |
| `idle_timeout_s` | How long an idle isolate survives | 0 to 86400 |

`max_instances` defaults to 1. That is the single most consequential default in
the platform: a function with one isolate serves one request at a time, and a
slow handler will queue everything behind it. Raise it before you expect
concurrency.

Memory and CPU are allocated together: the CPU share follows the memory limit,
so a function that needs more processor gets it by being given more memory.

## Deploying

```bash
cubicle init payments/create-charge --runtime python312
```

This creates the function on the instance if it does not exist and writes the
scaffold into a local directory.

```bash
cubicle deploy
```

This bundles the entry file, the dependency file, `cubicle.toml` and
`README.md`, sends them, and waits for the build. A build failure prints the log
and leaves the previous version serving.

The file names must match the runtime. A Python function takes `handler.py` and
`requirements.txt`; a Node function takes `handler.js` and `package.json`.
Sending the wrong pair is refused by name rather than failing later in the
build.

## Invoking

Every function has a URL, and it names the cluster in one of two ways:

```
https://fn.example.com/<cluster>/<namespace>/<function>
https://staging.example.com/<namespace>/<function>
```

The qualified form always works. The two segment form works only when the
hostname is pointed at a cluster of its own, because then the host already
identifies it.

There is no unqualified form. A bare `/<namespace>/<function>` on a shared
hostname returns a 404 that lists the clusters which do hold it. Every cluster
could own that namespace, and if the default answered it, changing the default
would quietly change what an existing URL addressed.

By default a function requires authentication. Turn that off and the URL is
public, which is the point for a webhook and a mistake for anything else.

To try one without leaving the terminal:

```bash
cubicle invoke payments/create-charge --data '{"amount": 100}'
```

This prints the status, the duration, whether it was a cold start, and any log
lines the handler produced.

## Schedules

A function can run on a cron schedule without anything calling it:

```bash
cubicle schedule add --function reports/nightly "0 2 * * *" --tz Europe/London
```

The schedule is read in its own timezone and survives restarts, because the
scheduler runs in the control plane rather than in a browser tab. Schedules
attach to independent functions only, since a function that expects a caller's
session has no session when a timer fires.

## Logs and metrics

```bash
cubicle logs --follow
cubicle metrics payments/create-charge
```

`print` and `console.log` from a handler are captured and appear in both the
console and the CLI, tagged with the function that produced them.
