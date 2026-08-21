# Installation

Cubicle needs one machine with Docker and Docker Compose. Two cores and 2 GB of
memory is enough to run the platform and a handful of functions. Everything else
it needs it builds or pulls itself.

## Local, on your own machine

```bash
./install.sh
```

This serves the console on `http://localhost:28080` with no certificate, which
is right for trying it out and wrong for anything else.

## On a server, with a domain

```bash
./install.sh --domain fn.example.com
```

Point the domain's A record at the server first. Caddy obtains and renews the
certificate itself, so there is nothing further to configure and no certbot
cron job to forget about. Ports 80 and 443 must reach the machine for the
certificate challenge to succeed.

## Behind a proxy you already run

```bash
./install.sh --domain fn.example.com --behind-proxy
```

This binds the published ports to `127.0.0.1` instead of every interface, so
your own proxy is the only thing that can reach them. The domain is still
required, because the URLs the platform hands out have to match what your proxy
serves.

## What the installer writes

It generates two 64 character keys and writes them, with the rest of the
configuration, to `.env`:

| Variable | What it is |
| --- | --- |
| `CUBICLE_SECRET_KEY` | Signs API key digests |
| `CUBICLE_MASTER_KEY` | The root of the envelope encryption that protects stored secrets |
| `CUBICLE_DOMAIN` | The hostname, empty for a local install |
| `CUBICLE_PUBLIC_URL` | What the platform believes its own address is |
| `CUBICLE_HTTP_PORT`, `CUBICLE_HTTPS_PORT` | Published ports, 28080 and 28443 by default |
| `CUBICLE_BIND` | Empty normally, `127.0.0.1:` behind a proxy |
| `CUBICLE_PROXY_HOPS` | How many proxies sit in front. 1 by default, for Caddy |
| `CUBICLE_EXPOSE_API_DOCS` | Off by default. Turns on `/api/docs` and the OpenAPI document |
| `CUBICLE_MARKETPLACE_ALLOW_PRIVATE` | Off by default. Lets a registry live on a private address |
| `CUBICLE_API_MEMORY` | Memory ceiling for the control plane container, `1g` by default |

`CUBICLE_PROXY_HOPS` decides which entry of `X-Forwarded-For` is treated as the
caller. Raise it only if you put your own proxy in front of Caddy, and see
[the security model](security.md) for why the number has to be right.

**Back up `.env` before you do anything else.** Losing `CUBICLE_MASTER_KEY`
means losing every stored secret and every environment variable, permanently.
That is the intended property, not a bug: nothing off the node can decrypt them.
There is no recovery path and support cannot help you.

`CUBICLE_PUBLIC_URL` does more than appear in generated URLs. Session cookies
are marked `Secure` only when it starts with `https://`, so an instance that
serves real traffic over plain HTTP hands out cookies that will travel over
plain HTTP.

## First run

Open the console. The first person to arrive names the cluster and chooses the
administrator password. That is the only account creation path in the platform:
there is no registration, and nobody can sign up.

The password must be at least twelve characters and mix at least three of lower
case, upper case, digits and symbols.

Setup hands back a CLI token once, on that screen only. Copy it. If you lose it,
make another in Settings under API keys.

After setup completes the setup endpoints refuse to run again, so the window
where an unclaimed instance can be taken over is the time between the containers
coming up and you finishing the wizard. On a public address, do not walk away in
the middle of it.

## Verifying the install

```bash
docker compose ps
```

Every container should be `running`, and `api` should be `healthy`.

```bash
curl -s localhost:28080/healthz
```

This reports the database, Redis and Docker checks. All three must be true for
functions to run.

From the CLI:

```bash
cubicle login http://localhost:28080
```

Then `cubicle status` prints the control plane version, the node list, how many
isolates are warm and what the cluster's ceilings are.

## Upgrading

```bash
git pull && docker compose up -d --build
```

Migrations run on start, under an advisory lock, so bringing up more than one
API container at once does not race them. The console also has an update card
that reports when the branch has moved on and applies the update in place, and
`cubicle update` does the same from a terminal.

Rebuild the runtime images after an upgrade if the agent changed. Images are
tagged with the instance version, so an upgrade rebuilds rather than silently
reusing the previous release's agent.

## Uninstalling

```bash
docker compose down -v
```

The `-v` removes the volumes, which is every function, every version and every
log. Without it the data survives and a later `up` finds it again.
