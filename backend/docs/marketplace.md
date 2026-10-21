# Marketplace and module activation (Phase L, part 1)

A **module** is a packaged AI employee role. Catalog (code: `app/services/modules.py`): 4 available (Digital Marketing Manager, Data Analyst, Institutional Clerk, Medical Assistant) and 5 "coming soon" (SEO Specialist, HR Manager, Cybersecurity Analyst, Financial Advisor, Project Manager; cannot be activated).

## Behaviour
- `GET /api/v1/modules` (any member): catalog plus whether each module is active for the caller's company.
- `POST /api/v1/modules/{key}/activate|deactivate` (company admins): idempotent; coming-soon -> 409, unknown -> 404; each real change is audit-logged (department `marketplace`).
- Table `module_activations(tenant_id, module_key, active, changed_by, changed_at)`, unique per company+module. **No row = catalog default**, and every available module defaults to ON, so existing companies lose nothing. A later billing step can flip a module's default to OFF without touching enforcement.
- Deactivating blocks use; it never deletes data. Re-activating restores access.

## Enforcement (403 with a message pointing to the Marketplace)
- Whole `/api/v1/clerk/*` and `/api/v1/clinic/*` routers (`require_module(...)` router dependency).
- `POST /api/v1/agent/execute` for the four catalog role keys. Custom roles made in the Employee Builder are not module-gated.
- Not gated: `X-Role-Key` on `/data/query` (an audit label only), marketing/analytics routes that have no module-specific router yet (execution is gated).

## Verification
`tests/test_marketplace.py` (9): catalog defaults, admin-only, idempotent + audited, tenant isolation, route and agent enforcement, 8 deliberate breakages caught. UI: `/marketplace` page. NOT built yet: billing/plans, per-user entitlements, usage limits.
