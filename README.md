# DataLens

An agentic internal chat interface for discovering, understanding, and evaluating the organisation's third-party data products. Instead of hunting across Confluence, JIRA, vendor portals, and Slack, teams ask DataLens in plain English and get a structured answer drawn from the real sources.

---

## The Problem

Third-party data sits across SaaS APIs, Snowflake shares, S3/Delta datalakes, and SNS event streams — from multiple vendors, with different access patterns, licensing constraints, and quality profiles. The people who need to work with this data (data scientists, engineers, product owners, procurement) each need different things from it, and there is no single place to find all of it.

The result: repeated Slack threads, stale Confluence pages, and engineers spending hours figuring out how to connect to a dataset or whether they are even allowed to use it for their use case.

---

## What DataLens Does

DataLens is a **multi-agent system** built on LangGraph. A user asks a question, the orchestrator autonomously decides which tools to call, calls them in sequence, and synthesises a response tailored to the user's role.

**Example questions it can answer:**

| Persona | Question |
|---------|----------|
| Data Scientist | What columns are in CreditPulse Pro and what are the null rates? Can I use it to train a churn model? |
| Data Engineer | How do I connect to the GeoMatrix datalake? What IAM role do I need? |
| Product Owner | Which data products are being used by more than 10 teams? What are the alternatives to BrandSense? |
| Procurement | Which contracts are up for renewal in the next 6 months and do they auto-renew? |
| Data Consumer | Can I use TransactIQ to answer questions about UK consumer spend? How do I get access? |

---

## How It Works

```
User message + persona
        │
        ▼
┌─────────────────────────────────────────────────────┐
│  Input Guardrails                                   │
│  PII detection · raw data export requests ·         │
│  prompt injection patterns                          │
└────────────────────┬────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────┐
│  LangGraph Orchestrator  (START → agent ⇄ tools → END)│
│                                                     │
│  Agent (LLM with bound tools)                       │
│  ├── decides which tools to call                    │
│  ├── calls tools, observes results                  │
│  └── loops until it has enough to answer            │
│                                                     │
│  Tools                                              │
│  ├── search_catalog          get_quality_metrics    │
│  ├── get_product_schema      get_contract_info      │
│  ├── check_legal_compliance  get_usage_statistics   │
│  ├── get_access_patterns     compare_products       │
│  ├── get_sample_queries      get_platform_overview  │
│  ├── search_confluence       get_confluence_page    │
│  ├── get_jira_issues         search_github          │
│  ├── get_github_file         get_api_spec           │
└─────────────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────┐
│  Output Guardrails                                  │
│  PII leakage · bulk data dump detection             │
└────────────────────┬────────────────────────────────┘
                     │
                     ▼
            Response + agent trace
         (tools called, latency, tokens)
```

The agent trace is visible in the UI for every message — users can see exactly which tools were called, in what order, and how long each took.

---

## Data Sources Covered

DataLens understands four access types and handles each differently:

| Access Type | Examples | Schema representation |
|-------------|----------|----------------------|
| `database` | Snowflake Data Sharing, Redshift | Tables, columns, types, nullable flags |
| `saas_api` | REST APIs (weather, brand, risk) | Endpoints, parameters, response fields |
| `datalake` | S3 + Delta Lake, S3 + Parquet | Partition schemes, column definitions, S3 paths |
| `sns_topic` | AWS SNS event streams | JSON message schema, filter policy, sample payload |

---

## Personas

The system prompt changes based on the selected persona, so the same underlying data is presented differently:

- **Data Scientist** — schemas, null rates, sample SQL/Python, ML training permissions, quality scores
- **Data Engineer** — connection strings, IAM roles, partition schemes, pipeline integrations, SLA
- **Product Owner** — use cases, team adoption, coverage, freshness fit
- **Procurement** — contract terms, renewal dates, auto-renewal flags, cost, alternatives
- **Data Consumer** — plain-English answers, access steps, who to contact, use case fit

---

## Guardrails

Every request passes through input and output checks before the agent sees it or the user sees the response.

**Input blocks:**
- PII patterns (SSN, credit card, passport, phone, email)
- Raw data exfiltration keywords ("export entire database", "give me all rows", etc.)
- Prompt injection patterns ("ignore previous instructions", "DAN mode", etc.)

**Output blocks:**
- PII present in generated response
- Large pipe-delimited table dumps (signs the LLM is echoing raw data)

Blocked requests return a plain-language message explaining what triggered the block. Nothing is silently dropped.

---

## Observability

A custom LangChain `BaseCallbackHandler` instruments every LLM call and tool call:

- Each request gets a `trace_id`
- Tool name, latency, and output summary logged per call
- Token usage (input / output / total) tracked per LLM call
- All logs emitted as structured JSON with `dd.trace_id` for Datadog correlation

The same trace data is returned in the API response and shown in the UI trace panel so developers and support teams can inspect agent behaviour without needing Datadog access.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Agent framework | LangGraph (StateGraph, ToolNode, tools_condition) |
| LLM | Amazon Bedrock — Claude 3.5 Sonnet (or Haiku for lower cost) |
| Backend | FastAPI + Mangum (Lambda-compatible) |
| Database | DynamoDB — usage statistics per product |
| Frontend | React + TypeScript + Vite + Tailwind CSS |
| Deployment | AWS Lambda (container image) + API Gateway HTTP API via SAM |
| Observability | Datadog — structured JSON logs + optional APM via `ddtrace` |

---

## Data Layer

The current implementation uses mock data (`backend/mock_data/data.py`) for 8 representative third-party products covering all four access types. This is intentional — it lets the agentic system run and be evaluated without requiring real vendor credentials.

**Usage statistics** are the one exception: they are already wired to DynamoDB. When `USAGE_TABLE_NAME` is set, the agent reads live data; when it is blank (local dev), it falls back to the mock values. Seed the table after deploying:

```bash
python backend/scripts/seed_dynamodb.py --table <UsageTableName from sam deploy output>
```

To replace the remaining mock data with real sources:

| Data stream | Real source | How |
|-------------|-------------|-----|
| Schemas | Snowflake `information_schema`, AWS Glue catalog | Scheduled Lambda crawler |
| Contracts / legal | Vendor PDF files | `pdfplumber` + LLM extraction → S3 JSON |
| Quality metrics | dbt test results, Great Expectations | Hook into CI/CD pipeline output |
| Usage stats | DynamoDB (already wired) | `scripts/seed_dynamodb.py` or live pipeline writes |
| Documentation | Confluence REST API | Live tool call or nightly enrichment |
| Incidents | JIRA REST API | Live tool call |
| Code / specs | GitHub API, OpenAPI / AsyncAPI files | Live tool call or nightly enrichment |

Catalog metadata (schemas, legal, quality) is best kept as S3 JSON files — one per product. S3 is sufficient for up to ~100 products and simpler to operate than a relational database.

---

## Project Structure

```
datalens/
├── backend/
│   ├── main.py                      # FastAPI app + Mangum Lambda handler
│   ├── requirements.txt
│   ├── .env.example
│   ├── Dockerfile                   # Lambda container image (arm64)
│   ├── template.yaml                # AWS SAM deployment template (Bedrock + DynamoDB)
│   ├── agents/
│   │   └── orchestrator.py          # LangGraph graph definition + persona prompts
│   ├── tools/
│   │   ├── tools.py                 # 10 catalog/schema/quality/legal/usage tools
│   │   └── external_tools.py        # Confluence, JIRA, GitHub, API spec tools
│   ├── mock_data/
│   │   └── data.py                  # Mock data — 8 products, all 4 access types
│   ├── scripts/
│   │   └── seed_dynamodb.py         # Seed DynamoDB usage-stats table from mock data
│   ├── guardrails/
│   │   └── guards.py                # Input + output guardrail checks
│   └── observability/
│       └── datadog_handler.py       # LangChain callback → structured Datadog logs
└── frontend/
    ├── vite.config.ts               # Dev proxy (/api → :8000) + VITE_API_URL for prod
    ├── .env.development
    ├── .env.production
    └── src/
        ├── App.tsx                  # Chat UI, persona selector, agent trace panel
        └── types.ts
```

---

## Getting Started

### Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.9+ | [python.org](https://python.org) |
| Node.js | 18+ | `brew install node` |
| AWS CLI | v2 | `brew install awscli` |

**AWS setup:**
- Configure credentials: `aws configure` (or set `AWS_PROFILE`)
- Enable the Bedrock model in your account: Bedrock console → Model access → enable `Claude 3.5 Sonnet`

### Backend

```bash
cd backend

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env:
#   BEDROCK_MODEL_ID  — model ID (default works if Claude 3.5 Sonnet is enabled)
#   AWS_REGION        — region where Bedrock is enabled (default: us-east-1)
#   AWS_PROFILE       — optional, if using a named AWS profile
#   USAGE_TABLE_NAME  — leave blank for local dev (falls back to mock data)
```

### Run

```bash
# Tab 1 — backend
cd backend
set -a && . .env && set +a
.venv/bin/uvicorn main:app --port 8000 --reload

# Tab 2 — frontend
cd frontend
npm install   # first time only
npm run dev
```

Open **http://localhost:5173**.

### API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/chat` | Agentic chat |
| `GET` | `/metrics` | Portfolio overview for sidebar |
| `GET` | `/products` | Product list |
| `GET` | `/health` | Health check |
| `GET` | `/docs` | Swagger UI |

---

## Deploying to AWS Lambda

```bash
cd backend
brew install aws-sam-cli      # if not already installed

sam build
sam deploy --guided           # first time — creates samconfig.toml
                              # prompted for: BedrockModelId, AllowedOrigins, DatadogApiKey
sam deploy                    # subsequent deploys
```

After first deploy, seed the DynamoDB usage-stats table:

```bash
# Get the table name from the stack outputs
TABLE=$(aws cloudformation describe-stacks \
    --stack-name datalens \
    --query "Stacks[0].Outputs[?OutputKey=='UsageTableName'].OutputValue" \
    --output text)

python scripts/seed_dynamodb.py --table "$TABLE"
```

After deploying, set the API Gateway URL in the frontend:

```bash
# frontend/.env.production
VITE_API_URL=https://<api-id>.execute-api.<region>.amazonaws.com
```

Then build and deploy the frontend to S3 + CloudFront or your preferred host.

---

## Enabling External Tools (Confluence, JIRA, GitHub)

Add to `backend/.env`:

```env
CONFLUENCE_URL=https://yourco.atlassian.net/wiki
CONFLUENCE_API_TOKEN=your_pat

JIRA_URL=https://yourco.atlassian.net
JIRA_EMAIL=your@email.com
JIRA_API_TOKEN=your_pat

GITHUB_TOKEN=ghp_your_pat
GITHUB_ORG=your-org
```

All tokens are read-only PATs. If a token is not set, the corresponding tool returns a "not configured" message and the agent moves on — no crash, no silent failure.

---

## Observability (Datadog)

Structured JSON logs are emitted for every request. To enable full APM locally:

```bash
pip install ddtrace
DD_API_KEY=your_key DD_ENV=prod DD_SERVICE=datalens ddtrace-run uvicorn main:app --port 8000
```

For Lambda, add the Datadog Lambda Extension layer ARN in `template.yaml` and set `DD_API_KEY` as a deploy parameter.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Failed to reach the DataLens API` | Backend not running | Start uvicorn (see Run section) |
| `Could not connect to the endpoint URL` | Wrong AWS region | Set `AWS_REGION` matching where Bedrock is enabled |
| `AccessDeniedException` on Bedrock | Model not enabled or IAM missing | Enable model in Bedrock console; check IAM policy |
| `ValidationException: model not found` | Wrong model ID or model disabled | Check `BEDROCK_MODEL_ID` in `.env`; enable model in Bedrock console |
| `NoCredentialsError` | AWS credentials not configured | Run `aws configure` or set `AWS_PROFILE` |
| `no such file or directory: .env` | Wrong directory when sourcing | `cd backend` first |
| `address already in use :8000` | Stale process | `kill $(lsof -ti:8000)` |
| `address already in use :5173` | Stale Vite process | `kill $(lsof -ti:5173)` |
