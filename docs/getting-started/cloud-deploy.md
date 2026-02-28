# Cloud Deployment

Deploy the InitRunner dashboard to a cloud platform in minutes. All options build from the Dockerfile, seed example roles on first boot, and expose the web dashboard on port 8420.

## Prerequisites

1. **LLM API key** - at least one of `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `GOOGLE_API_KEY`
2. **Dashboard password** (recommended) - set `INITRUNNER_DASHBOARD_API_KEY` to protect your public URL

## Deploy to Railway

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/template/FROM_REPO?referralCode=...)

1. Click the button above (or create a new project from this repo)
2. Set environment variables in the Railway dashboard:
   - `OPENAI_API_KEY` (or your preferred provider key)
   - `INITRUNNER_DASHBOARD_API_KEY` - password for the dashboard
3. Railway builds from `railway.json` and starts the dashboard automatically
4. **Volume**: Create a persistent volume mounted at `/data` in the Railway UI to keep roles, memory, and audit data across deploys

The health check at `/api/health` confirms the service is running.

## Deploy to Render

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/vladkesler/initrunner)

1. Click the button above
2. Render reads `render.yaml` and creates the service with a 1 GB persistent disk at `/data`
3. Set your API keys in the environment variable prompts during setup
4. The service starts automatically once the build completes

Render's Blueprint handles disk provisioning - no manual volume setup needed.

## Deploy to Fly.io

Fly.io requires the CLI. Install it from [fly.io/docs/flyctl](https://fly.io/docs/flyctl/install/).

```bash
# Clone the repo
git clone https://github.com/vladkesler/initrunner.git
cd initrunner

# Launch (uses deploy/fly.toml)
fly launch --config deploy/fly.toml --copy-config --no-deploy

# Create persistent storage
fly volumes create initrunner_data --region iad --size 1

# Set secrets
fly secrets set OPENAI_API_KEY=sk-...
fly secrets set INITRUNNER_DASHBOARD_API_KEY=your-password

# Deploy
fly deploy --config deploy/fly.toml
```

The dashboard will be available at `https://initrunner.fly.dev` (or your chosen app name).

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes* | OpenAI API key (default provider) |
| `ANTHROPIC_API_KEY` | No | Anthropic API key (for Claude models) |
| `GOOGLE_API_KEY` | No | Google AI API key (for Gemini models) |
| `INITRUNNER_DASHBOARD_API_KEY` | Recommended | Password protecting the web dashboard |
| `INITRUNNER_HOME` | No | Data directory (default: `/data`) |

*At least one LLM provider key is required. Which one depends on the models used in your roles.

## Post-Deploy

### Accessing the Dashboard

Open the URL provided by your platform. If you set `INITRUNNER_DASHBOARD_API_KEY`, you'll be prompted for the password on first visit.

The dashboard comes pre-loaded with 5 example roles:
- **hello-world** - minimal agent for testing
- **web-searcher** - web search and summarization
- **memory-assistant** - persistent memory across sessions
- **code-reviewer** - code review with git tools
- **full-tools-assistant** - all zero-config tools enabled

### Adding Custom Roles

Upload new roles through the dashboard's role editor, or mount a volume with your role files. On platforms with persistent storage, roles saved to `/data/roles/` persist across deploys.

### Storage

All platforms mount `/data` as persistent storage. This directory holds:
- `/data/roles/` - agent role YAML files
- `/data/memory/` - persistent agent memory
- `/data/audit/` - audit trail database
- `/data/vectors/` - vector store for RAG

## Extended Tools

The seeded `full-tools-assistant` role includes all tools that work without extra configuration. To add tools that require credentials or config, edit the role and add:

```yaml
# HTTP client (requires base_url)
- type: http
  base_url: https://api.example.com

# SQL database (requires connection string)
- type: sql
  database: postgresql://user:pass@host/db

# Email (requires SMTP credentials)
- type: email
  smtp_host: smtp.gmail.com
  smtp_port: 587

# Slack (requires webhook URL)
- type: slack
  webhook_url: https://hooks.slack.com/services/...
```

## Running the API Server

To run an OpenAI-compatible API server instead of the dashboard, change the start command:

```
initrunner serve /data/roles/full-tools-assistant.yaml --host 0.0.0.0 --port 8000
```

Update the port mapping and health check path accordingly (`/v1/models` for the API server).

## Troubleshooting

### "No API key configured"
Set at least one provider API key (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `GOOGLE_API_KEY`) in your platform's environment variables.

### Empty dashboard (no roles)
The entrypoint script seeds roles only if `/data/roles/` is empty or missing. If you mounted an empty host directory, it overrides the seeding. Either:
- Remove the volume mount and let the container manage `/data/roles/`
- Copy roles manually: `docker cp container:/opt/initrunner/example-roles/ ./roles/`

### Health check failures
The health check hits `/api/health` on port 8420. Ensure:
- Port 8420 is exposed and mapped correctly
- The `INITRUNNER_HOME` env var is set to `/data` (or the correct data directory)
- The container has finished building and starting (allow 30-60s for first boot)

### Volume not persisting
Each platform handles storage differently:
- **Railway**: Create a volume in the UI and mount it at `/data`
- **Render**: The `render.yaml` Blueprint creates a 1 GB disk automatically
- **Fly.io**: Run `fly volumes create initrunner_data --region iad --size 1`
