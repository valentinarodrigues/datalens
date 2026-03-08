"""
Input and output guardrails for DataLens.

Input checks:
  - PII detection (SSN, credit card, email, phone, passport)
  - Legal/raw data exfiltration keywords
  - Prompt injection patterns

Output checks:
  - PII leakage in responses
  - Raw data bulk dump detection (large tables of actual records)
"""
import re
from dataclasses import dataclass, field
from typing import List


@dataclass
class GuardrailResult:
    passed: bool
    violations: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"passed": self.passed, "violations": self.violations}


# ── PII patterns ──────────────────────────────────────────────────────────────
_PII_PATTERNS = {
    "SSN": r"\b\d{3}[-\s]\d{2}[-\s]\d{4}\b",
    "credit_card": r"\b(?:\d{4}[-\s]?){3}\d{4}\b",
    "email": r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",
    "US_phone": r"\b(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b",
    "passport": r"\b[A-Z]{1,2}\d{6,9}\b",
    "UK_NIN": r"\b[A-Z]{2}\s?\d{6}\s?[A-D]\b",
}

# ── Legal data / exfiltration keywords ────────────────────────────────────────
_LEGAL_DATA_KEYWORDS = [
    "download all records",
    "export entire database",
    "bulk export",
    "full dataset dump",
    "give me all rows",
    "extract all data",
    "dump the table",
    "raw records",
    "actual individual records",
    "get me real data",
    "show me real customer data",
    "export licensed data",
    "bypass license",
    "ignore restrictions",
]

# ── Prompt injection patterns ──────────────────────────────────────────────────
_INJECTION_PATTERNS = [
    r"ignore\s+(previous|prior|all)\s+instructions",
    r"disregard\s+(your\s+)?(system\s+prompt|instructions|rules)",
    r"you\s+are\s+now\s+a",
    r"act\s+as\s+(a\s+)?(different|unrestricted|evil|jailbroken)",
    r"pretend\s+(you\s+are|to\s+be)\s+",
    r"do\s+anything\s+now",
    r"DAN\s*mode",
    r"developer\s+mode\s+enabled",
]


def check_input(text: str) -> GuardrailResult:
    """Validate user input before sending to the agent."""
    violations = []

    # PII check
    for label, pattern in _PII_PATTERNS.items():
        if re.search(pattern, text, re.IGNORECASE):
            violations.append(
                f"PII detected in input ({label}). Do not paste real personal data into the chat."
            )

    # Legal/exfiltration keywords
    text_lower = text.lower()
    for keyword in _LEGAL_DATA_KEYWORDS:
        if keyword in text_lower:
            violations.append(
                f"Request appears to ask for raw licensed data export: '{keyword}'. "
                "DataLens provides metadata, schemas, and statistics — not raw records."
            )

    # Prompt injection
    for pattern in _INJECTION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            violations.append(
                "Input contains patterns that look like prompt injection. Request blocked."
            )

    return GuardrailResult(passed=len(violations) == 0, violations=violations)


def check_output(text: str) -> GuardrailResult:
    """Validate agent output before returning to user."""
    violations = []

    # PII leakage in output
    for label, pattern in _PII_PATTERNS.items():
        if label == "email":
            # Allow internal emails (company.internal) but flag external ones
            matches = re.findall(pattern, text, re.IGNORECASE)
            external = [m for m in matches if "company.internal" not in m.lower() and "example.com" not in m.lower()]
            if external:
                violations.append(f"Output may contain external email addresses: {external[:3]}")
        else:
            if re.search(pattern, text, re.IGNORECASE):
                violations.append(f"Output may contain PII ({label}). Review before sharing.")

    # Raw bulk data detection: many pipe-separated lines = possible raw table dump
    lines = text.split("\n")
    pipe_lines = sum(1 for l in lines if l.count("|") >= 3)
    if pipe_lines > 30:
        violations.append(
            "Output appears to contain a large table of raw data. "
            "DataLens should return metadata/stats, not bulk records."
        )

    return GuardrailResult(passed=len(violations) == 0, violations=violations)
