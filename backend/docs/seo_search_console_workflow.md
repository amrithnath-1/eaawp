# SEO workflow: Digital Marketing Manager -> Google Search Console

Same architecture as the GA4 workflow (`dmm_analytics_workflow.md`); nothing was duplicated.

## Request path
1. A DMM request such as *"What were our top search queries in Search Console over the last 28
   days? Show clicks, impressions, CTR and average position."*
2. **Readiness gate** (`services/task_readiness.py`, `first_unmet`): explicit "Search Console/GSC",
   or search-only vocabulary (search impressions, average position, top queries/pages, organic
   clicks...). Bare "clicks", "impressions" or "CTR" do **not** trigger it (ads/email use them).
   Checked in order: OAuth client -> Google authorisation -> role grant for
   `get_search_analytics` -> **property selected**.
3. Anything missing -> request saved as a pending task, truthful reply, admin guided:
   `CONFIGURATION_REQUIRED` -> `REDIRECT_TO_OAUTH` -> `GRANT_REQUIRED` (read-only, LOW risk only)
   -> `SELECT_PROPERTY`. Members are told to ask an admin (`ADMIN_REQUIRED`).
4. **Property selection**: the connected account's verified properties are listed live
   (`siteUnverifiedUser` excluded). Exactly one -> selected automatically; several -> an admin
   chooses (`POST /agent/pending-tasks/{id}/select-property`, admin only, audited). The choice
   is accepted only if it is in the freshly listed set, so a forged value is rejected. It is
   stored in `Integration.account_info_json.default_property` and survives re-testing the
   connection. The Integration Manager fills it in when the plan names no `site_url`.
5. `resume` re-checks readiness and runs the original request text.
6. **Execution**: planner (told today's date, UTC) -> dynamic tool -> manager (tenant, status,
   role grant, decrypt in memory) -> provider -> audit row.
7. **Verification**: failed calls give a plain reason with no figures. Every number (clicks,
   impressions, CTR, position, dates) in the model's answer is checked against returned data; an
   unsupported answer is replaced by the raw returned rows. Code computes total clicks/impressions
   and overall CTR (clicks / impressions), lists the dates present for `date` queries, and appends
   `Data source: Google Search Console (property ..., start to end; 2-3 day delay)`.

## Provider changes
* `start_date`/`end_date` accept `YYYY-MM-DD`, `today`, `yesterday`, `NdaysAgo`; defaults
  28 days ago -> 3 days ago (Search Console lags 2-3 days).
* `site_url` optional, validated (`sc-domain:` or http(s)); Google decides if the account may
  read it (403 -> readable message).
* Rows carry named columns (`query`, `page`, ...) plus the original `dimensions` list.
* Empty result (no `rows`) is a valid "no data" answer, not an error.
* Google client is built in a worker thread (it was blocking the event loop).
* Errors are mapped (401 reconnect, 403 no access / API disabled, 404, 429) and any stored
  credential value echoed by an upstream error is redacted.
* Fixed: `_should_refresh_token` referenced `timezone` without importing it.

## Status of each part (be precise)
| Part | Status |
|---|---|
| Gate, pending/resume, property selection, grants, tenancy, audit, grounding | Implemented and tested (`tests/test_search_console_seo_e2e.py`) |
| Provider request/response handling | Implemented; tested against a **fake** Google client |
| LLM planning / summarising | **Faked** in tests (scripted model) |
| Real Google Search Console API, real OAuth consent | **Not live-verified** |

Live verification needs a Google Cloud project with the *Search Console API* enabled, an OAuth
client (Web application) with this deployment's redirect URI, and a Google account that owns or
has full access to a Search Console property. Enter the client ID/secret only in the admin
form; never in chat or logs.

## Known limits
* Detection is keyword based; unusual phrasing is not gated (the planner then has no
  Search Console data and must say so).
* No dimension filters (queries containing X, a country, etc.) yet - rows are unfiltered.
* Totals are over the rows returned, not the site total, when a dimension is requested; the
  output says "across the N rows above".
