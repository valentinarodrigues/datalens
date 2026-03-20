"""
DataLens multi-agent orchestrator using LangGraph.

Graph topology:
    START → agent → (tool calls?) → tools → agent → ... → END

The agent node runs Claude with all tools bound. LangGraph's tools_condition
routes to the ToolNode when Claude emits tool_use blocks, then back to the
agent — creating the agentic loop automatically.

Persona-aware system prompts tailor the depth and focus of responses per role.
"""
import json
import operator
import sys
import os
from typing import Annotated, Any, Dict, Optional, Sequence, TypedDict

from langchain_aws import ChatBedrock
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

# Add parent to path so imports work when running from backend/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools import get_all_tools

# ── Persona system prompts ─────────────────────────────────────────────────────

PERSONA_CONTEXT = {
    "Data Scientist": """Focus on: schema details, data types, null rates, statistical properties,
quality scores, sample queries (Python/SQL), ML training permissions, data freshness,
and how to load data into pandas/Spark. Highlight any data quality issues that could affect models.""",

    "Data Engineer": """Focus on: access patterns (connection strings, IAM roles, S3 paths, SNS ARNs),
data pipeline integrations, partition schemes, data volumes, SLA/freshness, schema details,
sample code snippets. Highlight any infrastructure requirements or access provisioning steps.""",

    "Product Owner": """Focus on: what business problems each dataset solves, which teams already use it,
available coverage and record counts, data freshness fit for product use cases,
high-level quality, and whether the data is actively used and trusted in the org.""",

    "Procurement": """Focus on: contract details (PDF source, renewal dates, auto-renewal flags,
termination notice periods), annual cost, pricing model, utilisation vs limit, alternatives
evaluated, and any negotiation notes. Flag contracts approaching renewal.""",

    "Data Consumer": """Focus on: what questions this data can answer, how to get access (step-by-step),
who to contact, whether the data is available and fresh enough for the use case,
and any legal restrictions on intended use. Keep explanations non-technical.""",
}

BASE_SYSTEM_PROMPT = """You are DataLens, an intelligent internal assistant that helps
employees discover, understand, and evaluate the organization's third-party data products.

The portfolio includes data delivered via:
- SaaS APIs (REST endpoints, webhooks)
- Database access (Snowflake Data Sharing, Redshift)
- Datalake (S3/Delta Lake, Parquet)
- SNS Topic subscriptions (event streams)

Your responsibilities:
1. Help users find the right data product for their needs
2. Explain schemas, access patterns, and connection details
3. Surface data quality metrics and known issues
4. Clearly communicate legal restrictions (from vendor PDF contracts) — especially
   around ML training, redistribution, PII, and retention
5. Provide procurement/contract context when asked
6. Show usage stats to demonstrate organisational adoption

Rules you MUST follow:
- Never expose or suggest ways to extract raw licensed records
- Always mention legal restrictions when discussing restricted datasets
- Always cite which tool/source backs your answer
- If a product isn't in the catalog, say so clearly — don't hallucinate products
- Be concise but complete; structure answers with clear sections when multiple
  topics are covered
"""


def _build_system_prompt(persona: str) -> str:
    persona_ctx = PERSONA_CONTEXT.get(persona, "")
    if persona_ctx:
        return f"{BASE_SYSTEM_PROMPT}\n\nCurrent user persona: **{persona}**\n{persona_ctx}"
    return BASE_SYSTEM_PROMPT


# ── LangGraph state ────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    persona: str


# ── Build the graph ────────────────────────────────────────────────────────────

_tools = get_all_tools()

# ── Bedrock client ─────────────────────────────────────────────────────────────
# Auth: uses standard boto3 credential chain —
#   local dev:  AWS_PROFILE or AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY in .env
#   Lambda:     execution role IAM permissions (no credentials needed in code)
#
# The model must be enabled in your AWS account:
#   Bedrock console → Model access → Enable the chosen model
#
# Supported values for BEDROCK_MODEL_ID:
#   anthropic.claude-3-5-sonnet-20241022-v2:0   ← default, best tool use
#   anthropic.claude-3-haiku-20240307-v1:0       ← faster, cheaper
#   anthropic.claude-3-sonnet-20240229-v1:0

import boto3 as _boto3

_BEDROCK_MODEL_ID = os.getenv(
    "BEDROCK_MODEL_ID",
    "anthropic.claude-3-5-sonnet-20241022-v2:0",
)
_AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

_bedrock_client = _boto3.client(
    service_name="bedrock-runtime",
    region_name=_AWS_REGION,
)

_model = ChatBedrock(
    model_id=_BEDROCK_MODEL_ID,
    client=_bedrock_client,
    model_kwargs={"temperature": 0, "max_tokens": 4096},
)
_model_with_tools = _model.bind_tools(_tools)


def _agent_node(state: AgentState) -> Dict[str, Any]:
    """Agent node: run Claude with tools bound."""
    persona = state.get("persona", "Data Scientist")
    system = _build_system_prompt(persona)

    # Prepend system message
    messages = [SystemMessage(content=system)] + list(state["messages"])
    response = _model_with_tools.invoke(messages)
    return {"messages": [response]}


_tool_node = ToolNode(_tools)

_graph_builder = StateGraph(AgentState)
_graph_builder.add_node("agent", _agent_node)
_graph_builder.add_node("tools", _tool_node)
_graph_builder.add_edge(START, "agent")
_graph_builder.add_conditional_edges("agent", tools_condition)
_graph_builder.add_edge("tools", "agent")

graph = _graph_builder.compile()


# ── Public interface ───────────────────────────────────────────────────────────

def _messages_from_history(history: list) -> list:
    """Convert serialised conversation history to LangChain message objects."""
    messages = []
    for item in history:
        role = item.get("role", "user")
        content = item.get("content", "")
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))
    return messages


async def run_agent(
    message: str,
    persona: str,
    history: list,
    callback_handler=None,
) -> Dict[str, Any]:
    """
    Run the DataLens agentic graph for a user query.

    Args:
        message: The user's query
        persona: One of the defined personas
        history: Prior conversation messages [{"role": "user/assistant", "content": "..."}]
        callback_handler: DatadogCallbackHandler instance for observability

    Returns:
        dict with keys: response (str), structured_data (dict or None)
    """
    prior_messages = _messages_from_history(history)
    current_message = HumanMessage(content=message)

    initial_state: AgentState = {
        "messages": prior_messages + [current_message],
        "persona": persona,
    }

    config: RunnableConfig = {}
    if callback_handler:
        config = {"callbacks": [callback_handler]}

    final_state = await graph.ainvoke(initial_state, config=config)

    # Extract the last AI message as the response
    response_text = ""
    for msg in reversed(final_state["messages"]):
        if isinstance(msg, AIMessage) and isinstance(msg.content, str) and msg.content.strip():
            response_text = msg.content
            break
        elif isinstance(msg, AIMessage) and isinstance(msg.content, list):
            # Content blocks (tool_use + text mixed)
            for block in msg.content:
                if isinstance(block, dict) and block.get("type") == "text":
                    response_text = block["text"]
                    break
                elif hasattr(block, "text"):
                    response_text = block.text
                    break
            if response_text:
                break

    # Build structured_data from tool call outputs captured in the trace
    structured_data = None
    if callback_handler and callback_handler.tool_calls:
        tools_used = [tc["tool"] for tc in callback_handler.tool_calls]
        structured_data = {"tools_used": tools_used}

    return {
        "response": response_text or "I was unable to generate a response. Please try again.",
        "structured_data": structured_data,
    }
