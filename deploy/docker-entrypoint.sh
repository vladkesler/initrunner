#!/bin/sh
set -e

ROLES_DIR="${INITRUNNER_HOME:-/data}/roles"
EXAMPLES_DIR="/opt/initrunner/example-roles"

if [ -d "$EXAMPLES_DIR" ] && { [ ! -d "$ROLES_DIR" ] || [ -z "$(ls -A "$ROLES_DIR" 2>/dev/null)" ]; }; then
    mkdir -p "$ROLES_DIR"
    cp "$EXAMPLES_DIR"/*.yaml "$ROLES_DIR/"
    echo "Copied example roles to $ROLES_DIR"
fi

exec "$@"
