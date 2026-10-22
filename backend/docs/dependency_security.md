# Dependency security review (Phase M)

Scanned with `pip-audit` (backend) and `npm audit` (front end) on 2026-10-21. Re-run both before every release:
```
cd backend && python -m pip install pip-audit && python -m pip_audit -r requirements.txt
npm audit --omit=dev
```

## Fixed
| Package | From -> to | Why it matters here |
|---|---|---|
| fastapi / starlette | 0.115.6 / 0.41.3 -> 0.124.4 / 0.50.0 | 14 Starlette advisories (request parsing, file responses) on the public API surface. No Starlette advisory remains at 0.50.0. |
| python-multipart | 0.0.20 -> 0.0.32 | 12 advisories; parses every file upload (documents, datasets). |
| pypdf | 5.1.0 -> 6.21.2 | 90 advisories; parses untrusted PDFs (knowledge base, clerk). |
| python-jose | 3.3.0 -> 3.5.0 | JWT library used for sign-in tokens (6 advisories fixed). |
| cryptography | 43.0.3 -> 50.0.2 | Fernet encryption of saved credentials; 10 advisories. |
| anyio, python-dotenv, langchain-community (0.3.27), langsmith | patch/minor bumps | Advisories fixed without leaving the tested major versions. |
| vite 8.2.1 -> 8.3.5, seroval, source-map-js (`npm audit fix`, lockfile only) | | The lockfile pinned a vulnerable Vite (dev server) and a vulnerable `seroval` that ships in the browser bundle. `npm audit` now reports 0. |

Verified by: full backend suite on the new versions (2210 of 2211 passed; the one failure was a pre-existing flaky test, see below, since fixed), `pip check`, front-end `tsc` + build, real-browser smoke of every page and the new screens.

## Deliberately NOT changed (and why)
- **FastAPI 0.125+ / Starlette 1.x.** Newer FastAPI wraps each included router in a private object, which made our route-authentication inventory (and therefore the RBAC and "every route is protected" tests) see only 1 of 251 routes. Chasing private framework internals in a security guard is not worth it right now; Starlette is already clean at 0.50.0. Revisit by rewriting `app/core/route_inventory.py` against a public API.
- **LangChain family (langchain 0.3.30, langchain-core 0.3.86, langchain-openai 0.3.24; fixes need 1.x).** The advisories are in features this app does not use: loading prompts from files, image-URL token counting (SSRF) and `EverNoteLoader`. Moving to 1.x is a migration project; do it deliberately with the LLM gateway tests, not as a drive-by.
- **python-jose / ecdsa: removed.** Sign-in tokens now use PyJWT 2.10.1 (`app/core/auth.py`; required claims `exp`, `sub`, plus `iss`/`aud` when configured). Covered by the auth and JWT security suites, including new tests for missing `exp`, missing `sub` and `alg: none`.
- **pytest 8.3.4** (dev-only advisory): not shipped; pytest 9 needs a pytest-asyncio upgrade.

## A security test that was flaky (fixed)
`test_tampered_signature_rejected` "tampered" with the last base64url character of the signature. That character carries only 4 significant bits, so for about 5-6% of random tokens the change was a no-op and the token (correctly) still verified. Measured in both the old and new environments; real tampering was rejected 500 of 500 times in both. The test now alters a middle character and asserts the token really changed; a mutation check (signature verification switched off) makes it fail.

## Operator note
After updating the code, run `pip install -r requirements.txt` inside the back end's virtual environment (see windows_setup.md section 6) and `npm install` at the project root.
