#!/bin/sh
# initrunner installer
# Usage: curl -fsSL https://initrunner.ai/install.sh | sh
#        curl -fsSL https://initrunner.ai/install.sh | sh -s -- --extras tui,ingest
#        curl -fsSL https://initrunner.ai/install.sh | sh -s -- --version 0.2.0
#        curl -fsSL https://initrunner.ai/install.sh | sh -s -- --unmanaged
#        curl -fsSL https://initrunner.ai/install.sh | sh -s -- --method pipx
#        curl -fsSL https://initrunner.ai/install.sh | sh -s -- --uninstall
set -eu

INSTALLER_VERSION="1.0.0"
PACKAGE_NAME="initrunner"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=11
FENCE_START="# %% initrunner config start %%"
FENCE_END="# %% initrunner config end %%"

# ── Formatting helpers ────────────────────────────────────────────────

setup_colors() {
    if [ -t 1 ] && [ "${NO_COLOR:-}" = "" ]; then
        BOLD='\033[1m'
        DIM='\033[2m'
        RED='\033[0;31m'
        GREEN='\033[0;32m'
        YELLOW='\033[0;33m'
        BLUE='\033[0;34m'
        CYAN='\033[0;36m'
        RESET='\033[0m'
    else
        BOLD=''
        DIM=''
        RED=''
        GREEN=''
        YELLOW=''
        BLUE=''
        CYAN=''
        RESET=''
    fi
}

info() {
    printf "  %b%s%b\n" "$CYAN" "$1" "$RESET"
}

success() {
    printf "  %b✓%b %s\n" "$GREEN" "$RESET" "$1"
}

warn() {
    printf "  %b⚠%b %s\n" "$YELLOW" "$RESET" "$1" >&2
}

err() {
    printf "  %b✗%b %s\n" "$RED" "$RESET" "$1" >&2
}

header() {
    printf "\n  %b%s%b installer\n\n" "$BOLD" "$PACKAGE_NAME" "$RESET"
}

# ── Argument parsing ─────────────────────────────────────────────────

INSTALL_METHOD="${INITRUNNER_INSTALL_METHOD:-auto}"
EXTRAS="${INITRUNNER_EXTRAS:-}"
VERSION="${INITRUNNER_VERSION:-latest}"
NO_MODIFY_PATH="${INITRUNNER_NO_MODIFY_PATH:-}"
UNMANAGED=false
UNINSTALL=false

parse_args() {
    while [ $# -gt 0 ]; do
        case "$1" in
            --method)
                shift
                INSTALL_METHOD="$1"
                ;;
            --extras)
                shift
                EXTRAS="$1"
                ;;
            --version)
                shift
                VERSION="$1"
                ;;
            --unmanaged)
                UNMANAGED=true
                NO_MODIFY_PATH=1
                ;;
            --uninstall)
                UNINSTALL=true
                ;;
            --help|-h)
                show_help
                exit 0
                ;;
            *)
                err "Unknown option: $1"
                show_help
                exit 1
                ;;
        esac
        shift
    done
}

show_help() {
    cat <<EOF

  ${PACKAGE_NAME} installer v${INSTALLER_VERSION}

  Usage:
    curl -fsSL https://initrunner.ai/install.sh | sh
    curl -fsSL https://initrunner.ai/install.sh | sh -s -- [OPTIONS]

  Options:
    --method <uv|pipx|pip>  Force a specific installer
    --extras <list>         Comma-separated extras (tui,ingest,anthropic)
    --version <ver>         Pin to a specific version
    --unmanaged             Skip PATH/profile modifications (CI mode)
    --uninstall             Remove initrunner
    -h, --help              Show this help

  Environment variables:
    INITRUNNER_INSTALL_METHOD   Force installer (uv/pipx/pip)
    INITRUNNER_EXTRAS           Comma-separated extras
    INITRUNNER_VERSION          Pin version
    INITRUNNER_NO_MODIFY_PATH   Skip shell profile edits

EOF
}

# ── Platform detection ───────────────────────────────────────────────

DETECTED_OS=""
DETECTED_ARCH=""
DETECTED_SHELL_NAME=""
IS_WSL=false

detect_platform() {
    case "$(uname -s)" in
        Linux*)
            DETECTED_OS="linux"
            if [ -f /proc/version ] && grep -qi microsoft /proc/version 2>/dev/null; then
                IS_WSL=true
            fi
            ;;
        Darwin*)
            DETECTED_OS="macos"
            ;;
        *)
            err "Unsupported OS: $(uname -s)"
            exit 1
            ;;
    esac

    DETECTED_ARCH="$(uname -m)"

    # Detect current shell
    DETECTED_SHELL_NAME="$(basename "${SHELL:-sh}")"
}

# ── Python detection ─────────────────────────────────────────────────

PYTHON_CMD=""

check_python() {
    for cmd in python3 python3.13 python3.12 python3.11 python; do
        if command -v "$cmd" >/dev/null 2>&1; then
            if "$cmd" -c "import sys; sys.exit(0 if sys.version_info >= ($MIN_PYTHON_MAJOR, $MIN_PYTHON_MINOR) else 1)" 2>/dev/null; then
                PYTHON_CMD="$cmd"

                # Apple Silicon: warn if Python arch doesn't match system arch
                if [ "$DETECTED_OS" = "macos" ] && [ "$DETECTED_ARCH" = "arm64" ]; then
                    py_arch="$("$cmd" -c "import platform; print(platform.machine())" 2>/dev/null || true)"
                    if [ "$py_arch" = "x86_64" ]; then
                        warn "Detected x86_64 Python on arm64 macOS (Rosetta)."
                        warn "Consider installing a native ARM Python for better performance."
                    fi
                fi

                return 0
            fi
        fi
    done

    err "Python >= ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR} is required but not found."
    printf "\n"
    case "$DETECTED_OS" in
        macos)
            info "Install with: brew install python@3.12"
            ;;
        linux)
            if command -v apt-get >/dev/null 2>&1; then
                info "Install with: sudo apt-get install python3"
            elif command -v dnf >/dev/null 2>&1; then
                info "Install with: sudo dnf install python3"
            elif command -v pacman >/dev/null 2>&1; then
                info "Install with: sudo pacman -S python"
            else
                info "Install Python ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}+ from https://python.org"
            fi
            ;;
    esac
    exit 1
}

# ── Installer selection ──────────────────────────────────────────────

SELECTED_INSTALLER=""

has_cmd() {
    command -v "$1" >/dev/null 2>&1
}

check_pep668() {
    # Check if pip is blocked by PEP 668 EXTERNALLY-MANAGED marker
    "$PYTHON_CMD" -c "
import sysconfig, os
stdlib = sysconfig.get_path('stdlib')
marker = os.path.join(stdlib, 'EXTERNALLY-MANAGED')
exit(0 if os.path.exists(marker) else 1)
" 2>/dev/null
}

select_installer() {
    if [ "$INSTALL_METHOD" != "auto" ]; then
        case "$INSTALL_METHOD" in
            uv)
                if ! has_cmd uv; then
                    err "--method uv specified but uv is not installed."
                    exit 1
                fi
                SELECTED_INSTALLER="uv"
                ;;
            pipx)
                if ! has_cmd pipx; then
                    err "--method pipx specified but pipx is not installed."
                    exit 1
                fi
                SELECTED_INSTALLER="pipx"
                ;;
            pip)
                SELECTED_INSTALLER="pip"
                ;;
            *)
                err "Unknown install method: $INSTALL_METHOD (expected: uv, pipx, pip)"
                exit 1
                ;;
        esac
        return 0
    fi

    # Auto-detect: uv > pipx > pip (with PEP 668 guard) > auto-install uv
    if has_cmd uv; then
        SELECTED_INSTALLER="uv"
        return 0
    fi

    if has_cmd pipx; then
        SELECTED_INSTALLER="pipx"
        return 0
    fi

    if has_cmd pip3 || has_cmd pip; then
        if ! check_pep668; then
            SELECTED_INSTALLER="pip"
            return 0
        fi
        warn "pip is blocked by PEP 668 (externally-managed environment)."
    fi

    # Fallback: auto-install uv
    info "No suitable installer found. Installing uv..."
    install_uv_bootstrap
    SELECTED_INSTALLER="uv"
}

install_uv_bootstrap() {
    if ! has_cmd curl; then
        err "curl is required to install uv. Please install curl and try again."
        exit 1
    fi

    curl -LsSf https://astral.sh/uv/install.sh | sh

    # Source uv's env so it's available in this session
    if [ -f "$HOME/.local/bin/env" ]; then
        . "$HOME/.local/bin/env"
    elif [ -f "$HOME/.cargo/env" ]; then
        . "$HOME/.cargo/env"
    fi
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

    if ! has_cmd uv; then
        err "uv installation succeeded but uv is not on PATH."
        exit 1
    fi

    success "uv installed"
}

# ── Package spec construction ────────────────────────────────────────

build_pkg_spec() {
    _spec="$PACKAGE_NAME"

    if [ -n "$EXTRAS" ]; then
        _spec="${_spec}[${EXTRAS}]"
    fi

    if [ "$VERSION" != "latest" ]; then
        _spec="${_spec}==${VERSION}"
    fi

    printf '%s' "$_spec"
}

# ── Installation ─────────────────────────────────────────────────────

do_install() {
    _pkg="$(build_pkg_spec)"
    info "Installing ${_pkg}..."
    printf "\n"

    case "$SELECTED_INSTALLER" in
        uv)     install_with_uv "$_pkg" ;;
        pipx)   install_with_pipx "$_pkg" ;;
        pip)    install_with_pip "$_pkg" ;;
    esac
}

install_with_uv() {
    if [ "$VERSION" != "latest" ]; then
        uv tool install --force --python ">=${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}" "$1"
    else
        uv tool install --force --upgrade --python ">=${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}" "$1"
    fi
}

install_with_pipx() {
    pipx install --force "$1"
}

install_with_pip() {
    _pip_cmd=""
    if has_cmd pip3; then
        _pip_cmd="pip3"
    elif has_cmd pip; then
        _pip_cmd="pip"
    else
        err "pip is not installed."
        exit 1
    fi
    "$_pip_cmd" install --user "$1"
}

# ── Pre-flight check ────────────────────────────────────────────────

preflight_check() {
    if [ "${INITRUNNER_SKIP_PREFLIGHT:-}" = "1" ]; then
        return 0
    fi

    if ! has_cmd curl; then
        err "curl is required. Please install curl and try again."
        exit 1
    fi

    if ! curl -fsS --max-time 5 -o /dev/null https://pypi.org/simple/initrunner/; then
        err "Cannot reach PyPI. Check your internet connection or proxy settings."
        exit 1
    fi
}

# ── PATH configuration ──────────────────────────────────────────────

configure_path() {
    if [ "$UNMANAGED" = true ] || [ -n "$NO_MODIFY_PATH" ]; then
        return 0
    fi

    # Check if initrunner is already on PATH
    if command -v initrunner >/dev/null 2>&1; then
        return 0
    fi

    # Ensure ~/.local/bin is in PATH for the current session
    case ":$PATH:" in
        *":$HOME/.local/bin:"*)
            # Already in PATH, nothing to do
            return 0
            ;;
    esac

    _profile=""
    case "$DETECTED_SHELL_NAME" in
        zsh)
            _profile="$HOME/.zshrc"
            ;;
        bash)
            if [ "$DETECTED_OS" = "macos" ]; then
                if [ -f "$HOME/.bash_profile" ]; then
                    _profile="$HOME/.bash_profile"
                else
                    _profile="$HOME/.bashrc"
                fi
            else
                _profile="$HOME/.bashrc"
            fi
            ;;
        fish)
            # fish uses a different syntax, handle separately
            _profile="$HOME/.config/fish/config.fish"
            ;;
        *)
            _profile="$HOME/.profile"
            ;;
    esac

    if [ -z "$_profile" ]; then
        warn "Could not detect shell profile. Add ~/.local/bin to your PATH manually."
        return 0
    fi

    # Check if fenced block already exists (idempotency)
    if [ -f "$_profile" ] && grep -qF "$FENCE_START" "$_profile" 2>/dev/null; then
        return 0
    fi

    # Create profile file if it doesn't exist
    if [ ! -f "$_profile" ]; then
        mkdir -p "$(dirname "$_profile")"
        touch "$_profile"
    fi

    printf '\n%s\n' "$FENCE_START" >> "$_profile"
    if [ "$DETECTED_SHELL_NAME" = "fish" ]; then
        printf 'fish_add_path -g "%s/.local/bin"\n' "$HOME" >> "$_profile"
    else
        printf 'export PATH="$HOME/.local/bin:$PATH"\n' >> "$_profile"
    fi
    printf '%s\n' "$FENCE_END" >> "$_profile"

    # Update current session
    export PATH="$HOME/.local/bin:$PATH"

    success "Added ~/.local/bin to PATH in $_profile"
}

# ── Verify installation ─────────────────────────────────────────────

verify_install() {
    # Ensure ~/.local/bin is on PATH for this session
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

    if command -v initrunner >/dev/null 2>&1; then
        _version="$(initrunner --version 2>/dev/null || echo "unknown")"
        printf "\n"
        success "initrunner ${_version} installed successfully"
        return 0
    fi

    printf "\n"
    warn "initrunner was installed but is not on PATH."
    warn "Add ~/.local/bin to your PATH or restart your shell."
    return 0
}

# ── Summary ──────────────────────────────────────────────────────────

print_summary() {
    printf "\n"
    printf "  %bGet started:%b\n" "$BOLD" "$RESET"
    printf "    initrunner setup\n"
    printf "    initrunner init --name my-agent\n"
    printf "    initrunner run role.yaml -p \"Hello!\"\n"
    printf "    initrunner --help\n"
    printf "\n"
}

# ── Uninstall ────────────────────────────────────────────────────────

do_uninstall() {
    header
    info "Uninstalling ${PACKAGE_NAME}..."
    printf "\n"

    _uninstalled=false

    # Try uv first
    if has_cmd uv; then
        if uv tool list 2>/dev/null | grep -q "^${PACKAGE_NAME} "; then
            uv tool uninstall "$PACKAGE_NAME"
            _uninstalled=true
        fi
    fi

    # Try pipx
    if [ "$_uninstalled" = false ] && has_cmd pipx; then
        if pipx list 2>/dev/null | grep -q "package ${PACKAGE_NAME} "; then
            pipx uninstall "$PACKAGE_NAME"
            _uninstalled=true
        fi
    fi

    # Try pip
    if [ "$_uninstalled" = false ]; then
        _pip_cmd=""
        if has_cmd pip3; then _pip_cmd="pip3";
        elif has_cmd pip; then _pip_cmd="pip";
        fi
        if [ -n "$_pip_cmd" ]; then
            if "$_pip_cmd" show "$PACKAGE_NAME" >/dev/null 2>&1; then
                "$_pip_cmd" uninstall -y "$PACKAGE_NAME"
                _uninstalled=true
            fi
        fi
    fi

    if [ "$_uninstalled" = false ]; then
        warn "Could not find an initrunner installation to remove."
    else
        success "initrunner removed"
    fi

    # Remove fenced PATH block from shell profiles
    _removed_profile=false
    for _prof in "$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.zshrc" "$HOME/.profile" "$HOME/.config/fish/config.fish"; do
        if [ -f "$_prof" ] && grep -qF "$FENCE_START" "$_prof" 2>/dev/null; then
            # Remove the fenced block (POSIX-safe: use sed)
            _tmp="$(mktemp)"
            _inside=false
            while IFS= read -r _line || [ -n "$_line" ]; do
                case "$_line" in
                    *"$FENCE_START"*)
                        _inside=true
                        continue
                        ;;
                    *"$FENCE_END"*)
                        _inside=false
                        continue
                        ;;
                esac
                if [ "$_inside" = false ]; then
                    printf '%s\n' "$_line"
                fi
            done < "$_prof" > "$_tmp"
            mv "$_tmp" "$_prof"
            _removed_profile=true
            success "Removed PATH config from $_prof"
        fi
    done

    printf "\n"
    if [ -d "$HOME/.initrunner" ]; then
        info "Note: ~/.initrunner/ (audit logs, stores, memory) was preserved."
        info "Remove it manually if you no longer need it: rm -rf ~/.initrunner"
    fi
    printf "\n"
}

# ── Main ─────────────────────────────────────────────────────────────

main() {
    setup_colors
    parse_args "$@"

    if [ "$UNINSTALL" = true ]; then
        do_uninstall
        exit 0
    fi

    header

    detect_platform

    printf "  %bPlatform:%b  %s %s" "$DIM" "$RESET" "$DETECTED_OS" "$DETECTED_ARCH"
    if [ "$IS_WSL" = true ]; then
        printf " (WSL)"
    fi
    printf "\n"

    preflight_check
    check_python

    printf "  %bPython:%b    %s (%s)\n" "$DIM" "$RESET" "$("$PYTHON_CMD" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")" "$PYTHON_CMD"

    select_installer

    printf "  %bInstaller:%b %s\n" "$DIM" "$RESET" "$SELECTED_INSTALLER"
    printf "\n"

    do_install
    configure_path
    verify_install
    print_summary
}

main "$@"
