# DataLens — Third-Party Data Product Discovery

An agentic chat interface that helps teams discover, understand, and evaluate the organisation's third-party data products. Built with **LangGraph + Ollama (local LLM)** on the backend and **React + Vite** on the frontend.

---

## Architecture

```
Browser (localhost:5173)
    │  /api/* requests
    ▼
Vite Dev Server (proxy)
    │  rewrites /api → /
    ▼
FastAPI + Mangum (localhost:8000)
    │
    ▼
LangGraph Orchestrator
    ├── Tools (catalog, schema, quality, legal, contracts, usage)
    ├── External tools (Confluence, JIRA, GitHub, API specs)
    └── Guardrails + Datadog observability
    │
    ▼
Ollama (localhost:11434)
    └── llama3.1 / llama3.2
```

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.9+ | [python.org](https://python.org) |
| Node.js | 18+ | [nodejs.org](https://nodejs.org) or `brew install node` |
| Ollama | any | [ollama.com](https://ollama.com) or `brew install ollama` |

---

## Quick Start

### 1 — Clone and enter the project

```bash
git clone <repo-url>
cd datalens
```

---

### 2 — Backend setup

```bash
cd backend

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows

# Install dependencies
pip install -r requirements.txt
```

#### Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` — the only required fields for local development:

```env
# Which Ollama model to use
OLLAMA_MODEL=llama3.1
OLLAMA_BASE_URL=http://localhost:11434

# Optional: Datadog observability
DD_API_KEY=
DD_ENV=development
DD_SERVICE=datalens
DD_TRACE_ENABLED=false

# CORS origins (comma-separated)
ALLOWED_ORIGINS=http://localhost:5173,http://localhost:3000
```

> **No API key required** — DataLens uses Ollama (local LLM) by default.

#### Optional: external data sources (Confluence, JIRA, GitHub)

Add these to `.env` only if you want to enable live queries against those systems:

```env
# Confluence
CONFLUENCE_URL=https://yourco.atlassian.net/wiki
CONFLUENCE_API_TOKEN=your_pat

# JIRA
JIRA_URL=https://yourco.atlassian.net
JIRA_EMAIL=your@email.com
JIRA_API_TOKEN=your_pat

# GitHub
GITHUB_TOKEN=ghp_your_pat
GITHUB_ORG=your-org
```

---

### 3 — Pull an Ollama model

Ollama must be running before you start the backend.

```bash
# Start Ollama (runs on port 11434)
ollama serve

# In a separate terminal — pull a model (choose one)
ollama pull llama3.1    # 4.9 GB  — better reasoning, slower on CPU
ollama pull llama3.2    # 2.0 GB  — faster, good for most queries
```

> **Model comparison**
>
> | Model | Size | Speed (CPU) | Tool-use quality |
> |-------|------|-------------|-----------------|
> | `llama3.1` | 4.9 GB | ~60-120s/query | ⭐⭐⭐⭐ |
> | `llama3.2` | 2.0 GB | ~20-40s/query | ⭐⭐⭐ |
>
> Switch models by changing `OLLAMA_MODEL` in `.env` — no code change needed.

---

### 4 — Start the backend

```bash
# From the backend/ directory, with .env loaded
cd backend
set -a && . .env && set +a
.venv/bin/uvicorn main:app --port 8000 --reload
```

Confirm it is running:

```bash
curl http://localhost:8000/health
# {"status":"ok","service":"datalens","version":"1.0.0"}
```

Available endpoints:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/chat` | Main agentic chat |
| `GET` | `/metrics` | Portfolio overview metrics |
| `GET` | `/products` | Lightweight product list |
| `GET` | `/health` | Health check |
| `GET` | `/docs` | Interactive API docs (Swagger UI) |

---

### 5 — Start the frontend

Open a new terminal tab:

```bash
cd frontend
npm install       # first time only
npm run dev
```

Open **http://localhost:5173** in your browser.

---

## Running Everything at Once

For convenience, run all three services in separate terminal tabs:

```bash
# Tab 1 — Ollama
ollama serve

# Tab 2 — Backend
cd datalens/backend
set -a && . .env && set +a
.venv/bin/uvicorn main:app --port 8000 --reload

# Tab 3 — Frontend
cd datalens/frontend
npm run dev
```

---

## Project Structure

```
datalens/
├── backend/
│   ├── main.py                      # FastAPI app + Mangum Lambda handler
│   ├── requirements.txt
│   ├── .env.example                 # Environment variable template
│   ├── Dockerfile                   # Lambda container image
│   ├── template.yaml                # AWS SAM deployment template
│   ├── agents/
│   │   └── orchestrator.py          # LangGraph multi-agent loop
│   ├── tools/
│   │   ├── tools.py                 # Catalog, schema, quality, legal, usage tools
│   │   └── external_tools.py        # Confluence, JIRA, GitHub, API spec tools
│   ├── mock_data/
│   │   └── data.py                  # Mock data for 8 third-party products
│   ├── guardrails/
│   │   └── guards.py                # Input/output guardrails (PII, injection)
│   └── observability/
│       └── datadog_handler.py       # LangChain callback → Datadog structured logs
└── frontend/
    ├── index.html
    ├── vite.config.ts               # Vite proxy config (dev) / VITE_API_URL (prod)
    ├── .env.development             # Local API URL
    ├── .env.production              # API Gateway URL (set after SAM deploy)
    └── src/
        ├── App.tsx                  # Main app — chat, personas, trace panel
        └── types.ts                 # TypeScript types
```

---

## Switching from Mock Data to Real Data

The tools in `tools/tools.py` read from `mock_data/data.py`. To connect real sources:

1. **Schemas** — crawl Snowflake `information_schema` or AWS Glue catalog
2. **Contracts** — parse vendor PDFs with `pdfplumber` + an LLM; store extracted JSON in S3
3. **Quality metrics** — hook into dbt test results or Great Expectations
4. **Usage stats** — query Datadog metrics API or Snowflake query history
5. **API specs** — fetch OpenAPI/AsyncAPI files from GitHub or S3

Replace the mock dict lookups in `tools/tools.py` with calls to your real data store (S3 JSON files are sufficient for most team sizes — no database required unless you have 100+ products or need concurrent writes to catalog metadata).

---

## Deploying to AWS Lambda

The backend is Lambda-ready via **Mangum** (the `handler = Mangum(app)` export in `main.py`).

```bash
cd backend

# Install AWS SAM CLI if needed
brew install aws-sam-cli

# Build Docker image + deploy
sam build
sam deploy --guided     # first time — saves samconfig.toml
sam deploy              # subsequent deploys
```

After deploying, update the frontend:

```bash
# frontend/.env.production
VITE_API_URL=https://<api-id>.execute-api.<region>.amazonaws.com
```

Then rebuild the frontend and deploy to S3/CloudFront or your preferred host.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `Failed to reach the DataLens API` | Backend not running | Start uvicorn (Step 4) |
| `model not found` | Ollama model not pulled | `ollama pull llama3.1` |
| `connection refused` on port 11434 | Ollama not running | `ollama serve` |
| Very slow responses (>2 min) | Large model on CPU | Switch to `llama3.2` in `.env` |
| `no such file or directory: .env` | Wrong directory when sourcing | `cd backend` first, then `. .env` |
| `address already in use` port 8000 | Previous process still running | `kill $(lsof -ti:8000)` |
| `address already in use` port 5173 | Previous Vite process running | `kill $(lsof -ti:5173)` |

---

## Guardrails

DataLens blocks the following on every request:

- **Input**: SSN, credit card numbers, passport numbers, phone numbers, email addresses (PII)
- **Input**: Requests for raw data exports or bulk record dumps
- **Input**: Prompt injection patterns
- **Output**: PII in responses, large raw data table dumps

Blocked requests return a descriptive message explaining what was flagged.

---

## Observability (Datadog)

Structured JSON logs are emitted for every tool call and LLM call, tagged with `dd.trace_id` for correlation.

To enable full Datadog APM:

```bash
pip install ddtrace
DD_API_KEY=your_key DD_ENV=prod DD_SERVICE=datalens ddtrace-run uvicorn main:app --port 8000
```

For Lambda, add the [Datadog Lambda Extension layer](https://docs.datadoghq.com/serverless/installation/python/) ARN in `template.yaml`.
