ARG PYTHON_VERSION=3.12

# ---------------------------------------------------------------------------
# Stage 1 — Builder: install uv, build wheel, install with extras
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

ARG EXTRAS="all"

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /build

# Copy dependency metadata first for layer caching
COPY pyproject.toml uv.lock ./

# Copy source code
COPY initrunner/ initrunner/
COPY README.md LICENSE ./

# Build wheel and install into system Python
RUN uv build --wheel --out-dir /build/dist && \
    WHEEL=$(ls /build/dist/initrunner-*.whl) && \
    uv pip install --system "${WHEEL}[${EXTRAS}]"

# ---------------------------------------------------------------------------
# Stage 2 — Runtime: clean slim image with only installed packages
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates && \
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
      org.opencontainers.image.licenses="MIT"

EXPOSE 8000 8420

# Seed example roles for cloud/Docker first-boot
COPY examples/roles/hello-world.yaml \
     examples/roles/web-searcher.yaml \
     examples/roles/memory-assistant.yaml \
     examples/roles/code-reviewer.yaml \
     examples/roles/full-tools-assistant.yaml \
     /opt/initrunner/example-roles/

COPY deploy/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8420/api/health')" || exit 1

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["initrunner", "--help"]
