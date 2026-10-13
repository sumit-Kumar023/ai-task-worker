"""Run a terminal walkthrough without needing curl or a browser."""
from pprint import pprint

from .agent import Agent
from .db import init_db


def main() -> None:
    init_db()
    agent = Agent()
    task = agent.create_task(
        "Find the latest invoice from ABC Company, enter it into finance, and confirm when done.",
        require_approval=True,
    )
    print("\n--- TASK PAUSED FOR APPROVAL ---")
    pprint({"id": task["id"], "status": task["status"], "invoice": task["result"].get("invoice")})
    if task["status"] == "pending_approval":
        task = agent.approve_task(task["id"], actor="demo-reviewer", note="Approved for local demo")
    print("\n--- FINAL TASK RESULT ---")
    pprint({"id": task["id"], "status": task["status"], "evidence": task["result"].get("evidence"), "error": task["error"]})
    print("\n--- AUDIT TRAIL ---")
    for event in task["audit_events"]:
        print(event["event_type"], event["detail"])


if __name__ == "__main__":
    main()
