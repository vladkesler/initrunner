#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../dashboard"

if [ ! -f "package.json" ]; then
  echo "Error: dashboard/package.json not found. Nothing to build." >&2
  exit 1
fi

echo "Installing dashboard dependencies..."
pnpm install --frozen-lockfile

echo "Building dashboard frontend..."
pnpm build

echo "Dashboard built to ../initrunner/dashboard/_static/"
