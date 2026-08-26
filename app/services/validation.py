import json
from typing import Any

from jsonschema import Draft202012Validator, SchemaError, ValidationError

from app.core.errors import GatewayError, ProviderError

# Deliberately small JSON Schema subset: no regex, remote refs or recursive schemas.
ALLOWED = {
    "type",
    "properties",
    "required",
    "additionalProperties",
    "items",
    "enum",
    "const",
    "minimum",
    "maximum",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "description",
    "title",
}


def validate_schema(schema: dict[str, Any], depth: int = 0) -> None:
    if depth > 8 or set(schema) - ALLOWED:
        raise GatewayError("INVALID_REQUEST", "Unsupported or overly complex response schema.", 422)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise GatewayError("INVALID_REQUEST", "Response schema is invalid.", 422) from exc
    for child in schema.get("properties", {}).values():
        if not isinstance(child, dict):
            raise GatewayError("INVALID_REQUEST", "Schema nodes must be objects.", 422)
        validate_schema(child, depth + 1)
    for key in ("items", "additionalProperties"):
        if isinstance(schema.get(key), dict):
            validate_schema(schema[key], depth + 1)


def parse_output(content: str, schema: dict[str, Any] | None, json_mode: bool) -> Any:
    if schema is None and not json_mode:
        return content
    try:
        value = json.loads(content, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if schema is not None:
            Draft202012Validator(schema).validate(value)
        return value
    except (ValueError, ValidationError, RecursionError) as exc:
        raise ProviderError("INVALID_MODEL_RESPONSE") from exc
