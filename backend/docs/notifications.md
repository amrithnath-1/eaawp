# Notifications (Phase M)

## What exists
- **In-app notifications**, one row per recipient. Events: an action needs approval, a workflow run failed, a monitoring rule triggered, a new member joined. These go to the company's **active administrators only**; employees currently receive none (they have no notification types yet).
- **Per-person read state.** Marking a notification read affects only you. Other people's notifications return 404.
- **Bell in the header** (unread count, list, mark read / mark all read) and **Settings > Notifications** (your choices; administrators also see the company switch).
- Legacy company-wide rows from before this change (`user_id` NULL) are visible to administrators only.

## Email: double opt-in, default OFF
Nothing is emailed unless **both** are true, checked when the notification is created **and again at send time**:
1. An administrator authorized automatic notification emails for the company (`PUT /api/v1/notifications/settings`, admin only; refused unless the company's email connection is set up and enabled; switching off is always allowed).
2. The recipient switched email on for that event type (`PUT /api/v1/notifications/preferences`).

Also: the recipient must still be an active member; email is only offered for the four event types above; the email is a fixed generic template (event type + link to the app, never the notification text or company data); capped at 50 per company per hour (extra mail waits, it is not dropped); each attempt is recorded in the email audit log (no body, no credentials); failed sends are retried up to 3 times. Authorization changes and preference changes are written to the audit log.

Delivery runs from a durable outbox in the existing 60-second scheduler tick, so a restart loses nothing and a slow mail server never slows a request.

## Verification status
- Backend: `tests/test_notifications.py` (25 tests, mutation-checked: consent recheck, per-person filter, email content).
- Real SMTP: a local SMTP server received the email through the real scheduler tick; recipient and generic body checked.
- Real browser (scratch DB): employee sees no admin controls; admin authorizes + opts in; real invitation acceptance raised the bell badge; read flow works; mobile width has no horizontal scroll.
- NOT verified: a real mail provider (Gmail/SendGrid etc.), delivery to real inboxes, TLS modes against a real server, push notifications (none exist).

## Limits
Employees have no notification types yet; no digest/quiet hours; no per-event custom recipients; polling every 30 s (no live push).
