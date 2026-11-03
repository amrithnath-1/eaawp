# Tool Center API and chart contract

All endpoints: `Authorization: Bearer <jwt>`, administrators only (403 otherwise), tenant from the JWT.

## GET /api/v1/toolhub/registry
```json
{"tools": [{"id": "uuid", "key": "firecrawl_scrape", "name": "firecrawl_scrape", "description": "…",
            "source": "mcp" | "generated", "server": "Firecrawl" | null, "integration_id": "uuid" | null,
            "version": 1, "status": "active" | "removed" | "deactivated" | "rejected",
            "risk_class": "read_only" | "internal_compute" | "internal_modify" | "external_comm" | "financial" | "security_sensitive",
            "policy": "automatic" | "governed" | "approval" | "explicit_approval" | "blocked",
            "roles": ["DIGITAL_MARKETING_MANAGER"], "role_names": ["Digital Marketing Manager"],
            "validation": "discovered" | "active" | "rejected" | "superseded" | "none",
            "updated_at": "iso", "last_seen_at": "iso" | null,
            "metrics": {"total": 12 | null, "success_rate": 0.92 | null, "avg_ms": 840 | null,
                        "degraded": false | null, "last_failure": "iso" | null}}],
 "roles": {"DIGITAL_MARKETING_MANAGER": "Digital Marketing Manager", "…": "…"}}
```

## GET /api/v1/toolhub/executions?status=success|failed|blocked&tool=<key>&limit=100
```json
{"executions": [{"id": "uuid", "tool_key": "…", "tool_label": "…", "source": "builtin|integration|mcp|generated|internet|action|meta",
                 "role": "Digital Marketing Manager", "plan_id": "uuid" | null, "status": "success|failed|blocked",
                 "error_category": "timeout|auth|permission|rate_limit|unavailable|not_found|invalid_args|schema_mismatch|malformed_output|policy_blocked|execution_error" | null,
                 "error": "…" | null, "duration_ms": 120, "retries": 0, "recovery": "…" | null,
                 "input": "short summary", "output": "short summary", "started_at": "iso"}]}
```

## GET /api/v1/toolhub/builder
```json
{"requests": [{"at": "iso", "actor": "…", "need": "…", "role": "…", "decision": "reuse|build", "candidates": ["key"]}],
 "tools": [{"id": "uuid", "key": "gen_page_ctr", "name": "…", "description": "…", "status": "active|deactivated|rejected",
            "current_version": 2, "created_by": "…", "created_at": "iso",
            "versions": [{"version": 1, "status": "active|superseded|rolled_back|rejected", "purpose": "…",
                          "created_at": "iso", "created_by": "…", "code": "python source",
                          "input_schema": {}, "output_schema": {}, "dependencies": ["math"],
                          "attempts": [{"attempt": 1, "passed": false,
                                        "report": [{"check": "security", "passed": false, "detail": "…"}]}]}]}]}
```

## GET /api/v1/toolhub/health
```json
{"servers": [{"integration_id": "uuid", "name": "Firecrawl", "status": "connected|failed|…", "enabled": true,
              "last_checked": "iso" | null, "error": "…" | null, "discoveries": 4, "failed_discoveries": 1,
              "last_discovery": {"at": "iso", "tool_count": 22, "error": null, "duration_ms": 900,
                                 "added": ["x"], "removed": [], "changed": []} | null}],
 "tools": [{"tool_key": "…", "label": "…", "total": 10, "success": 6, "failed": 4, "success_rate": 0.6,
            "avg_ms": 1200, "timeouts": 1, "retries": 2, "degraded": true, "errors": {"timeout": 1},
            "last_success": "iso" | null, "last_failure": "iso" | null, "last_error": "…" | null}],
 "trend": [{"day": "2026-11-01", "success": 10, "failed": 2, "avg_ms": 700}],
 "recoveries": [{"tool_key": "…", "at": "iso", "status": "success", "retries": 1, "recovery": "…", "error_category": "timeout"}]}
```

## GET /api/v1/toolhub/audit?limit=200
```json
{"events": [{"id": "uuid", "at": "iso", "kind": "discovered|schema_changed|removed|generated|validated|rejected|registered|granted|revoked|deactivated|activated|rolled_back|capability_request",
             "actor": "…", "tool_id": "uuid" | null, "detail": "…"}]}
```

## Actions (POST, JSON)
- `/api/v1/toolhub/tools/{id}/grant` `{"role_key": "DATA_INTELLIGENCE_ANALYST"}` → `{"ok": true}` (generated tools)
- `/api/v1/toolhub/tools/{id}/revoke` `{"role_key": "…"}`
- `/api/v1/toolhub/tools/{id}/deactivate`, `/activate`
- `/api/v1/toolhub/tools/{id}/rollback` `{"version": 1}`
- `/api/v1/toolhub/mcp/{integration_id}/refresh` → `{"tool_count": 22, "refreshed": true}`
Errors: 404 not found, 409 not possible in this state, 422 bad input; body `{"detail": "message"}`.

## Charts in chat answers
`POST /api/v1/agent/execute` responses and saved conversation messages carry `charts: ChartSpec[]` (empty when none).
```ts
interface ChartSpec {
  id: string;
  type: "bar" | "line" | "area" | "pie" | "donut" | "scatter" | "kpi" | "table";
  title: string;
  unit: string | null;          // e.g. "%", "clicks"
  x_label: string | null;
  y_label: string | null;
  labels: string[];             // categories or x values (dates for line/area)
  series: { name: string; values: (number | null)[] }[];   // one value per label
  kpis: { label: string; value: number; unit: string | null }[];   // type "kpi" only
  source: string;               // where the data came from, shown under the chart
  note: string | null;
}
```
Scatter: `series[0].values` are x, `series[1].values` are y, `labels` name the points.
Every value comes from tool results of that same answer (verified on the server); the UI never invents or fills data.
