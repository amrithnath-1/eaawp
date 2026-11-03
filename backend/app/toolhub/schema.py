"""
A small JSON-schema validator for tool schemas (the subset MCP and generated tools use): type, properties, required,
items, enum, minimum/maximum, minLength/maxLength, maxItems, additionalProperties: false, anyOf/oneOf.
"""
from __future__ import annotations

from typing import Any

_TYPES = {
    "object": dict, "array": list, "string": str, "boolean": bool, "null": type(None),
    "number": (int, float), "integer": int,
}
SUPPORTED = {"type", "properties", "required", "items", "enum", "minimum", "maximum", "minLength", "maxLength",
             "maxItems", "minItems", "additionalProperties", "anyOf", "oneOf", "description", "title", "default",
             "format", "$schema", "examples"}


def check_schema(schema: Any, path: str = "schema") -> list[str]:
    """Problems with the schema itself (structure, unknown types)."""
    if not isinstance(schema, dict):
        return [f"{path} must be an object"]
    errs: list[str] = []
    t = schema.get("type")
    for one in (t if isinstance(t, list) else [t] if t else []):
        if one not in _TYPES:
            errs.append(f"{path}.type '{one}' is not a JSON type")
    props = schema.get("properties", {})
    if not isinstance(props, dict):
        errs.append(f"{path}.properties must be an object")
    else:
        for k, v in props.items():
            errs += check_schema(v, f"{path}.properties.{k}")
    req = schema.get("required", [])
    if not isinstance(req, list) or not all(isinstance(r, str) for r in req):
        errs.append(f"{path}.required must be a list of names")
    if "items" in schema:
        errs += check_schema(schema["items"], f"{path}.items")
    for key in ("anyOf", "oneOf"):
        for i, sub in enumerate(schema.get(key, []) or []):
            errs += check_schema(sub, f"{path}.{key}[{i}]")
    return errs


def validate(value: Any, schema: dict, path: str = "$") -> list[str]:
    """Problems with `value` against `schema` (empty list = valid)."""
    if not isinstance(schema, dict) or not schema:
        return []
    for key in ("anyOf", "oneOf"):
        if schema.get(key):
            if not any(not validate(value, s, path) for s in schema[key]):
                return [f"{path} matches none of the allowed shapes"]
    errs: list[str] = []
    t = schema.get("type")
    if t:
        types = t if isinstance(t, list) else [t]
        ok = False
        for one in types:
            py = _TYPES.get(one)
            if py is None:
                continue
            if one in ("number", "integer") and isinstance(value, bool):
                continue
            if isinstance(value, py) and not (one == "integer" and isinstance(value, float) and not value.is_integer()):
                ok = True
        if not ok:
            return [f"{path} should be {'/'.join(types)}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path} must be one of {schema['enum'][:10]}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append(f"{path} must be ≥ {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errs.append(f"{path} must be ≤ {schema['maximum']}")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errs.append(f"{path} is too short")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errs.append(f"{path} is too long")
    if isinstance(value, list):
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errs.append(f"{path} has too many items")
        if "minItems" in schema and len(value) < schema["minItems"]:
            errs.append(f"{path} has too few items")
        if isinstance(schema.get("items"), dict):
            for i, item in enumerate(value[:1000]):
                errs += validate(item, schema["items"], f"{path}[{i}]")
    if isinstance(value, dict):
        props = schema.get("properties") or {}
        for r in schema.get("required") or []:
            if r not in value:
                errs.append(f"{path}.{r} is required")
        for k, v in value.items():
            if k in props:
                errs += validate(v, props[k], f"{path}.{k}")
            elif schema.get("additionalProperties") is False:
                errs.append(f"{path}.{k} is not an allowed field")
    return errs[:20]
