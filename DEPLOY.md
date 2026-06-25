# Deployment Guide

## Quick Deploy (Docker)

```bash
# Build and run
docker build -t stockoverflow .
docker run -p 8000:8000 -v ./data:/app/data stockoverflow

# Or with docker-compose
docker-compose up -d
```

## Railway (Recommended)

1. Install Railway CLI: `npm i -g @railway/cli`
2. Login: `railway login`
3. Init: `railway init`
4. Deploy: `railway up`

The `railway.toml` is pre-configured.

## Fly.io

1. Install Fly CLI: `curl -L https://fly.io/install.sh | sh`
2. Login: `fly auth login`
3. Launch: `fly launch`
4. Deploy: `fly deploy`

The `fly.toml` is pre-configured.

## Heroku

1. Install Heroku CLI
2. Create app: `heroku create your-app-name`
3. Deploy: `git push heroku main`

The `Procfile` is pre-configured.

## Environment Variables

Set these in your deployment platform:

```bash
# Required for LLM features (configure via web UI)
LLM_API_KEY=sk-your-key
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o

# Optional
DEFAULT_HISTORY_PERIOD=5y
DEBUG=false
```

## Database

SQLite database is auto-created in `data/stocks.db`. Mount a persistent volume for `data/` directory.

## Health Check

All platforms can use: `GET /health`

Returns: `{"status": "healthy", "database": "ok", "version": "0.2.0"}`
