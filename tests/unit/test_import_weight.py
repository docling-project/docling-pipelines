# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Import-weight guards for lightweight CLI paths such as ``--list-operators``.

These run in a fresh interpreter so previously imported modules in the pytest process
cannot mask a regression. They assert on ``sys.modules`` (deterministic) rather than wall-clock time.
"""

import json
import subprocess  # nosec B404 - runs the current interpreter with a fixed script
import sys

HEAVY_MODULES = [
    "torch",
    "transformers",
    "sentence_transformers",
    "spacy",
    "nltk",
    "docling",
    "langchain_text_splitters",
]

_PROBE = """
import json, sys
{body}
print(json.dumps(sorted(m for m in {heavy!r} if m in sys.modules)))
"""


def _loaded_heavy_modules(*, body: str) -> list[str]:
    script = _PROBE.format(body=body, heavy=HEAVY_MODULES)
    result = subprocess.run(  # nosec B603 - fixed args, no user input
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


class TestLightweightImports:
    def test_list_operators_does_not_load_heavy_modules(self):
        body = "from docpipe.utils.operators.display import list_operators\nlist_operators()"
        assert _loaded_heavy_modules(body=body) == []

    def test_source_adapters_still_register_after_importing_registry(self):
        body = (
            "import docpipe.core.operators.operator_registry\n"
            "from docpipe.core.operators.ingest.adapters.outbound.sources.factories.source_factory import "
            "SourceAdapterFactory\n"
            "names = set(SourceAdapterFactory.get_registered_names())\n"
            "assert {'filesystem', 's3', 'sharepoint', 'onedrive', 'web'} <= names, names"
        )
        assert _loaded_heavy_modules(body=body) == []


class TestOperatorBaseImportWeight:
    """``AbstractOperator`` is the import every isolated custom operator worker pays for (task D.3)."""

    def test_operator_base_does_not_load_the_flow_engine(self):
        body = "import docpipe.core.operators.abstract_operator"
        probe = (
            "import json, sys\n"
            f"{body}\n"
            "heavy = ['docling_core', 'pandas', 'docpipe.lib.docpipe_flow_manager', 'docpipe.core.job_management', "
            "'docpipe.core.orchestration.flow_executor']\n"
            "print(json.dumps(sorted(m for m in heavy if m in sys.modules)))"
        )
        result = subprocess.run(  # nosec B603 - fixed args, no user input
            [sys.executable, "-c", probe], capture_output=True, text=True, timeout=240, check=False
        )
        assert result.returncode == 0, result.stderr[-2000:]
        assert json.loads(result.stdout.strip().splitlines()[-1]) == []

    def test_public_flow_manager_import_still_works(self):
        probe = (
            "from docpipe import DocpipeFlowManager\n"
            "import docpipe\n"
            "assert docpipe.DocpipeFlowManager is DocpipeFlowManager\n"
            "assert DocpipeFlowManager.__name__ == 'DocpipeFlowManager'\n"
            "try:\n"
            "    docpipe.not_a_name\n"
            "except AttributeError:\n"
            "    print('ok')\n"
        )
        result = subprocess.run(  # nosec B603 - fixed args, no user input
            [sys.executable, "-c", probe], capture_output=True, text=True, timeout=240, check=False
        )
        assert result.returncode == 0, result.stderr[-2000:]
        assert result.stdout.strip().splitlines()[-1] == "ok"
