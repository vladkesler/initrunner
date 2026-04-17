# HMAC-Signed Audit Chain

Every record written to `~/.initrunner/audit.db` is chained via HMAC-SHA256.
Each row stores `prev_hash` and `record_hash`, where:

```
record_hash = HMAC-SHA256(key, prev_hash || canonical_json(record))
```

The `canonical_json` is a deterministic serialisation of the record's signed
fields (see `_RECORD_FIELDS` in `initrunner/audit/logger.py`). Chain linkage
means any mutation, reordering, or middle-row deletion invalidates every
record from that point forward — as long as the HMAC key stays secret.

## What it proves

Running `initrunner audit verify-chain` succeeds (exit 0) only when:

- No field in any signed row has been modified since it was written.
- No row has been deleted from the middle of the chain, *unless* a pruning
  operation caused the id gap. (Pruning is reported separately as
  `pruned_gaps`, never as a break.)
- No row has been reordered.

## What it does not prove

Honest about the limits:

- **Removal of the tail is not detected.** An attacker who deletes the last
  N rows leaves a valid chain prefix, and `verify-chain` will still say
  `ok`. Mitigating this requires an external anchor — periodically pushing
  the latest `record_hash` to a separate system that the attacker cannot
  touch. Not provided today.
- **If the HMAC key leaks, nothing is proven.** An attacker with read
  access to `~/.initrunner/audit_hmac.key` (or the `INITRUNNER_AUDIT_HMAC_KEY`
  env var) can forge records.
- **Database rollback to an earlier consistent snapshot is indistinguishable
  from current valid state.** Same category as tail truncation.
- **Pre-existing rows from before this feature landed stay unsigned.** They
  show up as `unsigned_legacy_rows` in the verify output. The chain begins
  at the first insert after the migration ran.

## Key management

The key is 32 random bytes, auto-generated on the first `log()` call that
has to sign. Resolution order:

1. `INITRUNNER_AUDIT_HMAC_KEY` env var (hex-encoded, 64 chars). Overrides
   the file. Used for CI or for verifying a DB on a different host than
   where it was written.
2. `~/.initrunner/audit_hmac.key` (0600, 32 bytes). Auto-created once;
   persists for the life of the install.

Verification only ever *reads* the key. It will not auto-create one — this
matters when you copy an audit DB to a fresh machine. If there's no key and
no env var set, `verify-chain` exits 1 with `key_missing` and tells you
how to provide the key.

### Rotation

Not automated in this release. If you need to rotate, plan for a
"start-a-new-chain" cutover rather than re-signing history:

```bash
# 1. Verify the current chain is clean
initrunner audit verify-chain

# 2. Archive the DB
cp ~/.initrunner/audit.db ~/.initrunner/audit.db.$(date +%Y%m%d)

# 3. Rotate the key
mv ~/.initrunner/audit_hmac.key ~/.initrunner/audit_hmac.key.old
# New key will be generated on next log()
```

The archived DB remains verifiable with the old key; new writes sign under
the new key. Automated multi-key rotation (per-row key ids, re-sign under
new key) is future work.

## Pruning

`AuditLogger.prune()` deletes rows by retention window and trims to
`max_records`. Both modes preserve the chain's tail (rows are kept by
insertion id, not timestamp), but retention pruning can leave holes when
timestamps are out of insertion order (clock skew, replay, import). Those
holes are surfaced as `pruned_gaps` — informational, not a failure.

If an attacker deleted a middle row, that also shows up as a `pruned_gap`.
The chain itself cannot distinguish legitimate pruning from deletion. If
you need stronger "this row existed at time T" guarantees, combine the
audit chain with off-box anchoring.

## Running in CI

`audit verify-chain` exits 0 on success and 1 on any break or key
problem. Minimal GitHub Actions snippet:

```yaml
- name: Verify audit chain
  env:
    INITRUNNER_AUDIT_HMAC_KEY: ${{ secrets.INITRUNNER_AUDIT_HMAC_KEY }}
  run: uv run initrunner audit verify-chain --audit-db artifacts/audit.db
```

The `--audit-db` flag is useful when verifying a DB that was produced
elsewhere and shipped into the CI job as an artifact.

## Implementation notes

- Signing runs inside `BEGIN IMMEDIATE` so concurrent writers — same
  process, different threads, or separate processes — serialise through
  SQLite's RESERVED lock. Without this, two writers could read the same
  chain tip and fork the chain.
- The signing path is a dedicated helper (`_log_signed_locked`) rather
  than the generic `_execute_insert_locked`. Security events, budget
  state, and delegate events share the generic helper but are not signed.
- Verification streams rows via `fetchmany(500)` and never raises; all
  failures are returned in the `ChainVerifyResult`.
