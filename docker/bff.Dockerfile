# Stage 1: Bundle the BFF into a single self-contained CJS file.
# At runtime only `node` is needed — no node_modules, no npm.
# Full nodejs-22 image used here so npm is available for the build.
# ubi10/nodejs-22 matches the base used by the main Dockerfile's frontend-builder
# stage — consistent Node version and OS libraries across both build artefacts.
FROM registry.access.redhat.com/ubi10/nodejs-22 AS builder
WORKDIR /frontend
# Copy only what npm needs to install dependencies — maximises layer cache.
COPY frontend/package*.json ./
RUN npm ci
# esbuild bundles server/ but server.ts imports from ../src/utils/logger,
# so src/ must be present for the bundle to resolve.
COPY frontend/server ./server
COPY frontend/src ./src
COPY frontend/tsconfig.server.json ./
RUN npm run build:bff   # esbuild → bff/server.cjs

# Stage 2: Lean production image — Node runtime + bundled server only.
# nodejs-22-minimal keeps the runtime image small (no npm, no build tools).
FROM registry.access.redhat.com/ubi10/nodejs-22-minimal
WORKDIR /app

# Run as UBI's default non-root UID 1001 for OpenShift / restricted PSP compatibility.
USER 1001

COPY --from=builder --chown=1001:0 /frontend/bff/server.cjs ./server.cjs

EXPOSE 3001
ENV BFF_PORT=3001
# BACKEND_API_URL has no default — it must be injected by the orchestrator
# (docker-compose: http://docpipe:8080, k8s sidecar: http://localhost:8080).
# Leaving it unset surfaces misconfiguration early rather than silently
# routing to a wrong host.

# curl is available in UBI minimal; wget is not.
HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
    CMD curl -fs http://localhost:3001/health || exit 1

CMD ["node", "server.cjs"]
