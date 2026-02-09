"""Shared subprocess helpers for tool builders."""

from __future__ import annotations

import os
import subprocess


class SubprocessTimeout(Exception):
    """Raised when a subprocess exceeds its timeout."""

    def __init__(self, timeout: int) -> None:
        self.timeout = timeout
        super().__init__(f"Execution timed out after {timeout}s")


DEFAULT_SENSITIVE_ENV_PREFIXES = (
    # AI providers
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "HF_TOKEN",
    "HUGGING_FACE",
    "COHERE_API_KEY",
    "REPLICATE_API_TOKEN",
    # Cloud
    "AWS_SECRET",
    "AWS_SESSION_TOKEN",
    "GCP_",
    "GCLOUD_",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_CLOUD_",
    "AZURE_",
    "DIGITALOCEAN_TOKEN",
    # VCS/CI
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "GITLAB_TOKEN",
    "BITBUCKET_TOKEN",
    "CODECOV_TOKEN",
    # Messaging
    "SLACK_TOKEN",
    "SLACK_WEBHOOK",
    "SLACK_BOT_TOKEN",
    "SLACK_SIGNING_SECRET",
    "TWILIO_",
    "SENDGRID_API_KEY",
    "MAILGUN_API_KEY",
    # Payment
    "STRIPE_",
    # DB/infra
    "DATABASE_URL",
    "REDIS_URL",
    "MONGO_URI",
    "POSTGRES_PASSWORD",
    "MYSQL_PASSWORD",
    # Auth/crypto
    "SSH_AUTH_SOCK",
    "SSH_PRIVATE_KEY",
    # Other
    "NPM_TOKEN",
    "DOCKER_PASSWORD",
    "DOCKER_TOKEN",
    "VAULT_TOKEN",
    "SENTRY_DSN",
)

DEFAULT_SENSITIVE_ENV_SUFFIXES = (
    "_KEY",
    "_SECRET",
    "_TOKEN",
    "_PASSWORD",
    "_CREDENTIAL",
    "_CREDENTIALS",
    "_API_KEY",
    "_ACCESS_KEY",
    "_PRIVATE_KEY",
)

DEFAULT_ENV_ALLOWLIST: frozenset[str] = frozenset(
    {
        "SSH_AGENT_PID",
        "GPG_AGENT_INFO",
    }
)


def scrub_env(
    prefixes: tuple[str, ...] | list[str] = DEFAULT_SENSITIVE_ENV_PREFIXES,
    *,
    suffixes: tuple[str, ...] | list[str] = DEFAULT_SENSITIVE_ENV_SUFFIXES,
    allowlist: frozenset[str] | set[str] = DEFAULT_ENV_ALLOWLIST,
) -> dict[str, str]:
    """Return a copy of os.environ with sensitive keys removed.

    Parameters:
        prefixes: Key prefixes to strip. Defaults to ``DEFAULT_SENSITIVE_ENV_PREFIXES``.
        suffixes: Key suffixes to strip. Defaults to ``DEFAULT_SENSITIVE_ENV_SUFFIXES``.
        allowlist: Keys to keep even if they match a suffix. Defaults to
            ``DEFAULT_ENV_ALLOWLIST``.
    """
    env = dict(os.environ)
    upper_prefixes = tuple(p.upper() for p in prefixes)
    upper_suffixes = tuple(s.upper() for s in suffixes)
    to_remove = [
        k
        for k in env
        if k not in allowlist
        and (
            any(k.upper().startswith(p) for p in upper_prefixes)
            or any(k.upper().endswith(s) for s in upper_suffixes)
        )
    ]
    for k in to_remove:
        del env[k]
    return env


def run_subprocess(
    cmd: list[str],
    *,
    timeout: int,
    cwd: str | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Run a subprocess with scrubbed env and timeout."""
    return subprocess.run(
        cmd,
        capture_output=True,
        timeout=timeout,
        cwd=cwd,
        env=scrub_env(),
    )


def format_subprocess_output(
    stdout: str,
    stderr: str,
    returncode: int | None = None,
    max_bytes: int = 0,
    truncation_suffix: str = "\n[truncated]",
) -> str:
    """Assemble stdout/stderr/returncode into a single output string.

    Optionally truncates to *max_bytes* using the given suffix.
    """
    from initrunner.agent._truncate import truncate_output

    parts: list[str] = []
    if returncode is not None and returncode != 0:
        parts.append(f"Exit code: {returncode}")
    if stdout:
        parts.append(f"STDOUT:\n{stdout}")
    if stderr:
        parts.append(f"STDERR:\n{stderr}")
    output = "\n".join(parts) if parts else "(no output)"
    if max_bytes > 0:
        output = truncate_output(output, max_bytes, truncation_suffix)
    return output


def run_subprocess_text(
    cmd: list[str],
    *,
    timeout: int,
    cwd: str | None = None,
) -> tuple[str, str, int]:
    """Run a subprocess and return ``(stdout, stderr, returncode)`` as decoded text.

    Raises:
        SubprocessTimeout: If the subprocess exceeds *timeout* seconds.
    """
    try:
        result = run_subprocess(cmd, timeout=timeout, cwd=cwd)
    except subprocess.TimeoutExpired:
        raise SubprocessTimeout(timeout) from None
    return (
        result.stdout.decode("utf-8", errors="replace"),
        result.stderr.decode("utf-8", errors="replace"),
        result.returncode,
    )
