---
name: structured-extraction
description: >
  Extract structured data from web pages using browser snapshot and
  text tools, then process it into tables, comparisons, or summaries
  using Python.
requires:
  bins: [agent-browser]
---

Structured web data extraction skill.

## When to activate

Use this skill when you need to:
- Extract specific data points from a web page (prices, features, specs)
- Build a comparison table from multiple pages or sites
- Scrape a list of items from a page (search results, product listings)
- Extract tabular data from a web page into a structured format

## Methodology

### 1. Plan the extraction

Use the think tool to identify:
- What data points to extract (columns in your target table)
- Which pages contain the data (URLs or navigation paths)
- Whether the data is on one page or spread across multiple pages
- Whether pagination or interaction is needed to reveal the data

### 2. Navigate to the data

Open the target URL and confirm you landed on the right page:

```
open_url("https://example.com/pricing")
```

Check the title and URL in the response to verify.

### 3. Snapshot the page

Take a snapshot to understand the page structure:

```
snapshot()
```

Look for:
- Data containers (tables, cards, lists)
- Interactive elements that reveal more data (tabs, accordions,
  "Show more" buttons)
- Pagination controls

If the page has distinct sections, use a CSS selector to scope
the snapshot: `snapshot(selector=".pricing-table")`

### 4. Extract text content

Use `get_text` to pull text from specific elements or the full page:

```
get_text(ref="@e5")   # specific element
get_text()            # full page text
```

For tabular data, extracting the full page text often captures
tables in a readable format.

### 5. Take evidence screenshots

Screenshot key pages for the research report:

```
screenshot(full_page=false)           # viewport
screenshot(full_page=true)            # full page
screenshot(annotate=true)             # with element labels
```

Include screenshot paths in your report so the user can review
the raw source.

### 6. Process with Python

Use Python to structure the extracted text into clean data:

```python
data = [
    {"name": "Plan A", "price": "$10/mo", "features": "5 users, 10GB"},
    {"name": "Plan B", "price": "$25/mo", "features": "25 users, 100GB"},
]
# Format as markdown table
header = "| Plan | Price | Features |"
sep = "|------|-------|----------|"
rows = [f"| {d['name']} | {d['price']} | {d['features']} |" for d in data]
print(header)
print(sep)
print("\n".join(rows))
```

### 7. Handle pagination

For multi-page results:

1. Extract data from the current page
2. `snapshot()` to find the next page control
3. `click(@next_ref, wait_until="networkidle")`
4. Repeat extraction

Set a reasonable limit (e.g. 5 pages) unless the user asks for more.
Always report how many pages you processed.

### 8. Handle dynamic content

Some data loads dynamically. Strategies:
- `wait_for(text="Price")` -- wait for specific text to appear
- `wait_for(ref="@e1", state="visible")` -- wait for an element
- `click` on tabs or "Load more" buttons to reveal hidden content
- `wait_for(load="networkidle")` after interactions

## MUST

- Always snapshot before interacting with elements
- Always take at least one screenshot per site as evidence
- Always include source URLs in extracted data
- Use Python to structure data into clean tables
- Report how many pages/sites were processed

## MUST NOT

- Click on elements without first taking a snapshot to get references
- Assume page structure without observing it via snapshot
- Enter credentials, payment info, or personal data into forms
- Click purchase or payment buttons
- Extract more than 10 pages of paginated results without user approval
- Process data without presenting the raw source URLs
