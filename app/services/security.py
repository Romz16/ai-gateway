import hashlib
import json
import re
from typing import Any

from app.core.errors import GatewayError
from app.domain.models import GenerationRequest, Identity

PII_RULES = [
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"),
    re.compile(r"\b(?:\d[ -]?){13,19}\b"),
    re.compile(r"(?<!\w)\+?\d[\d ()-]{8,18}\d\b"),
    re.compile(r"\b(?:sk-[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._-]{12,})", re.I),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
]
INJECTION = re.compile(
    r"ignore\s+(all\s+)?(previous|prior|system)\s+instructions|"
    r"(reveal|print|show)\s+(the\s+)?system\s+prompt",
    re.I,
)


def protect(text: str, policy: str) -> tuple[str, bool]:
    detected = any(rule.search(text) for rule in PII_RULES)
    if detected and policy == "block":
        raise GatewayError("SECURITY_POLICY_VIOLATION", "Sensitive data is blocked by policy.", 400)
    if policy == "mask":
        for rule in PII_RULES:
            text = rule.sub("[REDACTED]", text)
    return text, detected


def secure_request(
    request: GenerationRequest, identity: Identity, injection: bool
) -> GenerationRequest:
    safe = request.model_copy(deep=True)
    for message in safe.messages:
        if injection and INJECTION.search(message.content):
            raise GatewayError(
                "SECURITY_POLICY_VIOLATION", "Input violates prompt security policy."
            )
        message.content, _ = protect(message.content, identity.pii_policy)
    if safe.response_schema is not None:
        # Schemas are also provider-visible input; do not silently change their constraints.
        schema_text = json.dumps(safe.response_schema)
        _, detected = protect(schema_text, "allow")
        if (detected and identity.pii_policy != "allow") or (
            injection and INJECTION.search(schema_text)
        ):
            raise GatewayError("SECURITY_POLICY_VIOLATION", "Schema violates input policy.")
    return safe


def protect_value(value: Any, policy: str) -> Any:
    if isinstance(value, str):
        return protect(value, policy)[0]
    if isinstance(value, list):
        return [protect_value(v, policy) for v in value]
    if isinstance(value, dict):
        return {protect(str(k), policy)[0]: protect_value(v, policy) for k, v in value.items()}
    return value


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def fingerprint(request: GenerationRequest, identity: Identity, catalog_version: str) -> str:
    context = [
        identity.tenant_id,
        identity.application_id,
        sorted(identity.scopes),
        sorted(identity.allowed_providers),
        identity.pii_policy,
        str(identity.request_budget),
        catalog_version,
        request.model_dump(mode="json"),
    ]
    return digest(json.dumps(context, sort_keys=True, separators=(",", ":")))
