---
name: document-comparison
description: >
  Compare two or more PDF documents by extracting targeted sections,
  building a structured comparison matrix, and highlighting differences
  with page references.
---

Document comparison skill.

## When to activate

Use this skill when the user asks you to:
- Compare two or more PDF documents
- Find differences between document versions
- Compare terms, clauses, or sections across documents
- Build a side-by-side comparison of document contents

## Methodology

### 1. Identify the documents

List available files and confirm which documents to compare. If the
user is vague ("compare the two contracts"), list the PDFs and ask
which ones they mean.

### 2. Extract metadata for both documents

Call `extract_pdf_metadata` on each document to get:
- Page count
- Title and author
- Creation and modification dates

This helps you understand the scope and identify if one is a revision
of the other (same title, different dates).

### 3. Determine comparison dimensions

Use the think tool to decide what to compare. Common dimensions:
- **Structure**: sections, headings, page count
- **Content**: specific clauses, terms, definitions
- **Numbers**: financial figures, dates, quantities
- **Coverage**: topics present in one but missing in the other

Ask the user what matters most if it is not clear from context.

### 4. Targeted extraction

Extract the relevant sections from each document. Use page ranges
to keep extractions focused:
- For structural comparison: extract the first 2-3 pages (table of
  contents, introduction) from each
- For clause comparison: extract the specific pages containing the
  target clauses
- For full comparison of short docs (< 20 pages): extract all

### 5. Build the comparison matrix

Use the think tool to construct a comparison. Structure it as:

```
| Dimension      | Document A (page) | Document B (page) | Difference |
|----------------|--------------------|--------------------|------------|
| Term length    | 12 months (p.3)    | 24 months (p.4)    | B is 2x    |
| Payment terms  | Net 30 (p.5)       | Net 60 (p.5)       | B is longer |
```

For numerical differences, use the calculator to compute deltas and
percentages.

### 6. Present findings

Structure the comparison report as:
1. **Overview**: what was compared, document metadata
2. **Key differences**: the most significant changes, ordered by impact
3. **Detailed comparison**: the full matrix with page references
4. **Summary**: a plain-language summary of the differences

## MUST

- Always extract metadata before content
- Always include page references for every cited fact
- Use the think tool to plan the comparison dimensions
- Use the calculator for any numerical comparisons (deltas, percentages)
- Present differences in a structured table format

## MUST NOT

- Compare documents without reading both -- never assume content
- Fabricate page numbers or content not in the extracted text
- Extract entire large documents when targeted extraction will do
- Present opinions about which document is "better" unless asked
- Skip the metadata step -- it reveals version relationships
