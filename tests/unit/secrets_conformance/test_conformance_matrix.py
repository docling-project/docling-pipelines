# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""The canary conformance matrix (task E.1): every declared secret-capable field through five scenarios.

For each ``(operator, field)`` of the declarations the real resolver, orchestrator, operator constructor, job
tracker, lineage observer and file writers run with fake clients whose exceptions embed a unique canary. Every
sink the harness collects (logs at all levels, exception text and ``repr``, node and job messages, run metadata,
REST bodies, lineage events, Prefect task parameters, table columns, document metadata, every written file) is
scanned for the canary and its encoded and derived forms.

The Prefect parameter sink is the ``op_def`` and ``global_config`` the orchestrator would pass to a Prefect
task; the Prefect run path itself is covered by
``tests/unit/core/orchestration/prefect/test_prefect_secret_parameters.py`` (D.5, D.6).

The whole matrix takes several minutes, so it is marked ``slow``.
"""

from pathlib import Path

import pytest

from tests.unit.secrets_conformance.catalog import NOT_REACHED, SUCCESS_NEEDS_REAL_SERVER, Entry, entries
from tests.unit.secrets_conformance.harness import RunResult, Scenario, format_failure, run_entry
from tests.unit.secrets_conformance.sinks import find_leaks

pytestmark = pytest.mark.slow

_ENTRIES = list(entries().values())
_CLIENT_SCENARIOS = {Scenario.CLIENT_FAILURE: "constructed", Scenario.MID_RUN_FAILURE: "called"}


@pytest.fixture
def run(*, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> "RunFactory":
    return RunFactory(workdir=tmp_path, monkeypatch=monkeypatch)


class RunFactory:
    """Runs one entry in one scenario in the test's own working directory."""

    def __init__(self, *, workdir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._workdir = workdir
        self._monkeypatch = monkeypatch

    def __call__(self, *, entry: Entry, scenario: Scenario) -> RunResult:
        return run_entry(entry=entry, scenario=scenario, workdir=self._workdir, monkeypatch=self._monkeypatch)


@pytest.mark.parametrize("scenario", list(Scenario), ids=lambda scenario: scenario.value)
@pytest.mark.parametrize("entry", _ENTRIES, ids=lambda entry: entry.test_id)
def test_no_canary_reaches_any_sink(*, entry: Entry, scenario: Scenario, run: "RunFactory") -> None:
    result = run(entry=entry, scenario=scenario)

    leaks = find_leaks(sinks=result.sinks, canaries=result.canaries)
    assert not leaks, format_failure(entry=entry, scenario=scenario, leaks=leaks, result=result)
    assert result.collector_errors == [], f"{entry.test_id} {scenario.value}: a sink could not be read"
    assert result.provider.calls >= 1, f"{entry.test_id} {scenario.value}: the reference was never resolved"

    if scenario is Scenario.SUCCESS:
        if entry.test_id not in SUCCESS_NEEDS_REAL_SERVER:
            assert not result.failed, f"{entry.test_id}: the success scenario failed: {result.recorded}"
        return
    counter = _CLIENT_SCENARIOS.get(scenario)
    if (entry.test_id, scenario.value) in NOT_REACHED:
        assert counter and getattr(result.clients, counter) == 0, (
            f"{entry.test_id}: the {scenario.value} scenario now reaches a faked client; remove it from NOT_REACHED"
        )
        return
    if counter is None:
        assert result.failed, f"{entry.test_id}: the {scenario.value} scenario did not fail the node"
    if counter:
        # Adapters often record a client error per document instead of failing the node, so only the reach is asserted.
        assert getattr(result.clients, counter) >= 1, (
            f"{entry.test_id}: the {scenario.value} scenario never reached a faked client; "
            "if this is expected, add the pair to NOT_REACHED with the reason"
        )


@pytest.mark.parametrize("pair", sorted(NOT_REACHED), ids=lambda pair: f"{pair[0]}:{pair[1]}")
def test_every_not_reached_pair_names_a_catalog_entry_and_scenario(*, pair: tuple[str, str]) -> None:
    test_id, scenario = pair

    assert test_id in {entry.test_id for entry in _ENTRIES}, f"NOT_REACHED names unknown entry {test_id}"
    assert scenario in {s.value for s in _CLIENT_SCENARIOS}, f"{scenario} is not a client-stage scenario"
