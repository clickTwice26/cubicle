from . import (
    auth,
    cluster,
    config,
    data_services,
    functions,
    invoke,
    observability,
    settings,
    setup,
)

ROUTERS = [
    setup.router,
    auth.router,
    functions.router,
    config.router,
    observability.router,
    cluster.router,
    data_services.router,
    settings.router,
    invoke.router,
]

__all__ = ["ROUTERS"]
