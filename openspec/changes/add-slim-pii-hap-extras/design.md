# Design

## Context

See proposal.md (Why) for the motivation. The requirements are in specs/backend/provider-extras/spec.md (packaging) and specs/backend/pii-and-hap-operator/spec.md (operator errors).

Current state:

- `slim/pyproject.toml` has no extra for either local provider. `transformers>=5.17.0,<5.18.0` and `sentence-transformers==6.3.0` are in its `extract` extra, together with Docling; `torch` is not declared anywhere in slim. A plain slim install has no `torch`, `transformers`, `sentence-transformers`, `scipy` or `scikit-learn`.
- The full distribution has `torch==2.15.0`, `transformers>=5.17,<5.18` and `sentence-transformers==6.3.0` as core dependencies and `presidio = ["presidio-analyzer==2.2.366"]` as an extra. The `presidio` extra is referenced by the README, the operator docs, one sample flow and the Presidio install hint; no CI job, Docker image or setup script installs it.
- `huggingface` is one provider shared by two operators. The core `HuggingFaceAdapter` serves HAP detection for `pii_and_hap` through `HuggingFaceClassificationClient` (`torch`, `transformers`), and local embeddings for `embeddings` through `HuggingFaceClient` (`sentence-transformers`). The embeddings client already checks for its package with `require_package("sentence_transformers", "pip install sentence-transformers")`, which raises `DependencyError`; the classification client has no such check.
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

### 1. One extra per provider, named exactly after the provider

| Distribution | `presidio` | `huggingface` |
|---|---|---|
| slim | `["presidio-analyzer==2.2.366"]` (new) | `["torch==2.15.0", "transformers>=5.17,<5.18", "sentence-transformers==6.3.0"]` (new) |
| full | unchanged | `[]` (new), with a comment that its packages are core dependencies |

spaCy is already a core dependency of both distributions, so `presidio` needs nothing else.

- The extra name is the provider value the flow already uses: `pii_provider: "presidio"` needs `[presidio]`, and `hap_provider: "huggingface"` or an `embeddings` node with the local `huggingface` provider needs `[huggingface]`. Error messages and docs can name the extra without a lookup table.
- One extra per provider, not per use. Because `huggingface` serves two operators, a single `huggingface` extra covers both. A future local Hugging Face provider in another operator reuses it instead of adding a name with overlapping contents.
- This follows the common convention of naming an extra after the integration it installs, as in Docling (`easyocr`, `rapidocr`), Presidio itself (`transformers`, `stanza`), prefect (`aws`, `docker`) and pymilvus (`model`). It also keeps the existing `presidio` extra as it is.
- The same names exist in both distributions, so one instruction works for either. For example, the `local_redacted_indexing` sample flow, which uses both providers, can say "needs the `presidio` and `huggingface` extras". That is why the full distribution gets an empty `huggingface`.
- Providers are independent: a Presidio-only user does not receive `torch`.
- Alternatives considered:
  - `<capability>-<provider>` names (`pii-presidio`, `hap-huggingface`). Rejected: once local embeddings need an extra too, `hap-huggingface` and an `embeddings-huggingface` would install mostly the same packages. The scheme is also uncommon among comparable projects and would rename the existing `presidio` extra.
  - `presidio` and `hap`. Rejected: one is named after a provider, the other after a capability.
  - `huggingface` without `sentence-transformers`. Rejected: `[huggingface]` would not make the local `huggingface` embeddings provider work, so the name would promise more than it installs.
  - Capability names only (`pii`, `hap`). Rejected: most PII providers (`litellm`, `watsonx`) need no extra, and a second local PII provider would have to share the name.
  - A single `pii_and_hap` extra. Rejected: Presidio-only users would get about 1 GB of `torch`, which slim exists to avoid. Consumers who want both write `[presidio,huggingface]`.
  - No extras, documented versions only. Rejected: consumers would copy pins by hand and never learn when docpipe changes them.
- `transformers` and `sentence-transformers` then appear in both `extract` and `huggingface` in slim with the same pins. Overlapping extras are valid and resolve to one install.

### 2. Pins start equal to the full distribution's, with no automated equality check

The initial slim pins are copied from `pyproject.toml`. Afterwards they are updated by the existing Dependabot entries (`/` for the full manifest, `/slim` for slim), like every other dependency (today 112 of the 113 shared packages have identical pins; the only difference, `transformers`, is the same range written differently).

- Alternative considered: a test that fails when the pins differ. Rejected: Dependabot opens one pull request per manifest, and each would fail that test on its own, so neither could merge without a hand-made edit to the other manifest.
- Alternative considered: grouping both directories into one Dependabot pull request. Out of scope: it changes repository-wide tooling and would apply to every dependency, not only these extras.

### 3. `torch` is pinned without a local version label

`torch==2.15.0`, not `torch==2.15.0+cpu`. Under PEP 440, `==2.15.0` matches `2.15.0+cpu`, so a CPU-only build installed first satisfies the extra and the installer leaves it in place (spec: "CPU-only torch satisfies the huggingface extra"). Pinning `+cpu` was rejected: PyTorch publishes no `+cpu` wheels for macOS, it would block GPU users, and installs would fail without PyTorch's index configured. Selecting the CPU build stays the consumer's job (a proposal non-goal) and is documented.

### 4. Both Hugging Face clients check their packages with the existing helper and one shared hint

- A new constant `ServiceConstants.HUGGINGFACE_INSTALL_HINT` in `core/constants/constants.py` (next to the existing `HUGGINGFACE_HAP_TOXIC_LABELS_HINT`) is a complete install instruction for both distributions, because the code cannot tell which one is installed (both install the `docpipe` package): `pip install "docling-pipelines[huggingface]"` or `pip install "docling-pipelines-slim[huggingface]"`, installing the CPU-only `torch` build first when no GPU is needed. On the full distribution, where these packages are core dependencies, installing the extra also restores a missing core dependency.
- `HuggingFaceClassificationClient.load()` calls `require_package("torch", HINT)` and `require_package("transformers", HINT)` before resolving the device. Today the first `torch` import happens in device resolution, so a missing package currently surfaces as a bare `ModuleNotFoundError`.
- `HuggingFaceClient._initialize_local_model()` keeps its `require_package("sentence_transformers", ...)` call, with the install command replaced by the same hint.
- `require_package` raises `DependencyError` with `"<package> package not installed. Install with: <hint>"`. The existing `validate_detection()` and `validate_embedding()` already turn any exception into a startup validation error, so no adapter or operator code changes.
- The message names the module as Python imports it, for example `sentence_transformers` rather than the distribution name `sentence-transformers`, and the specs say so. Passing a separate display name would mean changing `require_package`, which the litellm and Inference API clients share, for a cosmetic difference.
- `require_package("huggingface_hub", "pip install huggingface_hub")` in the Inference API path of `HuggingFaceClient` stays unchanged. That mode runs remotely and is out of scope (proposal non-goal), and the outdated-hint check in tasks.md does not match it.
- Imports stay inside methods, so importing an operator in a slim install without these packages still works (spec: "Offline operation").

Alternatives considered:
- A `find_spec` check in `HuggingFaceAdapter.validate_detection()` (the earlier plan). Rejected: the embeddings path already checks in its client with `require_package`, so checking in both clients gives one mechanism, one message format and one hint for the whole provider.
- Checking at import time. Rejected: breaks lazy imports and slim installs that never use the provider.

Putting an install hint in the integration clients follows existing practice: both clients already carry `pip install` hints. Because the extra is named after the provider rather than after one operator, the hint is correct for every caller.

### 5. Presidio messages name both extras and the model wheel

- `PRESIDIO_INSTALL_HINT` names `docling-pipelines[presidio]` and `docling-pipelines-slim[presidio]`.
- The engine-initialisation error keeps naming `language` and `spacy_model`, and replaces the `spacy download` instruction with: install the `<spacy_model>` wheel at a version matching the installed spaCy minor version. When spaCy can be imported, the message includes that `major.minor` (for example `3.8`), read from `spacy.about.__version__`; otherwise it omits it.
- The `spacy_model` field description in `PresidioPIIConfig` says the same. That description is published in operator metadata, so the UI shows the new text without frontend changes.
- No document text enters these messages (spec: "No document content in logs or errors").
- When the new engine message appears: with the model missing, Presidio calls `spacy.cli.download`. Without network access, spaCy's request for its compatibility table raises an ordinary exception (`requests.ConnectionError`), which `validate()` catches, so the new message is shown. This is the usual case in locked-down containers. When the server answers with an error, no `pip` or `uv` is available, or the install command fails, spaCy calls `sys.exit` instead. That `SystemExit` bypasses `validate()`, so the spec excludes it until the follow-up no-download guard exists.

### 6. Documentation

- `docs/guides/SLIM_VARIANT.md`: rows in the operator table for `pii_and_hap` with `presidio` (`presidio` extra plus a spaCy model the user installs) and with `huggingface` HAP (`huggingface` extra; install the CPU-only `torch` build first if a GPU is not needed). Change the "embeddings (HuggingFace local provider)" row from `extract` to `huggingface`. Add install commands, and note that `huggingface` also brings `scipy` and `scikit-learn` (through `sentence-transformers`). Also state that the `torch` pin is exact: any `2.15.0` build, CPU or CUDA (for example `2.15.0+cu128`), satisfies it, while a different `torch` version needs the installer's override feature (for example uv's `override-dependencies`).
- `README.md` and `docs/reference/OPERATORS.md` need no change: they describe the full distribution's `presidio` extra, which keeps its name and contents, and neither mentions `spacy download`.
- `docs/operators/functional/embeddings_readme.md`: note that the local `huggingface` provider needs `docling-pipelines-slim[huggingface]` on slim.
- `sample_flows/README.md` and the description in `sample_flows/use_cases/local_redacted_indexing.json`: the flow uses both providers, so they name both extras.
- `docs/operators/quality/pii_and_hap_readme.md`:
  - Fix the provider-table line that says `huggingface` needs no extra install.
  - Update the `spacy_model` row and the two Presidio rows in Troubleshooting.
  - Add a short offline-install subsection: install the CPU-only `torch` build first, install the spaCy model wheel, pre-download the HAP weights, then use `local_files_only` or `HF_HUB_OFFLINE`.
- Follow `docs/guides/DOCUMENTATION_STYLE_GUIDE.md` (section order, fenced code with language tags, relative links).

## Risks / Trade-offs

- [spaCy raises `SystemExit` while downloading a missing model, so the new Presidio message is never shown and the process can exit] -> Out of scope (proposal non-goal); the Troubleshooting entry says to install the model wheel before starting, and a follow-up change adds a guard that checks for the model before Presidio loads it.
- [HAP-only slim users also receive `sentence-transformers`, `scipy` and `scikit-learn`, which HAP does not use: roughly 150 MB installed when `scipy` is not already present, against about 1 GB for `torch`] -> Accepted in exchange for one extra per provider (Decision 1). `SLIM_VARIANT.md` says what the extra brings in; a consumer who needs the smallest HAP install can still pin `torch` and `transformers` directly.
- [A consumer installs `slim[huggingface]` on Linux without installing the CPU-only `torch` build first and gets the CUDA build, several GB] -> Cannot be prevented from package metadata (Decision 3). The `SLIM_VARIANT.md` instructions and the missing-dependency hint both say to install the CPU-only build first.
- [Between the root and `/slim` Dependabot pull requests, the two manifests briefly pin different versions] -> Accepted; this already happens for every shared dependency and is resolved when both pull requests merge.
- [`slim/uv.lock` grows: it now resolves `torch` and, for Linux, its CUDA dependencies] -> Affects only the repository's own lock file; consumers resolve their own environments. The root `uv.lock` changes only in its recorded extra names.
- [CI always has `torch`, `transformers` and `sentence-transformers` installed, so the missing-package paths are never exercised] -> Unit tests simulate absence by setting the module to `None` in `sys.modules` (which makes `__import__` raise `ImportError`) and by patching Presidio's import, and assert on the message text.

## Migration Plan

No flow, config or API migration. After release:

- Slim consumers can replace hand-pinned `presidio-analyzer`, `torch` and `transformers` lines with `docling-pipelines-slim[presidio,huggingface]`.
- Slim consumers who installed `extract` only to get local Hugging Face embeddings can use `huggingface` instead; `extract` keeps working.
- `docling-pipelines[presidio]` keeps working unchanged.

Rollback is a revert of the pyproject, lock, documentation and message changes.
