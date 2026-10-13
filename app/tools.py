from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .db import db_session, json_dump

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "invoices.json"


class ToolError(RuntimeError):
    """A tool failed in a way the agent may be able to recover from."""


class InvoiceTools:
    """Tools available to the agent. External writes target a local simulated finance app."""

    def __init__(self) -> None:
        self._invoices = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        self._failed_once: set[str] = set()
        self.simulate_failure = os.getenv("SIMULATE_TRANSIENT_WRITE_FAILURE", "true").lower() in {"1", "true", "yes"}

    def search_invoices(self, company: str) -> dict[str, Any]:
        matches = [x for x in self._invoices if company.casefold() in x["company"].casefold()]
        matches.sort(key=lambda x: x["invoice_date"], reverse=True)
        return {"count": len(matches), "invoices": matches}

    def read_invoice(self, invoice_id: str) -> dict[str, Any]:
        for invoice in self._invoices:
            if invoice["invoice_id"] == invoice_id:
                return dict(invoice)
        raise ToolError(f"Invoice '{invoice_id}' was not found")

    def validate_invoice(self, invoice: dict[str, Any]) -> dict[str, Any]:
        required = ["invoice_id", "company", "invoice_number", "amount", "currency", "due_date", "file_name"]
        missing = [key for key in required if invoice.get(key) in (None, "")]
        if missing:
            return {"valid": False, "missing_fields": missing}
        try:
            amount = float(invoice["amount"])
        except (TypeError, ValueError):
            return {"valid": False, "missing_fields": ["amount must be numeric"]}
        if amount <= 0:
            return {"valid": False, "missing_fields": ["amount must be positive"]}
        return {"valid": True, "missing_fields": [], "normalized_amount": round(amount, 2)}

    def create_finance_record(self, task_id: str, invoice: dict[str, Any]) -> dict[str, Any]:
        # Demonstration fault injection: fail once before the write, so a retry is safe.
        if self.simulate_failure and task_id not in self._failed_once:
            self._failed_once.add(task_id)
            raise ToolError("Simulated transient finance application timeout")

        with db_session() as conn:
            existing = conn.execute(
                "SELECT * FROM finance_records WHERE invoice_id = ? OR invoice_number = ?",
                (invoice["invoice_id"], invoice["invoice_number"]),
            ).fetchone()
            if existing:
                existing_dict = dict(existing)
                if existing_dict["invoice_id"] != invoice["invoice_id"]:
                    raise ToolError("Idempotency conflict: invoice number already belongs to another invoice")
                return {"record": existing_dict, "created": False, "idempotent_replay": True}
            cur = conn.execute(
                """INSERT INTO finance_records
                (invoice_id, invoice_number, company, amount, currency, due_date, source_file, created_by_task)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (invoice["invoice_id"], invoice["invoice_number"], invoice["company"],
                 float(invoice["amount"]), invoice["currency"], invoice["due_date"],
                 invoice["file_name"], task_id),
            )
            row = conn.execute("SELECT * FROM finance_records WHERE id = ?", (cur.lastrowid,)).fetchone()
            return {"record": dict(row), "created": True, "idempotent_replay": False}

    def verify_finance_record(self, invoice: dict[str, Any]) -> dict[str, Any]:
        with db_session() as conn:
            row = conn.execute(
                "SELECT * FROM finance_records WHERE invoice_id = ? AND invoice_number = ?",
                (invoice["invoice_id"], invoice["invoice_number"]),
            ).fetchone()
        if not row:
            return {"verified": False, "reason": "No persisted finance record found"}
        record = dict(row)
        checks = {
            "invoice_number_matches": record["invoice_number"] == invoice["invoice_number"],
            "amount_matches": round(float(record["amount"]), 2) == round(float(invoice["amount"]), 2),
            "due_date_matches": record["due_date"] == invoice["due_date"],
            "company_matches": record["company"] == invoice["company"],
        }
        return {"verified": all(checks.values()), "checks": checks, "record": record}


def list_finance_records() -> list[dict[str, Any]]:
    with db_session() as conn:
        rows = conn.execute("SELECT * FROM finance_records ORDER BY id DESC").fetchall()
    return [dict(row) for row in rows]
