from __future__ import annotations

import re
import uuid
from typing import Any

from .db import db_session, json_dump, json_load
from .tools import InvoiceTools, ToolError
from .planner import RequestPlanner

MAX_TOOL_ATTEMPTS = 2


class TaskNotFoundError(KeyError):
    pass


class Agent:
    """A transparent, bounded tool-using agent with persisted state and explicit approval."""

    def __init__(self, tools: InvoiceTools | None = None, planner: RequestPlanner | None = None) -> None:
        self.tools = tools or InvoiceTools()
        self.planner = planner or RequestPlanner()

    @staticmethod
    def _company_from_request(request: str) -> str | None:
        patterns = [
            r"(?:from|for)\s+([A-Z][A-Za-z0-9& .-]*?(?:Company|Labs|Inc\.?|Ltd\.?|Corp\.?)?)\s*(?:,|\.|$)",
            r"\b(ABC Company|Northstar Labs)\b",
        ]
        # Prefer known fixture company names, but keep matching isolated to the fixture dataset.
        known = ["ABC Company", "Northstar Labs"]
        for name in known:
            if name.casefold() in request.casefold():
                return name
        for pattern in patterns:
            match = re.search(pattern, request)
            if match:
                candidate = match.group(1).strip()
                if candidate:
                    return candidate
        return None

    def create_task(self, request: str, require_approval: bool = True) -> dict[str, Any]:
        task_id = str(uuid.uuid4())
        interpretation = self.planner.interpret(request)
        company = interpretation.get("company")
        plan = [
            {"step": "understand_request", "description": "Identify the target company and requested invoice workflow"},
            {"step": "search_invoices", "description": "Search available invoice sources and select the latest matching invoice"},
            {"step": "read_and_validate", "description": "Read invoice details and validate required fields"},
            {"step": "approval_gate", "description": "Obtain human approval before writing to the finance system"},
            {"step": "write_finance_record", "description": "Create the finance record with bounded retry and idempotency"},
            {"step": "verify_result", "description": "Read back the persisted record and verify key fields"},
        ]
        with db_session() as conn:
            conn.execute(
                "INSERT INTO tasks (id, request, status, current_step, require_approval, plan_json) VALUES (?, ?, ?, ?, ?, ?)",
                (task_id, request, "running", "understand_request", int(require_approval), json_dump(plan)),
            )
        self._audit(task_id, "task_created", {"request": request, "require_approval": require_approval, "planner": interpretation.get("planner")})
        self._audit(task_id, "request_interpreted", interpretation)
        if interpretation.get("intent") != "process_invoice" or not company:
            return self._fail(task_id, "Could not identify a supported invoice-processing request. Try naming ABC Company or Northstar Labs and ask to process its invoice.")
        self._patch_task(task_id, current_step="search_invoices")
        search = self._run_tool(task_id, "search_invoices", lambda: self.tools.search_invoices(company))
        if not search["invoices"]:
            return self._fail(task_id, f"No invoices found for {company}.")
        invoice = search["invoices"][0]  # Tool sorts newest-first; the selected source is retained as evidence.
        self._audit(task_id, "invoice_selected", {"invoice_id": invoice["invoice_id"], "invoice_number": invoice["invoice_number"], "source_file": invoice["file_name"]})
        self._patch_task(task_id, current_step="read_and_validate", result={"company": company, "search_count": search["count"], "invoice": invoice})
        invoice = self._run_tool(task_id, "read_invoice", lambda: self.tools.read_invoice(invoice["invoice_id"]))
        validation = self._run_tool(task_id, "validate_invoice", lambda: self.tools.validate_invoice(invoice))
        if not validation["valid"]:
            return self._fail(task_id, f"Invoice validation failed: {validation['missing_fields']}")
        invoice["amount"] = validation["normalized_amount"]
        result = {"company": company, "invoice": invoice, "validation": validation, "search_count": search["count"]}
        if require_approval:
            self._patch_task(task_id, status="pending_approval", current_step="approval_gate", result=result)
            self._audit(task_id, "approval_required", {"action": "create_finance_record", "invoice_number": invoice["invoice_number"], "amount": invoice["amount"], "currency": invoice["currency"]})
            return self.get_task(task_id)
        return self._complete_write(task_id, result, approved_by="system_policy")

    def approve_task(self, task_id: str, actor: str, note: str | None = None) -> dict[str, Any]:
        task = self.get_task(task_id)
        if task["status"] != "pending_approval":
            raise ValueError(f"Task must be pending_approval; current status is {task['status']}")
        with db_session() as conn:
            conn.execute("INSERT INTO approvals (task_id, decision, actor, note) VALUES (?, 'approved', ?, ?)", (task_id, actor, note))
            conn.execute("UPDATE tasks SET approved_by=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (actor, task_id))
        self._audit(task_id, "approval_granted", {"actor": actor, "note": note})
        return self._complete_write(task_id, task["result"], approved_by=actor)

    def reject_task(self, task_id: str, actor: str, note: str | None = None) -> dict[str, Any]:
        task = self.get_task(task_id)
        if task["status"] != "pending_approval":
            raise ValueError(f"Task must be pending_approval; current status is {task['status']}")
        with db_session() as conn:
            conn.execute("INSERT INTO approvals (task_id, decision, actor, note) VALUES (?, 'rejected', ?, ?)", (task_id, actor, note))
        self._audit(task_id, "approval_rejected", {"actor": actor, "note": note})
        return self._patch_task(task_id, status="rejected", current_step="approval_gate", error="Human reviewer rejected the finance write.")

    def _complete_write(self, task_id: str, result: dict[str, Any], approved_by: str) -> dict[str, Any]:
        invoice = result["invoice"]
        self._patch_task(task_id, status="running", current_step="write_finance_record", result=result)
        write_result = self._run_tool(
            task_id, "create_finance_record",
            lambda: self.tools.create_finance_record(task_id, invoice),
            retry=True,
        )
        result["finance_write"] = {"created": write_result["created"], "idempotent_replay": write_result["idempotent_replay"], "approved_by": approved_by}
        self._patch_task(task_id, current_step="verify_result", result=result)
        verification = self._run_tool(task_id, "verify_finance_record", lambda: self.tools.verify_finance_record(invoice), retry=True)
        result["verification"] = verification
        if not verification["verified"]:
            return self._fail(task_id, "Finance record was written but read-after-write verification failed.", result=result)
        result["evidence"] = {
            "invoice_number": invoice["invoice_number"],
            "source_file": invoice["file_name"],
            "finance_record_id": verification["record"]["id"],
            "checks": verification["checks"],
            "approved_by": approved_by,
        }
        self._audit(task_id, "task_verified", result["evidence"])
        return self._patch_task(task_id, status="completed", current_step="completed", result=result, error=None)

    def _run_tool(self, task_id: str, tool_name: str, call, retry: bool = False) -> Any:
        attempts = MAX_TOOL_ATTEMPTS if retry else 1
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            self._audit(task_id, "tool_started", {"tool": tool_name, "attempt": attempt})
            try:
                output = call()
                self._audit(task_id, "tool_succeeded", {"tool": tool_name, "attempt": attempt, "output_summary": self._summary(output)})
                return output
            except ToolError as exc:
                last_error = exc
                self._audit(task_id, "tool_failed", {"tool": tool_name, "attempt": attempt, "error": str(exc), "will_retry": attempt < attempts})
                if attempt >= attempts:
                    break
        assert last_error is not None
        self._fail(task_id, f"Tool '{tool_name}' failed after {attempts} attempt(s): {last_error}")
        raise last_error

    @staticmethod
    def _summary(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: value[k] for k in list(value)[:5] if k not in {"invoices", "record"}}
        return str(value)[:200]

    def _audit(self, task_id: str, event_type: str, detail: dict[str, Any]) -> None:
        with db_session() as conn:
            conn.execute("INSERT INTO audit_events (task_id, event_type, detail_json) VALUES (?, ?, ?)", (task_id, event_type, json_dump(detail)))

    def _patch_task(self, task_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {"status", "current_step", "result", "error", "approved_by"}
        updates: list[str] = []
        values: list[Any] = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            column = "result_json" if key == "result" else key
            updates.append(f"{column} = ?")
            values.append(json_dump(value) if key == "result" else value)
        updates.append("updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')")
        values.append(task_id)
        with db_session() as conn:
            conn.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?", values)
        return self.get_task(task_id)

    def _fail(self, task_id: str, error: str, result: dict[str, Any] | None = None) -> dict[str, Any]:
        self._audit(task_id, "task_failed", {"error": error})
        return self._patch_task(task_id, status="failed", current_step="failed", error=error, **({"result": result} if result is not None else {}))

    def get_task(self, task_id: str) -> dict[str, Any]:
        with db_session() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not row:
                raise TaskNotFoundError(task_id)
            task = dict(row)
            events = conn.execute("SELECT id, event_type, detail_json, created_at FROM audit_events WHERE task_id=? ORDER BY id", (task_id,)).fetchall()
            approval = conn.execute("SELECT decision, actor, note, created_at FROM approvals WHERE task_id=?", (task_id,)).fetchone()
        task["plan"] = json_load(task.pop("plan_json"), [])
        task["result"] = json_load(task.pop("result_json"), {})
        task["require_approval"] = bool(task["require_approval"])
        task["audit_events"] = [{**dict(e), "detail": json_load(e["detail_json"], {})} for e in events]
        for e in task["audit_events"]:
            e.pop("detail_json", None)
        task["approval"] = dict(approval) if approval else None
        return task

    def list_tasks(self, limit: int = 50) -> list[dict[str, Any]]:
        with db_session() as conn:
            rows = conn.execute("SELECT id FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [self.get_task(row["id"]) for row in rows]
