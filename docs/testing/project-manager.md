# Project Manager AI employee — how to test

Ported from Vyuham (AF-07 team coordination & task allocation). It uses Gemini through EAAWP's AI gateway; when no
Gemini key is set, document reading, plans and minutes use Vyuham's labelled rule-based method. Allocation, scores and
progress never use AI.

## Turn it on
1. Marketplace → **Project Manager** is available (active by default).
2. Switch AI employee → **Project Manager**. The navigation gains **Projects**.

## Administrator walk-through
1. **Team** → *Add from your EAAWP team* and/or *Import people from a file* (CSV/Excel/PDF/Word). Review, then confirm.
   Nothing is saved before you confirm; skills you add should state a level (e.g. `Python (Advanced)`).
2. **New project** → name, objective, deadline.
3. Project → **Documents** → upload the brief. Text that looks like an instruction to the AI is flagged and ignored.
4. **Specification & plan** → *Read the documents* → answer the questions → *Approve specification* → *Draft the plan*
   → review → *Approve plan and create tasks* (tasks are created once).
5. **Tasks** → *Allocate this project's open tasks*. *Who fits?* shows the ranked people and why someone is not eligible.
6. **Approvals** → critical tasks and assignments above 85% load wait here; approve or reject.
7. **Team** → *On leave* creates reallocation proposals for that person's open work (approve them in Approvals).
8. **Budget**, **Team room** (messages; minutes count as decisions only after approval), **Audit** (SHA-256 chain).

## Team member
- Their sign-in email must be on the roster. **My work** shows their tasks, why they were chosen, what they wait on;
  they save progress and *Submit for review*. Work counts as done only after a manager accepts it.
- An administrator can name a member as a project's manager (API: `POST /api/v1/pm/projects/{id}/managers`);
  they then manage only that project.

## In chat
Ask: "How are our projects doing?", "Who is overloaded?", "Which allocations need my approval?", "What are my tasks?".
Actions (create project, run allocation, assign, record leave) appear in Approvals first and run only when approved.

## Automated checks
`backend/tests/test_project_manager.py` (17 tests): Vyuham's reference allocation, approvals, hard constraints,
access rules, company isolation, module switch-off, document → plan flow with an injected instruction, verified
progress, budget, minutes, roster, import, audit ledger, the Gemini path, and the chat role.
