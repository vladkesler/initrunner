# AcmeDB FAQ

## Is AcmeDB thread-safe?

Yes. AcmeDB uses file-level locking so multiple threads in the same process
can read and write safely. However, only one process should open a database
file at a time.

## What is the maximum database size?

AcmeDB supports databases up to 16 GB. For larger datasets, consider
sharding across multiple database files.

## Can I use AcmeDB with async/await?

AcmeDB operations are synchronous. For async applications, wrap calls with
`asyncio.to_thread()`:

```python
doc = await asyncio.to_thread(db.get, doc_id)
```

## How do I back up a database?

Close the database first, then copy the `.adb` file. Alternatively, use the
built-in export:

```python
db.export_json("backup.json")
```

## Does AcmeDB support full-text search?

Yes. Enable it per field when creating an index:

```python
db.create_index("description", full_text=True)
results = db.search("description", "fast embedded database")
```

## What happens if my application crashes mid-write?

AcmeDB uses write-ahead logging (WAL) to ensure durability. On the next
open, incomplete transactions are rolled back automatically.
