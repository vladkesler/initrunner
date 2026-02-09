# Getting Started with AcmeDB

AcmeDB is a lightweight, embedded document database designed for applications
that need fast local storage without the overhead of a separate server process.

## Installation

Install AcmeDB using pip:

```bash
pip install acmedb
```

AcmeDB requires Python 3.10 or later and has no external dependencies.

## Creating a Database

Open or create a database by specifying a file path:

```python
import acmedb

db = acmedb.open("myapp.adb")
```

If the file does not exist, AcmeDB creates it automatically. Data is persisted
to disk after every write operation.

## Basic Usage

Store documents as Python dictionaries:

```python
# Insert a document
doc_id = db.insert({"name": "Alice", "role": "engineer", "level": 3})

# Retrieve by ID
doc = db.get(doc_id)

# Query with filters
engineers = db.find({"role": "engineer"})

# Update a document
db.update(doc_id, {"level": 4})

# Delete a document
db.delete(doc_id)
```

## Indexes

Create indexes to speed up queries on frequently searched fields:

```python
db.create_index("role")
db.create_index("name", unique=True)
```

Indexes are persisted alongside the data and rebuilt automatically on startup.

## Configuration

Pass options when opening the database:

```python
db = acmedb.open("myapp.adb", cache_size=1000, auto_compact=True)
```

- `cache_size` — number of documents to keep in memory (default: 500)
- `auto_compact` — reclaim disk space on close (default: False)
- `read_only` — open in read-only mode (default: False)
