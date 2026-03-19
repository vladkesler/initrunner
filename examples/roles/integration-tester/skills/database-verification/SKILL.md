---
name: database-verification
description: >
  Shell-based database connectivity and integrity checks. Verifies that
  databases are reachable, schemas match expectations, and data integrity
  constraints hold.
requires:
  bins: []
---

Database verification skill using standard database CLI tools.

## When to activate

Use this skill when tests fail with connection errors or timeouts to a
database, when database-related tests exist in the test suite, when
docker-compose or similar configs define database services, or when a
migration has recently been applied and needs verification.

## Connectivity checks

Test reachability before running any data queries. Each database has its
own tool:

### PostgreSQL

```
pg_isready -h host -p 5432
```

Returns exit code 0 if accepting connections. For authenticated check:

```
psql -h host -p 5432 -U user -d dbname -c "SELECT 1"
```

### Redis

```
redis-cli -h host -p 6379 ping
```

Expected response: `PONG`.

### SQLite

```
sqlite3 /path/to/file.db ".tables"
```

Returns the list of tables. A missing file or corrupt database produces
an error.

### MySQL / MariaDB

```
mysql -h host -u user -p -e "SELECT 1"
```

Or check just connectivity:

```
mysqladmin -h host -u user ping
```

### MongoDB

```
mongosh --host host --port 27017 --eval "db.runCommand({ ping: 1 })"
```

## Schema verification

After connectivity is confirmed:

1. **Tables exist** -- query the information schema or equivalent to list
   tables; compare against expected table names.
2. **Columns match** -- for each critical table, list columns and types;
   verify expected columns are present with correct types.
3. **Indexes present** -- check that performance-critical indexes exist
   (primary keys, foreign key indexes, unique constraints).
4. **Constraints** -- verify NOT NULL, UNIQUE, and foreign key constraints
   are in place on the relevant columns.

## Data integrity

- **Row counts** -- check that tables have expected minimum rows (not
  empty when they should be populated).
- **Foreign key consistency** -- verify that foreign key references point
  to existing rows (no orphaned records).
- **Null checks** -- scan NOT NULL columns for unexpected nulls (can
  happen if constraints were added after data).
- **Duplicate detection** -- check unique columns for duplicates when
  constraints might be missing.

## Migration status

1. Check for a migration tracking table (alembic_version, schema_migrations,
   django_migrations, knex_migrations, etc.).
2. Read the latest applied migration version or timestamp.
3. Compare against the latest migration file in the source tree.
4. Report whether migrations are up to date, behind, or in a dirty state.

## Docker database health

When databases run in containers:

```
docker-compose ps          # check service status
docker exec <container> pg_isready -U postgres
docker logs --tail 20 <container>    # recent errors
docker inspect --format='{{.State.Health.Status}}' <container>
```

Verify the health check status is "healthy" before proceeding with
further checks.

## MUST

- Check connectivity before running any data queries -- fail fast with a
  clear "cannot connect" message rather than cryptic SQL errors
- Handle missing database tools gracefully -- if pg_isready is not installed,
  report "pg_isready not found; install postgresql-client to enable
  PostgreSQL connectivity checks" rather than failing silently
- Test read-only when possible -- prefer SELECT queries over writes
- Report the specific database host, port, and database name being tested
- Check all configured databases, not just the first one

## MUST NOT

- Write to or delete data in production databases -- verification is
  read-only
- Expose connection strings, passwords, or credentials in output -- mask
  sensitive portions
- Assume a specific database tool is installed -- check for the binary
  first and report clearly if it is missing
- Run expensive full-table scans on large production databases -- use
  LIMIT or COUNT queries instead
- Store database credentials in test artifacts or logs
