# The command line client

`cubicle` is a client of the same HTTP API the console uses. There is no
privileged back channel, so anything it can do you can also do from the console
or with `curl`, and anything it cannot do is a missing command rather than a
missing permission.

It depends on nothing outside the Python standard library, so it installs
without a network and runs on an air gapped jump host.

## Installing

Straight from GitHub, with no clone:

```bash
pipx install "git+https://github.com/clickTwice26/cubicle.git#subdirectory=cli"
```

Python 3.11 or newer. `pip install` takes the same argument if you would rather
not use pipx, though pipx is worth it here: it keeps the CLI in its own
environment rather than in whichever one happens to be active.

From a clone, if you already have the repository:

```bash
pipx install ./cli
```

To upgrade later:

```bash
pipx upgrade cubicle-cli
```

It re-resolves the git ref and swaps the commit, then reports "already at latest
version 1.0.0". Read the `-` and `+` lines above that instead: the version
string is the platform's and does not move between commits, so it is the commit
that tells you anything. `cubicle --version` names it:

```
cubicle 1.0.0 (467648a)
```

If a stale copy will not budge, force it:

```bash
pipx install --force "git+https://github.com/clickTwice26/cubicle.git#subdirectory=cli"
```

The `#subdirectory=cli` matters. The repository holds the whole platform and the
CLI is one directory inside it.

## Removing it

```bash
cubicle uninstall
```

This removes the program and the saved profile from the machine it runs on. It
makes no request, so the instance, its clusters and its functions are untouched.
It works out how the copy was installed and calls the right package manager.

`--config-only` forgets the saved instance and token but leaves the program
installed, which is what signing out of a shared machine looks like.
`--keep-config` does the opposite. The profile is removed by default because it
holds an API token in plain text, and a credential outliving the program that
reads it is a file nobody will think to look at again.

## Signing in

```bash
cubicle login https://fn.example.com
```

It prompts for a token, which you make in the console under Settings, API keys.
The profile is written to `~/.cubicle/config.toml` with mode 600. Treat that
file as the credential it is.

For CI, set `CUBICLE_URL` and `CUBICLE_TOKEN` in the environment instead and
skip the login step entirely.

Point it at the address the console is on, which is what Caddy serves. Not the
`api` container, which is not published.

## Working from your own machine against a server

This is the normal way to use it. The CLI is an ordinary HTTPS client and holds
nothing that has to be on the server.

Two things are worth knowing before you start.

**Certificates are verified and there is no way around it.** A real certificate
works, and an install with `--domain` gets one automatically. A self-signed
certificate fails, and there is no `--insecure` flag. A local install over plain
`http://localhost:28080` is fine, because no TLS is involved.

**Sign-in protection does not get in the way.** `cubicle login` authenticates
with the API key against `/api/auth/me`; it never touches the password form. So
an instance with Turnstile turned on is still reachable from a terminal and from
CI.

### Two instances at once

The saved profile holds one instance. To work against production and a local
install in the same week, override per shell rather than logging in again:

```bash
CUBICLE_URL=https://fn.example.com CUBICLE_TOKEN=cbcl_… cubicle ls
```

Or keep separate profile files:

```bash
CUBICLE_CONFIG=~/.cubicle/prod.toml cubicle deploy
```

### Give the key the least it needs

A key carries the lower of its creator's role and its own scope, and can be
restricted to one cluster. Both are offered when you create one. A key that
lives on a laptop or in CI should be `deploy` scope on one cluster, not `admin`
across the instance.

### The one thing that does not reach you

`cubicle services url postgres` prints a host that is a container name on the
cluster's own Docker network:

```
postgres://cubicle:…@cubicle-pg-a1b2c3:5432/cubicle
```

That resolves for a function and for the control plane, and for nothing on your
machine. The command prints the tunnel you need on stderr, so the URL itself
stays clean for `$(…)` substitution:

```bash
ssh -L 5432:cubicle-pg-a1b2c3:5432 you@your-server
```

Then connect to `localhost:5432` with the password from the URL. Everything else
works directly: deploy, invoke, logs and its live tail, instances, scale,
schedules, the marketplace, runtimes, update and reconcile.

## Global flags

| Flag | Effect |
| --- | --- |
| `--url`, `--token` | Override the saved profile for one command |
| `--cluster <slug>` | Act on a cluster other than your default |
| `--yes`, `-y` | Answer every confirmation with yes. Required when there is no terminal |
| `--version` | Print the client version |

`--yes` is global rather than per command on the reasoning that a script which
has decided it is not being supervised has decided that for the whole
invocation.

## Commands

### Getting oriented

| Command | What it does |
| --- | --- |
| `cubicle status` | Control plane, database, Docker, nodes, warm isolates, ingress, ceilings |
| `cubicle clusters` | Every cluster on the instance, marking your default |
| `cubicle ls` | Namespaces and functions with runtime, version, invocations and p95 |

### Writing and shipping

| Command | What it does |
| --- | --- |
| `cubicle init <ns>/<fn> [--runtime <key>]` | Create the function and scaffold it locally |
| `cubicle deploy [dir]` | Bundle the directory and deploy it |
| `cubicle invoke <ns>/<fn> [--data <json>]` | Call it and print status, timing and logs |
| `cubicle versions <ns>/<fn>` | Every build, with status and duration |

`init` reads the live runtime list from the instance, so a runtime you installed
five minutes ago is offered immediately.

`--data` takes JSON inline or `@file.json`.

### Running functions

| Command | What it does |
| --- | --- |
| `cubicle instances <ns>/<fn>` | The containers serving it right now |
| `cubicle kill <ns>/<fn> <container>` | Destroy one isolate |
| `cubicle scale <ns>/<fn> [--min N] [--max N]` | How many isolates may run |
| `cubicle config <ns>/<fn> [--memory N] [--timeout N] ...` | Show or change settings |
| `cubicle pause <ns>/<fn>` / `cubicle resume <ns>/<fn>` | Stop serving and drain, then serve again |
| `cubicle metrics <ns>/<fn>` | Latency, errors and cold starts over a window |
| `cubicle rm <ns>/<fn>` | Delete the function and every version |

Bounds are checked locally, so a typo fails immediately with a readable message
instead of coming back as a 422.

### Configuration and secrets

| Command | What it does |
| --- | --- |
| `cubicle env ls` | Cluster wide values, secrets masked |
| `cubicle env set KEY=value [--secret]` | Set one |
| `cubicle env rm KEY` | Remove one |
| `cubicle secrets ls --function <ns>/<fn>` | Secrets on one function |
| `cubicle secrets set --function <ns>/<fn> KEY` | Prompts for the value |
| `cubicle secrets rm --function <ns>/<fn> KEY` | Remove one |

`secrets set` reads the value from a prompt rather than the command line, so it
never lands in shell history.

### Schedules

| Command | What it does |
| --- | --- |
| `cubicle schedule ls --function <ns>/<fn>` | Every schedule, with next and last run |
| `cubicle schedule add --function <ns>/<fn> "<cron>" [--tz TZ]` | Add one |
| `cubicle schedule enable\|disable --function <ns>/<fn> <id>` | Turn one on or off |
| `cubicle schedule run --function <ns>/<fn> <id>` | Fire it now |
| `cubicle schedule rm --function <ns>/<fn> <id>` | Remove one |
| `cubicle schedule preview "<cron>" [--tz TZ]` | The next few times it would fire |

A trigger id may be given as an unambiguous prefix rather than the whole UUID.

### Runtimes

| Command | What it does |
| --- | --- |
| `cubicle runtimes` | Every runtime, marking which are installed |
| `cubicle runtimes install <key>` | Build and install one |
| `cubicle runtimes rebuild <key>` | Rebuild after an upgrade |
| `cubicle runtimes rm <key>` | Remove one |

Installing builds an image, which takes minutes. The command reports that the
build continues on the server rather than pretending to be finished.

### Data services

| Command | What it does |
| --- | --- |
| `cubicle services` | Postgres and Redis with status and stats |
| `cubicle services show <kind>` | One service in detail |
| `cubicle services url <kind>` | The connection URL |
| `cubicle services create <kind>` | Create it |
| `cubicle services start\|stop <kind>` | Start or stop |
| `cubicle services recreate <kind>` | Destroy and rebuild, losing the data |
| `cubicle services rm <kind>` | Remove it |

A connection URL contains a password, so it is printed only by `services url`
and never in the list.

### The marketplace

| Command | What it does |
| --- | --- |
| `cubicle market` | Browse the index |
| `cubicle market show <url>` | Review a package before installing |
| `cubicle market install <url> --namespace <ns>` | Install it |
| `cubicle market export <ns>/<fn>` | Print your function as a package document |

### Operating the instance

| Command | What it does |
| --- | --- |
| `cubicle update` | Whether the branch has moved on |
| `cubicle update apply` | Apply it, with progress |
| `cubicle reconcile` | Where the database and Docker disagree |
| `cubicle reconcile apply` | Fix the disagreements |
| `cubicle metering` | This month's usage for the cluster |
| `cubicle logs [--follow] [--level L] [--limit N]` | Recent logs, or a live tail |

### This machine

| Command | What it does |
| --- | --- |
| `cubicle uninstall` | Remove the CLI and the saved profile from this computer |
| `cubicle uninstall --config-only` | Forget the instance and token, keep the program |

Neither makes a request. The instance is not involved.

Destructive commands confirm before acting. `--yes` is the only way past the
prompt, which is why it is required in CI.

## Exit codes

`0` on success, `1` on any error the server or the client reports, `130` on
interrupt. Errors print the server's own message rather than a status code, so a
failed deploy tells you what the build did not like.
