"""
Deterministic analysis engine. The language model may only choose the parameters of a SPEC; this
module validates the spec against the dataset's real schema and computes every number itself.
No code, SQL or expressions from the model or the user are ever executed.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from statistics import mean, median, pstdev

from app.services.dataset_service import load_table

MAX_RESULT_ROWS = 200
MAX_GROUPS = 2
OPS = {"describe", "aggregate", "timeseries", "value_counts", "correlation", "preview"}
AGGS = {"sum", "mean", "min", "max", "count", "median", "nunique"}
FILTER_OPS = {"=", "!=", ">", ">=", "<", "<=", "contains", "in"}
INTERVALS = {"day", "week", "month", "year"}
CHARTS = {"bar", "line", "pie", "scatter", "none"}
_ALLOWED_KEYS = {"op", "filters", "group_by", "metrics", "date_column", "interval", "column", "columns",
                 "sort_by", "descending", "limit", "chart"}


class SpecError(ValueError):
    """The requested analysis is not valid for this dataset; the message is safe to show."""


def _col(cols: dict[str, dict], name, want: set[str] | None = None) -> dict:
    if not isinstance(name, str) or name not in cols:
        raise SpecError(f"There is no column named '{str(name)[:60]}'. Columns: {', '.join(list(cols)[:30])}.")
    if want and cols[name]["type"] not in want:
        raise SpecError(f"Column '{name}' is {cols[name]['type']}, which this analysis cannot use (needs {' or '.join(sorted(want))}).")
    return cols[name]


def validate_spec(spec: dict, columns: list[dict]) -> dict:
    """Return a normalised copy of the spec or raise SpecError."""
    if not isinstance(spec, dict):
        raise SpecError("The analysis request is not valid.")
    unknown = set(spec) - _ALLOWED_KEYS
    if unknown:
        raise SpecError("Unsupported options: " + ", ".join(sorted(map(str, unknown))[:5]))
    cols = {c["name"]: c for c in columns}
    op = spec.get("op")
    if op not in OPS:
        raise SpecError(f"Unsupported analysis '{str(op)[:30]}'. Supported: {', '.join(sorted(OPS))}.")
    out: dict = {"op": op}

    filters = []
    for f in (spec.get("filters") or [])[:8]:
        if not isinstance(f, dict) or f.get("op") not in FILTER_OPS:
            raise SpecError("A filter is not valid.")
        c = _col(cols, f.get("column"))
        val = f.get("value")
        if f["op"] == "in":
            if not isinstance(val, list) or not val or len(val) > 50:
                raise SpecError("An 'in' filter needs a list of values.")
        elif isinstance(val, (list, dict)) or val is None:
            raise SpecError("A filter value must be a single value.")
        if f["op"] in (">", ">=", "<", "<=") and c["type"] == "text":
            raise SpecError(f"Column '{c['name']}' is text; use =, !=, contains or in.")
        filters.append({"column": c["name"], "op": f["op"], "value": val})
    out["filters"] = filters

    limit = spec.get("limit", 20)
    out["limit"] = max(1, min(int(limit) if isinstance(limit, (int, float)) else 20, MAX_RESULT_ROWS))
    out["descending"] = bool(spec.get("descending", True))
    chart = spec.get("chart") or {}
    ctype = chart.get("type", "none") if isinstance(chart, dict) else "none"
    if ctype not in CHARTS:
        raise SpecError("Unsupported chart type.")
    out["chart"] = {"type": ctype}

    if op == "preview":
        out["columns"] = [(_col(cols, c))["name"] for c in (spec.get("columns") or list(cols))[:20]]
    elif op == "describe":
        out["columns"] = [(_col(cols, c))["name"] for c in (spec.get("columns") or list(cols))[:30]]
    elif op == "value_counts":
        out["column"] = _col(cols, spec.get("column"))["name"]
    elif op == "correlation":
        pair = spec.get("columns")
        if not isinstance(pair, list) or len(pair) != 2:
            raise SpecError("Correlation needs exactly two numeric columns.")
        out["columns"] = [_col(cols, c, {"number"})["name"] for c in pair]
    else:                                                     # aggregate / timeseries
        metrics = []
        raw_metrics = spec.get("metrics") or []
        if not isinstance(raw_metrics, list) or len(raw_metrics) > 4:
            raise SpecError("Use at most 4 metrics per analysis.")
        for m in raw_metrics:
            if not isinstance(m, dict) or m.get("agg") not in AGGS:
                raise SpecError(f"A metric needs an aggregation: {', '.join(sorted(AGGS))}.")
            if m["agg"] == "count" and not m.get("column"):
                metrics.append({"agg": "count", "column": None})
                continue
            want = None if m["agg"] in ("count", "nunique") else {"number"}
            metrics.append({"agg": m["agg"], "column": _col(cols, m.get("column"), want)["name"]})
        if not metrics:
            raise SpecError("Say what to calculate (for example total of a column, or a count).")
        out["metrics"] = metrics
        if op == "aggregate":
            gb = spec.get("group_by") or []
            if not isinstance(gb, list) or len(gb) > MAX_GROUPS:
                raise SpecError(f"Group by at most {MAX_GROUPS} columns.")
            out["group_by"] = [_col(cols, g)["name"] for g in gb]
        else:
            out["date_column"] = _col(cols, spec.get("date_column"), {"date"})["name"]
            iv = spec.get("interval", "month")
            if iv not in INTERVALS:
                raise SpecError(f"Interval must be one of {', '.join(sorted(INTERVALS))}.")
            out["interval"] = iv
        sb = spec.get("sort_by")
        if sb is not None:
            labels = {_metric_label(m) for m in metrics} | set(out.get("group_by", [])) | {out.get("date_column")}
            if sb not in labels:
                raise SpecError(f"Cannot sort by '{str(sb)[:40]}'. Options: {', '.join(sorted(x for x in labels if x))}.")
            out["sort_by"] = sb
    for k in ("x", "y"):
        if isinstance(chart, dict) and isinstance(chart.get(k), str):
            out["chart"][k] = chart[k][:60]
    return out


def _metric_label(m: dict) -> str:
    return "count" if m["agg"] == "count" and not m["column"] else f"{m['agg']}({m['column']})"


def _match(row: dict, f: dict, ctype: str) -> bool:
    v, op, ref = row.get(f["column"]), f["op"], f["value"]
    if ctype == "number":
        conv = lambda x: float(x) if isinstance(x, (int, float)) or (isinstance(x, str) and re.fullmatch(r"-?\d+(\.\d+)?", x.strip())) else None
    elif ctype == "date":
        from app.services.dataset_service import parse_date
        conv = lambda x: parse_date(str(x))
    else:
        conv = lambda x: str(x)
    if op == "in":
        refs = [conv(x) for x in ref]
        return v is not None and v in refs
    r = conv(ref)
    if v is None or v == "" or r is None:
        return False
    if op == "=":
        return v == r if ctype != "text" else str(v).lower() == str(r).lower()
    if op == "!=":
        return v != r if ctype != "text" else str(v).lower() != str(r).lower()
    if op == "contains":
        return str(r).lower() in str(v).lower()
    return {">": v > r, ">=": v >= r, "<": v < r, "<=": v <= r}[op]


def _agg(values: list, agg: str):
    if agg == "count":
        return len(values)
    if agg == "nunique":
        return len(set(values))
    nums = [v for v in values if isinstance(v, float)]
    if not nums:
        return None
    return {"sum": sum, "mean": mean, "min": min, "max": max, "median": median}[agg](nums)


def _r(v):
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        return round(v, 4)
    if isinstance(v, date):
        return v.isoformat()
    return v


def _bucket(d: date, interval: str) -> date:
    if interval == "day":
        return d
    if interval == "week":
        return d - timedelta(days=d.weekday())
    if interval == "month":
        return d.replace(day=1)
    return d.replace(month=1, day=1)


def run(spec: dict, columns: list[dict], content_csv: str, dataset_name: str) -> dict:
    """Validate and compute. Returns {columns, rows, chart, source, spec, ...}."""
    spec = validate_spec(spec, columns)
    cols = {c["name"]: c for c in columns}
    table = load_table(content_csv, columns)
    total = len(table)
    for f in spec["filters"]:
        table = [r for r in table if _match(r, f, cols[f["column"]]["type"])]
    n = len(table)
    op = spec["op"]
    notes: list[str] = []
    chart = dict(spec["chart"])

    if op == "preview":
        names = spec["columns"]
        rows = [[_r(r[c]) for c in names] for r in table[: spec["limit"]]]
        out_cols = names
    elif op == "describe":
        out_cols = ["column", "type", "count", "distinct", "mean", "median", "min", "max", "std"]
        rows = []
        for name in spec["columns"]:
            c = cols[name]
            vals = [r[name] for r in table if r[name] not in (None, "")]
            if c["type"] == "number" and vals:
                rows.append([name, "number", len(vals), len(set(vals)), _r(mean(vals)), _r(median(vals)), _r(min(vals)), _r(max(vals)), _r(pstdev(vals))])
            elif c["type"] == "date" and vals:
                rows.append([name, "date", len(vals), len(set(vals)), None, None, _r(min(vals)), _r(max(vals)), None])
            else:
                rows.append([name, c["type"], len(vals), len(set(vals)), None, None, None, None, None])
    elif op == "value_counts":
        name = spec["column"]
        counts = Counter(r[name] for r in table if r[name] not in (None, ""))
        items = counts.most_common(spec["limit"])
        out_cols, rows = [name, "count"], [[_r(k), v] for k, v in items]
        chart.setdefault("type", "bar")
        if chart["type"] == "none":
            chart["type"] = "bar"
        chart.update(x=name, y="count")
    elif op == "correlation":
        a, b = spec["columns"]
        pairs = [(r[a], r[b]) for r in table if isinstance(r[a], float) and isinstance(r[b], float)]
        if len(pairs) < 3:
            raise SpecError("Not enough rows with both values to compute a correlation (need at least 3).")
        xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
        mx, my = mean(xs), mean(ys)
        sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
        sy = math.sqrt(sum((y - my) ** 2 for y in ys))
        if sx == 0 or sy == 0:
            raise SpecError("One of the columns does not vary, so a correlation is undefined.")
        r_val = sum((x - mx) * (y - my) for x, y in pairs) / (sx * sy)
        out_cols, rows = ["column_a", "column_b", "pearson_r", "rows_used"], [[a, b, _r(r_val), len(pairs)]]
        notes.append("Correlation measures association, not cause.")
    else:
        metrics = spec["metrics"]
        labels = [_metric_label(m) for m in metrics]
        groups: dict[tuple, list[dict]] = defaultdict(list)
        if op == "aggregate":
            keys = spec["group_by"]
            for r in table:
                groups[tuple(r[k] for k in keys)].append(r)
            if not keys:
                groups[()] = table
            key_cols = keys
        else:
            dc = spec["date_column"]
            for r in table:
                if r[dc] is not None:
                    groups[(_bucket(r[dc], spec["interval"]),)].append(r)
            key_cols = [dc]
        out_cols = key_cols + labels
        rows = []
        for k, grp in groups.items():
            vals = [_agg([g[m["column"]] for g in grp if m["column"] and g[m["column"]] not in (None, "")] if m["column"] else grp, m["agg"]) for m in metrics]
            rows.append([_r(x) for x in k] + [_r(v) for v in vals])
        sort_key = spec.get("sort_by") or (key_cols[0] if op == "timeseries" else labels[0])
        si = out_cols.index(sort_key)
        rows.sort(key=lambda r: (r[si] is None, r[si]), reverse=spec["descending"] and op != "timeseries")
        if op == "timeseries":
            rows.sort(key=lambda r: r[0])
        if len(rows) > spec["limit"]:
            notes.append(f"Showing the first {spec['limit']} of {len(rows)} rows.")
            rows = rows[: spec["limit"]]
        if chart["type"] == "none" and op == "timeseries":
            chart["type"] = "line"
        if chart["type"] == "none" and op == "aggregate" and key_cols and len(rows) <= 30:
            chart["type"] = "bar"
        chart.setdefault("x", key_cols[0] if key_cols else labels[0])
        chart.setdefault("y", labels[0])
        if chart["x"] not in out_cols:
            chart["x"] = out_cols[0]
        if chart["y"] not in out_cols:
            chart["y"] = labels[0]

    filt = f" after {len(spec['filters'])} filter(s)" if spec["filters"] else ""
    source = f"Computed from dataset '{dataset_name}': {total:,} rows{filt and f', {n:,} rows' + filt}."
    return {"columns": out_cols, "rows": rows, "row_count": len(rows), "chart": chart if chart.get("type", "none") != "none" else {"type": "none"},
            "source": source, "notes": notes, "spec": spec}
