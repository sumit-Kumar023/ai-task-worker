# CompanyPilot — Autonomous AI Task Worker

A narrow, runnable proof of concept for CentrAlign AI's AI Employee / Autonomous Company Operator problem statement. It takes a natural-language invoice task, finds the latest matching fixture invoice, validates its fields, pauses for human approval before writing, creates a record in a simulated finance app, recovers from a simulated transient failure, reads the record back, and returns evidence plus an audit trail.

> This is a local prototype, not a production-ready agent. The invoice source and finance application are intentionally simulated. No real company credentials or third-party systems are accessed.

## Why this scope

The problem statement values a narrow workflow that genuinely works over broad simulated autonomy. CompanyPilot demonstrates the loop:

`Goal → Understand → Plan → Execute → Observe → Adapt → Verify → Complete`

## Features

- Natural-language task request with a narrow, explicit supported scope.
- Optional LLM-assisted request interpretation (`ENABLE_LLM_PLANNER=true` and `OPENAI_API_KEY`); deterministic fallback keeps the demo runnable offline. The LLM only interprets intent/company and cannot bypass tool controls.
- Latest-invoice selection from a local fixture source.
- Required-field and amount validation.
- Human approval gate before a finance write (enabled by default).
- Tool execution with bounded retry for a simulated transient timeout.
- Idempotent writes keyed by invoice ID and invoice number.
- Read-after-write verification of company, amount, due date, and invoice number.
- SQLite persistence for tasks, finance records, approvals, and audit events.
- Inspectable plan, current step, task state, evidence, and event log.
- FastAPI API plus an interactive Swagger UI.
- Tests for approval, rejection, retry/recovery, invoice selection, and API health.

## Quick start

Requires Python 3.11+.

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000/docs> to use the API.

## Demo flow

### 1. Create a task

`POST /tasks`

```json
{
  "request": "Find the latest invoice from ABC Company, enter it into finance, and confirm when done.",
  "require_approval": true
}
```

The agent finds `ABC-2026-041`, validates the invoice, and returns a task in `pending_approval` state. No finance write has happened yet.

### 2. Approve the write

Copy the `id` from the response and call `POST /tasks/{id}/approve`:

```json
{
  "actor": "reviewer@example.com",
  "note": "Approved for demo"
}
```

The agent attempts the write. With the default fault injection, the first attempt times out; the bounded retry succeeds. It then reads the record back and verifies the fields.

### 3. Inspect evidence

- `GET /tasks/{id}` — current state, plan, results, evidence, approval, audit trail.
- `GET /finance/records` — persisted finance records.
- `GET /audit/{id}` — chronological audit events.

A successful result has `status: "completed"`, `result.verification.verified: true`, and `result.evidence` with the invoice number, source file, persisted record ID, checks, and approver.

### One-command terminal demo

```bash
python -m app.cli_demo
```

The demo approves its own task as a local walkthrough. The API path does not bypass the approval gate unless `require_approval` is explicitly set to `false`.

## Run tests

```bash
pytest -q
```

## API overview

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Liveness check |
| POST | `/tasks` | Create and execute task up to approval gate |
| GET | `/tasks` | List recent tasks |
| GET | `/tasks/{task_id}` | Inspect task, results, plan, and audit trail |
| POST | `/tasks/{task_id}/approve` | Approve pending finance write |
| POST | `/tasks/{task_id}/reject` | Reject pending finance write |
| GET | `/finance/records` | Inspect simulated finance records |
| GET | `/audit/{task_id}` | Inspect task audit events |

## Architecture

- `app/agent.py` — task orchestration, explicit plan, bounded tool attempts, state transitions, approval gate, evidence generation.
- `app/tools.py` — invoice source and simulated finance tools. The agent interacts through tool interfaces rather than directly editing fixture data.
- `app/db.py` — SQLite schema and persistence for tasks, approvals, records, and audit events.
- `app/main.py` — FastAPI endpoints and request validation.
- `fixtures/invoices.json` — sample invoice source data.
- `tests/test_agent.py` — core workflow tests.

## Design decisions

1. **Narrow scope:** invoice processing gives a concrete end-to-end task with observable success criteria.
2. **Approval before side effects:** finance writes pause by default until a reviewer approves.
3. **Bounded retries:** retry only a known transient tool error, with a maximum of two attempts.
4. **Idempotency:** duplicate attempts for the same invoice return the existing record instead of creating a second one.
5. **Independent verification:** success is based on reading back the stored record and checking critical fields, not the model's self-report.
6. **Auditability:** tool starts, successes, failures, approvals, and final verification are recorded.
7. **No hidden LLM requirement:** this baseline is deterministic and reproducible. An LLM planner can be added behind a typed plan interface after tests define the required behavior; the LLM should not bypass permissions or verification.

## Limitations and next steps

- The current parser recognizes only the fixture companies `ABC Company` and `Northstar Labs`.
- Invoice documents are JSON fixtures; PDF/OCR parsing is not implemented.
- The finance app is a local SQLite-backed simulation, not an external enterprise integration.
- The execution plan and tool sequence are intentionally fixed for this narrow workflow; an optional LLM helps interpret intent, but does not dynamically choose tools yet.
- API endpoints do not yet include real authentication/authorization; `actor` is demo metadata, not verified identity. Do not expose this prototype publicly as-is.
- SQLite is appropriate for a local demo, not a multi-worker production deployment.
- Retry policy is deliberately simple; production writes need tool-specific retry classification, idempotency keys, timeouts, and reconciliation.

Suggested next iterations:
1. Add an LLM planner with a strict typed plan schema and deterministic fallback.
2. Add real document parsing for PDF invoices and source provenance for extracted fields.
3. Add browser automation in a sandbox or Playwright against a local mock finance UI.
4. Add authenticated users, role-based permissions, approval expiration, and audit integrity.
5. Move long-running tasks to a queue/worker architecture with cancellation and resumability.
6. Add evaluation cases for ambiguous requests, duplicate invoices, malformed documents, tool failures, and permission violations.
7. Add a demo video showing approval, transient failure, retry, verification, and audit evidence.

## Environment variables

- `COMPANYPILOT_DB_PATH` — optional SQLite file path.
- `SIMULATE_TRANSIENT_WRITE_FAILURE=true` — fail the first finance write attempt for each task to demonstrate recovery. Set `false` to disable the fault injection.
- `ENABLE_LLM_PLANNER=false` — set `true` to enable optional OpenAI request interpretation. Requires `OPENAI_API_KEY`.
- `OPENAI_MODEL=gpt-4o-mini` — optional planner model name.

## Demo safety

Use only the included fixtures or other synthetic data. Do not connect real company accounts or use unauthorized credentials. Keep the service bound to localhost during the demo.
