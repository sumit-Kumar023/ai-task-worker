import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app.agent import Agent
from app.main import app
from app.tools import InvoiceTools


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setattr(db, "DB_PATH", Path(tmp.name))
    db.init_db()
    yield
    try:
        os.unlink(tmp.name)
    except OSError:
        pass


def make_tools(fail=True):
    tools = InvoiceTools()
    tools.simulate_failure = fail
    return tools


def test_task_pauses_for_approval_and_completes_with_verified_evidence():
    agent = Agent(make_tools(fail=True))
    task = agent.create_task("Find the latest invoice from ABC Company and enter it into finance.", True)
    assert task["status"] == "pending_approval"
    assert task["result"]["invoice"]["invoice_number"] == "ABC-2026-041"

    done = agent.approve_task(task["id"], actor="reviewer@example.com", note="Approved")
    assert done["status"] == "completed"
    assert done["result"]["verification"]["verified"] is True
    assert done["result"]["evidence"]["invoice_number"] == "ABC-2026-041"
    event_types = [e["event_type"] for e in done["audit_events"]]
    assert "tool_failed" in event_types
    assert "tool_succeeded" in event_types
    assert "task_verified" in event_types


def test_latest_invoice_selection():
    agent = Agent(make_tools(fail=False))
    task = agent.create_task("Process the latest invoice from ABC Company", True)
    assert task["result"]["invoice"]["invoice_number"] == "ABC-2026-041"


def test_rejection_does_not_write_finance_record():
    agent = Agent(make_tools(fail=False))
    task = agent.create_task("Process the latest invoice from Northstar Labs", True)
    rejected = agent.reject_task(task["id"], actor="reviewer", note="Needs review")
    assert rejected["status"] == "rejected"
    assert agent.tools.verify_finance_record(task["result"]["invoice"])["verified"] is False


def test_unknown_company_fails_with_actionable_error():
    agent = Agent(make_tools(fail=False))
    task = agent.create_task("Process an invoice from Unknown Vendor", True)
    assert task["status"] == "failed"
    assert "Could not identify a supported invoice-processing request" in task["error"]


def test_api_health_and_task_creation():
    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "ok"
        response = client.post("/tasks", json={"request": "Process the latest invoice from ABC Company", "require_approval": True})
        assert response.status_code == 201
        assert response.json()["status"] == "pending_approval"
