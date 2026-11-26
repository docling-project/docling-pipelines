# Proposal

## Why

The slim distribution (`docling-pipelines-slim`) has no supported way to install docpipe's local `presidio` and `huggingface` providers. It has no extra for Presidio. The `huggingface` provider serves both HAP detection in `pii_and_hap` and local embeddings in `embeddings`, and the only slim extra that brings in its packages is `extract`, which also installs Docling. For HAP, even `extract` is not enough, because nothing in slim declares `torch`. Slim users have to guess package versions, and the errors they get do not help: a missing `torch` shows up as a bare `No module named 'torch'`. The Presidio hints tell users to run `python -m spacy download`, which needs `pip` or a `uv` binary inside the running container. Teams that adopted slim to keep `torch` and other heavy packages out of their images now need these providers, and they need a supported, versioned way to install them.

## What Changes

- Name each provider extra exactly after the provider value that flows use to select it: `presidio` for `pii_provider: "presidio"`, and `huggingface` for the `huggingface` provider wherever it appears (`hap_provider: "huggingface"` in `pii_and_hap`, and the local `huggingface` provider in `embeddings`). Both distributions expose both names, so one install instruction works for either.
- Slim: add `presidio` with the full distribution's `presidio-analyzer` pin, and `huggingface` with the full distribution's core pins of `torch`, `transformers` and `sentence-transformers`. `huggingface` does not choose a CPU or CUDA build of `torch`; consumers who need the CPU build install it from PyTorch's CPU index (or a mirror) before installing the extra.
- Full: keep the existing `presidio` extra unchanged, and add an empty `huggingface` extra, because its packages are already core dependencies there.
- Replace the bare missing-`torch`/`transformers` error of the `huggingface` HAP provider with an error that names the missing module and gives install commands for both `docling-pipelines[huggingface]` and `docling-pipelines-slim[huggingface]`. Point the local embeddings provider's missing-`sentence-transformers` error, which says `pip install sentence-transformers` today, at the same extra.
- Reword the Presidio missing-package and engine-initialisation errors so they name the extra for both distributions and tell users to install the spaCy model wheel (`<model>==<version>` matching the installed spaCy minor version), not to run `python -m spacy download`.
- Document both providers for slim in `docs/guides/SLIM_VARIANT.md`, including local Hugging Face embeddings, which move from the `extract` extra to `huggingface`. Fix `docs/operators/quality/pii_and_hap_readme.md`, which says the `huggingface` provider needs no extra install (true only for the full distribution), and note the slim extra in `docs/operators/functional/embeddings_readme.md`.
- Update the `local_redacted_indexing` sample flow's description and its row in `sample_flows/README.md`, which list the extras it needs, to name `presidio` and `huggingface`.

No flow JSON, configuration key, REST route or output column changes. Not breaking: the existing `presidio` extra keeps its name and contents, and the `extract` extra is unchanged.

## Non-goals

- Shipping spaCy models through any extra. PyPI rejects packages that depend on direct URLs, and a name-only dependency would resolve from public PyPI, where unrelated packages already squat spaCy model names (for example `de-core-news-md` at version `999.9.9`).
- Selecting the CPU build of `torch` from package metadata. A published package cannot choose the index its dependencies come from; the consumer's installer does.
- Stopping Presidio from downloading a missing spaCy model at runtime, or the `SystemExit` that spaCy raises when that download cannot run. That is a separate change (a Presidio no-download guard).
- Passing the requested entity types to Presidio, multi-language Presidio, per-language recognizer coverage, and an ONNX backend for HAP.
- Changing any dependency or pin of the full distribution; it only gains the empty `huggingface` extra.
- Changing the slim `extract` extra, which keeps its own `transformers` and `sentence-transformers` entries.
- Improving errors of the Hugging Face Inference API mode of `embeddings`, which runs remotely and needs none of these packages.
- An automated check that the slim extras' pins equal the full distribution's. Dependabot updates the root and `slim/` manifests in separate pull requests, so such a check would fail on each of them. The extras follow the same process as the rest of the slim manifest, whose shared pins already match the full distribution's.
- Rejecting unknown keys in Presidio's `provider_config`.

## Capabilities

### New Capabilities

- `backend/provider-extras`: how the optional local providers of docpipe operators are installed through package extras in the full and slim distributions (one extra per provider, named after it), what each extra installs, and how a missing provider package is reported.

### Modified Capabilities

- `backend/pii-and-hap-operator`: adds requirements for the operator's startup errors when a Presidio or Hugging Face package or a spaCy model is missing, naming what to install.

## Impact

- **Layer**: backend only. No frontend, BFF, routing or Redux changes; the properties panel is driven by the published config schema, which does not change.
- **REST routes**: none. Validation errors returned by the existing validation endpoints change wording only.
- **Operators**: `pii_and_hap` (the `presidio` and `huggingface` providers) and `embeddings` (the local `huggingface` provider). Storage adapters: none.
- **Packaging**: `pyproject.toml` (one empty extra, and the `presidio` extra's comment, which still recommends `spacy download`), `uv.lock`, `slim/pyproject.toml` (two extras, plus the root manifest's `numpy` override so `presidio-analyzer`'s `numpy<2.5.0` cap does not lower `numpy` for all slim installs) and `slim/uv.lock` (both lock files regenerated with `uv lock`). Dependabot's existing `/` and `/slim` entries keep the new pins up to date.
- **Code**:
  - `src/docpipe/core/constants/constants.py`: one shared Hugging Face install hint.
  - `src/docpipe/integrations/huggingface/classification_client.py`: missing `torch`/`transformers` check for HAP.
  - `src/docpipe/integrations/huggingface/client.py`: the embeddings hint.
  - `src/docpipe/core/operators/quality/pii_and_hap/adapters/outbound/presidio/adapter.py` and `config.py`: hint and field-description text.
- **Docs and samples**: `docs/guides/SLIM_VARIANT.md`, `docs/operators/quality/pii_and_hap_readme.md`, `docs/operators/functional/embeddings_readme.md`, `sample_flows/README.md`, `sample_flows/use_cases/local_redacted_indexing.json` (description only).
- **Tests**: unit tests for the new error messages.
