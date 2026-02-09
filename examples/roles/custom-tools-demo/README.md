# Custom Tools Demo

Demonstrates InitRunner's `custom` tool type, which auto-discovers public
functions from a Python module and registers them as agent tools.

## Setup

Run from this directory so Python can find `my_tools.py`:

```bash
cd examples/roles/custom-tools-demo
initrunner run custom-tools-demo.yaml -i
```

## Example prompts

- "Convert 100 kg to pounds"
- "Generate a UUID for me"
- "Pretty-print this JSON: {\"name\":\"Alice\",\"age\":30}"
- "Count the words in: The quick brown fox jumps over the lazy dog"
- "Hash the string 'hello world' with sha256"
- "Look up 'test query'"

## Writing your own custom tools

1. Create a Python module (e.g. `my_tools.py`) with public functions.
2. Add type annotations and docstrings — these become the tool schema.
3. Reference the module in your role YAML:

```yaml
tools:
  - type: custom
    module: my_tools
    config:
      key: value
```

4. To receive config from the YAML, add a `tool_config: dict` parameter to
   your function. This parameter is hidden from the LLM.
