# PDF Analyst

Analyze, compare, and summarize PDF documents using direct text extraction. No ingestion pipeline needed. Point it at a directory of PDFs, ask questions, and get answers with page references. Compare documents side-by-side, extract key terms, find specific clauses, and build structured summaries.

## Quick start

```bash
# Install
initrunner install vladkesler/pdf-analyst

# Install PDF parsing dependency
pip install initrunner[ingest]

# Interactive session
initrunner run pdf-analyst -i

# One-shot analysis
initrunner run pdf-analyst -p "Summarize the key terms in contract.pdf"
```

Requires `pip install initrunner[ingest]` for pymupdf4llm (PDF parsing). Requires `OPENAI_API_KEY` (or configure another provider).

## Example prompts

```
What PDFs are available?
Summarize the key terms in contract.pdf
What is the payment schedule in the agreement?
Compare contract-v1.pdf and contract-v2.pdf
What changed between the two versions?
Extract all dates and deadlines from proposal.pdf
How many pages is the report? What are the main sections?
Find every mention of "liability" in the contract
What are the financial figures on pages 15-20?
```

## Example session

```
$ initrunner run pdf-analyst -i

You: Compare contract-v1.pdf and contract-v2.pdf

> list_directory(".")
contract-v1.pdf, contract-v2.pdf, notes.md

> extract_pdf_metadata("contract-v1.pdf")
Title: Service Agreement v1
Pages: 24, Author: Legal Team, Created: 2026-01-15

> extract_pdf_metadata("contract-v2.pdf")
Title: Service Agreement v2
Pages: 26, Author: Legal Team, Created: 2026-03-01

> think: Both are service agreements, v2 is 2 pages longer and 6 weeks
> newer. Extract key sections from both for comparison.

> extract_pdf_text("contract-v1.pdf", pages="1-5")
> extract_pdf_text("contract-v2.pdf", pages="1-5")

> think: Building comparison matrix on payment terms, liability,
> termination, and SLA sections...

## Comparison: Service Agreement v1 vs v2

| Dimension        | v1 (page)           | v2 (page)            | Change           |
|------------------|---------------------|----------------------|------------------|
| Term length      | 12 months (p.3)     | 24 months (p.3)      | Doubled          |
| Payment terms    | Net 30 (p.5)        | Net 45 (p.5)         | Extended 15 days |
| Liability cap    | $500,000 (p.12)     | $1,000,000 (p.13)    | Doubled          |
| SLA uptime       | 99.5% (p.18)        | 99.9% (p.19)         | Stricter         |
| Termination      | 30 days notice (p.8)| 60 days notice (p.9) | Extended         |
| New section      | --                  | Data processing (p.22)| Added in v2      |

**Key changes**: v2 extends the term to 24 months, doubles the liability
cap, adds a data processing addendum (pages 22-26), and tightens the
SLA from 99.5% to 99.9%.
```

## Customization

### Document directory

By default, the agent reads PDFs from the current directory. Change `root_path` to point elsewhere:

```yaml
tools:
  - type: pdf_extract
    root_path: "./documents"
    max_pages: 200
    max_file_size_mb: 50
  - type: filesystem
    root_path: "./documents"
    read_only: true
    allowed_extensions: [.pdf, .md, .txt]
```

### Large documents

For documents over 200 pages, increase the limit:

```yaml
tools:
  - type: pdf_extract
    max_pages: 500
    max_content_bytes: 1048576  # 1MB
```

### Memory sizing

```yaml
memory:
  semantic:
    max_memories: 500    # document profiles, key findings
  episodic:
    max_episodes: 200    # analysis session records
```

### Token budget

```yaml
guardrails:
  max_tokens_per_run: 60000   # increase for very large documents
  max_tool_calls: 40
```

## Changing the model

Edit `spec.model` in `role.yaml`:

```yaml
spec:
  model:
    provider: anthropic
    name: claude-sonnet-4-5-20250929
    temperature: 0.1
```
