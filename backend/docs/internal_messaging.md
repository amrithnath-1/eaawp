# Internal messaging (Phase J, part 2)

Private one-to-one messages between **active** members of the same company, at `/messages` (unread badge in the nav).

## Rules (enforced in `app/api/routers/messages.py`)
* Sender always comes from the JWT. You can message only active people in YOUR company; other companies are a 404.
* **Privacy: only the two participants can read a conversation. Administrators cannot read other people's messages.**
* Max 2000 characters; control characters are stripped; bodies are rendered as plain text in the UI.
* Deactivated people cannot be messaged (history stays readable to the other person); they cannot sign in anyway.
* Opening a thread marks only that person's messages to you as read.

## API (`/api/v1/messages`)
`GET /people`, `GET /conversations`, `GET /unread-count`, `GET /with/{user_id}` (last 200 messages), `POST /with/{user_id}`.

## Limits / honest status
* IMPLEMENTED, MOCK-TESTED ONLY (real API + two-user real-browser run). Updates arrive by polling (8-20 s), not push.
* No attachments, group chats, edit/delete, or email/push notification of new messages (Phase M / J part 3).
* Messages are stored unencrypted at rest and are not covered by the audit log (content is deliberately not logged).
* Migration `e8f2a37b9c45` (additive; one table).
