ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

# Install curl (needed by installer) and python3 (for http server)
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates python3 && rm -rf /var/lib/apt/lists/*

# Copy wheel + installer
COPY dist/ /tmp/dist/
COPY install.sh /tmp/install.sh
COPY hello-world.yaml /tmp/hello-world.yaml

# Build PEP 503 simple index from the wheel
RUN python3 -c "\
import pathlib, os;\
dist = pathlib.Path('/tmp/dist');\
idx = pathlib.Path('/tmp/pypi/simple/initrunner');\
idx.mkdir(parents=True, exist_ok=True);\
html = '<html><body>';\
wheels = sorted(dist.glob('*.whl'));\
[os.link(str(w), str(idx / w.name)) for w in wheels];\
html += ''.join(f'<a href=\"{w.name}\">{w.name}</a>\n' for w in wheels);\
html += '</body></html>';\
(idx / 'index.html').write_text(html);\
pathlib.Path('/tmp/pypi/simple/index.html').write_text(\
    '<html><body><a href=\"initrunner/\">initrunner</a></body></html>'\
)"

# Skip PyPI connectivity check, point installers at local index
ENV INITRUNNER_SKIP_PREFLIGHT=1
ENV UV_INDEX_URL=http://localhost:8080/simple/
ENV UV_EXTRA_INDEX_URL=https://pypi.org/simple/
ENV PIP_INDEX_URL=http://localhost:8080/simple/
ENV PIP_EXTRA_INDEX_URL=https://pypi.org/simple/
ENV PIP_TRUSTED_HOST=localhost

# Optional API key for e2e tests
ARG OPENAI_API_KEY=""
ENV OPENAI_API_KEY=${OPENAI_API_KEY}

# Build args for test scenario
ARG INSTALL_FLAGS="--unmanaged"
ARG PRE_CMD=""
ARG POST_CMD="initrunner --version"

# Start local pypi server, optional pre-command, run installer, post-check
RUN python3 -m http.server 8080 --directory /tmp/pypi &>/dev/null & \
    sleep 1 && \
    ${PRE_CMD:+sh -c "$PRE_CMD" &&} \
    sh /tmp/install.sh ${INSTALL_FLAGS} && \
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH" && \
    sh -c "$POST_CMD"
