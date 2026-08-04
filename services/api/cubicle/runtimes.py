"""The runtimes a function can be written in.

A runtime is an image that serves the agent protocol — `GET /healthz` and
`POST /invoke` — plus the two facts the rest of the platform needs about it:
what its entry file is called, and how its dependencies are declared. Nothing
else in the control plane knows one language from another.

Python and JavaScript ship with the instance; the compose file builds both.
Everything else is present here but not installed, and is built on demand from
Settings. Building rather than pulling is deliberate: the agent has to be
inside the image, and there is no public registry of Cubicle runtime images to
pull one from. It also means a runtime installs onto whichever node needs it,
including a remote engine reached over TCP.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RuntimeSpec:
    key: str
    label: str
    #: What to call the language in prose, and what to group by in the console.
    language: str
    #: The image the isolate runs. Tagged with the instance version so an
    #: upgrade rebuilds rather than silently reusing last release's agent.
    repository: str
    #: What the runtime image is built FROM. This is the download an operator
    #: waits for when installing one.
    base_image: str
    entry_file: str
    deps_file: str
    #: Where the build context lives, relative to services/runtime.
    context: str
    build_args: dict[str, str] = field(default_factory=dict)
    #: Shipped with the instance rather than installed on demand.
    builtin: bool = False
    #: Shown in the console when choosing. One line.
    summary: str = ""

    @property
    def min_memory_mb(self) -> int:
        """The smallest limit an isolate of this runtime actually serves at.

        Measured, not guessed: a Python agent with a trivial handler holds
        18 MB and serves at a 32 MB limit; at 24 MB it starts but never
        answers, and at 16 MB the container will not start at all. Node's
        baseline is higher, so it gets more headroom rather than one floor
        that is wrong for one of them.
        """
        return 64 if self.language == "JavaScript" else 32

    @property
    def env(self) -> dict[str, str]:
        """Where the isolate looks for the dependencies the build installed."""
        if self.language == "JavaScript":
            return {"NODE_PATH": "/srv/.deps/node_modules:/srv/node_modules"}
        return {"PYTHONPATH": "/srv/.deps:/srv", "PYTHONDONTWRITEBYTECODE": "1"}


RUNTIMES: dict[str, RuntimeSpec] = {
    "python312": RuntimeSpec(
        key="python312",
        label="Python 3.12",
        language="Python",
        repository="cubicle/runtime-py312",
        base_image="python:3.12-slim",
        entry_file="handler.py",
        deps_file="requirements.txt",
        context="python",
        build_args={"PYTHON_VERSION": "3.12"},
        builtin=True,
        summary="The default. Ships with psycopg and redis already installed.",
    ),
    "python311": RuntimeSpec(
        key="python311",
        label="Python 3.11",
        language="Python",
        repository="cubicle/runtime-py311",
        base_image="python:3.11-slim",
        entry_file="handler.py",
        deps_file="requirements.txt",
        context="python",
        build_args={"PYTHON_VERSION": "3.11"},
        builtin=True,
        summary="For dependencies that have not caught up with 3.12 yet.",
    ),
    "node22": RuntimeSpec(
        key="node22",
        label="Node 22",
        language="JavaScript",
        repository="cubicle/runtime-node22",
        base_image="node:22-slim",
        entry_file="handler.js",
        deps_file="package.json",
        context="node",
        build_args={"NODE_VERSION": "22"},
        builtin=True,
        summary="Current LTS. ES modules and CommonJS both work.",
    ),
    "node20": RuntimeSpec(
        key="node20",
        label="Node 20",
        language="JavaScript",
        repository="cubicle/runtime-node20",
        base_image="node:20-slim",
        entry_file="handler.js",
        deps_file="package.json",
        context="node",
        build_args={"NODE_VERSION": "20"},
        summary="The previous LTS, for packages that have not moved on.",
    ),
    "node18": RuntimeSpec(
        key="node18",
        label="Node 18",
        language="JavaScript",
        repository="cubicle/runtime-node18",
        base_image="node:18-slim",
        entry_file="handler.js",
        deps_file="package.json",
        context="node",
        build_args={"NODE_VERSION": "18"},
        summary="Maintenance only. Choose it to match an existing deployment.",
    ),
    "python313": RuntimeSpec(
        key="python313",
        label="Python 3.13",
        language="Python",
        repository="cubicle/runtime-py313",
        base_image="python:3.13-slim",
        entry_file="handler.py",
        deps_file="requirements.txt",
        context="python",
        build_args={"PYTHON_VERSION": "3.13"},
        summary="Newest Python. Some native packages have no wheels for it yet.",
    ),
    "python310": RuntimeSpec(
        key="python310",
        label="Python 3.10",
        language="Python",
        repository="cubicle/runtime-py310",
        base_image="python:3.10-slim",
        entry_file="handler.py",
        deps_file="requirements.txt",
        context="python",
        build_args={"PYTHON_VERSION": "3.10"},
        summary="For code that has not been ported past 3.10.",
    ),
}

#: The runtime a new function gets when nothing else is said.
DEFAULT = "python312"


def get(key: str) -> RuntimeSpec:
    """The spec for a runtime, falling back to the default rather than raising.

    A function whose runtime was removed from this table still has to be
    serialisable and still has to run; falling back keeps the console usable
    while the operator changes it.
    """
    return RUNTIMES.get(key, RUNTIMES[DEFAULT])


def keys() -> list[str]:
    return list(RUNTIMES)


def builtin() -> list[RuntimeSpec]:
    return [spec for spec in RUNTIMES.values() if spec.builtin]


def by_language() -> dict[str, list[RuntimeSpec]]:
    grouped: dict[str, list[RuntimeSpec]] = {}
    for spec in RUNTIMES.values():
        grouped.setdefault(spec.language, []).append(spec)
    return grouped


def labels() -> dict[str, str]:
    return {key: spec.label for key, spec in RUNTIMES.items()}
