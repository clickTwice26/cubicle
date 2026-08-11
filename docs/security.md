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

Failed sign-ins are counted per IP and email, ten within five minutes. Note the
limitation recorded as CUB-01 in the audit: the IP is taken from a header a
caller can set, so the counter is currently bypassable.

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

Five things answer without a credential: the login endpoint, the setup
endpoints before setup completes, `/healthz`, `/metrics`, and the function
invoke path. Of these, `/metrics` and the API documentation at `/api/docs`
disclose more than they should; both are listed in the audit with one-line
fixes.

A function is authenticated by default. Turning `auth_required` off makes its
URL public, which is correct for a webhook and a mistake for anything else.

## Hardening checklist

- [ ] Serve over HTTPS and set `CUBICLE_PUBLIC_URL` to match
- [ ] Back up `.env` somewhere the server is not
- [ ] Fix CUB-01 before the login page is reachable from the internet
- [ ] Turn off `/api/docs` and gate `/metrics`
- [ ] Keep the `admin` role narrow; it includes arbitrary SQL
- [ ] Grant cluster access explicitly rather than broadly
- [ ] Scope API keys to one cluster where you can
- [ ] Leave `auth_required` on unless the URL is meant to be public
- [ ] Review anything installed from the marketplace before installing it
- [ ] If you host mutually untrusting tenants, fix CUB-02 first

## Reporting a problem

Open an issue for anything that is not exploitable. For anything that is,
contact the maintainer directly rather than filing publicly.
