# Credential Vault

A local encrypted vault for your API keys and bot tokens. Drop-in: everything that currently reads `OPENAI_API_KEY`, `DISCORD_BOT_TOKEN`, `${SLACK_WEBHOOK_URL}` placeholders, or `api_key_env:` in a role keeps working — the vault just fills in when the env var isn't set.

> **If you lose the passphrase, your secrets are gone.** The vault is encrypted with a key derived from your passphrase. There is no recovery mechanism, no backdoor, no support reset. Back up `~/.initrunner/vault.enc` to wherever you keep your dotfiles, or run `initrunner vault export --json > backup.json` and keep that somewhere safe.

## Install

```bash
uv pip install 'initrunner[vault]'
# optional: cache the passphrase in the OS keyring
uv pip install 'initrunner[vault-keyring]'
```

The vault is opt-in. InitRunner without the `vault` extra keeps reading from `os.environ` and `~/.initrunner/.env` exactly as before.

## Quickstart

```bash
initrunner vault init
initrunner vault set OPENAI_API_KEY      # prompts for the value, never echoed
unset OPENAI_API_KEY                     # prove it works from the vault only
initrunner run my-agent.yaml
```

## How resolution works

Every place that asks for a credential goes through a `ChainedResolver`:

1. `os.environ[NAME]` — env vars always win. CI, `docker run -e`, shell exports: unchanged.
2. The vault at `~/.initrunner/vault.enc`, unlocked via `INITRUNNER_VAULT_PASSPHRASE` or a keyring-cached passphrase.
3. If neither has the key, it's missing.

This covers model `api_key_env`, trigger `token_env` (Discord, Telegram), `${VAR}` placeholders in tool configs, embedding keys, and the dashboard's provider status page. Nothing in your `role.yaml` needs to change.

## Migrating from `~/.initrunner/.env`

One command:

```bash
initrunner vault import          # reads ~/.initrunner/.env, offers to delete it
```

Or point at any dotenv or JSON file:

```bash
initrunner vault import ./secrets.json
initrunner vault import ./prod.env
```

## CI / headless usage

Provide the passphrase via env var and pass `--no-prompt` for belt-and-braces (it's also the default when stdin isn't a TTY, so CI scripts can't hang on a hidden prompt).

```yaml
# .github/workflows/agent.yml
env:
  INITRUNNER_VAULT_PASSPHRASE: ${{ secrets.VAULT_PASSPHRASE }}
steps:
  - run: initrunner vault import ./secrets.json --no-prompt
  - run: initrunner run agent.yaml
```

The runtime (`run`, `daemon`, `dashboard`, triggers, ingestion) **never** prompts for a passphrase, even on a TTY. If the vault is locked and no passphrase source is available, the caller either falls through to env (resolver) or raises `CredentialNotFound` with an actionable message (`require_credential`). Hidden prompts from a background daemon would be a production hazard, so the policy is strict.

## Keyring cache (optional)

When the `vault-keyring` extra is installed and an OS keyring backend is available, you can avoid re-typing the passphrase:

```bash
initrunner vault cache           # stores passphrase in Keychain/Secret Service/Credential Manager
initrunner vault lock            # clears it
```

Caveats:

- Headless Linux usually has no Secret Service backend; `vault cache` will print a clear error. Use `INITRUNNER_VAULT_PASSPHRASE` instead.
- The cache is per-`INITRUNNER_HOME` (keyed on a hash), so multiple installations on the same machine don't collide.
- `vault rotate` updates the cached passphrase automatically if one was stored. If the keyring write fails after rotation, the cache is cleared and the command tells you to re-run `vault cache`.

## Backup and restore

Two portable paths:

1. `initrunner vault export --json --out backup.json` — re-import on another machine with the passphrase.
2. Copy `~/.initrunner/vault.enc` — works as-is on any machine with the same passphrase and cryptography library version.

## Subprocess safety

`INITRUNNER_VAULT_PASSPHRASE` and any `*_PASSPHRASE` env var are added to the sensitive-env suffix list used by `scrub_env()`. Every tool subprocess (shell, git, python, MCP stdio) runs with those stripped. The unlock passphrase never leaks to child processes.

## Command reference

| Command | What it does |
|---|---|
| `vault init` | Create the vault. Prompts twice; prints the recovery warning. |
| `vault set NAME [VALUE]` | Store a credential. Value is prompted (not echoed) when omitted. |
| `vault get NAME` | Print a value to stdout. |
| `vault list` | Print stored names (never values). |
| `vault rm NAME` | Remove an entry. |
| `vault export --env \| --json [--out PATH]` | Dump decrypted contents. |
| `vault import [FILE]` | Import dotenv or JSON; defaults to `~/.initrunner/.env` with a delete prompt. |
| `vault rotate` | Re-encrypt under a new passphrase; updates the keyring cache if present. |
| `vault verify` | Check that the passphrase decrypts the vault. Does not cache. |
| `vault cache` | Store the passphrase in the OS keyring. |
| `vault lock` | Clear the cached passphrase. |
| `vault status` | Path, entry count, last-modified, keyring state. |

Every command accepts `--no-prompt` and exits with code 2 (rather than prompting) when no passphrase is available non-interactively.
