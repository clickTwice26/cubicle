from . import (
    ai,
    auth,
    cluster,
    clusters,
    config,
    data_services,
    database,
    functions,
    invoke,
    live,
    observability,
    redis_browser,
    settings,
    setup,
)

ROUTERS = [
    setup.router,
    ai.router,
    auth.router,
    clusters.router,
    functions.router,
    config.router,
    observability.router,
    live.router,
    cluster.router,
    data_services.router,
    database.router,
    redis_browser.router,
    settings.router,
    invoke.router,
]

__all__ = ["ROUTERS"]
