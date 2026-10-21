# Team invitations and member management (Phase J, parts 1 and 3)

Admins invite colleagues by email address, the invitee sets their own name and password through a one-time link, and admins
manage roles and access. Part 2 (internal messaging) and part 3 (authorized email sending) follow.

## Invitations
* `POST /api/v1/team/invitations` (admin) returns the link path **once**; only a SHA-256 of the 256-bit token is stored.
* Valid for 7 days, single-use. "New link" (resend) rotates the token, so the previous link stops working. Revoke is final.
* Unknown, expired, revoked and used tokens all return the same generic 404, so a token cannot be probed.
* Public endpoints (`lookup`, `accept`) are rate-limited per IP; failed attempts (bad password, empty name) do not burn the token.
* Roles that can be granted: Employee, Manager, Company Admin, AI Administrator. Never `superadmin`.
* One pending invitation per email; existing accounts (any case) are refused; max 50 pending per company.
* The new user lands only in the inviting company and signs in with that company ID.

## Members
`GET /members`, `POST /members/{id}/role|deactivate|reactivate` (admin, same company only; other company = 404).
* An admin cannot change their own role or deactivate themselves, so a company always keeps an administrator.
* Accounts holding roles outside the assignable set (e.g. `superadmin`) cannot be edited here.
* Deactivating revokes all of the person's refresh tokens and blocks login and existing access tokens immediately.
* All of this is in the audit log (department `team`); tokens are never logged.

## Emailing an invitation (part 3)
* Optional per invitation ("Email it to them" / "Email new link"): the **administrator's explicit action is the authorization**.
  Without it nothing is sent.
* Sent through the company's OWN SMTP integration (`/api/v1/email/integration`), to the invitation's own address only, with a
  fixed template (no free text). Names are stripped of line breaks (no header/line injection).
* The link host must be one of the app's configured origins (`CORS_ORIGINS`); anything else is refused (no phishing links).
* Max 20 invitation emails per company per hour. Failures (no SMTP, refused, transport error) never lose the invitation; the admin is
  told plainly and can copy the link. Raw error text is never echoed.
* Each attempt writes a safe row to `email_audit_logs` (domain only, lengths, outcome; no address, body, token or credentials).
* Also fixed: re-saving an existing SMTP configuration used to 500 (MissingGreenlet) and lose the change.
* Verified with a fake provider in tests AND against a real local SMTP server (real `SMTPEmailProvider` path) in a browser run.
  **NOT verified against a real mail provider** (Gmail/SES/etc.) - needs the owner's SMTP details via the secure admin form.
* Not done: automatic "you have a new message" emails (deliberately skipped - unsolicited sends need their own consent controls, Phase M).

## Honest status / limits
* IMPLEMENTED, MOCK-TESTED ONLY: real API + real browser run, no external services involved.
* Email is optional and only on explicit admin action (above); otherwise the admin copies the link.
* No self-service password reset yet, no per-feature permissions beyond the four roles (finer permissions can build on this).
* Migration `d7e1f26a8b34` (additive; one table).
