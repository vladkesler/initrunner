"""Shared sync service functions for role discovery, validation, and operations.

These are the core operations used by the CLI, API, and TUI.
Each function is sync and can be called directly or wrapped in asyncio.to_thread().

This package is organized by domain:
- discovery: role scanning, validation, default directories
- execution: agent building and running
- memory: session and memory CRUD
- roles: role generation and YAML persistence
- api_models: API response builders and report export
- operations: audit, ingestion, triggers, MCP introspection
"""
