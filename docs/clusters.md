# Clusters and access control

One instance can host several clusters. A cluster is a tenant: its own
namespaces and functions, its own environment store, its own nodes, its own
data services, its own logs, and its own ceilings on memory, CPU and storage.

Most installs have one cluster and never think about this. The rest of the page
matters when you have more than one, or more than one person.

## How a request picks a cluster

Every cluster scoped endpoint depends on a single resolver. The console and the
CLI name the cluster explicitly with the `X-Cubicle-Cluster` header, carrying
either an id or a slug. A request that does not name one gets the first cluster
the caller can reach, which is why a single cluster install never has to think
about it.

Two properties of that resolver are worth knowing.

**It is the only way to obtain a cluster.** A new endpoint cannot forget the
check, because it cannot get a cluster object without passing through the
resolver that performs it.

**A cluster you may not reach answers exactly like one that does not exist.**
Both return 404. Distinguishing them would tell an account which clusters it has
been kept out of, which is itself information.

Because browsers cannot set headers on an `EventSource`, the resolver also
accepts a `cluster` query parameter. That path is checked identically.

## Roles

Four roles, ranked. Each includes everything below it.

| Role | May |
| --- | --- |
| `readonly` | See functions, logs and metrics |
| `developer` | Deploy, invoke, change function settings, manage secrets and schedules |
| `admin` | Manage users, data services, the database browser, cluster settings |
| `owner` | Everything, including creating clusters, setting ceilings and granting access |

Roles are a property of the account, not of the account within a cluster. An
admin is an admin everywhere they have been granted access.

## Granting access

Access is explicit. An account with no grant reaches nothing, and adding an
account does not by itself give it anything. Grants are managed by an owner in
Settings, under Users.

There is no registration anywhere in the platform. The only account creation
paths are first run setup, which makes exactly one owner, and an owner creating
an account afterwards. Nobody can sign themselves up.

## API keys

A key belongs to the account that created it and inherits that account's role.
It can be narrowed to a single cluster, and a narrowed key cannot reach another
cluster even if the account that made it could.

Two behaviours are worth stating because they are easy to assume wrongly:

- A key whose creator has been deleted or deactivated stops being a credential.
  It does not fall back to another account.
- Revoking a key takes effect on the next request. There is no cache to wait
  for.

Keys are stored as an HMAC digest, never in a recoverable form. The token is
shown once, when it is created. If it is lost, make another and revoke the old
one.

## Sessions

A console session is an opaque token held in Redis, so signing out or revoking
every session takes effect immediately rather than waiting for a token to
expire. Sessions last twelve hours and slide forward while you are active, so an
operator is not signed out mid task.

The session cookie is `HttpOnly` and `SameSite=Lax`. It is marked `Secure` only
when `CUBICLE_PUBLIC_URL` starts with `https://`, which is one more reason to
set that correctly.

## Ceilings

Each cluster has a ceiling on memory, CPU and storage that an owner sets. Every
function and every data service counts against it, and admission control refuses
an allocation that would exceed it rather than overcommitting the host.

The console shows what is committed against each ceiling in the cluster header,
and `cubicle status` prints the same figures.

## Adding a cluster

Owners create clusters in Settings. A new cluster gets its own slug, which
becomes part of the function URLs it serves, its own ingress domain if you want
one, and its own data directory.

From the CLI, `cubicle clusters` lists them and `--cluster <slug>` acts on one:

```bash
cubicle --cluster staging ls
```

Set `CUBICLE_CLUSTER` in the environment to change your default for a shell.

## What is not isolated

Cluster isolation is enforced in the API, thoroughly. It is not enforced at the
network layer: all isolates and all managed data services share one Docker
network. Function code in one cluster can therefore open a connection to another
cluster's isolate.

This matters if you intend to host tenants who do not trust each other. See
[the security model](security.md) and finding CUB-02 in
[the audit](security-audit.md).
