# Institutional Clerk (Phase H)

Service requests with a visible timeline, a review queue, templated documents that are drafted and then issued
with a serial number, field extraction from uploaded documents, and a Clerk agent role with identity-aware tools.

## Request lifecycle
`submitted -> in_review | needs_info | approved | rejected | cancelled`, `needs_info -> in_review | rejected | cancelled`,
`approved -> fulfilled`; rejected / fulfilled / cancelled are final. Enforced in `app/services/clerk_service.py` (not the UI).
* Rejecting or asking for info needs a reason (the requester sees it).
* A requester reply to "needs info" moves the request back to "in review" automatically.
* Requesters may cancel only their own still-open request. Internal notes are admin-only and never returned to requesters.
* Every status change, assignment, document issue/void is on the timeline AND in the audit log.
* Types: certificate, transcript, leave, fee query, ID card, complaint, general. Cap: 25 open requests per person.

## Documents
Built-in templates: bonafide certificate, leave approval letter, notice, general letter. Values fill only declared
placeholders in a single pass (a value can never expand into another token; control characters are stripped).
Draft -> **issued** (admin; gets `PREFIX-YEAR-00001`, unique per company) -> optionally **void** (reason required, kept visible).
Requesters only ever see ISSUED documents of THEIR OWN request. Download is plain text.

## Extraction ("Fill from a document")
Admin uploads PDF/DOCX/TXT/MD (<= 5 MB). The LLM may propose `full_name, id_number, from_date, to_date, purpose, reason`;
a value is kept **only if it appears verbatim in the document text**, otherwise it is dropped. The file is not stored.
Scanned images (no text layer) are not supported.

## Agent (role `INSTITUTIONAL_CLERK`)
* `list_service_requests`, `get_service_request` (read): enforce visibility by the **person asking** (admins: whole company;
  others: only their own). The asker's id/admin flag now travels in the tool context (`set_tool_context(user_id, is_admin)`).
* `draft_service_document` (low risk, no approval): creates a DRAFT only; never issues.
* `update_service_request` (medium risk, **always requires human approval**): status change through the same state machine.

## API (`/api/v1/clerk`)
`GET /meta`; requests: `POST/GET /requests`, `GET /requests/{id}`, `POST /requests/{id}/comments|cancel` (members),
`POST /requests/{id}/status|assign` (admin); documents: `POST/GET /documents`, `GET /documents/{id}/download`,
`POST /documents/{id}/issue|void` (admin); `POST /extract` (admin).

## Limits / honest status
* Verified with a scripted LLM only. No email/notification is sent to requesters yet (Phase J/M); they see updates on the page.
* Documents are plain text (no PDF/letterhead). No fee payment or student-record database integration (Phase K).
Migration: `b5c9d04e6f22` (additive; three tables).
