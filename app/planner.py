from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

KNOWN_COMPANIES = ["ABC Company", "Northstar Labs"]


class RequestPlanner:
    """Optional LLM-assisted intent extraction with a deterministic offline fallback.

    The LLM only interprets the request. It cannot choose arbitrary tools, bypass approval,
    or declare a task complete; execution and verification remain controlled by the agent.
    """

    def __init__(self) -> None:
        self.enabled = os.getenv("ENABLE_LLM_PLANNER", "false").lower() in {"1", "true", "yes"}
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    def interpret(self, request: str) -> dict[str, Any]:
        if self.enabled and self.api_key:
            try:
                result = self._interpret_with_llm(request)
                if result.get("company") in KNOWN_COMPANIES and result.get("intent") == "process_invoice":
                    return {**result, "planner": "llm"}
            except Exception:
                # Do not fail a useful narrow task because the planner provider is unavailable.
                pass
        return self._interpret_deterministically(request)

    def _interpret_with_llm(self, request: str) -> dict[str, Any]:
        prompt = (
            "Interpret the user's request for a narrowly scoped invoice-processing worker. "
            "Return only JSON with keys intent, company, asks_to_record, and summary. "
            "intent must be process_invoice or unsupported. company must be exactly one of "
            "ABC Company, Northstar Labs, or null. Do not invent facts. User request: " + request
        )
        with httpx.Client(timeout=12.0) as client:
            response = client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": "You are a strict request interpreter. Never execute tools."},
                        {"role": "user", "content": prompt},
                    ],
                },
            )
            response.raise_for_status()
            data = response.json()
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        return {
            "intent": parsed.get("intent"),
            "company": parsed.get("company"),
            "asks_to_record": bool(parsed.get("asks_to_record", True)),
            "summary": str(parsed.get("summary", ""))[:500],
        }

    @staticmethod
    def _interpret_deterministically(request: str) -> dict[str, Any]:
        for company in KNOWN_COMPANIES:
            if company.casefold() in request.casefold():
                return {
                    "intent": "process_invoice" if re.search(r"invoice|bill|finance", request, re.I) else "unsupported",
                    "company": company,
                    "asks_to_record": bool(re.search(r"enter|record|submit|save|process|finance", request, re.I)),
                    "summary": f"Process invoice workflow for {company} using the local demo source.",
                    "planner": "deterministic_fallback",
                }
        # Do not guess a company from arbitrary text. Ask for a supported, explicit target.
        return {
            "intent": "unsupported",
            "company": None,
            "asks_to_record": False,
            "summary": "Could not identify a supported company and invoice-processing intent.",
            "planner": "deterministic_fallback",
        }
