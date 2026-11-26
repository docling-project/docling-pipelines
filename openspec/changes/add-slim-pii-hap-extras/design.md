# Design

## Context

See proposal.md (Why) for the motivation and specs/backend/pii-and-hap-operator/spec.md for the requirements.

Current state:

- `slim/pyproject.toml` has no `presidio` and no `hap` extra. `transformers>=5.17.0,<5.18.0` is in its `extract` extra; `torch` is not declared anywhere in slim. The full distribution has `torch==2.15.0` and `transformers>=5.17,<5.18` as core dependencies and `presidio = ["presidio-analyzer==2.2.366"]` as an extra.
- Dependabot has separate `uv` entries for `/` and `/slim`, so one upstream release produces one pull request per manifest.
- The `huggingface` HAP path is layered as: operator adapter `HuggingFaceHAPAdapter` (no torch) -> core `HuggingFaceAdapter` behind `TextDetectionPort` -> integration client `HuggingFaceClassificationClient`, which imports `torch` and `transformers` lazily. A missing `torch` raises `ModuleNotFoundError` inside the client; `HuggingFaceAdapter.validate_detection()` turns it into a validation error whose text is just `No module named 'torch'`.
- `PresidioPIIAdapter.validate()` maps `ImportError` to `PRESIDIO_INSTALL_HINT` (names only the full distribution's extra) and any other exception to a message telling the user to run `python -m spacy download <model>`. The `spacy_model` field description in `PresidioPIIConfig` says the same.
- When a spaCy model is missing, Presidio calls `spacy.cli.download`. spaCy 3.8 installs with `pip`, or with a `uv` binary if `pip` is absent, and raises `SystemExit` (not an `Exception`) when neither works or the install command fails. Those `SystemExit` cases are not changed here (see Risks).

## Goals / Non-Goals

**Goals:**

- Slim consumers install each local provider with one extra and get the versions docpipe is tested with.
- Every startup failure caused by a missing provider package names the package and the extra to install, for both distributions where relevant.
- No error text or config description recommends `python -m spacy download`.

**Non-Goals:**

- Enforcing pin equality between the two manifests (see Decision 2).
- Changing when or how models are loaded, which exceptions are caught, or the operator's output schema and metadata. The spec requirement "Output table and metadata contract unchanged" continues to hold: the new failures happen at startup, before any table is produced.

## Decisions

### 1. One extra per provider, named after the provider

`presidio = ["presidio-analyzer==2.2.366"]` and `hap = ["torch==2.15.0", "transformers>=5.17,<5.18"]` in `slim/pyproject.toml`. spaCy is already a core slim dependency, so `presidio` needs nothing else.

- The name `presidio` matches the full distribution's existing extra, so one instruction (`<distribution>[presidio]`) works for both.
- Providers are independent: a Presidio-only user must not receive `torch`.
- Alternatives considered:
  - A single `pii_and_hap` extra. Rejected: Presidio-only users would get about 1 GB of `torch`, which slim exists to avoid. Consumers who want both write `[presidio,hap]`.
  - No extras, documented versions only. Rejected: consumers would copy pins by hand and never learn when docpipe changes them.
- `transformers` then appears in both `extract` and `hap` with the same range. Overlapping extras are valid and resolve to one install.

### 2. Pins start equal to the full distribution's, with no automated equality check

The initial pins are copied from `pyproject.toml`. Afterwards they are updated by the existing Dependabot `/slim` entry, like every other slim dependency (today 112 of the 113 shared packages have identical pins; the only difference, `transformers`, is the same range written differently).

- Alternative considered: a test that fails when the pins differ. Rejected: Dependabot opens one pull request per manifest, and each would fail that test on its own, so neither could merge without a hand-made edit to the other manifest.
- Alternative considered: grouping both directories into one Dependabot pull request. Out of scope: it changes repository-wide tooling and would apply to every dependency, not only these extras.

### 3. `torch` is pinned without a local version label

`torch==2.15.0`, not `torch==2.15.0+cpu`. Under PEP 440, `==2.15.0` matches `2.15.0+cpu`, so a CPU-only build installed first satisfies the extra and the installer leaves it in place (spec: "CPU-only torch satisfies the hap extra"). Pinning `+cpu` was rejected: PyTorch publishes no `+cpu` wheels for macOS, it would block GPU users, and installs would fail without PyTorch's index configured. Selecting the CPU build stays the consumer's job (a proposal non-goal) and is documented.

### 4. The missing-dependency check lives in the core detection adapter

`HuggingFaceAdapter.validate_detection()` checks that `torch` and `transformers` can be found (`importlib.util.find_spec`) before it creates the classification client. If one is missing, it returns a validation error that names the package, `docling-pipelines-slim[hap]` and the CPU-only build. This keeps the existing layers:

- The operator adapter (`HuggingFaceHAPAdapter`) stays free of `torch` knowledge.
- The integration client stays generic and knows nothing about docpipe's distributions or extras.
- The check runs only on the detection path. The same core adapter also serves local embeddings, whose slim install is covered by the `extract` extra, so its embedding validation is left unchanged.
- No import happens at module load, so importing the operator in a slim install without `torch` still works (spec: "Offline operation").

Alternatives considered: catching the `ImportError` in the classification client (rejected: it would put packaging names into a generic integration module), and checking at import time (rejected: breaks lazy imports and slim imports).

The hint text is a module-level constant next to the existing `_DEFAULT_MODEL_LOAD_HINT`, following the file's current pattern.

### 5. Presidio messages name both extras and the model wheel

- `PRESIDIO_INSTALL_HINT` names `docling-pipelines[presidio]` and `docling-pipelines-slim[presidio]`.
- The engine-initialisation error keeps naming `language` and `spacy_model`, and replaces the `spacy download` instruction with: install the `<spacy_model>` wheel at a version matching the installed spaCy minor version. When spaCy can be imported, the message includes that `major.minor` (for example `3.8`), read from `spacy.about.__version__`; otherwise it omits it.
- The `spacy_model` field description in `PresidioPIIConfig` says the same. That description is published in operator metadata, so the UI shows the new text without frontend changes.
- No document text enters these messages (spec: "No document content in logs or errors").

### 6. Documentation

- `docs/guides/SLIM_VARIANT.md`: rows in the operator table for `pii_and_hap` with `presidio` (`presidio` extra plus a spaCy model the user installs) and with `huggingface` HAP (`hap` extra; install the CPU-only `torch` build first if a GPU is not needed), and install commands for both.
- `docs/operators/quality/pii_and_hap_readme.md`:
  - Fix the provider-table line that says `huggingface` needs no extra install.
  - Update the `spacy_model` row and the two Presidio rows in Troubleshooting.
  - Add a short offline-install subsection: install the CPU-only `torch` build first, install the spaCy model wheel, pre-download the HAP weights, then use `local_files_only` or `HF_HUB_OFFLINE`.
- Follow `docs/guides/DOCUMENTATION_STYLE_GUIDE.md` (section order, fenced code with language tags, relative links).

## Risks / Trade-offs

- [spaCy raises `SystemExit` while downloading a missing model, so the new Presidio message is never shown and the process can exit] -> Out of scope (proposal non-goal); the Troubleshooting entry says to install the model wheel before starting, and a follow-up change adds a guard that checks for the model before Presidio loads it.
- [A consumer installs `slim[hap]` on Linux without installing the CPU-only `torch` build first and gets the CUDA build, several GB] -> Cannot be prevented from package metadata (Decision 3). The `SLIM_VARIANT.md` instructions and the missing-dependency hint both say to install the CPU-only build first.
- [Between the root and `/slim` Dependabot pull requests, the two manifests briefly pin different versions] -> Accepted; this already happens for every shared dependency and is resolved when both pull requests merge.
- [`slim/uv.lock` grows: it now resolves `torch` and, for Linux, its CUDA dependencies] -> Affects only the repository's own lock file; consumers resolve their own environments.
- [`find_spec` finds a package that then fails to import (broken install)] -> The existing load path still reports the import error at startup, so the operator still fails before any document is processed.
- [CI always has `torch` installed, so the missing-package paths are never exercised] -> Unit tests simulate absence by patching `importlib.util.find_spec` and Presidio's import, and assert on the message text.

## Migration Plan

Additive. No flow, config or API migration. After release, slim consumers can replace hand-pinned `presidio-analyzer`, `torch` and `transformers` lines with `docling-pipelines-slim[presidio,hap]`. Rollback is a revert of the pyproject, lock and message changes.
