ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim

# The isolate image. It carries the Cubicle SDK and the agent that runs a
# function; the function's own code and dependencies arrive at run time on a
# read-only volume built at deploy.

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CUBICLE_AGENT_PORT=8080

RUN pip install --no-cache-dir "psycopg[binary]==3.2.3" "redis==5.2.1"

COPY sdk/cubicle_context /opt/cubicle/sdk/cubicle_context
COPY sdk/cubicle_db /opt/cubicle/sdk/cubicle_db
COPY agent.py /opt/cubicle/agent.py

# Registered through a .pth file rather than PYTHONPATH, so the SDK stays
# importable even though the control plane sets PYTHONPATH for the function's
# own dependencies.
RUN python -c "import pathlib, site; \
pathlib.Path(site.getsitepackages()[0], 'cubicle_sdk.pth').write_text('/opt/cubicle/sdk\n')" \
    && python -c "import cubicle_context, cubicle_db; print('sdk ok')"

# Isolates run unprivileged with a read-only root filesystem; /tmp is the only
# writable location and it is a tmpfs the control plane attaches.
RUN useradd --uid 65532 --no-create-home --shell /usr/sbin/nologin isolate
USER 65532:65532

EXPOSE 8080
WORKDIR /srv

CMD ["python", "/opt/cubicle/agent.py"]
