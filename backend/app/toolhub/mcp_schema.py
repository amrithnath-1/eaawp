"""
MCP tool schemas: what the model is shown, and what is checked before anything is sent.

Every MCP server describes each tool's inputs as JSON schema (tools/list → inputSchema). Two things are built from it,
for ANY server (nothing here knows a product):

  function_schema(schema)  a model-safe copy for native function calling: the subset Gemini/OpenAI function
                           declarations accept (type, properties, required, items, enum, description, nullable,
                           min/max…), with $ref/$defs resolved, anyOf/oneOf reduced to one usable branch, and size
                           limits. The model then fills real typed fields instead of writing a JSON string.
  validate(args, schema)   the authoritative server-side check against the FULL schema the server published:
                           required fields, unexpected fields (additionalProperties: false), types (nested objects
                           and arrays), enum/const, numeric ranges, string/array lengths, anyOf/oneOf/allOf.
                           Formats and patterns the checker cannot judge are left to the server.
  describe(schema)         one line per input: name, type, required/optional, allowed values, description.
"""
from __future__ import annotations

import copy
import re
from typing import Any

_TYPES = {"string": str, "boolean": bool, "object": dict, "array": list, "number": (int, float), "integer": int,
          "null": type(None)}
_KEEP = {"type", "description", "properties", "required", "items", "enum", "nullable", "minimum", "maximum",
         "minItems", "maxItems", "minLength", "maxLength", "format", "title", "default"}
MAX_DEPTH = 6
MAX_PROPS = 60


# ── $ref resolution ───────────────────────────────────────────────────────────

def _resolve(node: Any, root: dict, depth: int = 0) -> Any:
    if depth > 20:
        return {}
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/"):
            target: Any = root
            for part in ref[2:].split("/"):
                target = target.get(part, {}) if isinstance(target, dict) else {}
            merged = {**_resolve(target, root, depth + 1), **{k: v for k, v in node.items() if k != "$ref"}}
            return merged
        return {k: _resolve(v, root, depth + 1) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve(v, root, depth + 1) for v in node]
    return node


def resolved(schema: Any) -> dict:
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}
    return _resolve(copy.deepcopy(schema), schema)


# ── Model-safe function schema ────────────────────────────────────────────────

def _types_of(node: dict) -> list[str]:
    t = node.get("type")
    if isinstance(t, list):
        return [x for x in t if isinstance(x, str)]
    return [t] if isinstance(t, str) else []


def _pick_branch(node: dict) -> dict:
    """anyOf/oneOf → the first non-null branch (the full schema is still enforced by validate())."""
    for key in ("anyOf", "oneOf"):
        branches = [b for b in node.get(key) or [] if isinstance(b, dict)]
        if branches:
            non_null = [b for b in branches if _types_of(b) != ["null"]]
            chosen = dict((non_null or branches)[0])
            nullable = len(non_null) < len(branches)
            base = {k: v for k, v in node.items() if k not in ("anyOf", "oneOf")}
            out = {**chosen, **base}
            if nullable:
                out["nullable"] = True
            return out
    if isinstance(node.get("allOf"), list):
        out: dict = {k: v for k, v in node.items() if k != "allOf"}
        for b in node["allOf"]:
            if isinstance(b, dict):
                props = {**(out.get("properties") or {}), **(b.get("properties") or {})}
                out = {**b, **out, "properties": props} if props else {**b, **out}
                out["required"] = sorted(set(out.get("required") or []) | set(b.get("required") or []))
        return out
    return node


def _safe(node: Any, depth: int) -> dict:
    if not isinstance(node, dict):
        return {"type": "string"}
    node = _pick_branch(node)
    types = _types_of(node)
    nullable = "null" in types or bool(node.get("nullable"))
    types = [t for t in types if t != "null"]
    t = types[0] if types else ("object" if "properties" in node else "array" if "items" in node else
                               "string" if "enum" in node and all(isinstance(e, str) for e in node["enum"]) else None)
    if t is None:
        t = "string"
    if "const" in node and "enum" not in node:
        node = {**node, "enum": [node["const"]]}
    out: dict = {"type": t}
    if node.get("description"):
        out["description"] = str(node["description"])[:400]
    if nullable:
        out["nullable"] = True
    if isinstance(node.get("enum"), list) and t in ("string", "integer", "number"):
        vals = [v for v in node["enum"] if isinstance(v, (str, int, float)) and not isinstance(v, bool)][:50]
        if t == "string":
            vals = [str(v) for v in vals]
        if vals:
            out["enum"] = vals
    for k in ("minimum", "maximum", "minItems", "maxItems", "minLength", "maxLength"):
        if isinstance(node.get(k), (int, float)) and not isinstance(node.get(k), bool):
            out[k] = node[k]
    if t == "object":
        props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
        if depth >= MAX_DEPTH:
            out["description"] = (out.get("description", "") + " (JSON object)").strip()
            return out
        out["properties"] = {str(k)[:64]: _safe(v, depth + 1) for k, v in list(props.items())[:MAX_PROPS]}
        req = [r for r in (node.get("required") or []) if isinstance(r, str) and r in out["properties"]]
        if req:
            out["required"] = req
        if not out["properties"]:
            out.pop("properties")
    elif t == "array":
        out["items"] = _safe(node.get("items") or {"type": "string"}, depth + 1)
    return out


def function_schema(schema: Any) -> dict:
    """The tool's input schema in the form native function calling accepts (always an object at the top)."""
    s = _safe(resolved(schema), 0)
    if s.get("type") != "object":
        return {"type": "object", "properties": {"value": s}, "required": ["value"]}
    s.setdefault("properties", {})
    return s


# ── Description of the inputs ─────────────────────────────────────────────────

def describe(schema: Any, limit: int = 14) -> str:
    s = resolved(schema)
    props = s.get("properties") if isinstance(s.get("properties"), dict) else {}
    req = set(s.get("required") or [])
    parts = []
    for name, spec in list(props.items())[:limit]:
        spec = _pick_branch(spec) if isinstance(spec, dict) else {}
        types = "/".join(t for t in _types_of(spec) if t != "null") or ("object" if "properties" in spec else "value")
        extra = ""
        if isinstance(spec.get("enum"), list):
            extra = " one of " + ", ".join(map(str, spec["enum"][:8]))
        desc = str(spec.get("description") or "").strip().split("\n")[0][:90]
        parts.append(f"{name} ({types}, {'REQUIRED' if name in req else 'optional'}{extra})" + (f": {desc}" if desc else ""))
    more = f"; +{len(props) - limit} more optional" if len(props) > limit else ""
    return "; ".join(parts) + more if parts else "no inputs"


def required_of(schema: Any) -> list[str]:
    return [r for r in (resolved(schema).get("required") or []) if isinstance(r, str)]


# ── Validation (authoritative, full schema) ───────────────────────────────────

def _type_ok(v: Any, t: str) -> bool:
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool) or (isinstance(v, float) and v.is_integer())
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    py = _TYPES.get(t)
    return True if py is None else isinstance(v, py) and not (t != "boolean" and isinstance(v, bool) and py is not bool)


def _check(v: Any, node: Any, path: str, out: list[str], depth: int) -> None:
    if not isinstance(node, dict) or depth > 30 or len(out) > 20:
        return
    for key in ("anyOf", "oneOf"):
        branches = [b for b in node.get(key) or [] if isinstance(b, dict)]
        if branches:
            errs_per = []
            for b in branches:
                e: list[str] = []
                _check(v, b, path, e, depth + 1)
                if not e:
                    break
                errs_per.append(e)
            else:
                out.append(f"{path}: matches none of the allowed forms ({errs_per[0][0] if errs_per[0] else ''})")
                return
    for b in node.get("allOf") or []:
        _check(v, b, path, out, depth + 1)
    types = _types_of(node)
    if types and not any(_type_ok(v, t) for t in types):
        out.append(f"{path} should be {'/'.join(types)}, got {type(v).__name__}")
        return
    if "const" in node and v != node["const"]:
        out.append(f"{path} must be {node['const']!r}")
    if isinstance(node.get("enum"), list) and v not in node["enum"]:
        out.append(f"{path} must be one of {', '.join(map(str, node['enum'][:10]))}")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if isinstance(node.get("minimum"), (int, float)) and v < node["minimum"]:
            out.append(f"{path} must be ≥ {node['minimum']}")
        if isinstance(node.get("maximum"), (int, float)) and v > node["maximum"]:
            out.append(f"{path} must be ≤ {node['maximum']}")
    if isinstance(v, str):
        if isinstance(node.get("minLength"), int) and len(v) < node["minLength"]:
            out.append(f"{path} must have at least {node['minLength']} characters")
        if isinstance(node.get("maxLength"), int) and len(v) > node["maxLength"]:
            out.append(f"{path} must have at most {node['maxLength']} characters")
    if isinstance(v, list):
        if isinstance(node.get("minItems"), int) and len(v) < node["minItems"]:
            out.append(f"{path} needs at least {node['minItems']} item(s)")
        if isinstance(node.get("maxItems"), int) and len(v) > node["maxItems"]:
            out.append(f"{path} allows at most {node['maxItems']} item(s)")
        if isinstance(node.get("items"), dict):
            for i, item in enumerate(v[:200]):
                _check(item, node["items"], f"{path}[{i}]", out, depth + 1)
    if isinstance(v, dict):
        props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
        for r in node.get("required") or []:
            if isinstance(r, str) and r not in v:
                out.append(f"{path + '.' if path else ''}{r} is missing (required)")
        for k, item in v.items():
            if k in props:
                _check(item, props[k], f"{path + '.' if path else ''}{k}", out, depth + 1)
            elif node.get("additionalProperties") is False and props:
                out.append(f"{path + '.' if path else ''}{k} is not an input of this tool")
            elif isinstance(node.get("additionalProperties"), dict):
                _check(item, node["additionalProperties"], f"{path + '.' if path else ''}{k}", out, depth + 1)


def validate(args: Any, schema: Any) -> list[str]:
    """Problems with `args` for this schema ([] = valid). Never raises."""
    if not isinstance(args, dict):
        return ["arguments must be a JSON object"]
    s = resolved(schema)
    if not s:
        return []
    out: list[str] = []
    try:
        _check(args, {**s, "type": s.get("type") or "object"}, "", out, 0)
    except Exception as exc:  # noqa: BLE001 - a schema we cannot read is the server's to judge
        return [] if not out else out + [f"(schema could not be fully checked: {type(exc).__name__})"]
    return out


_NAME_OK = re.compile(r"^[A-Za-z0-9_.\-/:]{1,128}$")


def valid_tool_name(name: Any) -> bool:
    """A tool name that can be dispatched: a non-empty string of safe characters (never None/'null'/'undefined')."""
    return (isinstance(name, str) and bool(_NAME_OK.match(name))
            and name.strip().lower() not in ("null", "none", "undefined", "nan", "tool_name"))


def function_name(integration_id: str, tool: str) -> str:
    """The native function name for one MCP tool: mcp_<id8>_<tool>, ≤64 chars, [A-Za-z0-9_]."""
    safe = re.sub(r"[^A-Za-z0-9_]", "_", tool)[:50]
    return f"mcp_{integration_id.replace('-', '')[:8].lower()}_{safe}"
