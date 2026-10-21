# Team invitations and member management (Phase J, part 1)

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

## Honest status / limits
* IMPLEMENTED, MOCK-TESTED ONLY: real API + real browser run, no external services involved.
* **No email is sent.** The admin copies the link and passes it on. Authorized email delivery is part 3 (needs a configured provider).
* No self-service password reset yet, no per-feature permissions beyond the four roles (finer permissions can build on this).
* Migration `d7e1f26a8b34` (additive; one table).
