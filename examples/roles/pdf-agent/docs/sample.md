# Sample Document

This is a sample markdown file for the pdf-agent example. In a real setup, you would place your PDF and Markdown files in this directory.

## Getting Started

To use this agent with your own documents:

1. Place your `.pdf` and `.md` files in this `docs/` directory.
2. Run `initrunner ingest pdf-agent.yaml` to index the documents.
3. Run `initrunner run pdf-agent.yaml -i` to start an interactive session.

## Notes

- PDF support requires the `initrunner[ingest]` extra (`pip install initrunner[ingest]`).
- The larger `chunk_size` (1024) works well for dense technical PDFs where answers often span multiple sentences.
- Re-run `initrunner ingest` after adding or updating documents.
