"""What the two read-only views say about a cluster.

Both had gone quiet about facts that had since become the interesting ones: a
cluster's ceilings, whether Redis is the thing that is down, whether a node
can still take work, and how far a function is allowed to scale.
"""

from __future__ import annotations

HEALTH = {
    "status": "ok",
    "version": "1.0.0",
    "checks": {"database": True, "redis": True, "docker": True},
    "warm_isolates": 2,
}

INSTANCE = {
    "cluster_name": "Production",
    "cluster_slug": "prod",
    "base_url": "https://fn.example.com",
    "cluster_count": 2,
    "version": "1.0.0",
}


def _node(name: str, *, status: str = "ready", schedulable: bool = True) -> dict:
    return {"name": name, "status": status, "schedulable": schedulable, "pool": "general"}


def _resources(*, memory_cap: float = 0, cpu_cap: float = 0, isolates: int = 3) -> dict:
    def headroom(cap: float, held: float) -> dict:
        return {
            "limited": bool(cap),
            "used": held,
            "reserved": 0,
            "held": held,
            "cap": cap,
            "free": max(0.0, cap - held),
            "pct": round(held / cap * 100, 1) if cap else 0.0,
        }

    return {
        "cluster": "prod",
        "isolates": isolates,
        "memory": headroom(memory_cap, 768),
        "cpu": headroom(cpu_cap, 1.5),
    }


def _serve_status(api, *, nodes=None, resources=None) -> None:
    api.on("GET", "/healthz", HEALTH)
    api.on("GET", "/api/settings/instance", INSTANCE)
    api.on("GET", "/api/cluster/nodes", nodes if nodes is not None else [_node("node-01")])
    api.on("GET", "/api/cluster/resources", resources or _resources())


def test_status_shows_the_ceilings_a_deploy_runs_into(api, run, capsys):
    """These are the numbers behind a 507, and nothing else reports them."""
    _serve_status(api, resources=_resources(memory_cap=2048, cpu_cap=4))

    assert run("status") == 0

    out = capsys.readouterr().out
    assert "MEMORY          768/2048 MB (38%)" in out
    assert "CPU             1.50/4.00 cores (38%)" in out


def test_an_unlimited_cluster_gets_no_denominator(api, run, capsys):
    """With no quota there is no fraction to print, so the line is left out."""
    _serve_status(api)

    run("status")

    out = capsys.readouterr().out
    assert "MEMORY" not in out
    assert "ISOLATES        3 warm" in out


def test_the_isolate_count_is_the_one_for_this_cluster(api, run, capsys):
    """/api/cluster/isolates counts the whole instance; every other line here does not."""
    _serve_status(api, resources=_resources(isolates=7))

    run("status")

    assert "ISOLATES        7 warm" in capsys.readouterr().out
    assert api.sent("GET", "/api/cluster/isolates") == []


def test_redis_gets_its_own_line(api, run, capsys):
    """Health is degraded when Redis is down, so the block has to say which one it was."""
    checks = {**HEALTH["checks"], "redis": False}
    api.on("GET", "/healthz", {**HEALTH, "status": "degraded", "checks": checks})
    api.on("GET", "/api/settings/instance", INSTANCE)
    api.on("GET", "/api/cluster/nodes", [_node("node-01")])
    api.on("GET", "/api/cluster/resources", _resources())

    run("status")

    out = capsys.readouterr().out
    assert "CONTROL PLANE   down" in out
    assert "REDIS           down" in out
    assert "DATABASE        ready" in out


def test_a_drained_node_is_not_a_ready_node(api, run, capsys):
    """It is up, and it will not take a single isolate."""
    _serve_status(api, nodes=[_node("node-01"), _node("node-02", schedulable=False)])

    run("status")

    assert "NODES           1/2" in capsys.readouterr().out


def test_ls_shows_the_type_and_the_instance_range(api, run, capsys, api_function):
    """Both arrived after the CLI was last touched, and both change what a function is."""
    api.on(
        "GET",
        "/api/functions",
        [api_function(function_type="independent", min_instances=1, max_instances=8)],
    )

    assert run("ls") == 0

    out = capsys.readouterr().out
    assert "TYPE" in out
    assert "SCALE" in out
    assert "independent" in out
    assert "1-8" in out


def test_a_paused_function_says_paused(api, run, capsys, api_function):
    """A paused function has a ready version and serves nothing."""
    api.on("GET", "/api/functions", [api_function(status="paused")])

    run("ls")

    assert "v3 paused" in capsys.readouterr().out


def test_nothing_deployed_is_not_an_error(api, run, capsys):
    """An empty cluster prints the table helper's own empty line."""
    api.on("GET", "/api/functions", [])

    assert run("ls") == 0
    assert "(nothing to show)" in capsys.readouterr().out
