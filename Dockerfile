FROM node:24-slim AS frontend
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN npm ci --prefix frontend
COPY frontend/index.html frontend/vite.config.ts frontend/tsconfig.json frontend/tsconfig.node.json ./frontend/
COPY frontend/src ./frontend/src
RUN npm run build --prefix frontend

FROM node:24-slim
WORKDIR /app
RUN corepack enable
RUN apt-get update \
  && apt-get install -y --no-install-recommends python3 python3-venv \
  && rm -rf /var/lib/apt/lists/*
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY tsconfig.json biome.json ./
COPY src ./src
COPY db ./db
COPY sdk ./sdk
COPY --from=frontend /app/frontend/dist ./frontend/dist
EXPOSE 3000
CMD ["pnpm", "start"]
