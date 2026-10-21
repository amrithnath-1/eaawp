# Medical Assistant (Phase I) - clinic SUPPORT only

Appointment requests, a clinic staff queue, intake captured in the patient's own words, and a Medical Assistant agent role.
It is NOT a clinical tool: it never diagnoses, prescribes, gives dosing or treatment advice, or triages.

## Safety boundary (`app/services/medical_guard.py`) - runs BEFORE any model
* **Emergency** wording (chest pain, can't breathe, stroke signs, severe bleeding, overdose, anaphylaxis...) -> immediate
  "call emergency services now" message. No LLM, no booking talk.
* **Crisis** wording (suicide / self-harm) -> supportive message pointing to emergency services and a crisis line.
* **Advice requests** (dose, "should I take", "do I have", diagnosis) -> boundary message; offers an appointment instead.
* Patterns are deliberately broad (false alarm = one sentence). This is a safety net, not triage. `POST /clinic/screen`
  lets the UI show the banner while typing; the agent path applies the same guard in `execute_agent` for role `MEDICAL_ASSISTANT`.
* A request whose reason matches emergency wording is stored with `red_flag=true` and the patient gets the emergency notice.

## Appointment lifecycle
`requested -> confirmed | cancelled`, `confirmed -> completed | no_show | cancelled` (state machine in `medical_service.py`).
* Confirming needs a future `scheduled_for`. Cap: 10 open requests per person.
* Patients see only their own appointments and public comments; internal notes are staff-only.
* Staff (= company admin for now) viewing someone else's record is written to the audit log.
* Patients may cancel their own open appointment; "Erase record" deletes it (audited).

## Intake summary ("Organise intake")
The LLM may propose symptoms / duration / medications / allergies *as the patient wrote them*; each value is kept only if it
appears verbatim in the patient's text, else dropped. Nothing is interpreted or advised.

## Agent (role `MEDICAL_ASSISTANT`)
* Read tools `list_appointments`, `get_appointment`: visibility by the **asker** (admin: all; others: own only).
* `update_appointment_status`: always requires human approval.
* Conversations are never written to shared agent memory (`PERSONAL_DATA_ROLES`).

## API (`/api/v1/clinic`)
`GET /meta`, `POST /screen`, `POST/GET /appointments`, `GET/DELETE /appointments/{id}`, `POST .../notes|cancel` (members),
`POST .../status|summarize` (admin).

## Limits / honest status
* Verified with a scripted LLM only (real server + browser run, no live LLM).
* **Medical text is stored unencrypted at rest** in the app database. Do not use for real patient data without
  encryption-at-rest, retention policy and a compliance review (HIPAA/GDPR etc.). Not a medical device.
* Staff = admin; granular clinic roles arrive with Phase J. No email/SMS reminders yet (Phase J/M).
* Migration `c6d0e15f7a23` (additive; one table).
