# Marketplace

The marketplace is a way to publish a function as a document and install
someone else's into your own namespace. It is a convention, not a service: a
package is a JSON document at a URL, and the index is a list of them.

## Installing

Review before you install:

```bash
cubicle market show https://example.com/packages/pdf-render.json
```

This prints what the package is, what runtime it needs, and what files it
carries. Then:

```bash
cubicle market install https://example.com/packages/pdf-render.json --namespace tools
```

The console has the same flow under Marketplace, with the source shown before
you confirm.

## What installing actually does

**It runs someone else's code on your cluster.** Installing creates a function
from source you did not write and builds an image from it, which runs that
package's dependency file through pip or npm. Treat a package the way you would
treat a dependency in any other project: from a source you trust, read before
you install.

Two things the platform does on your behalf:

The package is fetched again server side rather than taken from the browser.
What was shown for review is not necessarily what a request body claims it was,
and the source that gets built should be the source the registry actually
serves.

The runtime it needs must already be installed. If it is not, the install is
refused and tells you which runtime to install first:

```bash
cubicle runtimes install node22
```

A package may carry only `handler.py`, `requirements.txt`, `handler.js`,
`package.json` and `README.md`. Nothing else is accepted, and a JavaScript
package must carry `handler.js`.

## Publishing

Export a function you have written:

```bash
cubicle market export tools/pdf-render
```

This prints the package document. Host it anywhere that serves JSON over HTTPS
and share the URL. There is no central registry to submit to and no approval to
wait for.

The document carries the source, the runtime, the method and the default
resource settings. It does not carry your secrets or your environment values,
which is deliberate: a package that installed with its author's credentials
would be a hazard rather than a convenience. Whoever installs it sets their own.

## The `marketplace/` directory

The repository has a `marketplace/` directory with the packages that ship with
the project. They are ordinary packages, useful mostly as worked examples of the
format.
