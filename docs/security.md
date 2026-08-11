# Security model

What protects what, and where the edges are. For specific defects found by
review, see [the security audit](security-audit.md).

## What Cubicle assumes

The operator owns the machine and trusts the people they give accounts to. That
assumption is why the admin role can run arbitrary SQL against a cluster's
database and why the control plane holds the Docker socket. If your situation is
different, read [tenant isolation](#tenant-isolation) carefully before you rely
on it.

## Accounts

There is no registration. The first person to open a new instance becomes the
owner, and after that only an owner can create accounts. Nobody can sign
themselves up, and there is no password reset by email because there is no email.

Passwords need twelve characters and three of the four character classes. They
are hashed with argon2id at 64 MB of memory per verification, which is what
makes offline cracking expensive if the database is ever taken.

Failed sign-ins are counted per IP and email, ten within five minutes. The
address is read from the right of `X-Forwarded-For`, counting in by
`CUBICLE_PROXY_HOPS` (one by default, for Caddy). That direction matters: each
proxy appends, so the left of that header is whatever the caller chose to send,
and reading it would hand an attacker a fresh identity per request.

Raise `CUBICLE_PROXY_HOPS` if you put another proxy in front of Caddy. Setting
it too high reads an entry the caller controls; too low reads your own proxy.

## Sign-in protection

An instance can put Cloudflare Turnstile on the sign-in form. It is off by
default and nothing contacts Cloudflare until an operator turns it on, which
matters for a platform whose premise is that it does not call home.

Turn it on in Settings, under Access. You need a widget from the Cloudflare
dashboard, which gives you two keys:

- The **site key** is public. It is rendered into the sign-in page, where any
  visitor can read it, so it is stored in the clear.
- The **secret key** is envelope-encrypted like every other secret here, is
  never returned to the console once saved, and only leaves the machine to
  reach Cloudflare's verification endpoint.

The challenge is checked before the password is, because verifying a password
costs argon2id at 64 MB and that is the work an anonymous caller would
otherwise spend freely. A failed challenge counts as a failed sign-in attempt,
so anyone who defeats Turnstile still meets the throttle.

Two behaviours worth knowing:

**Saving with the toggle on verifies the keys with Cloudflare first.** A
mistyped secret would otherwise lock every operator out of the instance, with
no way back except editing the database by hand.

**If Cloudflare cannot be reached, sign-in fails rather than passing.** The
alternative is that anyone able to disrupt the control plane's outbound traffic
also turns the challenge off, which makes the control worthless exactly when it
is under attack. The cost is that a Cloudflare outage stops sign-in, which an
operator ends by turning Turnstile off.

The site key reaches the sign-in page at runtime from `/api/setup/status`, the
one endpoint that page can call before anyone has signed in. Nothing is baked
into the console bundle, so changing a key takes effect on the next page load
with no rebuild and no restart.

## Sessions and keys

Console sessions are opaque tokens in Redis, not signed cookies. That choice
costs a Redis lookup per request and buys immediate revocation: signing out ends
the session there and then, and an owner can end every session for an account.

Sessions last twelve hours, sliding while you work. The cookie is `HttpOnly`, so
JavaScript cannot read it, and `SameSite=Lax`. It is marked `Secure` only when
`CUBICLE_PUBLIC_URL` starts with `https://`.

API keys are stored as an HMAC digest and shown once. A key inherits the role of
the account that made it, can be narrowed to a single cluster, and stops working
if its creator is deleted or deactivated.

## Authorisation

Four roles, ranked: `readonly`, `developer`, `admin`, `owner`. A role belongs to
the account, not to the account within a cluster.

Cluster access is separate and explicit. An account reaches only the clusters it
has been granted, and the check lives in the one resolver that every
cluster-scoped endpoint depends on. A new endpoint cannot forget it, because it
cannot obtain a cluster without passing through the check. A cluster you cannot
reach returns the same 404 as one that does not exist.

## Secrets at rest

Environment values marked secret, function secrets and data service passwords
are protected with envelope encryption. Each value gets its own random 256 bit
key, encrypted with AES-256-GCM; that key is wrapped under a key derived from
`CUBICLE_MASTER_KEY`. The database holds only wrapped material, so a database
dump alone does not reveal a single secret.

The master key never leaves the process and is never stored in the database.
Losing it means losing every secret, permanently. Back up `.env`.

## The isolate boundary

A deployed function runs in its own container with:

- a read-only root filesystem
- every Linux capability dropped
- `no-new-privileges` set
- a non-root user, uid 65532
- memory and swap both capped, so swap is not a way around the limit
- a CPU quota proportional to the memory limit
- at most 256 processes
- `/tmp` as a 64 MB tmpfs, which is the only writable path
- its code mounted read only
- no restart policy, so a killed container stays dead

Running a developer's code is the platform's purpose, so the question is not
whether they can execute code but what that code can reach. Postgres and Redis
are on a network isolates do not join, so the control plane's own database is
out of reach.

## Tenant isolation

Cluster isolation is enforced thoroughly in the API. It is **not** enforced at
the network layer. Every isolate in every cluster shares one Docker network, and
the isolate agent does not authenticate its caller.

The consequence: code inside a function can open a connection to another
cluster's isolate and invoke it directly, bypassing the API and everything the
API enforces. It can also reach the control plane API without passing through
the proxy.

For a single team running their own functions this is not much of a boundary to
begin with. For hosting parties who do not trust each other it is the thing to
fix first. See CUB-02 in [the audit](security-audit.md).

## The Docker socket

The control plane mounts `/var/run/docker.sock` because starting containers is
its job. This means code execution in the API container is equivalent to root on
the host. No configuration removes that; a socket proxy or a rootless daemon
would reduce it, and both are real work.

## The public surface

Four things answer without a credential: the login endpoint, the setup
endpoints before setup completes, `/healthz`, and the function invoke path.

`/metrics` requires a principal, so give a scraper a read-only API key rather
than opening the endpoint. The browsable API reference at `/api/docs` and its
OpenAPI document are off unless `CUBICLE_EXPOSE_API_DOCS` is set, because
publishing the shape of every administrative endpoint to anonymous callers is
reconnaissance handed over for free.

A function is authenticated by default. Turning `auth_required` off makes its
URL public, which is correct for a webhook and a mistake for anything else.

## Hardening checklist

- [ ] Serve over HTTPS and set `CUBICLE_PUBLIC_URL` to match
- [ ] Back up `.env` somewhere the server is not
- [ ] Turn on sign-in protection if the console faces the internet
- [ ] Set `CUBICLE_PROXY_HOPS` if anything sits in front of Caddy
- [ ] Keep the `admin` role narrow; it includes arbitrary SQL
- [ ] Grant cluster access explicitly rather than broadly
- [ ] Scope API keys to one cluster where you can
- [ ] Leave `auth_required` on unless the URL is meant to be public
- [ ] Review anything installed from the marketplace before installing it
- [ ] If you host mutually untrusting tenants, fix CUB-02 first

## Reporting a problem

Open an issue for anything that is not exploitable. For anything that is,
contact the maintainer directly rather than filing publicly.
