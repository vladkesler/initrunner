---
name: container-scan
description: >
  Dockerfile security review. Checks for running as root, leaked secrets
  in build layers, insecure base images, and missing best practices.
---

Dockerfile security review skill. No external tools needed -- this is
pure code review of Dockerfile content.

## When to activate

Use this skill when the repository contains Dockerfile or
docker-compose.yaml files.

## Scanner approach

Read each Dockerfile with read_file. Analyze line by line for the
following checks.

## Checks

### 1. Running as root

- No `USER` instruction means the container runs as root
- `USER root` without switching to a non-root user later
- Flag as high severity

### 2. Unpinned base image

- `FROM` using `:latest` tag or no tag at all
- Recommend pinning to a specific version or digest

### 3. Secret exposure

- `ENV` or `ARG` instructions with password, secret, key, or token
  values baked into the image
- `COPY .env` or `COPY` of credential files into the image
- Flag as critical -- secrets persist in image layers

### 4. COPY vs ADD

- `ADD` from remote URLs (use `COPY` + `curl` instead for
  transparency and caching)
- `ADD` of archives without needing extraction (use `COPY`)

### 5. Missing HEALTHCHECK

- No `HEALTHCHECK` instruction in the final stage
- Flag as low severity (best practice)

### 6. Package manager hygiene

- `apt-get install` without `--no-install-recommends`
- Missing `rm -rf /var/lib/apt/lists/*` cleanup in the same layer
- Large image size from uncleaned package caches

### 7. Multi-stage builds

- Single-stage builds that include build tools (gcc, make, npm) in
  the final image
- Recommend multi-stage to separate build and runtime

## MUST flag

- No `USER` instruction (runs as root by default)
- Secrets in `ENV` or `ARG` instructions
- `COPY .env` or `COPY` of known credential files
- `ADD` from remote URLs

## MUST NOT flag

- Dev/CI Dockerfiles (Dockerfile.dev, Dockerfile.test, Dockerfile.ci)
- `scratch` or `distroless` base images (no USER needed, no shell)
- Multi-stage builds where root is only used in the builder stage
- `HEALTHCHECK` absence in builder stages (only matters in final stage)
