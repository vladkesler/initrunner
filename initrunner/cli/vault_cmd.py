"""``initrunner vault`` -- manage the local encrypted credential vault."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(help="Manage the local encrypted credential vault.", no_args_is_help=True)

_NO_PROMPT_HELP = (
    "Never prompt for a passphrase. Use INITRUNNER_VAULT_PASSPHRASE or the keyring cache."
)


def _is_interactive(no_prompt: bool) -> bool:
    """Interactive iff a TTY is attached AND the user hasn't opted out."""
    return (not no_prompt) and sys.stdin.isatty() and sys.stdout.isatty()


def _vault():
    from initrunner.config import get_vault_path
    from initrunner.credentials.local_vault import LocalEncryptedVault

    return LocalEncryptedVault(get_vault_path())


def _require_existing_vault() -> None:
    if not _vault().exists():
        typer.echo(
            "No vault. Run `initrunner vault init` to create one.",
            err=True,
        )
        raise typer.Exit(code=2)


def _acquire_passphrase_or_exit(*, interactive: bool, confirm: bool = False) -> str:
    from initrunner.credentials import passphrase as _pp

    pw = _pp.acquire(interactive=interactive, confirm=confirm)
    if pw is None:
        typer.echo(
            "vault locked and no passphrase available "
            "(set INITRUNNER_VAULT_PASSPHRASE or run `vault cache`)",
            err=True,
        )
        raise typer.Exit(code=2)
    return pw


def _unlock_or_exit(vault, *, interactive: bool) -> None:
    from initrunner.credentials.store import WrongPassphrase

    pw = _acquire_passphrase_or_exit(interactive=interactive)
    try:
        vault.unlock(pw)
    except WrongPassphrase:
        typer.echo("invalid passphrase", err=True)
        raise typer.Exit(code=1) from None


@app.command()
def init(
    no_prompt: Annotated[bool, typer.Option("--no-prompt", help=_NO_PROMPT_HELP)] = False,
) -> None:
    """Create a new vault at ``~/.initrunner/vault.enc``."""
    from initrunner.credentials import passphrase as _pp

    vault = _vault()
    if vault.exists():
        typer.echo(f"vault already exists at {vault.path}", err=True)
        raise typer.Exit(code=1)

    interactive = _is_interactive(no_prompt)

    typer.echo(
        "IMPORTANT: if you lose the passphrase, your secrets are gone. "
        "There is no recovery mechanism. Back up the vault file "
        "(or `vault export --json`) once it has entries.\n"
    )

    pw_env = _pp.from_env()
    if pw_env is not None:
        passphrase_value = pw_env
    elif interactive:
        passphrase_value = _pp.prompt_interactive(prompt="New passphrase: ", confirm=True)
    else:
        typer.echo(
            "no passphrase available (set INITRUNNER_VAULT_PASSPHRASE or run in a TTY)",
            err=True,
        )
        raise typer.Exit(code=2)

    vault.init(passphrase_value)
    typer.echo(f"vault created at {vault.path}")

    from initrunner.config import get_global_env_path

    if get_global_env_path().exists():
        typer.echo(
            "note: you have entries in ~/.initrunner/.env. "
            "Run `initrunner vault import` to move them into the vault."
        )


@app.command()
def set(
    name: Annotated[str, typer.Argument(help="Credential name, e.g. OPENAI_API_KEY")],
    value: Annotated[str | None, typer.Argument()] = None,
    no_prompt: Annotated[bool, typer.Option("--no-prompt", help=_NO_PROMPT_HELP)] = False,
) -> None:
    """Set a credential. Prompts for the value when omitted (not echoed)."""
    _require_existing_vault()
    vault = _vault()
    interactive = _is_interactive(no_prompt)
    _unlock_or_exit(vault, interactive=interactive)

    if value is None:
        if not interactive:
            typer.echo("value required when stdin is not a TTY", err=True)
            raise typer.Exit(code=2)
        import getpass

        value = getpass.getpass(f"Value for {name}: ")
        if not value:
            typer.echo("empty value -- aborted", err=True)
            raise typer.Exit(code=1)

    vault.set(name, value)
    typer.echo(f"stored {name}")


@app.command()
def get(
    name: Annotated[str, typer.Argument()],
    no_prompt: Annotated[bool, typer.Option("--no-prompt", help=_NO_PROMPT_HELP)] = False,
) -> None:
    """Print a credential value to stdout."""
    _require_existing_vault()
    vault = _vault()
    _unlock_or_exit(vault, interactive=_is_interactive(no_prompt))
    value = vault.get(name)
    if value is None:
        typer.echo(f"{name} not in vault", err=True)
        raise typer.Exit(code=1)
    typer.echo(value)


@app.command(name="list")
def list_cmd() -> None:
    """List credential names (values are never printed)."""
    _require_existing_vault()
    for name in _vault().list_keys():
        typer.echo(name)


@app.command()
def rm(
    name: Annotated[str, typer.Argument()],
    no_prompt: Annotated[bool, typer.Option("--no-prompt", help=_NO_PROMPT_HELP)] = False,
) -> None:
    """Remove a credential from the vault."""
    _require_existing_vault()
    vault = _vault()
    _unlock_or_exit(vault, interactive=_is_interactive(no_prompt))
    if name not in vault.list_keys():
        typer.echo(f"{name} not in vault", err=True)
        raise typer.Exit(code=1)
    vault.rm(name)
    typer.echo(f"removed {name}")


@app.command()
def export(
    fmt_env: Annotated[
        bool, typer.Option("--env", help="Write dotenv-style KEY=VAL lines.")
    ] = False,
    fmt_json: Annotated[bool, typer.Option("--json", help="Write a JSON object.")] = False,
    out: Annotated[
        Path | None, typer.Option("--out", help="Write to path instead of stdout.")
    ] = None,
    no_prompt: Annotated[bool, typer.Option("--no-prompt", help=_NO_PROMPT_HELP)] = False,
) -> None:
    """Export the vault contents. Pass either ``--env`` or ``--json``."""
    if fmt_env == fmt_json:
        typer.echo("choose exactly one of --env or --json", err=True)
        raise typer.Exit(code=2)
    _require_existing_vault()
    vault = _vault()
    _unlock_or_exit(vault, interactive=_is_interactive(no_prompt))
    data = vault.export_dict()

    if fmt_json:
        payload = json.dumps(data, indent=2)
    else:
        lines = []
        for k, v in data.items():
            escaped = v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
            lines.append(f'{k}="{escaped}"')
        payload = "\n".join(lines)

    if out is not None:
        out.write_text(payload + ("\n" if not payload.endswith("\n") else ""), encoding="utf-8")
        out.chmod(0o600)
        typer.echo(f"wrote {out}")
    else:
        typer.echo(payload)


@app.command(name="import")
def import_cmd(
    file: Annotated[
        Path | None,
        typer.Argument(help="Source file; defaults to ~/.initrunner/.env"),
    ] = None,
    no_prompt: Annotated[bool, typer.Option("--no-prompt", help=_NO_PROMPT_HELP)] = False,
) -> None:
    """Import credentials from a dotenv or JSON file.

    When ``FILE`` is omitted the command reads ``~/.initrunner/.env`` and
    offers to delete the source after a successful import.
    """
    from initrunner.config import get_global_env_path

    _require_existing_vault()
    vault = _vault()
    _unlock_or_exit(vault, interactive=_is_interactive(no_prompt))

    defaulted = file is None
    source = file if file is not None else get_global_env_path()
    if not source.exists():
        typer.echo(f"source file not found: {source}", err=True)
        raise typer.Exit(code=1)

    items = _parse_import(source)
    count = vault.import_items(items.items())
    typer.echo(f"imported {count} entries from {source}")

    if defaulted and sys.stdin.isatty() and not no_prompt:
        if typer.confirm(f"delete {source}?", default=False):
            source.unlink()
            typer.echo(f"deleted {source}")


def _parse_import(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    stripped = text.lstrip()
    if stripped.startswith("{"):
        data = json.loads(text)
        if not isinstance(data, dict):
            raise typer.BadParameter("JSON import must be an object of name->value")
        return {str(k): str(v) for k, v in data.items()}

    from dotenv import dotenv_values

    values = dotenv_values(path)
    return {k: v for k, v in values.items() if v is not None}


@app.command()
def rotate(
    no_prompt: Annotated[bool, typer.Option("--no-prompt", help=_NO_PROMPT_HELP)] = False,
) -> None:
    """Re-encrypt the vault under a new passphrase.

    If the old passphrase was cached in the keyring, the cache is updated
    to the new one (otherwise the cache would silently fail on next unlock).
    """
    from initrunner.credentials import keyring_cache
    from initrunner.credentials import passphrase as _pp

    _require_existing_vault()
    vault = _vault()
    interactive = _is_interactive(no_prompt)

    _unlock_or_exit(vault, interactive=interactive)

    had_cache = keyring_cache.load_passphrase() is not None

    if interactive:
        new_pw = _pp.prompt_interactive(prompt="New passphrase: ", confirm=True)
    else:
        typer.echo(
            "rotation requires a TTY for the new passphrase (no non-interactive form)",
            err=True,
        )
        raise typer.Exit(code=2)

    vault.rotate(new_pw)
    typer.echo("vault rotated")

    if had_cache:
        if keyring_cache.store_passphrase(new_pw):
            typer.echo("keyring cache updated")
        else:
            keyring_cache.clear_passphrase()
            typer.echo(
                "keyring cache cleared (could not store new passphrase); "
                "run `vault cache` to re-cache"
            )


@app.command()
def verify(
    no_prompt: Annotated[bool, typer.Option("--no-prompt", help=_NO_PROMPT_HELP)] = False,
) -> None:
    """Check that a passphrase decrypts the vault. Does not cache."""
    _require_existing_vault()
    vault = _vault()
    _unlock_or_exit(vault, interactive=_is_interactive(no_prompt))
    typer.echo("ok")


@app.command()
def cache(
    no_prompt: Annotated[bool, typer.Option("--no-prompt", help=_NO_PROMPT_HELP)] = False,
) -> None:
    """Store the passphrase in the OS keyring for future commands."""
    from initrunner.credentials import keyring_cache
    from initrunner.credentials import passphrase as _pp

    _require_existing_vault()
    if not keyring_cache.is_available():
        typer.echo(
            "no keyring backend available. "
            "Install extras: uv pip install initrunner[vault-keyring]",
            err=True,
        )
        raise typer.Exit(code=2)

    interactive = _is_interactive(no_prompt)
    pw_env = _pp.from_env()
    if pw_env is not None:
        pw = pw_env
    elif interactive:
        pw = _pp.prompt_interactive()
    else:
        typer.echo("no passphrase available", err=True)
        raise typer.Exit(code=2)

    from initrunner.credentials.store import WrongPassphrase

    vault = _vault()
    try:
        vault.unlock(pw)
    except WrongPassphrase:
        typer.echo("invalid passphrase", err=True)
        raise typer.Exit(code=1) from None

    if keyring_cache.store_passphrase(pw):
        typer.echo("passphrase cached in keyring")
    else:
        typer.echo("could not write to keyring", err=True)
        raise typer.Exit(code=1)


@app.command()
def lock() -> None:
    """Clear any keyring-cached passphrase."""
    from initrunner.credentials import keyring_cache

    if keyring_cache.clear_passphrase():
        typer.echo("keyring cache cleared")
    else:
        typer.echo("no cached passphrase to clear")


@app.command()
def status() -> None:
    """Show vault location, entry count, last-modified, and cache state."""
    from initrunner.credentials import keyring_cache

    vault = _vault()
    if not vault.exists():
        typer.echo(f"vault: (none) -- expected at {vault.path}")
        typer.echo("status: uninitialized")
        return

    last = vault.last_modified()
    entries = len(vault.list_keys())
    cached = keyring_cache.load_passphrase() is not None

    typer.echo(f"vault:        {vault.path}")
    typer.echo("backend:      local-encrypted (Fernet + scrypt)")
    typer.echo(f"entries:      {entries}")
    typer.echo(f"last-modified:{' ' + last.isoformat() if last else ' (unknown)'}")
    typer.echo(f"keyring:      {'cached' if cached else 'not cached'}")
