from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from openai import AsyncOpenAI

from .budget import Ledger
from .settings import Settings


class ModelFailure(RuntimeError):
    """Sanitized failure; never includes SDK exception body or credentials."""


class APIClient:
    def __init__(self, settings: Settings, ledger: Ledger, stage: str, stage_cap: float):
        if not settings.paid or not settings.key.strip():
            raise ValueError("Paid calls disabled or API key missing")
        self.settings, self.ledger = settings, ledger
        self.stage, self.stage_cap = stage, stage_cap
        self.sem = asyncio.Semaphore(settings.request_concurrency)
        self.stopped = False
        self.client = AsyncOpenAI(
            api_key=settings.key,
            organization=settings.organization or None,
            project=settings.project or None,
            base_url="https://api.openai.com/v1",
            timeout=settings.timeout,
            max_retries=0,
        )

    async def close(self):
        await self.client.close()

    async def call(self, system: str, user: str, schema: dict, path: Path, label: str):
        payload = {
            "model": self.settings.model,
            "reasoning": {"effort": self.settings.effort},
            "input": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "agent_turn",
                    "schema": schema,
                    "strict": True,
                }
            },
            "max_output_tokens": self.settings.max_output,
            "store": False,
            "service_tier": "default",
        }
        async with self.sem:
            if self.stopped:
                raise ModelFailure("Further requests stopped after an earlier failure")
            amount = self.ledger.reserve_amount(payload, self.settings.max_output)
            try:
                call_id = self.ledger.reserve(self.stage, label, amount, self.stage_cap)
            except Exception:
                self.stopped = True
                raise
            started = time.monotonic()
            path.parent.mkdir(parents=True, exist_ok=True)
            # Save complete scientific input, never the credential-bearing client/settings.
            path.with_suffix(".request.json").write_text(json.dumps(payload, indent=2))
            try:
                response = await self.client.responses.create(**payload)
                raw = response.model_dump(mode="json")
                path.write_text(
                    json.dumps(
                        {
                            "call_id": call_id,
                            "response": raw,
                            "elapsed_seconds": time.monotonic() - started,
                        },
                        indent=2,
                    )
                )
                if response.usage is None:
                    raise ModelFailure("Response has no usage; reservation retained")
                self.ledger.complete(call_id, response.usage.model_dump(), response.id)
                if response.status != "completed":
                    raise ModelFailure(
                        f"Response incomplete: {response.status}; no automatic retry"
                    )
                parsed = json.loads(response.output_text)
                validate(parsed, schema)
                return parsed
            except BaseException as exc:
                self.stopped = True
                self.ledger.uncertain(call_id)
                # Never print str(exc): authentication errors can echo credentials.
                error = {
                    "error_type": type(exc).__name__,
                    "http_status": getattr(exc, "status_code", None),
                    "call_id": call_id,
                    "reservation_retained_if_unsettled": True,
                }
                path.with_suffix(".error.json").write_text(json.dumps(error, indent=2))
                if isinstance(exc, asyncio.CancelledError):
                    raise
                raise ModelFailure(json.dumps(error)) from None


def validate(value: dict, schema: dict):
    if not isinstance(value, dict) or set(value) != set(schema["required"]):
        raise ValueError("Invalid JSON keys")
    for key, rule in schema["properties"].items():
        item = value[key]
        if not isinstance(item, str):
            raise TypeError("Expected a string")
        if "maxLength" in rule and len(item) > rule["maxLength"]:
            raise ValueError("Message too long; no truncation or silent repair")
        if "enum" in rule and item not in rule["enum"]:
            raise ValueError("Unknown action")


class MockClient:
    """Offline protocol check only. NOT a language-model pilot or a research result."""

    stopped = False

    async def close(self):
        pass

    async def call(self, system, user, schema, path, label):
        context = json.loads(user)
        if "message" in schema["properties"]:
            result = {"message": "Offline harness check: allocate distinct tasks."}
        else:
            index = context["team_members"].index(context["you"])
            choices = schema["properties"]["task_id"]["enum"]
            result = {
                "task_id": choices[index % (len(choices) - 1)],
                "explanation": "Deterministic mock action; not an LLM result.",
            }
        validate(result, schema)
        return result
