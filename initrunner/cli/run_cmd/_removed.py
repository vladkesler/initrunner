"""Removed ``run`` flags: a one-line pointer instead of "No such option".

Every flag here was removed because the setting belongs in the role YAML, an
environment variable, or another flag. Click would report an unknown option and
leave the user guessing which; this names the replacement instead.

Delete this module, its wiring in ``initrunner/cli/main.py``, and the tests that
cover it one release after the removal.
"""

from __future__ import annotations

import sys

import click
import typer
from typer.core import TyperCommand

# flag -> the predicate completing "<flag> was removed from 'initrunner run'; ..."
REMOVED_RUN_FLAGS: dict[str, str] = {
    "--max-iterations": "use guardrails.max_iterations in the role",
    "--token-budget": "use guardrails.run_token_budget in the role",
    "--budget-timezone": "use guardrails.budget_timezone in the role",
    "--allowed-users": "use allowed_users on the telegram trigger in the role",
    "--allowed-user-ids": "use allowed_user_ids on the telegram or discord trigger in the role",
    "--cors-origin": "use security.server.cors_origins in the role",
    "--api-key": "use the INITRUNNER_API_KEY environment variable",
    "--autopilot": (
        "use 'autonomous: true' on each trigger plus 'autonomy: {}' in the role, then --daemon"
    ),
    "--provider": "use --model provider:model, or 'provider:' in ~/.initrunner/run.yaml",
    "--tool-profile": "use --tools none|minimal|all",
    "--list-tools": "see --tools in 'initrunner run --help'",
    "--explain-profiles": "see --tools in 'initrunner run --help'",
    "--role-dir": (
        "--sense already searches the current directory, ./examples/roles,"
        " ~/.initrunner/roles and the bundled starters"
    ),
    "--confirm-role": "--sense already confirms whenever there is a terminal",
    "--report-template": "use --report TEMPLATE:PATH, for example --report pr-review:out.md",
    "--save": "use 'initrunner examples copy <starter>'",
    "--no-stream": "use --format rich",
    "--dev": "use --format rich",
    "--audit-db": "use the INITRUNNER_AUDIT_DB environment variable",
    "--skill-dir": "use the INITRUNNER_SKILL_DIR environment variable",
    "--bot": (
        "add a telegram or discord trigger to the role and use --daemon"
        " (try: initrunner run telegram --daemon)"
    ),
}


class RunCommand(TyperCommand):
    """``run`` with a pointer for flags that used to exist.

    Typer handles ``ClickException`` inside its own ``_main``, so this has to
    intercept at parse time rather than around the app.
    """

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        try:
            return super().parse_args(ctx, args)
        except Exception as e:
            # Not `except click.NoSuchOption`. Typer 0.27 vendors its own copy of
            # Click, so the error it raises is typer._click.exceptions.NoSuchOption,
            # which is not an instance of click.NoSuchOption. Catching the class
            # meant the pointer worked against the pinned dev environment and
            # nowhere else: a fresh `pip install initrunner` resolves the newer
            # pair and every user saw Click's "No such option" instead. The
            # attribute is the part both versions agree on.
            option_name = getattr(e, "option_name", None)
            hint = REMOVED_RUN_FLAGS.get(option_name) if isinstance(option_name, str) else None
            if hint is None:
                raise
            typer.echo(
                f"Error: {option_name} was removed from 'initrunner run'; {hint}.",
                err=True,
            )
            # sys.exit, not click.exceptions.Exit, for the same reason: the Exit
            # class Typer's runtime recognises is whichever Click it vendored,
            # and raising the wrong one surfaces as a traceback. SystemExit is
            # the one exception both versions let through untouched.
            sys.exit(2)
