# Editor support

InitRunner publishes a JSON Schema for agent files. Point your editor at it and
you get completion for every key, hover text, and a red underline on a
misspelled setting while you type, instead of at `initrunner run`.

The schema lives at:

```
https://raw.githubusercontent.com/vladkesler/initrunner/main/schemas/agent.v3.json
```

It describes the flat agent format (`spec_version: 3`): solo agents, teams,
flows and groups. Legacy `apiVersion`/`kind` envelope files are not covered;
convert them with `initrunner doctor --fix`.

## Files the builder creates

`initrunner new` and the dashboard's new-agent page write this line at the top
of every file they create:

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/vladkesler/initrunner/main/schemas/agent.v3.json
name: my-agent
prompt: You are a helpful assistant.
```

That comment is the whole setup for any editor that runs the YAML language
server. The bundled examples and starters carry it too, so a copy from
`initrunner examples copy` works the same way. For older files, paste the same
line at the top.

## VS Code

Install the YAML extension (`redhat.vscode-yaml`). It reads the comment line
above, so nothing else is needed.

To cover files without the comment, map a glob to the schema in
`settings.json`:

```json
{
  "yaml.schemas": {
    "https://raw.githubusercontent.com/vladkesler/initrunner/main/schemas/agent.v3.json": [
      "agents/**/*.yaml",
      "agent.yaml"
    ]
  }
}
```

## Neovim

`yamlls` (yaml-language-server through `nvim-lspconfig`) reads the comment line
too. For a glob mapping, set `settings.yaml.schemas` in the server config, with
the same shape as the VS Code setting above.

## JetBrains IDEs

Open **Settings | Languages & Frameworks | Schemas and DTDs | JSON Schema
Mappings**, add a mapping, paste the schema URL (or pick a local file, see
below), and add your agent files or folders to it.

## Matching your installed version

The URL above follows the `main` branch, which can be ahead of the release you
have installed. A setting added on `main` would show as valid in the editor and
then fail `initrunner validate`. To check against exactly what you run, export
the schema from your install and point the comment at the file:

```bash
initrunner schema > agent.schema.json
```

```yaml
# yaml-language-server: $schema=./agent.schema.json
```

The path is relative to the agent file. Re-export after upgrading. The command
needs no API keys, network access or extras.

## What the editor can't check

The schema covers structure: which keys exist, their types, allowed values, and
the shorthand forms (`model: openai:gpt-5-mini`, `tools: [think]`,
`- shell: {...}`, an agent child written as a plain prompt string). Rules that
depend on more than one field are checked by `initrunner validate` and the run
pre-flight, not the editor. For example: a `then:` edge naming an agent that
exists, `prompt_cache` only on Anthropic or Bedrock, `run:` only when `agents:`
is set.

Tool names that are not built in are treated as plugin tools, and their options
are not checked, because the plugin defines them.
