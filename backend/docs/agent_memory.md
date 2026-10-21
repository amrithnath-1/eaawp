# Agent memory

Memory gives a role background context from earlier work. It never overrides permissions, rules or approvals.

## What is stored
- **Company notes** (preferences, strategy, decisions, admin instructions): written by company administrators only, shared by every user of that role in that company. `user_id` is NULL.
- **Conversation history** (`execution_history`): saved automatically after a reply, owned by the user who asked, retrieved only for that user. Bounded to 100 active rows per user/role (oldest least-relevant archived).
- Roles that handle personal records (`INSTITUTIONAL_CLERK`, `MEDICAL_ASSISTANT`) never store or retrieve memory.
- Rows from before this change have no owner; they are never retrieved.

## How it reaches the model
Up to 5 keyword-matched notes are added to the prompt as one-line, control-character-stripped bullets under "Relevant Memory", marked as information only. Both simple and planning modes use it. A memory failure is logged and never fails the request.

## API (`/api/v1/memory`)
- `POST` / `GET` / `DELETE /{id}`: admin only, audited. Category must be valid and not `execution_history`; role key must look like `UPPER_SNAKE`.
- `GET /search?q=&role_key=`: any member; returns only their visible notes.

## Known limits
Keyword (not semantic) matching; admins cannot browse or delete users' personal history through the API.
