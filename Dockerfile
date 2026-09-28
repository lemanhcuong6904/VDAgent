# Build the browser bundle with its isolated npm lockfile.
FROM node@sha256:0e0ff40c39bc087845bfb27465a0df4ea419520094bc35842ff83dd8cbe6f9b6 AS frontend
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN npm ci --prefix frontend
COPY frontend/index.html frontend/vite.config.ts frontend/tsconfig.json frontend/tsconfig.node.json ./frontend/
COPY frontend/src ./frontend/src
RUN npm run build --prefix frontend

# Compile the TypeScript server and materialize the Python roster in a build stage.
FROM node@sha256:0e0ff40c39bc087845bfb27465a0df4ea419520094bc35842ff83dd8cbe6f9b6 AS build
WORKDIR /app
RUN corepack enable \
  && apt-get update \
  && apt-get install -y --no-install-recommends gcc libc6-dev libseccomp-dev python3 python3-venv \
  && rm -rf /var/lib/apt/lists/*
# Pin the multi-architecture uv index by digest rather than a mutable tag.
COPY --from=ghcr.io/astral-sh/uv@sha256:f3660c56d5b08d6c516360981bedc439f499b9bf37f46a216018da3777a74011 /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_PYTHON=python3 UV_LINK_MODE=copy
COPY package.json pnpm-lock.yaml versions.json tsconfig.json tsconfig.build.json ./
RUN pnpm install --frozen-lockfile
COPY src ./src
COPY db ./db
COPY sdk ./sdk
COPY agents ./agents
COPY docker/bwrap-seccomp.c ./docker/bwrap-seccomp.c
RUN gcc -O2 -Wall -Wextra -Werror docker/bwrap-seccomp.c -lseccomp -o /tmp/make-bwrap-seccomp \
  && /tmp/make-bwrap-seccomp > ./agent-seccomp.bpf
RUN pnpm build:server
RUN uv sync --frozen --no-dev --project agents
# Remove development-only JavaScript packages before the runtime image is assembled.
RUN pnpm prune --prod

# Runtime image: no TypeScript loader, compiler, test runner or linter is included.
FROM node@sha256:0e0ff40c39bc087845bfb27465a0df4ea419520094bc35842ff83dd8cbe6f9b6 AS runtime
WORKDIR /app
RUN apt-get update \
  && apt-get install -y --no-install-recommends python3 bubblewrap \
  && rm -rf /var/lib/apt/lists/* \
  && mkdir -p /app /tmp \
  && chown -R node:node /app
COPY --from=ghcr.io/astral-sh/uv@sha256:f3660c56d5b08d6c516360981bedc439f499b9bf37f46a216018da3777a74011 /uv /usr/local/bin/uv
COPY --from=build --chown=node:node /app/package.json /app/tsconfig.json /app/versions.json ./
COPY --from=build --chown=node:node /app/node_modules ./node_modules
COPY --from=build --chown=node:node /app/dist ./dist
COPY --from=build --chown=node:node /app/db ./db
COPY --from=build --chown=node:node /app/sdk ./sdk
COPY --from=build --chown=node:node /app/agents ./agents
COPY --from=build --chown=node:node /app/agent-seccomp.bpf ./agent-seccomp.bpf
COPY --from=frontend --chown=node:node /app/frontend/dist ./frontend/dist
ENV NODE_ENV=production \
  UV_PYTHON_DOWNLOADS=never \
  UV_PYTHON=python3 \
  UV_LINK_MODE=copy \
  UV_CACHE_DIR=/tmp/uv-cache
USER node
EXPOSE 3000

FROM runtime AS api
CMD ["node", "dist/server.js"]

FROM runtime AS worker
CMD ["node", "dist/worker.js"]
