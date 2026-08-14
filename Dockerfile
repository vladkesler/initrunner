ARG PYTHON_VERSION=3.13

# ---------------------------------------------------------------------------
# Stage 0 — Dashboard UI. `_static/` is gitignored and only produced by
# `pnpm build`; without this stage the image's default `dashboard` CMD is
# API-only and `/` 404s after login.
# Assets are arch-independent: build once on the native builder so the
# arm64 image does not compile Vite under QEMU.
# ---------------------------------------------------------------------------
FROM --platform=$BUILDPLATFORM node:22-bookworm-slim AS dashboard
WORKDIR /src/dashboard
RUN corepack enable
COPY dashboard/package.json dashboard/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY dashboard/ ./
# adapter-static writes to ../initrunner/dashboard/_static
RUN mkdir -p /src/initrunner/dashboard && pnpm build \
    && test -f /src/initrunner/dashboard/_static/index.html

# ---------------------------------------------------------------------------
# Stage 1 — Builder: install uv, build wheel, install with extras
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

ARG EXTRAS="all"

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Build toolchain for Python C extensions that lack prebuilt wheels for every
# arch/interpreter combination (e.g. fastavro on linux/arm64 cp313, pulled in
# transitively via pydantic-ai-slim[cohere]).
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libc6-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy dependency metadata first for layer caching
COPY pyproject.toml uv.lock ./

# Copy source code, then overlay the compiled dashboard so hatch packs it
# (`[tool.hatch.build] artifacts` includes the gitignored `_static/` tree).
COPY initrunner/ initrunner/
COPY --from=dashboard /src/initrunner/dashboard/_static/ initrunner/dashboard/_static/
COPY README.md LICENSE-MIT LICENSE-APACHE ./
RUN test -f initrunner/dashboard/_static/index.html

# Build wheel and install into system Python
RUN uv build --wheel --out-dir /build/dist && \
    WHEEL=$(ls /build/dist/initrunner-*.whl) && \
    uv pip install --system "${WHEEL}[${EXTRAS}]" && \
    python -c "from pathlib import Path; import initrunner.dashboard as d; \
p = Path(d.__file__).parent / '_static' / 'index.html'; \
assert p.is_file(), f'dashboard UI missing from wheel: {p}'"

# ---------------------------------------------------------------------------
# Stage 2 — Runtime: clean slim image with only installed packages
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim

# Install ca-certificates (runtime) and Docker CLI (for sandbox socket passthrough)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates curl && \
    DOCKER_ARCH="$(uname -m)" && \
    curl -fsSL "https://download.docker.com/linux/static/stable/${DOCKER_ARCH}/docker-27.5.1.tgz" \
      | tar xz --strip-components=1 -C /usr/local/bin docker/docker && \
    apt-get purge -y curl && apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# Copy installed packages and scripts from builder
COPY --from=builder /usr/local/lib/ /usr/local/lib/
COPY --from=builder /usr/local/bin/ /usr/local/bin/

# Persistent state directory
ENV INITRUNNER_HOME=/data
RUN mkdir -p /data

# OCI labels
LABEL org.opencontainers.image.title="InitRunner" \
      org.opencontainers.image.description="YAML-first AI agent platform" \
      org.opencontainers.image.source="https://github.com/vladkesler/initrunner" \
      org.opencontainers.image.licenses="MIT OR Apache-2.0"

EXPOSE 8000 8100

# Seed example roles for cloud/Docker first-boot
COPY examples/roles/hello-world.yaml \
     examples/roles/web-searcher.yaml \
     examples/roles/memory-assistant.yaml \
     examples/roles/code-reviewer.yaml \
     examples/roles/full-tools-assistant.yaml \
     /opt/initrunner/example-roles/

COPY deploy/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh


ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["initrunner", "dashboard", "--expose", "--no-open"]
