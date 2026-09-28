from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from .evidence import validate_findings
from .models import EvidenceFact, Finding
from .report import compose_report


def compose_with_optional_llm(
    question: str, metrics: dict[str, Any], evidence: tuple[EvidenceFact, ...]
) -> tuple[tuple[Finding, ...], tuple[str, ...], str]:
    fallback_findings, fallback_actions = compose_report(metrics, evidence)
    endpoint = os.getenv("PLAN_EXECUTE_LLM_URL", "").strip()
    api_key = os.getenv("PLAN_EXECUTE_LLM_API_KEY", "").strip()
    model = os.getenv("PLAN_EXECUTE_LLM_MODEL", "").strip()
    if not endpoint:
        return fallback_findings, fallback_actions, "deterministic: LLM not configured"
    body = {
        "question": question,
        "instruction": (
            "Return JSON with findings [{text, evidence_ids}] and actions [string]. "
            "Only use supplied evidence IDs; never introduce a number not in cited evidence."
        ),
        "evidence": [
            {"id": fact.id, "path": fact.path, "label": fact.label, "value": fact.value}
            for fact in evidence
        ],
    }
    request_body: dict[str, Any] = body
    if model:
        request_body = {
            "model": model,
            "temperature": 0.1,
            "stream": False,
            "max_tokens": 800,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": body["instruction"]},
                {"role": "user", "content": json.dumps(body, ensure_ascii=False)},
            ],
        }
    try:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        request = Request(
            endpoint,
            data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urlopen(request, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if model:
            payload = json.loads(payload["choices"][0]["message"]["content"])
        findings = tuple(
            Finding(str(item["text"]), tuple(item["evidence_ids"]))
            for item in payload["findings"]
        )
        actions = tuple(str(item) for item in payload.get("actions", []))
        validate_findings(findings, evidence)
        return findings, actions or fallback_actions, "llm: validated"
    except (
        IndexError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        URLError,
        TimeoutError,
    ):
        return fallback_findings, fallback_actions, "deterministic: LLM output unavailable or invalid"
