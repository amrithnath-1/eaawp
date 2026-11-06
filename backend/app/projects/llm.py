"""
Model access for the Project Manager AI employee: Gemini through EAAWP's LLM gateway (Vyuham used Claude directly).

``structured`` asks the configured model for JSON that matches a schema and validates it (required keys, types, enums).
When the gateway is not ready, ``is_configured()`` is False and the callers use Vyuham's labelled rule-based paths, so
nothing pretends to be AI output. Text passed in is always wrapped as untrusted data by the callers.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict

logger = logging.getLogger(__name__)


class LLMUnavailable(Exception):
    """The model could not be used; the message is safe to show."""


def _gateway():
    from app.llm import get_llm_gateway
    return get_llm_gateway()


def is_configured() -> bool:
    try:
        return bool(_gateway().health().is_ready)
    except Exception:  # noqa: BLE001
        return False


def model() -> str:
    try:
        h = _gateway().health()
        return f"{getattr(h, 'provider', 'llm')}:{getattr(h, 'model', '') or 'default'}"
    except Exception:  # noqa: BLE001
        return "llm"


def status() -> Dict:
    ok = is_configured()
    return {"configured": ok, "model": model() if ok else None,
            "setup": None if ok else "The AI model is not configured (GEMINI_API_KEY). Rule-based analysis is used instead."}


def _extract(text: str) -> Any:
    t = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    try:
        return json.loads(t)
    except ValueError:
        start = min([i for i in (t.find("{"), t.find("[")) if i >= 0], default=-1)
        if start < 0:
            raise
        end = max(t.rfind("}"), t.rfind("]"))
        return json.loads(t[start:end + 1])


def _check(value: Any, schema: Dict, path: str = "$") -> list[str]:
    errs: list[str] = []
    t = schema.get("type")
    types = t if isinstance(t, list) else [t] if t else []
    py = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float), "boolean": bool,
          "null": type(None)}
    if types and not any(isinstance(value, py[x]) and not (x in ("integer", "number") and isinstance(value, bool))
                         for x in types if x in py):
        return [f"{path} should be {'/'.join(types)}"]
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path} must be one of {schema['enum']}")
    if isinstance(value, dict):
        for k in schema.get("required", []):
            if k not in value:
                errs.append(f"{path}.{k} is missing")
        for k, sub in (schema.get("properties") or {}).items():
            if k in value:
                errs += _check(value[k], sub, f"{path}.{k}")
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for i, item in enumerate(value[:200]):
            errs += _check(item, schema["items"], f"{path}[{i}]")
    return errs


def _coerce(value: Any, schema: Dict) -> Any:
    """Small, safe repairs models commonly need: numbers sent as strings, integers sent as floats."""
    t = schema.get("type")
    if t == "integer" and isinstance(value, (float, str)):
        try:
            return int(float(value))
        except ValueError:
            return value
    if t == "number" and isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return value
    if isinstance(value, dict):
        props = schema.get("properties") or {}
        return {k: _coerce(v, props[k]) if k in props else v for k, v in value.items()}
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        return [_coerce(v, schema["items"]) for v in value]
    return value


async def structured(feature: str, *, system: str, prompt: str, schema: Dict, max_tokens: int = 16000) -> Dict:
    """JSON from the model that matches ``schema`` (one correction attempt). Raises LLMUnavailable otherwise."""
    from langchain_core.messages import HumanMessage, SystemMessage
    if not is_configured():
        raise LLMUnavailable("The AI model is not configured.")
    try:
        chat = _gateway().get_chat_model(temperature=0)
    except Exception as exc:  # noqa: BLE001
        raise LLMUnavailable(f"The AI model could not be used: {type(exc).__name__}") from exc
    ask = (f"{prompt}\n\nRespond with ONLY one JSON value that matches this JSON schema (no prose, no code fences):\n"
           f"{json.dumps(schema)[:12000]}")
    messages = [SystemMessage(content=system), HumanMessage(content=ask)]
    last = ""
    for attempt in range(2):
        try:
            resp = await chat.ainvoke(messages)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Project Manager model call failed (%s): %s", feature, type(exc).__name__)
            raise LLMUnavailable("The AI model request failed. Please try again shortly.") from exc
        content = resp.content if isinstance(resp.content, str) else "".join(
            p.get("text", "") if isinstance(p, dict) else str(p) for p in (resp.content or []))
        try:
            value = _coerce(_extract(content), schema)
        except ValueError:
            last = "the reply was not valid JSON"
        else:
            problems = _check(value, schema)
            if not problems:
                return value
            last = "; ".join(problems[:6])
        messages += [HumanMessage(content=f"That reply did not match the schema ({last}). Send the corrected JSON only.")]
    raise LLMUnavailable(f"The AI model returned data that could not be used ({last}).")
