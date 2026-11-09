import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from swarm.__main__ import execute, main
from swarm.budget import Ledger
from swarm.settings import Settings


def test_main_requires_frozen_count_and_intervention_check(tmp_path, monkeypatch):
    (tmp_path / "configs").mkdir()
    monkeypatch.setattr("swarm.__main__.ROOT", tmp_path)
    monkeypatch.setattr("swarm.__main__.protocol_hash", lambda _: "hash")
    settings = replace(Settings(), runs=tmp_path / "runs")
    ledger = Ledger(settings.runs / "spending.sqlite3")
    args = SimpleNamespace(command="main", confirm_main=True, seeds=20)
    with pytest.raises(ValueError, match="reviewed frozen_protocol"):
        asyncio.run(execute(args, settings, ledger))
    path = tmp_path / "configs/frozen_protocol.json"
    approval = {"protocol_hash": "hash", "rubric_validated": True, "planned_seed_count": 25}
    path.write_text(json.dumps(approval))
    with pytest.raises(ValueError, match="planned_seed_count"):
        asyncio.run(execute(args, settings, ledger))
    approval["planned_seed_count"] = 20
    path.write_text(json.dumps(approval))
    with pytest.raises(ValueError, match="intervention check"):
        asyncio.run(execute(args, settings, ledger))
    assert ledger.summary()["stages"] == {}


def test_budget_does_not_load_credentials_or_require_valid_experiment_config(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr("swarm.__main__.ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", ["swarm", "budget"])

    def forbidden_load():
        raise AssertionError("Budget inspection must not read .env")

    monkeypatch.setattr("swarm.__main__.Settings.load", forbidden_load)
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["total_cap_usd"] == 50
