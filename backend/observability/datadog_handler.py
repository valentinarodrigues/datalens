"""
Datadog observability for DataLens.

Emits structured JSON logs that Datadog log ingestion can parse.
In production:
  1. Run with `ddtrace-run uvicorn main:app` for APM traces
  2. Set DD_API_KEY, DD_ENV, DD_SERVICE env vars
  3. Configure Datadog log pipeline to parse `dd.trace_id` for trace correlation
  4. Add `pip install ddtrace` to requirements and uncomment ddtrace imports

LangChain callbacks are the hook point — DatadogCallbackHandler is passed to
graph.ainvoke(config={"callbacks": [handler]}) so every tool call, LLM call,
and chain step is automatically captured.
"""
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Union

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

# Configure structured JSON logger — Datadog parses this automatically
# when log format matches the Datadog Log Management JSON spec.
logger = logging.getLogger("datalens")
logger.setLevel(logging.INFO)

if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))  # raw JSON
    logger.addHandler(handler)


def _dd_log(event: str, trace_id: str, level: str = "info", **kwargs):
    """Emit a Datadog-compatible structured log entry."""
    payload = {
        "service": "datalens",
        "ddsource": "python",
        "event": event,
        "dd.trace_id": trace_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **kwargs,
    }
    if level == "error":
        logger.error(json.dumps(payload))
    elif level == "warning":
        logger.warning(json.dumps(payload))
    else:
        logger.info(json.dumps(payload))


class DatadogCallbackHandler(BaseCallbackHandler):
    """
    LangChain callback handler that instruments every LLM call and tool call,
    emitting structured logs compatible with Datadog Log Management + APM.

    Usage:
        handler = DatadogCallbackHandler(trace_id="abc123", persona="Data Scientist")
        result = await graph.ainvoke(input, config={"callbacks": [handler]})
        # Access handler.tool_calls, handler.total_tokens, handler.total_latency_ms
    """

    def __init__(self, trace_id: str, persona: str = "Unknown"):
        super().__init__()
        self.trace_id = trace_id
        self.persona = persona

        # Accumulated telemetry returned to the API
        self.tool_calls: List[Dict] = []
        self.llm_calls: List[Dict] = []
        self.total_latency_ms: float = 0.0
        self.total_tokens: Dict[str, int] = {"input": 0, "output": 0, "total": 0}

        # Internal timing tracking
        self._run_start_times: Dict[str, float] = {}
        self._request_start = time.time()

    # ── Tool callbacks ────────────────────────────────────────────────────────

    def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        *,
        run_id: uuid.UUID,
        **kwargs,
    ):
        tool_name = serialized.get("name", "unknown_tool")
        run_key = str(run_id)
        self._run_start_times[run_key] = time.time()

        _dd_log(
            "tool_start",
            self.trace_id,
            tool=tool_name,
            persona=self.persona,
            input_preview=str(input_str)[:200],
        )

    def on_tool_end(
        self,
        output: str,
        *,
        run_id: uuid.UUID,
        **kwargs,
    ):
        run_key = str(run_id)
        latency_ms = (time.time() - self._run_start_times.pop(run_key, time.time())) * 1000
        tool_name = kwargs.get("name", "unknown_tool")

        # Try to parse output size
        try:
            parsed = json.loads(output)
            output_keys = list(parsed.keys()) if isinstance(parsed, dict) else []
        except Exception:
            output_keys = []

        call_record = {
            "tool": tool_name,
            "latency_ms": round(latency_ms),
            "output_keys": output_keys,
            "output_preview": str(output)[:150],
        }
        self.tool_calls.append(call_record)
        self.total_latency_ms += latency_ms

        _dd_log(
            "tool_end",
            self.trace_id,
            tool=tool_name,
            latency_ms=round(latency_ms),
            persona=self.persona,
        )

    def on_tool_error(
        self,
        error: Union[Exception, KeyboardInterrupt],
        *,
        run_id: uuid.UUID,
        **kwargs,
    ):
        run_key = str(run_id)
        latency_ms = (time.time() - self._run_start_times.pop(run_key, time.time())) * 1000
        tool_name = kwargs.get("name", "unknown_tool")

        _dd_log(
            "tool_error",
            self.trace_id,
            level="error",
            tool=tool_name,
            error=str(error)[:300],
            latency_ms=round(latency_ms),
        )

    # ── LLM callbacks ─────────────────────────────────────────────────────────

    def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        *,
        run_id: uuid.UUID,
        **kwargs,
    ):
        run_key = str(run_id)
        self._run_start_times[run_key] = time.time()
        model_name = serialized.get("kwargs", {}).get("model", "unknown")

        _dd_log(
            "llm_start",
            self.trace_id,
            model=model_name,
            persona=self.persona,
            num_prompts=len(prompts),
        )

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: uuid.UUID,
        **kwargs,
    ):
        run_key = str(run_id)
        latency_ms = (time.time() - self._run_start_times.pop(run_key, time.time())) * 1000

        # Extract token usage from LLM response metadata
        token_usage: Dict[str, int] = {}
        if response.llm_output and "usage" in response.llm_output:
            usage = response.llm_output["usage"]
            token_usage = {
                "input": usage.get("input_tokens", 0),
                "output": usage.get("output_tokens", 0),
                "total": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            }
        elif response.generations:
            for gen_list in response.generations:
                for gen in gen_list:
                    if hasattr(gen, "generation_info") and gen.generation_info:
                        usage = gen.generation_info.get("usage", {})
                        if usage:
                            token_usage = {
                                "input": usage.get("input_tokens", 0),
                                "output": usage.get("output_tokens", 0),
                                "total": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                            }

        for k, v in token_usage.items():
            self.total_tokens[k] = self.total_tokens.get(k, 0) + v

        call_record = {
            "latency_ms": round(latency_ms),
            "tokens": token_usage,
        }
        self.llm_calls.append(call_record)
        self.total_latency_ms += latency_ms

        _dd_log(
            "llm_end",
            self.trace_id,
            latency_ms=round(latency_ms),
            tokens=token_usage,
            persona=self.persona,
        )

    def on_llm_error(
        self,
        error: Union[Exception, KeyboardInterrupt],
        *,
        run_id: uuid.UUID,
        **kwargs,
    ):
        _dd_log("llm_error", self.trace_id, level="error", error=str(error)[:300])

    # ── Summary ───────────────────────────────────────────────────────────────

    def get_summary(self) -> Dict:
        wall_time_ms = round((time.time() - self._request_start) * 1000)
        return {
            "trace_id": self.trace_id,
            "persona": self.persona,
            "tool_calls": self.tool_calls,
            "llm_call_count": len(self.llm_calls),
            "total_tokens": self.total_tokens,
            "agent_latency_ms": round(self.total_latency_ms),
            "wall_time_ms": wall_time_ms,
            "tools_used": list({tc["tool"] for tc in self.tool_calls}),
        }
