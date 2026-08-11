# Cubicle documentation

Cubicle is a serverless functions platform you run on your own server. You give
it a machine with Docker, it gives you a console, an HTTP API and a command line
client for writing functions, deploying them and watching them run.

These pages are written for two people: the operator who has to keep the
instance alive, and the developer who has to ship a function on it. Where the
two overlap, the operator's answer comes first.

## Start here

| If you want to | Read |
| --- | --- |
| Put Cubicle on a server | [Installation](install.md) |
| Understand how it is built | [Architecture](architecture.md) |
| Write and deploy a function | [Writing functions](functions.md) |
| Work from a terminal | [The CLI](cli.md) |
| Give your team access | [Clusters and access control](clusters.md) |
| Run a database next to your functions | [Data services](data-services.md) |
| Install someone else's function | [Marketplace](marketplace.md) |
| Keep the instance healthy | [Operations](operations.md) |
| Know what protects what | [Security model](security.md) |
| See where it is weak today | [Security audit](security-audit.md) |

## The shape of it in one page

An instance runs five containers: a reverse proxy, the console, the control
plane, Postgres and Redis. The control plane holds the Docker socket, so when a
request arrives for a function it can start a container to serve it, keep that
container warm for the next request, and take it back when nothing has used it
for a while.

A function is source code, a runtime, and a few numbers: how much memory, how
long before it is killed, how many copies may run at once. Deploying builds an
image, and the next request is served by it. Nothing runs until something calls
it, and a function nobody calls costs a row in the database.

One instance can host several clusters. A cluster is a tenant: its own
functions, its own configuration, its own ceilings on memory and CPU, and its
own list of accounts that may reach it. Accounts are granted clusters
explicitly, and an account with no grant sees nothing.

## Conventions in these pages

Commands you type are shown without a prompt character, one command per block,
so they can be copied whole. Paths are relative to the repository root. Where a
page states a default it is the default in the code, not a recommendation, and
the two are called out separately when they differ.
