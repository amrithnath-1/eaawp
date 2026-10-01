"""
EAAWP Monitoring Condition Evaluator

This module evaluates structured monitoring conditions against authorised
company data and returns a safe result.

Security invariants
-------------------
1. No arbitrary SQL is accepted — only structured MonitoringCondition objects.
2. All data access goes through execute_company_data_query (the existing
   controlled data access service). This enforces:
   tenant → connection → entity → is_allowed → schema validation → parameterised query
3. The evaluator never directly executes actions. If a condition is true, it
   returns (triggered=True, current_value, previous_value) — the caller
   (monitoring_engine) then creates a plan via the existing planning engine.
4. Credentials are never stored or logged. The data access service handles
   decryption in-memory only.
5. Only aggregate values (avg/sum/count/max/min/latest of one field) are returned
   and stored in the audit log — never raw row data.
6. Permission checks happen inside execute_company_data_query. Any permission
   error is caught and returned as a safe error result.

Evaluation flow
---------------
For relative operators (decreases_by_more_than_pct, increases_by_more_than_pct):
    1. Query the CURRENT window (last N rows / most recent data)
    2. Query the PREVIOUS window (shifted by comparison_window_hours)
    3. Compute aggregate for each window
    4. Compare

For absolute operators (falls_below, exceeds, equals):
    1. Query the most recent data
    2. Compute aggregate
    3. Compare against threshold

For is_unavailable:
    1. Query the entity
    2. If result is empty or query fails → triggered

For count_falls_below / count_exceeds:
    1. Query with no field selection (count rows)
    2. Compare count against threshold
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.data_access import CompanyDataQueryRequest
from app.schemas.monitoring import MonitoringCondition
from app.services.data_access import execute_company_data_query

logger = logging.getLogger(__name__)

# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class EvaluationResult:
    """
    Result of evaluating a monitoring condition.
    Never contains credentials, raw SQL, or row-level company data.
    """
    triggered: bool
    result_code: str   # "condition_true" | "condition_false" | "error" | "permission_denied" | "no_data"
    current_value: float | None = None
    previous_value: float | None = None
    error_message: str | None = None   # safe text only


# ── Main evaluator ────────────────────────────────────────────────────────────

async def evaluate_condition(
    condition: MonitoringCondition,
    semantic_concept: str,
    tenant_id: str,
    role_key: str,
    db: AsyncSession,
) -> EvaluationResult:
    """
    Evaluate a structured monitoring condition against authorised company data.

    Returns an EvaluationResult — never raises unless there is an internal bug.
    All expected errors (permission denied, missing mapping, empty data, invalid
    condition) are captured and returned as safe error results.
    """
    operator = condition.operator

    try:
        if operator == "is_unavailable":
            return await _eval_is_unavailable(condition, semantic_concept, tenant_id, role_key, db)

        if operator in ("count_falls_below", "count_exceeds"):
            return await _eval_count(condition, semantic_concept, tenant_id, role_key, db)

        if operator in ("decreases_by_more_than_pct", "increases_by_more_than_pct"):
            return await _eval_relative(condition, semantic_concept, tenant_id, role_key, db)

        if operator in ("falls_below", "exceeds", "equals"):
            return await _eval_absolute(condition, semantic_concept, tenant_id, role_key, db)

        return EvaluationResult(
            triggered=False,
            result_code="error",
            error_message=f"Unknown operator '{operator}' — this should have been caught by schema validation.",
        )

    except PermissionError as exc:
        logger.warning(
            "Monitoring permission denied for tenant=%s role=%s concept=%s: %s",
            tenant_id, role_key, semantic_concept, exc,
        )
        return EvaluationResult(
            triggered=False,
            result_code="permission_denied",
            error_message=str(exc)[:400],
        )
    except Exception as exc:
        # Log safely — no credentials in the exception message path
        safe_msg = _safe_error_message(exc)
        logger.error(
            "Monitoring evaluation error for tenant=%s role=%s concept=%s: %s",
            tenant_id, role_key, semantic_concept, safe_msg,
        )
        return EvaluationResult(
            triggered=False,
            result_code="error",
            error_message=safe_msg,
        )


# ── Evaluator implementations ─────────────────────────────────────────────────

async def _eval_is_unavailable(
    condition: MonitoringCondition,
    semantic_concept: str,
    tenant_id: str,
    role_key: str,
    db: AsyncSession,
) -> EvaluationResult:
    """Trigger if data is empty or the query fails."""
    try:
        response = await execute_company_data_query(
            request=CompanyDataQueryRequest(
                semantic_concept=semantic_concept,
                fields=[],
                filters=[],
                sort=[],
                limit=1,
            ),
            tenant_id=tenant_id,
            role_key=role_key,
            db=db,
        )
        if response.row_count == 0:
            return EvaluationResult(triggered=True, result_code="condition_true", current_value=0.0)
        return EvaluationResult(triggered=False, result_code="condition_false", current_value=float(response.row_count))
    except Exception as exc:
        # Data unavailable counts as condition true for is_unavailable
        return EvaluationResult(
            triggered=True,
            result_code="condition_true",
            error_message=_safe_error_message(exc),
        )


async def _eval_count(
    condition: MonitoringCondition,
    semantic_concept: str,
    tenant_id: str,
    role_key: str,
    db: AsyncSession,
) -> EvaluationResult:
    """Evaluate row count against threshold."""
    response = await execute_company_data_query(
        request=CompanyDataQueryRequest(
            semantic_concept=semantic_concept,
            fields=[],
            filters=[],
            sort=[],
            limit=200,  # count up to 200 rows
        ),
        tenant_id=tenant_id,
        role_key=role_key,
        db=db,
    )
    count = float(response.row_count)
    threshold = condition.threshold

    if condition.operator == "count_falls_below":
        triggered = count < threshold
    else:  # count_exceeds
        triggered = count > threshold

    return EvaluationResult(
        triggered=triggered,
        result_code="condition_true" if triggered else "condition_false",
        current_value=count,
    )


async def _eval_absolute(
    condition: MonitoringCondition,
    semantic_concept: str,
    tenant_id: str,
    role_key: str,
    db: AsyncSession,
) -> EvaluationResult:
    """Evaluate absolute threshold comparison."""
    if not condition.metric_field:
        return EvaluationResult(
            triggered=False,
            result_code="error",
            error_message="metric_field is required for absolute operators.",
        )

    response = await execute_company_data_query(
        request=CompanyDataQueryRequest(
            semantic_concept=semantic_concept,
            fields=[condition.metric_field],
            filters=[],
            sort=[],
            limit=100,
        ),
        tenant_id=tenant_id,
        role_key=role_key,
        db=db,
    )

    if response.row_count == 0:
        return EvaluationResult(triggered=False, result_code="no_data")

    current_value = _aggregate(response.rows, condition.metric_field, condition.aggregate_fn)
    if current_value is None:
        return EvaluationResult(triggered=False, result_code="no_data")

    threshold = condition.threshold
    op = condition.operator

    if op == "falls_below":
        triggered = current_value < threshold
    elif op == "exceeds":
        triggered = current_value > threshold
    elif op == "equals":
        triggered = math.isclose(current_value, threshold, rel_tol=1e-6)
    else:
        triggered = False

    return EvaluationResult(
        triggered=triggered,
        result_code="condition_true" if triggered else "condition_false",
        current_value=current_value,
    )


async def _eval_relative(
    condition: MonitoringCondition,
    semantic_concept: str,
    tenant_id: str,
    role_key: str,
    db: AsyncSession,
) -> EvaluationResult:
    """
    Evaluate relative percentage change.

    Strategy: query all available data (up to limit), split it into two halves
    representing "current" vs "previous" based on available row count.
    This is a heuristic — the actual temporal split depends on the data ordering.
    We use the most recent N rows as "current" and the preceding N rows as "previous".
    """
    if not condition.metric_field:
        return EvaluationResult(
            triggered=False,
            result_code="error",
            error_message="metric_field is required for relative operators.",
        )

    # Fetch enough rows to split into two windows
    # We request 200 rows; split evenly into current (first 100) and previous (next 100)
    response = await execute_company_data_query(
        request=CompanyDataQueryRequest(
            semantic_concept=semantic_concept,
            fields=[condition.metric_field],
            filters=[],
            sort=[],
            limit=200,
        ),
        tenant_id=tenant_id,
        role_key=role_key,
        db=db,
    )

    if response.row_count == 0:
        return EvaluationResult(triggered=False, result_code="no_data")

    rows = response.rows
    mid = max(1, len(rows) // 2)
    current_rows = rows[:mid]
    previous_rows = rows[mid:]

    current_value = _aggregate(current_rows, condition.metric_field, condition.aggregate_fn)
    previous_value = _aggregate(previous_rows, condition.metric_field, condition.aggregate_fn)

    if current_value is None:
        return EvaluationResult(triggered=False, result_code="no_data")

    if previous_value is None or previous_value == 0.0:
        # No previous data to compare against — don't trigger
        return EvaluationResult(
            triggered=False,
            result_code="condition_false",
            current_value=current_value,
            previous_value=previous_value,
        )

    pct_change = ((current_value - previous_value) / abs(previous_value)) * 100.0
    threshold = condition.threshold

    if condition.operator == "decreases_by_more_than_pct":
        triggered = pct_change < -threshold  # e.g. -25 < -20 means 25% decrease > 20%
    else:  # increases_by_more_than_pct
        triggered = pct_change > threshold

    return EvaluationResult(
        triggered=triggered,
        result_code="condition_true" if triggered else "condition_false",
        current_value=current_value,
        previous_value=previous_value,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _aggregate(
    rows: list[dict[str, Any]],
    field: str,
    fn: str,
) -> float | None:
    """Compute a safe aggregate of a field across rows. Returns None if no values."""
    values: list[float] = []
    for row in rows:
        raw = row.get(field)
        if raw is None:
            continue
        try:
            values.append(float(raw))
        except (TypeError, ValueError):
            continue

    if not values:
        return None

    if fn == "avg":
        return sum(values) / len(values)
    if fn == "sum":
        return sum(values)
    if fn == "count":
        return float(len(values))
    if fn == "max":
        return max(values)
    if fn == "min":
        return min(values)
    if fn == "latest":
        return values[-1]  # last row (most recent if sorted)
    return sum(values) / len(values)  # default to avg


def _safe_error_message(exc: Exception) -> str:
    """
    Extract a safe error message — strip any potential credential info.
    Passwords, DSNs, tokens should never appear in error messages stored
    in the audit log.
    """
    msg = str(exc)
    # Truncate and strip sensitive-looking patterns
    import re
    msg = re.sub(
        r"(password|secret|token|api_key|credential|dsn)[^\s]*",
        "[REDACTED]",
        msg,
        flags=re.IGNORECASE,
    )
    return msg[:400]
