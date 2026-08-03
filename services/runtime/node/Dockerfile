ARG NODE_VERSION=22
FROM node:${NODE_VERSION}-slim

# The JavaScript isolate image. It carries the Cubicle agent; the function's own
# code and dependencies arrive at run time on a read-only volume built at deploy,
# exactly as they do for the Python runtime.

ENV NODE_ENV=production \
    CUBICLE_AGENT_PORT=8080 \
    # npm writes its cache and logs somewhere, and the root filesystem is
    # read-only. /tmp is the tmpfs the control plane attaches.
    npm_config_cache=/tmp/.npm

COPY agent.js /opt/cubicle/agent.js

RUN node --check /opt/cubicle/agent.js && echo "agent ok"

# Isolates run unprivileged with a read-only root filesystem. The node image
# ships a `node` user at 1000; Cubicle runs every isolate as 65532 so the two
# runtimes are indistinguishable to the platform.
RUN useradd --uid 65532 --no-create-home --shell /usr/sbin/nologin isolate
USER 65532:65532

EXPOSE 8080
WORKDIR /srv

CMD ["node", "/opt/cubicle/agent.js"]
