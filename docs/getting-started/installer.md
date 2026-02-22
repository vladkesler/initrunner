# Installer

InitRunner ships a portable shell installer that works on Linux and macOS. A single `curl | sh` command detects your platform, finds (or installs) a package manager, installs the `initrunner` package from PyPI, and configures your `PATH`.

## Quick Start

```bash
# Install latest version
curl -fsSL https://initrunner.ai/install.sh | sh

# Install with extras (TUI, ingestion, Anthropic provider)
curl -fsSL https://initrunner.ai/install.sh | sh -s -- --extras tui,ingest

# Pin to a specific version
curl -fsSL https://initrunner.ai/install.sh | sh -s -- --version 0.2.0

# Force a specific installer
curl -fsSL https://initrunner.ai/install.sh | sh -s -- --method pipx

# CI mode (no PATH modifications)
curl -fsSL https://initrunner.ai/install.sh | sh -s -- --unmanaged

# Uninstall
curl -fsSL https://initrunner.ai/install.sh | sh -s -- --uninstall
```

## Requirements

- **curl** — used to fetch the installer and verify PyPI connectivity
- **Python >= 3.11** — detected automatically (`python3`, `python3.12`, `python3.11`, `python`)
- **Linux or macOS** — WSL is detected and supported; other platforms are rejected

## Options Reference

| Flag | Argument | Description |
|------|----------|-------------|
| `--method` | `uv`, `pipx`, or `pip` | Force a specific package installer instead of auto-detection. |
| `--extras` | comma-separated list | Install optional extras (e.g. `tui,ingest,anthropic`). |
| `--version` | version string | Pin to a specific PyPI version (e.g. `0.2.0`). Default: `latest`. |
| `--unmanaged` | *(none)* | Skip all shell profile / PATH modifications. Implies `INITRUNNER_NO_MODIFY_PATH`. |
| `--uninstall` | *(none)* | Remove initrunner and clean up PATH entries from shell profiles. |
| `-h`, `--help` | *(none)* | Show help and exit. |

## Environment Variables

All flags can be set via environment variables. Flags take precedence when both are provided.

| Variable | Equivalent Flag | Description |
|----------|----------------|-------------|
| `INITRUNNER_INSTALL_METHOD` | `--method` | Force installer (`uv`, `pipx`, or `pip`). Default: `auto`. |
| `INITRUNNER_EXTRAS` | `--extras` | Comma-separated extras to install. |
| `INITRUNNER_VERSION` | `--version` | Pin to a specific version. Default: `latest`. |
| `INITRUNNER_NO_MODIFY_PATH` | `--unmanaged` | Set to any non-empty value to skip shell profile edits. |

## How It Works

The installer runs through these stages in order:

### 1. Pre-flight Check

Verifies that `curl` is available and that PyPI is reachable (`https://pypi.org/simple/initrunner/`). Exits immediately if either check fails.

### 2. Platform Detection

Detects the OS (`linux` or `macos`), architecture (`uname -m`), and current shell (`$SHELL`). WSL is detected via `/proc/version`. Unsupported operating systems cause the installer to exit.

### 3. Python Detection

Searches for a suitable Python in this order: `python3`, `python3.12`, `python3.11`, `python`. The first binary with version >= 3.11 is selected. If none is found, the installer prints platform-specific install instructions (`brew`, `apt-get`, `dnf`, `pacman`, or `python.org`) and exits.

On Apple Silicon Macs, the installer warns if the detected Python is running under Rosetta (x86_64 binary on arm64 hardware).

### 4. Installer Selection

The auto-detection priority is:

1. **uv** — preferred if already installed
2. **pipx** — used if uv is not found
3. **pip** — used if neither uv nor pipx is found *and* the environment is not PEP 668-managed
4. **Auto-install uv** — if none of the above are viable, uv is installed automatically via `https://astral.sh/uv/install.sh`

When `--method` is passed, the specified installer is used directly. If it is not found on `PATH`, the installer exits with an error.

#### PEP 668 Handling

On systems with an `EXTERNALLY-MANAGED` marker (common on Debian 12+, Ubuntu 23.04+, Fedora 38+), `pip install` is blocked by PEP 668. The installer detects this by checking for the marker file in the Python stdlib path and falls through to auto-installing uv instead.

### 5. Package Installation

Builds a package spec from the name, extras, and version (e.g. `initrunner[tui,ingest]==0.2.0`) and installs it:

| Installer | Command |
|-----------|---------|
| uv | `uv tool install --force [--upgrade] --python ">=3.11" <spec>` |
| pipx | `pipx install --force <spec>` |
| pip | `pip3 install --user <spec>` |

### 6. PATH Configuration

If `initrunner` is not already on `PATH` and `--unmanaged` was not passed, the installer adds `~/.local/bin` to your shell profile using fenced markers:

```bash
# %% initrunner config start %%
export PATH="$HOME/.local/bin:$PATH"
# %% initrunner config end %%
```

For fish shell:

```fish
# %% initrunner config start %%
fish_add_path -g "$HOME/.local/bin"
# %% initrunner config end %%
```

The profile file is chosen based on the detected shell:

| Shell | Profile |
|-------|---------|
| zsh | `~/.zshrc` |
| bash (macOS) | `~/.bash_profile` (or `~/.bashrc` if no `.bash_profile` exists) |
| bash (Linux) | `~/.bashrc` |
| fish | `~/.config/fish/config.fish` |
| other | `~/.profile` |

**Idempotency**: if the fenced block already exists in the profile, no changes are made. If `initrunner` is already on `PATH`, profile editing is skipped entirely.

### 7. Verification

The installer checks that the `initrunner` command is available and prints the installed version. If the binary is not found on `PATH`, a warning is printed with instructions to add `~/.local/bin` manually.

## CI / Automation

For CI pipelines and automated environments:

```bash
# Skip all profile modifications
curl -fsSL https://initrunner.ai/install.sh | sh -s -- --unmanaged

# Or use environment variables
INITRUNNER_INSTALL_METHOD=uv INITRUNNER_NO_MODIFY_PATH=1 \
  curl -fsSL https://initrunner.ai/install.sh | sh
```

- **`--unmanaged`** skips shell profile edits and sets `NO_MODIFY_PATH` internally.
- **Non-TTY detection**: when stdout is not a terminal (or `NO_COLOR` is set), the installer disables colored output automatically.
- All options are available as environment variables for easy integration with CI configuration.

## Uninstall

```bash
curl -fsSL https://initrunner.ai/install.sh | sh -s -- --uninstall
```

The uninstaller:

1. **Removes the package** by trying each installer in order: `uv tool uninstall`, then `pipx uninstall`, then `pip uninstall`.
2. **Cleans up PATH entries** by removing the fenced `# %% initrunner config start %%` / `# %% initrunner config end %%` block from all known shell profiles (`~/.bashrc`, `~/.bash_profile`, `~/.zshrc`, `~/.profile`, `~/.config/fish/config.fish`).
3. **Preserves `~/.initrunner/`** — audit logs, memory stores, and ingested data are *not* deleted. A note is printed with instructions to remove the directory manually if desired:

```
rm -rf ~/.initrunner
```

## Troubleshooting

### PyPI unreachable

```
✗ Cannot reach PyPI. Check your internet connection or proxy settings.
```

The pre-flight check failed. Verify your network connection and ensure `https://pypi.org` is accessible. If you are behind a corporate proxy, configure `https_proxy` before running the installer.

### Python not found

```
✗ Python >= 3.11 is required but not found.
```

The installer could not find a Python >= 3.11 binary. Install one using the suggested command for your platform:

- **macOS**: `brew install python@3.12`
- **Debian/Ubuntu**: `sudo apt-get install python3`
- **Fedora**: `sudo dnf install python3`
- **Arch**: `sudo pacman -S python`

### PATH not updated after install

```
⚠ initrunner was installed but is not on PATH.
```

Restart your shell or run `source ~/.bashrc` (or the appropriate profile for your shell). Alternatively, run `export PATH="$HOME/.local/bin:$PATH"` in the current session.

### PEP 668 — externally managed environment

```
⚠ pip is blocked by PEP 668 (externally-managed environment).
```

Your system Python is marked as externally managed. The installer handles this automatically by falling back to uv. If you want to use pip explicitly, consider using a virtual environment instead.

### Apple Silicon Rosetta warning

```
⚠ Detected x86_64 Python on arm64 macOS (Rosetta).
⚠ Consider installing a native ARM Python for better performance.
```

Your Python binary is an x86_64 build running under Rosetta translation on Apple Silicon. Install a native ARM Python (e.g. via `brew install python@3.12`) for better performance.

## Testing

The installer has a Docker-based test harness in `tests/installer/`. Each scenario builds a fresh container with a local PyPI index so the installer never hits the real PyPI during tests.

### How it works

1. **Build wheel** — `uv build` creates a wheel in `tests/installer/dist/`.
2. **Local PyPI** — the Dockerfile generates a PEP 503 simple index from the wheel and serves it with `python3 -m http.server` inside the container.
3. **Run installer** — `install.sh` runs against the local index with `INITRUNNER_SKIP_PREFLIGHT=1` to skip the connectivity check.
4. **Post-check** — each scenario runs a verification command (default: `initrunner --version`).

### Scenarios

| Scenario | Base Image | What it tests |
|----------|-----------|---------------|
| `auto-ubuntu` | `ubuntu:24.04` | Auto-detection on a bare Ubuntu image (installs uv automatically) |
| `method-pip` | `python:3.12-slim` | Explicit `--method pip` |
| `method-pipx` | `python:3.12-slim` | Explicit `--method pipx` (pre-installs pipx) |
| `extras` | `python:3.12-slim` | `--extras tui` installs optional dependencies |
| `uninstall` | `python:3.12-slim` | Install then `--uninstall`, verifies binary is removed |
| `e2e-hello` | `ubuntu:24.04` | Full end-to-end: installs, then runs a role with `initrunner run` |

### Running tests

```bash
# Run all scenarios
bash tests/installer/test-installer.sh

# Run a single scenario
bash tests/installer/test-installer.sh auto-ubuntu
bash tests/installer/test-installer.sh e2e-hello
```

The `e2e-hello` scenario requires `OPENAI_API_KEY` to be set in the environment. It is automatically skipped when the variable is absent.

### Notes

- The `((count++)) || true` pattern in `test-installer.sh` prevents arithmetic expansion from returning exit code 1 when the value is 0, which would trip `set -e`.
- On failure, the harness re-runs the Docker build with output visible and prints the last 40 lines for debugging.
