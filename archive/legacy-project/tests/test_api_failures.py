import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from swarm.budget import Ledger
from swarm.client import APIClient, ModelFailure
from swarm.settings import Settings

SCHEMA = {
    "type": "object",
    "properties": {"message": {"type": "string", "enum": ["ok"]}},
    "required": ["message"],
    "additionalProperties": False,
}


class Usage:
    def model_dump(self):
        return {
            "input_tokens": 10,
            "output_tokens": 20,
            "input_tokens_details": {"cached_tokens": 0},
        }


class Response:
    usage = Usage()
    status = "completed"
    id = "response_fake"
    output_text = '{"message":"ok"}'

    def model_dump(self, **kwargs):
        return {"usage": self.usage.model_dump(), "status": self.status, "id": self.id}


def test_api_usage_and_safe_logs(tmp_path, monkeypatch):
    sent = []

    class FakeAPI:
        def __init__(self, **kwargs):
            assert kwargs["max_retries"] == 0
            assert kwargs["base_url"] == "https://api.openai.com/v1"
            self.responses = SimpleNamespace(create=self.create)

        async def create(self, **kwargs):
            sent.append(kwargs)
            return Response()

        async def close(self):
            pass

    monkeypatch.setattr("swarm.client.AsyncOpenAI", FakeAPI)
    ledger = Ledger(tmp_path / "spend.db")
    settings = replace(Settings(), key="SECRET_SENTINEL", paid=True)
    client = APIClient(settings, ledger, "pilot", 5)
    result = asyncio.run(client.call("system", "user", SCHEMA, tmp_path / "turn.json", "label"))
    assert result == {"message": "ok"}
    assert sent[0]["store"] is False
    assert sent[0]["reasoning"] == {"effort": "low"}
    assert sent[0]["max_output_tokens"] == 2048
    assert ledger.summary()["stages"]["pilot"]["unresolved_calls"] == 0
    assert all("SECRET_SENTINEL" not in p.read_text() for p in tmp_path.glob("*.json"))


def test_network_failure_stops_dispatch_and_retains_budget(tmp_path, monkeypatch):
    sent = []

    class FailingAPI:
        def __init__(self, **kwargs):
            self.responses = SimpleNamespace(create=self.create)

        async def create(self, **kwargs):
            sent.append(kwargs)
            raise RuntimeError("could echo SECRET_SENTINEL from upstream")

        async def close(self):
            pass

    monkeypatch.setattr("swarm.client.AsyncOpenAI", FailingAPI)
    ledger = Ledger(tmp_path / "spend.db")
    client = APIClient(replace(Settings(), paid=True, key="SECRET_SENTINEL"), ledger, "pilot", 5)

    async def exercise():
        with pytest.raises(ModelFailure) as caught:
            await client.call("s", "u", SCHEMA, tmp_path / "turn.json", "label")
        assert "SECRET_SENTINEL" not in str(caught.value)
        with pytest.raises(ModelFailure):
            await client.call("s", "u", SCHEMA, tmp_path / "next.json", "next")

    asyncio.run(exercise())
    assert len(sent) == 1
    summary = ledger.summary()["stages"]["pilot"]
    assert summary["unresolved_calls"] == 1
    assert summary["accounted_or_reserved_usd"] > 0
    assert all("SECRET_SENTINEL" not in p.read_text() for p in tmp_path.glob("*.json"))


def test_incomplete_output_is_billed_but_not_repaired(tmp_path, monkeypatch):
    class IncompleteAPI:
        def __init__(self, **kwargs):
            self.responses = SimpleNamespace(create=self.create)

        async def create(self, **kwargs):
            response = Response()
            response.status = "incomplete"
            return response

        async def close(self):
            pass

    monkeypatch.setattr("swarm.client.AsyncOpenAI", IncompleteAPI)
    ledger = Ledger(tmp_path / "spend.db")
    client = APIClient(replace(Settings(), paid=True, key="fake"), ledger, "pilot", 5)
    with pytest.raises(ModelFailure):
        asyncio.run(client.call("s", "u", SCHEMA, tmp_path / "turn.json", "label"))
    summary = ledger.summary()["stages"]["pilot"]
    assert summary["calls"] == 1
    assert summary["standard_token_estimate_usd"] > 0
    assert summary["unresolved_calls"] == 0
    assert client.stopped
    assert json.loads((tmp_path / "turn.error.json").read_text())["error_type"] == "ModelFailure"
