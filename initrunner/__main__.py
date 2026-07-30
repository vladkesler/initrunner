"""Allow ``python -m initrunner …`` for service daemon children and scripting."""

from initrunner.cli.main import app_entry

if __name__ == "__main__":
    app_entry()
