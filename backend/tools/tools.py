"""
LangChain tools for DataLens agents.

Usage statistics are read from DynamoDB when USAGE_TABLE_NAME is set.
All other data reads from mock_data (swap for real S3/catalog calls in production).
"""
import json
import logging
import os
from decimal import Decimal
from typing import Optional

import boto3
from botocore.exceptions import ClientError
from langchain_core.tools import tool
from mock_data import (
    DATA_CATALOG, SCHEMAS, QUALITY_METRICS,
    LEGAL_METADATA, PROCUREMENT, USAGE_STATS,
)

logger = logging.getLogger("datalens.tools")

# ── DynamoDB setup ─────────────────────────────────────────────────────────────
# Set USAGE_TABLE_NAME in .env to enable live DynamoDB queries.
# If not set, falls back to mock data — local dev works without AWS credentials.
_USAGE_TABLE_NAME = os.getenv("USAGE_TABLE_NAME", "")
_dynamodb = boto3.resource("dynamodb", region_name=os.getenv("AWS_REGION", "us-east-1"))
_usage_table = _dynamodb.Table(_USAGE_TABLE_NAME) if _USAGE_TABLE_NAME else None


def _decimal_to_native(obj):
    """Recursively convert DynamoDB Decimal types to int/float for JSON."""
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    if isinstance(obj, dict):
        return {k: _decimal_to_native(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimal_to_native(i) for i in obj]
    return obj


def _get_usage(product_id: str) -> dict:
    """
    Fetch usage stats from DynamoDB if configured, otherwise fall back to mock data.
    DynamoDB table schema:
        PK  product_id  (String)  — partition key
        Attributes: total_teams, total_users, monthly_api_calls_avg,
                    top_use_cases, top_teams, growth_trend, mom_growth_pct,
                    data_pipeline_integrations, utilisation_pct, ...
    """
    if _usage_table:
        try:
            response = _usage_table.get_item(Key={"product_id": product_id})
            item = response.get("Item")
            if item:
                item.pop("product_id", None)      # don't duplicate in response
                return _decimal_to_native(item)
            logger.warning("DynamoDB: no usage item found for %s", product_id)
        except ClientError as e:
            logger.error("DynamoDB error for %s: %s", product_id, e)
    # Fallback to mock data (local dev / DynamoDB not configured)
    return USAGE_STATS.get(product_id, {})


def _find_products(query: str = "", domain: str = "", access_type: str = "") -> list:
    """Helper: fuzzy-match products against query/domain/access_type."""
    query_lower = query.lower()
    domain_lower = domain.lower()
    access_lower = access_type.lower()
    results = []
    for p in DATA_CATALOG["products"]:
        score = 0
        if query_lower:
            searchable = " ".join([
                p["name"], p["vendor"], p["domain"],
                p["description"], " ".join(p["tags"]),
            ]).lower()
            if query_lower in searchable:
                score += 2
            # partial word match
            for word in query_lower.split():
                if word in searchable:
                    score += 1
        if domain_lower and domain_lower in p["domain"].lower():
            score += 3
        if access_lower and p["access_type"] == access_lower:
            score += 3
        if score > 0 or (not query_lower and not domain_lower and not access_lower):
            results.append((score, p))
    results.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in results]


@tool
def search_catalog(query: str, domain: str = "", access_type: str = "") -> str:
    """
    Search the third-party data product catalog.
    Use this to discover available data products.

    Args:
        query: Keyword search (e.g. "credit", "weather", "supply chain risk")
        domain: Optional domain filter (e.g. "financial", "healthcare", "geospatial")
        access_type: Optional filter - one of: saas_api, database, datalake, sns_topic

    Returns JSON with matching products including id, name, vendor, domain, access_type,
    description, tags, data_freshness, record_count, coverage, status.
    """
    products = _find_products(query, domain, access_type)
    if not products:
        return json.dumps({"found": 0, "products": [], "message": "No products matched the search criteria."})
    summary = []
    for p in products:
        summary.append({
            "id": p["id"],
            "name": p["name"],
            "vendor": p["vendor"],
            "domain": p["domain"],
            "access_type": p["access_type"],
            "description": p["description"],
            "tags": p["tags"],
            "data_freshness": p["data_freshness"],
            "record_count": p["record_count"],
            "coverage": p["coverage"],
            "owner_team": p["owner_team"],
            "contact": p["contact"],
            "status": p["status"],
            "vendor_tier": p.get("vendor_tier"),
        })
    return json.dumps({"found": len(summary), "products": summary})


@tool
def get_product_schema(product_id: str) -> str:
    """
    Get the detailed schema / data structure for a specific data product.
    Handles all access types differently:
      - database: returns tables with column definitions
      - saas_api: returns endpoints, parameters, response fields
      - datalake: returns Delta/Parquet table schemas and S3 paths
      - sns_topic: returns message schema and sample payload

    Also returns connection/access details and sample code snippets.

    Args:
        product_id: The product ID from search_catalog (e.g. "credit_pulse_pro")
    """
    schema = SCHEMAS.get(product_id)
    if not schema:
        # Return basic info if no detailed schema
        products = {p["id"]: p for p in DATA_CATALOG["products"]}
        p = products.get(product_id)
        if p:
            return json.dumps({
                "product_id": product_id,
                "access_type": p["access_type"],
                "note": "Detailed schema not yet catalogued. Contact the owner team.",
                "owner_team": p["owner_team"],
                "contact": p["contact"],
            })
        return json.dumps({"error": f"Product '{product_id}' not found. Use search_catalog to find valid product IDs."})
    return json.dumps({"product_id": product_id, "schema": schema})


@tool
def get_quality_metrics(product_id: str) -> str:
    """
    Get data quality metrics for a specific product: completeness, accuracy,
    timeliness, uniqueness, consistency scores (0-100), known issues, SLA,
    and quality trend (stable/improving/degrading).

    Args:
        product_id: The product ID (e.g. "weather_core_api")
    """
    metrics = QUALITY_METRICS.get(product_id)
    if not metrics:
        return json.dumps({"error": f"Quality metrics not found for '{product_id}'."})
    return json.dumps({"product_id": product_id, "quality": metrics})


@tool
def check_legal_compliance(product_id: str, intended_use_case: str = "") -> str:
    """
    Check legal and compliance restrictions for a data product.
    Returns: compliance frameworks, PII presence, ML training permissions,
    redistribution rules, purpose limitations, prohibited uses,
    data retention policy, and a plain-English restrictions summary.

    Metadata is extracted from vendor PDF contracts.

    Args:
        product_id: The product ID (e.g. "health_insights_pro")
        intended_use_case: Optional - describe your intended use so restrictions
                           can be assessed (e.g. "train an ML churn model")
    """
    legal = LEGAL_METADATA.get(product_id)
    if not legal:
        return json.dumps({"error": f"Legal metadata not found for '{product_id}'."})

    result = dict(legal)
    result["product_id"] = product_id

    if intended_use_case:
        use_lower = intended_use_case.lower()
        warnings = []
        if not legal.get("ml_training_allowed") or legal.get("ml_training_allowed") is False:
            if any(kw in use_lower for kw in ["ml", "train", "model", "machine learning", "ai"]):
                warnings.append("ML training may be restricted for this dataset — check ml_training_allowed field.")
        if not legal.get("redistribution_allowed", True):
            if any(kw in use_lower for kw in ["share", "send", "export", "publish", "redistribute"]):
                warnings.append("Redistribution is NOT permitted for this dataset.")
        for prohibited in legal.get("prohibited_uses", []):
            if any(word in use_lower for word in prohibited.lower().split()):
                warnings.append(f"Possible conflict with prohibited use: '{prohibited}'")
        result["use_case_assessment"] = {
            "intended_use": intended_use_case,
            "warnings": warnings,
            "verdict": "REVIEW_REQUIRED" if warnings else "LIKELY_PERMITTED",
        }

    return json.dumps(result)


@tool
def get_contract_info(product_id: str) -> str:
    """
    Get procurement and contract details for a data product.
    Metadata is extracted from PDF vendor contracts.
    Returns: contract status, effective/renewal dates, annual cost, payment terms,
    pricing model, termination notice period, auto-renewal flag, alternatives,
    and procurement notes.

    Args:
        product_id: The product ID (e.g. "market_pulse_events")
    """
    proc = PROCUREMENT.get(product_id)
    if not proc:
        return json.dumps({"error": f"Contract info not found for '{product_id}'."})
    return json.dumps({"product_id": product_id, "contract": proc})


@tool
def get_usage_statistics(product_id: str) -> str:
    """
    Get usage statistics for a data product: how many teams and users consume it,
    monthly API call volume and utilisation %, top use cases, team breakdown,
    growth trend, and which data pipeline integrations exist.

    Data is read from DynamoDB (when USAGE_TABLE_NAME is configured) or
    falls back to mock data for local development.

    Args:
        product_id: The product ID (e.g. "geo_matrix_demographics")
    """
    usage = _get_usage(product_id)
    if not usage:
        return json.dumps({"error": f"Usage stats not found for '{product_id}'."})
    source = "dynamodb" if _usage_table else "mock"
    return json.dumps({"product_id": product_id, "usage": usage, "source": source})


@tool
def get_access_patterns(product_id: str) -> str:
    """
    Get how to technically connect to and consume a data product.
    Returns connection details based on access type:
      - database → connection string details, IAM role, Snowflake/Redshift specifics
      - saas_api → base URL, auth method, rate limits, SDK examples
      - datalake → S3 bucket/prefix, IAM role, Glue database, format details
      - sns_topic → topic ARN, subscription process, filter policy options, DLQ

    Args:
        product_id: The product ID
    """
    schema = SCHEMAS.get(product_id)
    if not schema:
        products = {p["id"]: p for p in DATA_CATALOG["products"]}
        p = products.get(product_id)
        if p:
            return json.dumps({
                "product_id": product_id,
                "access_type": p["access_type"],
                "note": "Detailed access patterns not yet documented. Contact owner team.",
                "contact": p.get("contact"),
            })
        return json.dumps({"error": f"Product '{product_id}' not found."})

    access_type = schema.get("access_type")
    result = {"product_id": product_id, "access_type": access_type}

    if access_type == "database":
        result["connection"] = schema.get("connection", {})
        result["how_to_request_access"] = "Submit IT access request with your team lead approval. Specify Snowflake role or Redshift IAM role needed."
    elif access_type == "saas_api":
        result["base_url"] = schema.get("base_url")
        result["auth_method"] = schema.get("auth_method")
        result["rate_limits"] = schema.get("rate_limits")
        result["sdk_examples"] = schema.get("sdk_examples", {})
        result["how_to_request_access"] = "API keys managed in Vault. Request access via IT portal — approval from team lead required. Keys rotated every 90 days."
    elif access_type == "datalake":
        result["connection"] = schema.get("connection", {})
        result["how_to_request_access"] = "IAM role assumption via STS. Submit IT access request with justification. Role grants read-only access to specific S3 prefix."
    elif access_type == "sns_topic":
        result["topic_details"] = schema.get("topic_details", {})
        result["filter_policy_fields"] = schema.get("filter_policy_fields", [])
        result["how_to_subscribe"] = schema.get("topic_details", {}).get("how_to_subscribe", "Raise IT ticket with your SQS ARN.")

    return json.dumps(result)


@tool
def compare_products(product_ids: list) -> str:
    """
    Compare multiple data products side by side across key dimensions:
    access type, cost, data freshness, quality score, teams using it,
    legal restrictions, and coverage.

    Args:
        product_ids: List of product IDs to compare (e.g. ["credit_pulse_pro", "supply_shield_risk"])
    """
    if not product_ids or len(product_ids) < 2:
        return json.dumps({"error": "Provide at least 2 product_ids to compare."})

    products_map = {p["id"]: p for p in DATA_CATALOG["products"]}
    comparison = []

    for pid in product_ids:
        product = products_map.get(pid)
        if not product:
            comparison.append({"product_id": pid, "error": "Not found"})
            continue
        quality = QUALITY_METRICS.get(pid, {})
        procurement = PROCUREMENT.get(pid, {})
        legal = LEGAL_METADATA.get(pid, {})
        usage = USAGE_STATS.get(pid, {})

        comparison.append({
            "product_id": pid,
            "name": product["name"],
            "vendor": product["vendor"],
            "domain": product["domain"],
            "access_type": product["access_type"],
            "data_freshness": product["data_freshness"],
            "coverage": product["coverage"],
            "quality_overall_score": quality.get("overall_score"),
            "annual_cost_usd": procurement.get("annual_value_usd"),
            "contract_renewal_date": procurement.get("renewal_date"),
            "ml_training_allowed": legal.get("ml_training_allowed"),
            "pii_present": legal.get("pii_present"),
            "total_teams_using": usage.get("total_teams"),
            "total_users": usage.get("total_users"),
            "growth_trend": usage.get("growth_trend"),
        })

    return json.dumps({"comparison": comparison, "products_compared": len(product_ids)})


@tool
def get_sample_queries(product_id: str, role: str = "data_scientist") -> str:
    """
    Get sample queries or code snippets for accessing a data product,
    tailored to a specific role.

    Args:
        product_id: The product ID
        role: One of: data_scientist, data_engineer, product_owner, consumer
    """
    schema = SCHEMAS.get(product_id)
    products_map = {p["id"]: p for p in DATA_CATALOG["products"]}
    product = products_map.get(product_id)

    if not product:
        return json.dumps({"error": f"Product '{product_id}' not found."})

    access_type = product["access_type"]
    samples = {}

    if schema:
        samples = schema.get("sample_queries", {})

    role_key = role.lower().replace(" ", "_")
    if role_key not in samples:
        # Generate generic guidance
        if access_type == "database":
            samples[role_key] = f"-- Connect via Snowflake/Redshift. See get_access_patterns for connection details.\n-- Example: SELECT * FROM <table> WHERE <partition_column> = CURRENT_DATE - 1 LIMIT 100;"
        elif access_type == "saas_api":
            samples[role_key] = "# Use requests or httpx to call the REST API.\n# See get_product_schema for endpoint details and get_access_patterns for auth."
        elif access_type == "datalake":
            samples[role_key] = "# Use delta-rs (Python), PySpark, or AWS Glue.\n# See get_product_schema for S3 path and get_access_patterns for IAM role."
        elif access_type == "sns_topic":
            samples[role_key] = "# Subscribe your SQS queue to the SNS topic ARN.\n# Configure filter policy to reduce volume. Process messages via Lambda or ECS consumer."

    result = {
        "product_id": product_id,
        "access_type": access_type,
        "role": role,
        "sample": samples.get(role_key, samples.get("data_scientist", "No sample available.")),
        "all_available_roles": list(samples.keys()),
    }
    return json.dumps(result)


@tool
def get_platform_overview() -> str:
    """
    Get a high-level overview of all available third-party data products
    in the organization: counts by domain, access type, vendor tier,
    and total spend. Use this to answer broad questions about the data
    product portfolio.
    """
    products = DATA_CATALOG["products"]
    total_spend = sum(PROCUREMENT.get(p["id"], {}).get("annual_value_usd", 0) for p in products)
    domains = {}
    access_types = {}
    tiers = {}
    for p in products:
        domains[p["domain"]] = domains.get(p["domain"], 0) + 1
        access_types[p["access_type"]] = access_types.get(p["access_type"], 0) + 1
        tier = p.get("vendor_tier", "Unknown")
        tiers[tier] = tiers.get(tier, 0) + 1

    total_teams = len(set(
        t["name"]
        for pid in USAGE_STATS
        for t in USAGE_STATS[pid].get("top_teams", [])
    ))

    return json.dumps({
        "total_products": len(products),
        "total_vendors": len(set(p["vendor"] for p in products)),
        "total_annual_spend_usd": total_spend,
        "products_by_domain": domains,
        "products_by_access_type": access_types,
        "products_by_vendor_tier": tiers,
        "approx_total_teams_using": total_teams,
        "products": [{"id": p["id"], "name": p["name"], "domain": p["domain"], "access_type": p["access_type"]} for p in products],
    })


ALL_TOOLS = [
    search_catalog,
    get_product_schema,
    get_quality_metrics,
    check_legal_compliance,
    get_contract_info,
    get_usage_statistics,
    get_access_patterns,
    compare_products,
    get_sample_queries,
    get_platform_overview,
]


def get_all_tools():
    return ALL_TOOLS


def execute_tool(tool_name: str, tool_input: dict) -> str:
    """Execute a tool by name — used outside LangGraph when needed."""
    tool_map = {t.name: t for t in ALL_TOOLS}
    if tool_name not in tool_map:
        return json.dumps({"error": f"Tool '{tool_name}' not found."})
    return tool_map[tool_name].invoke(tool_input)
