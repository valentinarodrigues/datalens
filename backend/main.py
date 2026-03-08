"""
DataLens FastAPI backend — runs as AWS Lambda (container image) via Mangum.

Endpoints:
  POST /chat         - Main agentic chat endpoint
  GET  /metrics      - Platform overview metrics for sidebar
  GET  /products     - List all products (lightweight)
  GET  /health       - Health check

Local dev:
  uvicorn main:app --reload --port 8000

Lambda deployment:
  Build + push the container image, then deploy via SAM (template.yaml).
  The `handler` export at the bottom of this file is the Lambda entry point.
  API Gateway (HTTP API) proxies all routes to the Lambda.

Production with Datadog APM:
  Add Datadog Lambda Extension layer + DD_API_KEY env var in template.yaml.
  Set DD_TRACE_ENABLED=true — ddtrace auto-instruments FastAPI + LangChain.
"""
import os
import sys
import uuid
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Use explicit path so .env is found regardless of the working directory
# (important for Lambda cold start and running uvicorn from a parent dir)
_here = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(_here, ".env"), override=True)

# Ensure backend directory is on path
sys.path.insert(0, _here)

from agents import run_agent
from guardrails import check_input, check_output
from observability import DatadogCallbackHandler
from mock_data import DATA_CATALOG, PROCUREMENT, USAGE_STATS, QUALITY_METRICS

app = FastAPI(
    title="DataLens API",
    description="Agentic third-party data product discovery assistant",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    # In Lambda/API Gateway, set ALLOWED_ORIGINS env var to your CloudFront or
    # frontend domain. Falls back to localhost for local dev.
    allow_origins=os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response models ──────────────────────────────────────────────────

class Message(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    persona: str = "Data Scientist"
    conversation_history: List[Message] = []


class ToolCall(BaseModel):
    tool: str
    latency_ms: int
    output_preview: str = ""
    output_keys: List[str] = []


class TraceData(BaseModel):
    trace_id: str
    persona: str
    tool_calls: List[ToolCall] = []
    llm_call_count: int = 0
    total_tokens: Dict[str, int] = {}
    agent_latency_ms: int = 0
    wall_time_ms: int = 0
    tools_used: List[str] = []


class GuardrailStatus(BaseModel):
    input_passed: bool
    input_violations: List[str] = []
    output_passed: bool
    output_violations: List[str] = []


class ChatResponse(BaseModel):
    response: str
    trace: TraceData
    guardrails: GuardrailStatus
    structured_data: Optional[Dict[str, Any]] = None
    blocked: bool = False


# ── Chat endpoint ──────────────────────────────────────────────────────────────

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    trace_id = str(uuid.uuid4())[:8]

    # 1. Input guardrail
    input_check = check_input(request.message)
    if not input_check.passed:
        blocked_response = (
            "⚠️ **Request blocked by DataLens guardrails.**\n\n"
            + "\n".join(f"- {v}" for v in input_check.violations)
            + "\n\nDataLens provides metadata, schemas, and statistics about data products — "
            "not raw data records. Please rephrase your question."
        )
        return ChatResponse(
            response=blocked_response,
            trace=TraceData(trace_id=trace_id, persona=request.persona),
            guardrails=GuardrailStatus(
                input_passed=False,
                input_violations=input_check.violations,
                output_passed=True,
            ),
            blocked=True,
        )

    # 2. Run agent with observability
    handler = DatadogCallbackHandler(trace_id=trace_id, persona=request.persona)

    try:
        result = await run_agent(
            message=request.message,
            persona=request.persona,
            history=[m.model_dump() for m in request.conversation_history],
            callback_handler=handler,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")

    response_text = result.get("response", "")

    # 3. Output guardrail
    output_check = check_output(response_text)
    if not output_check.passed:
        response_text = (
            response_text
            + "\n\n⚠️ *Note: Output guardrail flagged potential issues — "
            "response reviewed before display.*"
        )

    # 4. Build trace
    summary = handler.get_summary()
    trace = TraceData(
        trace_id=summary["trace_id"],
        persona=summary["persona"],
        tool_calls=[ToolCall(**tc) for tc in summary["tool_calls"]],
        llm_call_count=summary["llm_call_count"],
        total_tokens=summary["total_tokens"],
        agent_latency_ms=summary["agent_latency_ms"],
        wall_time_ms=summary["wall_time_ms"],
        tools_used=summary["tools_used"],
    )

    return ChatResponse(
        response=response_text,
        trace=trace,
        guardrails=GuardrailStatus(
            input_passed=True,
            output_passed=output_check.passed,
            output_violations=output_check.violations,
        ),
        structured_data=result.get("structured_data"),
    )


# ── Metrics endpoint ───────────────────────────────────────────────────────────

@app.get("/metrics")
def get_metrics():
    """Platform overview metrics — displayed in the chat sidebar."""
    products = DATA_CATALOG["products"]
    total_spend = sum(
        PROCUREMENT.get(p["id"], {}).get("annual_value_usd", 0) for p in products
    )
    total_teams = sum(USAGE_STATS.get(p["id"], {}).get("total_teams", 0) for p in products)
    total_users = sum(USAGE_STATS.get(p["id"], {}).get("total_users", 0) for p in products)

    access_type_counts: Dict[str, int] = {}
    domain_counts: Dict[str, int] = {}
    for p in products:
        at = p["access_type"]
        access_type_counts[at] = access_type_counts.get(at, 0) + 1
        d = p["domain"].split(" / ")[0]
        domain_counts[d] = domain_counts.get(d, 0) + 1

    contracts_expiring_soon = []
    for p in products:
        proc = PROCUREMENT.get(p["id"], {})
        renewal = proc.get("renewal_date", "")
        if renewal and renewal <= "2026-12-31":
            contracts_expiring_soon.append({
                "name": p["name"],
                "renewal_date": renewal,
                "auto_renewal": proc.get("auto_renewal", False),
            })

    return {
        "total_products": len(products),
        "total_vendors": len(set(p["vendor"] for p in products)),
        "total_annual_spend_usd": total_spend,
        "total_teams_using": total_teams,
        "total_users": total_users,
        "access_type_counts": access_type_counts,
        "domain_counts": domain_counts,
        "contracts_expiring_soon": contracts_expiring_soon,
    }


# ── Products list endpoint ─────────────────────────────────────────────────────

@app.get("/products")
def list_products():
    """Lightweight product list for autocomplete / browsing."""
    products = DATA_CATALOG["products"]
    result = []
    for p in products:
        quality = QUALITY_METRICS.get(p["id"], {})
        usage = USAGE_STATS.get(p["id"], {})
        result.append({
            "id": p["id"],
            "name": p["name"],
            "vendor": p["vendor"],
            "domain": p["domain"],
            "access_type": p["access_type"],
            "tags": p["tags"],
            "data_freshness": p["data_freshness"],
            "quality_score": quality.get("overall_score"),
            "teams_using": usage.get("total_teams", 0),
            "status": p["status"],
        })
    return {"products": result}


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "datalens", "version": "1.0.0"}


# ── Lambda entry point ─────────────────────────────────────────────────────────
# Mangum translates API Gateway HTTP API (payload v2) events into ASGI requests
# so the same FastAPI app works locally (uvicorn) and on Lambda unchanged.
#
# Lambda handler is:  main.handler
# lifespan="off" — Lambda doesn't support the ASGI lifespan protocol.
from mangum import Mangum  # noqa: E402

handler = Mangum(app, lifespan="off")
