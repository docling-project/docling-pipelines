# Proposal

## Why

The slim distribution (`docling-pipelines-slim`) has no way to install the two local providers of the `pii_and_hap` operator. It has no `presidio` extra and no extra that brings in `torch` for the `huggingface` HAP provider. Slim users have to guess package versions, and the errors they get do not help: a missing `torch` shows up as a bare `No module named 'torch'`. The Presidio hints tell users to run `python -m spacy download`, which needs `pip` or a `uv` binary inside the running container. Teams that adopted slim to keep `torch` and other heavy packages out of their images now need these providers, and they need a supported, versioned way to install them.

## What Changes

- Add a `presidio` extra to the slim distribution with the same `presidio-analyzer` pin as the full distribution's `presidio` extra.
- Add a `hap` extra to the slim distribution with the `torch` and `transformers` pins of the full distribution's core dependencies. It does not choose a CPU or CUDA build of `torch`; consumers who need the CPU build install it from PyTorch's CPU index (or a mirror) before installing the extra.
- Replace the bare missing-`torch`/`transformers` error of the `huggingface` HAP provider with an error that names the missing package and the extra that installs it.
- Reword the Presidio missing-package and engine-initialisation errors so they name the extra for both distributions and tell users to install the spaCy model wheel (`<model>==<version>` matching the installed spaCy minor version), not to run `python -m spacy download`.
- Document both providers for slim in `docs/guides/SLIM_VARIANT.md` and fix `docs/operators/quality/pii_and_hap_readme.md`, which says the `huggingface` provider needs no extra install (true only for the full distribution).

No flow JSON, configuration key, REST route or output column changes. Not breaking.

## Non-goals

- Shipping spaCy models through any extra. PyPI rejects packages that depend on direct URLs, and a name-only dependency would resolve from public PyPI, where unrelated packages already squat spaCy model names (for example `de-core-news-md` at version `999.9.9`).
- Selecting the CPU build of `torch` from package metadata. A published package cannot choose the index its dependencies come from; the consumer's installer does.
- Stopping Presidio from downloading a missing spaCy model at runtime, or the `SystemExit` that spaCy raises when that download cannot run. That is a separate change (a Presidio no-download guard).
- Passing the requested entity types to Presidio, multi-language Presidio, per-language recognizer coverage, and an ONNX backend for HAP.
- Changing the full distribution's dependencies.
- An automated check that the slim extras' pins equal the full distribution's. Dependabot updates the root and `slim/` manifests in separate pull requests, so such a check would fail on each of them. The extras follow the same process as the rest of the slim manifest, whose shared pins already match the full distribution's.
- Rejecting unknown keys in Presidio's `provider_config`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `backend/pii-and-hap-operator`: adds requirements for installing the `presidio` and `huggingface` providers on the slim distribution, and for startup errors that name the missing package or spaCy model and how to install it.

## Impact

- **Layer**: backend only. No frontend, BFF, routing or Redux changes; the properties panel is driven by the published config schema, which does not change.
- **REST routes**: none. Validation errors returned by the existing validation endpoints change wording only.
- **Operators**: `pii_and_hap` (the `presidio` and `huggingface` providers). Storage adapters: none.
- **Packaging**: `slim/pyproject.toml` and `slim/uv.lock` (regenerated with `uv lock`). The full distribution's `pyproject.toml` is not changed. Dependabot's existing `/slim` entry picks up the new pins.
- **Code**: `src/docpipe/core/operators/quality/pii_and_hap/adapters/outbound/presidio/adapter.py` and `config.py` (hint and field-description text), `src/docpipe/core/adapters/huggingface/huggingface_adapter.py` (missing-dependency error for detection).
- **Docs**: `docs/guides/SLIM_VARIANT.md`, `docs/operators/quality/pii_and_hap_readme.md`.
- **Tests**: unit tests for the new error messages.
