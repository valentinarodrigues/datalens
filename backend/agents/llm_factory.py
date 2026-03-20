"""
LLM factory — returns the correct chat model based on the LLM_BACKEND env var.

Supported backends
------------------
bedrock (default)
    Uses Amazon Bedrock via the boto3 credential chain.
    Requires: AWS credentials + Bedrock model enabled in your account.
    Set: BEDROCK_MODEL_ID, AWS_REGION

ollama
    Uses a local Ollama server — no AWS account or API key needed.
    Requires: `ollama serve` running + model pulled (`ollama pull llama3.1`).
    Set: OLLAMA_MODEL, OLLAMA_BASE_URL

Usage
-----
    from agents.llm_factory import get_llm
    model = get_llm()
    model_with_tools = model.bind_tools(tools)

Switch backends by setting LLM_BACKEND in .env:
    LLM_BACKEND=ollama        # local dev, no AWS needed
    LLM_BACKEND=bedrock       # production / when AWS creds are available
"""
import os


def get_llm():
    """Return a LangChain chat model configured from environment variables."""
    backend = os.getenv("LLM_BACKEND", "bedrock").lower().strip()

    if backend == "bedrock":
        return _make_bedrock()
    elif backend == "ollama":
        return _make_ollama()
    else:
        raise ValueError(
            f"Unknown LLM_BACKEND={backend!r}. "
            "Valid values: 'bedrock' (default), 'ollama'."
        )


# ── Bedrock ────────────────────────────────────────────────────────────────────

def _make_bedrock():
    try:
        import boto3
        from langchain_aws import ChatBedrock
    except ImportError as e:
        raise ImportError(
            "langchain-aws and boto3 are required for the Bedrock backend. "
            "Run: pip install langchain-aws boto3"
        ) from e

    model_id = os.getenv(
        "BEDROCK_MODEL_ID",
        "anthropic.claude-3-5-sonnet-20241022-v2:0",
    )
    region = os.getenv("AWS_REGION", "us-east-1")

    client = boto3.client(service_name="bedrock-runtime", region_name=region)

    return ChatBedrock(
        model_id=model_id,
        client=client,
        model_kwargs={"temperature": 0, "max_tokens": 4096},
    )


# ── Ollama ─────────────────────────────────────────────────────────────────────

def _make_ollama():
    try:
        from langchain_ollama import ChatOllama
    except ImportError as e:
        raise ImportError(
            "langchain-ollama is required for the Ollama backend. "
            "Run: pip install langchain-ollama"
        ) from e

    model = os.getenv("OLLAMA_MODEL", "llama3.1")
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    return ChatOllama(
        model=model,
        base_url=base_url,
        temperature=0,
        # Keep the context window large enough for multi-tool traces
        num_ctx=8192,
    )
