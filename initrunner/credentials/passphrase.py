"""Passphrase acquisition with a strict non-interactive policy.

Runtime code (``run`` / ``daemon`` / ``dashboard`` / ``triggers`` / ``ingestion``)
must never block on stdin. Only vault CLI commands are allowed to prompt,
and only when stdin is a TTY. This module is the single choke point for
that policy.

Order of sources:
    1. ``INITRUNNER_VAULT_PASSPHRASE`` env var.
    2. Keyring cache (when the ``vault-keyring`` extra is installed).
    3. Interactive prompt — only when explicitly enabled AND stdin is a TTY.
"""

from __future__ import annotations

import getpass
import os
import sys

from . import keyring_cache

PASSPHRASE_ENV = "INITRUNNER_VAULT_PASSPHRASE"


def from_env() -> str | None:
    value = os.environ.get(PASSPHRASE_ENV)
    return value if value else None


def from_keyring() -> str | None:
    return keyring_cache.load_passphrase()


def acquire(
    *, interactive: bool, confirm: bool = False, prompt: str = "Vault passphrase: "
) -> str | None:
    """Return a passphrase from the configured sources.

    ``interactive=True`` opts into prompting; the prompt is still skipped
    when stdin is not a TTY so CI hangs are impossible even if a caller
    forgets ``--no-prompt``. Returns ``None`` when no passphrase is
    available and no prompt was allowed.
    """
    env = from_env()
    if env is not None:
        return env
    cached = from_keyring()
    if cached is not None:
        return cached
    if interactive and sys.stdin.isatty():
        return prompt_interactive(prompt=prompt, confirm=confirm)
    return None


def prompt_interactive(*, prompt: str = "Vault passphrase: ", confirm: bool = False) -> str:
    """Prompt the user for a passphrase. Callers must guard with an ``isatty()`` check.

    When ``confirm`` is true the user types the passphrase twice; mismatches
    raise ``ValueError`` rather than silently accepting the second entry.
    """
    first = getpass.getpass(prompt)
    if confirm:
        second = getpass.getpass("Confirm passphrase: ")
        if first != second:
            raise ValueError("passphrases did not match")
    return first
