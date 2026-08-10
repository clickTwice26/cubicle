"""What `cubicle market` and `cubicle services` promise.

Two of these are pinned harder than the rest. An install runs a stranger's code
on this cluster, so it says what the package is and asks before it creates
anything. A connection URL carries a password in plain text, so exactly one
command prints one, and it prints nothing else.
"""

from __future__ import annotations

import json

from cubicle_cli.client import BUILD_TIMEOUT, CubicleError
from cubicle_cli.commands import market, services

URL = "https://registry.test/packages/slack-notify.json"

GROUP = {"id": "grp-1", "name": "payments", "ns": "payments", "function_count": 1}


def _listing(**overrides) -> dict:
    """One row of a registry index, as GET /api/marketplace returns them."""
    listing = {
        "slug": "slack-notify",
        "name": "Slack Notify",
        "summary": "Post a message to a Slack webhook",
        "author": "cubicle",
        "runtime": "python312",
        "language": "Python",
        "tags": ["slack"],
        "url": URL,
        "version": "1.2.0",
        "homepage": "",
        "runtime_installed": True,
    }
    return {**listing, **overrides}


def _index(*packages: dict, registry: str = "https://registry.test/index.json") -> dict:
    return {"registry": registry, "is_default": True, "packages": list(packages) or [_listing()]}


def _package(**overrides) -> dict:
    """One package in full, as GET /api/marketplace/package returns it."""
    package = {
        "slug": "slack-notify",
        "name": "Slack Notify",
        "summary": "Post a message to a Slack webhook",
        "author": "cubicle",
        "license": "MIT",
        "version": "1.2.0",
        "homepage": "",
        "runtime": "python312",
        "runtime_label": "Python 3.12",
        "language": "Python",
        "method": "POST",
        "ctx_access": "rw",
        "function_type": "dependent",
        "memory_mb": 128,
        "timeout_s": 30,
        "tags": ["slack"],
        "env": [],
        "readme": "",
        "files": {"handler.py": "def handler(event, ctx):\n    return {'ok': True}\n"},
        "runtime_installed": True,
        "source_url": URL,
    }
    return {**package, **overrides}


def _node_package() -> dict:
    return _package(runtime="node22", runtime_label="Node 22", files={"handler.js": "//\n"})


def _installed(**overrides) -> dict:
    """The function POST /api/marketplace/install answers with, still building."""
    created = {
        "id": "fn-9",
        "namespace": "payments",
        "name": "slack-notify",
        "runtime": "python312",
        "version": 1,
        "version_status": "pending",
        "url": "https://fn.example.com/payments/slack-notify",
        "build_log": "",
        "declared_env": [],
    }
    return {**created, **overrides}


# ── market ───────────────────────────────────────────────────────────────────


def test_the_listing_carries_the_url_every_other_command_takes(api, run, capsys):
    """A package is addressed by URL, so a listing that omitted it would be unusable."""
    api.on("GET", "/api/marketplace", _index())

    assert run("market") == 0

    out = capsys.readouterr().out
    assert "slack-notify" in out
    assert URL in out


def test_a_package_this_instance_could_not_run_says_so(api, run, capsys):
    """Installing needs the runtime already built here, and browsing is where that shows."""
    api.on("GET", "/api/marketplace", _index(_listing(runtime="node22", runtime_installed=False)))

    run("market")

    assert "node22 (not installed)" in capsys.readouterr().out


def test_browse_reads_the_registry_it_is_pointed_at(api, run):
    """A company registry is a URL, not a fork, and the endpoint takes one."""
    api.on("GET", "/api/marketplace", _index(registry="https://private.test/index.json"))

    assert run("market", "--registry", "https://private.test/index.json") == 0

    assert api.last("GET", "/api/marketplace").params["url"] == "https://private.test/index.json"


def test_show_prints_the_source_it_would_build(api, run, capsys):
    """Reviewing the code is the only thing between a stranger's repository and the cluster."""
    api.on("GET", "/api/marketplace/package", _package())

    assert run("market", "show", URL) == 0

    out = capsys.readouterr().out
    assert "def handler(event, ctx):" in out
    assert api.last("GET", "/api/marketplace/package").params == {"url": URL}


def test_show_says_when_the_runtime_is_not_on_this_instance(api, run, capsys):
    """The package reads fine and could not be installed; that is worth saying once."""
    api.on("GET", "/api/marketplace/package", _package(runtime_installed=False))

    run("market", "show", URL)

    assert "not installed on this instance" in capsys.readouterr().out


def test_show_lists_the_env_the_package_expects(api, run, capsys):
    """Nothing sets these for you, so they are the work the install leaves behind."""
    api.on(
        "GET",
        "/api/marketplace/package",
        _package(env=[{"key": "SLACK_WEBHOOK", "required": True, "description": "Incoming URL"}]),
    )

    run("market", "show", URL)

    out = capsys.readouterr().out
    assert "SLACK_WEBHOOK" in out
    assert "required" in out


def test_install_asks_before_running_someone_elses_code(api, run, capsys):
    """With no terminal to ask, it names the flag rather than assuming yes."""
    api.on("GET", "/api/marketplace/package", _package())

    assert run("market", "install", URL, "--namespace", "payments") == 1

    assert "--yes" in capsys.readouterr().err
    assert api.sent("POST", "/api/marketplace/install") == []


def test_saying_no_to_an_install_creates_nothing_at_all(api, run, capsys, monkeypatch):
    """The namespace is asked for after the answer, so a refusal leaves none behind."""
    monkeypatch.setattr(market, "confirm", lambda *_, **__: False)
    api.on("GET", "/api/marketplace/package", _package())

    assert run("market", "install", URL, "--namespace", "payments") == 1

    assert "nothing installed" in capsys.readouterr().out
    assert api.sent("GET", "/api/groups") == []
    assert api.sent("POST", "/api/marketplace/install") == []


def test_install_creates_the_function_and_waits_for_its_build(api, run, capsys):
    """The install answers while the build is still an asyncio task, so the news comes later."""
    api.on("GET", "/api/marketplace/package", _package())
    api.on("GET", "/api/groups", [GROUP])
    api.on("POST", "/api/marketplace/install", _installed())
    api.on("GET", "/api/functions/fn-9", _installed(version_status="ready"))

    assert run("--yes", "market", "install", URL, "--namespace", "payments") == 0

    assert api.last("POST", "/api/marketplace/install").body == {
        "url": URL,
        "group_id": "grp-1",
        "name": "slack-notify",
    }
    out = capsys.readouterr().out
    assert "installed" in out
    assert "deployed" in out
    assert "https://fn.example.com/payments/slack-notify" in out


def test_a_name_of_your_own_is_the_one_created(api, run):
    """Two installs of one package into one namespace need different names."""
    api.on("GET", "/api/marketplace/package", _package())
    api.on("GET", "/api/groups", [GROUP])
    api.on("POST", "/api/marketplace/install", _installed(name="notify-ops"))
    api.on("GET", "/api/functions/fn-9", _installed(name="notify-ops", version_status="ready"))

    run("--yes", "market", "install", URL, "--namespace", "payments", "--name", "notify-ops")

    assert api.last("POST", "/api/marketplace/install").body["name"] == "notify-ops"


def test_install_stops_early_when_the_runtime_is_missing(api, run, capsys):
    """The server would refuse this too; refusing here means nobody is asked to confirm it."""
    api.on("GET", "/api/marketplace/package", _node_package() | {"runtime_installed": False})

    assert run("--yes", "market", "install", URL, "--namespace", "payments") == 1

    assert "cubicle runtimes install node22" in capsys.readouterr().err
    assert api.sent("POST", "/api/marketplace/install") == []


def test_the_control_planes_own_refusal_becomes_the_same_advice(api, run, capsys):
    """It re-checks the runtime itself, and its message points at the console instead."""
    api.on("GET", "/api/marketplace/package", _node_package())
    api.on("GET", "/api/groups", [GROUP])
    api.on(
        "POST",
        "/api/marketplace/install",
        CubicleError("409: This function needs Node 22, which is not installed on this instance."),
    )

    assert run("--yes", "market", "install", URL, "--namespace", "payments") == 1

    assert "cubicle runtimes install node22" in capsys.readouterr().err


def test_a_failed_build_comes_back_with_its_log(api, run, capsys):
    """A package that does not build is the one time the build log is the whole answer."""
    api.on("GET", "/api/marketplace/package", _package())
    api.on("GET", "/api/groups", [GROUP])
    api.on("POST", "/api/marketplace/install", _installed())
    api.on(
        "GET",
        "/api/functions/fn-9",
        _installed(version_status="failed", build_log="ModuleNotFoundError: slack_sdk"),
    )

    assert run("--yes", "market", "install", URL, "--namespace", "payments") == 1

    assert "ModuleNotFoundError: slack_sdk" in capsys.readouterr().out


def test_a_successful_install_names_the_env_it_still_needs(api, run, capsys):
    """The package declares them and the installer deliberately sets none of them."""
    declared = [{"key": "SLACK_WEBHOOK", "required": True, "description": "Incoming URL"}]
    api.on("GET", "/api/marketplace/package", _package())
    api.on("GET", "/api/groups", [GROUP])
    api.on("POST", "/api/marketplace/install", _installed(declared_env=declared))
    api.on("GET", "/api/functions/fn-9", _installed(version_status="ready"))

    run("--yes", "market", "install", URL, "--namespace", "payments")

    out = capsys.readouterr().out
    assert "SLACK_WEBHOOK" in out
    assert "cubicle env set KEY=value" in out


def test_export_prints_a_document_and_nothing_else(api, run, capsys, api_function):
    """It is a file on its way to a registry, so anything friendly around it would be deleted."""
    document = {"schema": 1, "slug": "create-charge", "files": {"handler.py": "x = 1\n"}}
    api.on("GET", "/api/functions", [api_function()])
    api.on("GET", "/api/marketplace/export/fn-1", document)

    assert run("market", "export", "payments/create-charge") == 0

    assert json.loads(capsys.readouterr().out) == document


# ── services ─────────────────────────────────────────────────────────────────


def _service(kind: str = "postgres", **overrides) -> dict:
    """One entry of GET /api/services, running, with its own shape of stats."""
    if kind == "postgres":
        config = {
            "memory": "512 MB",
            "storage": "10 GB",
            "node_pool": "general",
            "database": "cubicle",
            "user": "cubicle",
        }
        stats = {
            "size_bytes": 50331648,
            "size_label": "48 MB",
            "tables": 12,
            "connections": 4,
            "max_connections": 100,
        }
        url = "postgres://cubicle:••••••@cubicle-postgres:5432/cubicle"
    else:
        config = {"memory": "128 MB", "eviction": "allkeys-lru", "node_pool": "general"}
        stats = {"used_memory": 12582912, "memory_label": "12 MB", "keys": 1204, "max_memory": 0}
        url = "redis://:••••••@cubicle-redis:6379/0"

    service = {
        "kind": kind,
        "created": True,
        "status": "running",
        "version": "16.3" if kind == "postgres" else "7.2",
        "config": config,
        "connection_url": url,
        "node": "node-01",
        "stats": stats,
        "last_error": None,
    }
    return {**service, **overrides}


def _uncreated(kind: str) -> dict:
    return _service(
        kind,
        created=False,
        status="not_created",
        config={},
        connection_url=None,
        node="",
        stats={},
    )


def test_the_listing_keeps_the_password_out_of_it(api, run, capsys):
    """The API sends a masked URL with every service and none of them belong in a list."""
    api.on("GET", "/api/services", [_service("postgres"), _service("redis")])

    assert run("services") == 0

    out = capsys.readouterr().out
    assert "postgres://" not in out
    assert "redis://" not in out
    assert "cubicle services url" in out


def test_the_listing_says_what_each_service_is_holding(api, run, capsys):
    """Postgres counts tables and connections, Redis counts keys, and neither reads as the other."""
    api.on("GET", "/api/services", [_service("postgres"), _service("redis")])

    run("services")

    out = capsys.readouterr().out
    assert "48 MB · 12 tables · 4/100 connections" in out
    assert "12 MB · 1204 keys" in out


def test_a_service_that_does_not_exist_yet_says_how_to_get_one(api, run, capsys):
    """A cluster starts with neither, and `not_created` on its own explains nothing."""
    api.on("GET", "/api/services/redis", _uncreated("redis"))

    assert run("services", "show", "redis") == 0

    out = capsys.readouterr().out
    assert "not created" in out
    assert "cubicle services create redis" in out


def test_show_prints_the_masked_url_and_the_settings_behind_it(api, run, capsys):
    """The masked URL says which host and database, which is the useful half of it."""
    api.on("GET", "/api/services/postgres", _service())

    run("services", "show", "postgres")

    out = capsys.readouterr().out
    assert "cubicle-postgres:5432" in out
    assert "••••••" in out
    assert "cubicle as cubicle" in out


def test_the_url_command_prints_the_url_and_absolutely_nothing_else(api, run, capsys):
    """`$(cubicle services url redis)` has to be the URL, so there is no frame around it."""
    revealed = _service("redis", connection_url="redis://:s3cr3t@cubicle-redis:6379/0")
    api.on("GET", "/api/services/redis/connection", revealed)

    assert run("services", "url", "redis") == 0

    assert capsys.readouterr().out == "redis://:s3cr3t@cubicle-redis:6379/0\n"


def test_there_is_no_url_while_the_container_is_not_running(api, run, capsys):
    """The API answers null rather than an error, and null is not something to print."""
    stopped = _service(status="stopped", connection_url=None)
    api.on("GET", "/api/services/postgres/connection", stopped)

    assert run("services", "url", "postgres") == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "stopped" in captured.err


def test_create_asks_the_instance_which_version_it_defaults_to(api, run):
    """ServiceCreate requires a version and has no default, and the API knows its own."""
    api.on("GET", "/api/services/postgres", _uncreated("postgres"))
    api.on("POST", "/api/services/postgres", _service())

    assert run("services", "create", "postgres") == 0

    assert api.last("POST", "/api/services/postgres").body == {"version": "16.3"}


def test_create_waits_out_a_cold_image_pull(api, run):
    """The image is pulled inside the request, which is minutes on an engine that lacks it."""
    api.on("GET", "/api/services/postgres", _uncreated("postgres"))
    api.on("POST", "/api/services/postgres", _service())

    run("services", "create", "postgres")

    assert api.last("POST", "/api/services/postgres").timeout == BUILD_TIMEOUT


def test_create_sends_only_the_settings_it_was_given(api, run):
    """Every one of these has a default in the API, and the API should be the one applying it."""
    api.on("POST", "/api/services/redis", _service("redis"))

    assert (
        run(
            "services",
            "create",
            "redis",
            "--version",
            "7.2",
            "--memory",
            "512mb",
            "--eviction",
            "noeviction",
        )
        == 0
    )

    assert api.last("POST", "/api/services/redis").body == {
        "version": "7.2",
        "memory": "512 MB",
        "eviction": "noeviction",
    }
    assert api.sent("GET", "/api/services/redis") == []


def test_a_memory_size_the_api_would_round_off_is_refused(api, run, capsys):
    """An unlabelled size is read as 1 GB there rather than refused, which nobody would see."""
    assert run("services", "create", "postgres", "--version", "16.3", "--memory", "500 MB") == 1

    assert "must be one of" in capsys.readouterr().err
    assert api.sent("POST", "/api/services/postgres") == []


def test_a_setting_that_belongs_to_the_other_service_is_refused(api, run, capsys):
    """create_postgres never sees --eviction, so passing it would be silently ignored."""
    argv = ("services", "create", "postgres", "--version", "16.3", "--eviction", "noeviction")

    assert run(*argv) == 1

    assert "Redis setting" in capsys.readouterr().err
    assert api.sent("POST", "/api/services/postgres") == []


def test_start_and_stop_report_the_state_they_left_it_in(api, run, capsys):
    """Stopping takes a twenty second Docker timeout, so the answer is worth printing."""
    api.on("POST", "/api/services/redis/start", _service("redis", status="running"))

    assert run("services", "start", "redis") == 0

    assert "started redis · running" in capsys.readouterr().out


def test_recreate_will_not_replace_a_container_unasked(api, run, capsys):
    """Everything connected to it is cut off while it restarts."""
    assert run("services", "recreate", "postgres") == 1

    assert "--yes" in capsys.readouterr().err
    assert api.sent("POST", "/api/services/postgres/recreate") == []


def test_saying_no_to_a_delete_deletes_nothing(api, run, capsys, monkeypatch):
    """The default takes the volume with it, so a refusal has to reach the API not at all."""
    monkeypatch.setattr(services, "confirm", lambda *_, **__: False)

    assert run("services", "rm", "postgres") == 1

    assert "nothing removed" in capsys.readouterr().out
    assert api.sent("DELETE", "/api/services/postgres") == []


def test_rm_takes_the_volume_with_it_by_default(api, run):
    """keep_data defaults to false in the router, and this sends nothing that would change it."""
    api.on("DELETE", "/api/services/postgres", None)

    assert run("--yes", "services", "rm", "postgres") == 0

    assert api.last("DELETE", "/api/services/postgres").params == {}


def test_keeping_the_data_says_what_that_actually_leaves(api, run, capsys):
    """The password row goes with the service, so the volume it keeps is unreadable."""
    api.on("DELETE", "/api/services/redis", None)

    assert run("--yes", "services", "rm", "redis", "--keep-data") == 0

    assert api.last("DELETE", "/api/services/redis").params == {"keep_data": "true"}
    assert "no future service can read it" in capsys.readouterr().out
