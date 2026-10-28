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
