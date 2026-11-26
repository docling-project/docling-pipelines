# Tasks

## 1. Slim extras

- [ ] 1.1 [backend] Add `presidio = ["presidio-analyzer==2.2.366"]` and `hap = ["torch==2.15.0", "transformers>=5.17,<5.18"]` to `[project.optional-dependencies]` in `slim/pyproject.toml`, with the pins copied from the root `pyproject.toml` at the time of the change; verify by diffing the two files' pins for these three packages.
- [ ] 1.2 [backend] Run `uv lock` in `slim/` and commit `slim/pyproject.toml` and `slim/uv.lock` together; verify `uv lock --check` passes in `slim/`.
- [ ] 1.3 [backend] Build the slim wheel (`cd slim && uv build --wheel`) and install it into a fresh venv with the CPU-only `torch==2.15.0` build installed first, then `[presidio,hap]`; verify `torch.__version__` still ends in `+cpu`, `presidio_analyzer` and `transformers` import, and no spaCy model package was installed.
- [ ] 1.4 [backend] Update `docs/guides/SLIM_VARIANT.md`: operator-table rows for `pii_and_hap` with `presidio` (extra plus a spaCy model wheel the user installs) and with `huggingface` HAP (extra; install the CPU-only `torch` build first when no GPU is needed), plus install commands; verify every code fence has a language tag and every link resolves.

## 2. Hugging Face HAP missing-dependency error

- [ ] 2.1 [backend] In `src/docpipe/core/adapters/huggingface/huggingface_adapter.py`, make `validate_detection()` check `torch` and `transformers` with `importlib.util.find_spec` before creating the classification client, and return a validation error naming the missing package, `docling-pipelines-slim[hap]` and the CPU-only build (hint as a module constant next to `_DEFAULT_MODEL_LOAD_HINT`); verify no new module-level import of either package.
- [ ] 2.2 [backend] Add unit tests in `tests/unit/core/adapters/huggingface/test_huggingface_adapter.py` that patch `find_spec` to report `torch` missing and then `transformers` missing, and assert the validation result is invalid, names the package and the extra, and no client is created; verify they pass with `pytest tests/unit/core/adapters/huggingface -v`.
- [ ] 2.3 [backend] Add a test in `tests/unit/operators/pii_and_hap/test_huggingface_hap_adapter.py` that a `pii_and_hap` operator with `hap_provider: "huggingface"` fails at startup with that message when `torch` is reported missing, before any document is processed; verify it passes.
- [ ] 2.4 [backend] In `docs/operators/quality/pii_and_hap_readme.md`, fix the provider-table line for `huggingface` (no extra on the full distribution; `docling-pipelines-slim[hap]` on slim) and add a Troubleshooting row for the new missing-`torch`/`transformers` error; verify the row's error text matches the constant from 2.1.

## 3. Presidio messages

- [ ] 3.1 [backend] Change `PRESIDIO_INSTALL_HINT` in `presidio/adapter.py` to name `docling-pipelines[presidio]` and `docling-pipelines-slim[presidio]`; verify with a test that patches the Presidio import to fail and asserts both extras appear in the validation error.
- [ ] 3.2 [backend] Change the engine-initialisation error in `PresidioPIIAdapter.validate()` to name `language` and `spacy_model` and tell the user to install the model's wheel matching the installed spaCy `major.minor` (from `spacy.about.__version__`, omitted if spaCy cannot be imported); verify with a test that makes engine creation raise and asserts the model name and version appear and `spacy download` does not.
- [ ] 3.3 [backend] Change the `spacy_model` field description in `presidio/config.py` to the same wheel guidance; verify with a test that the published config JSON schema description contains no `spacy download`.
- [ ] 3.4 [backend] In `docs/operators/quality/pii_and_hap_readme.md`, update the provider-table `presidio` line, the `spacy_model` config row and the two Presidio Troubleshooting rows to name both extras and the model wheel; add an offline-install subsection (CPU-only `torch` first, spaCy model wheel, pre-downloaded HAP weights, `local_files_only` or `HF_HUB_OFFLINE`) and note in Troubleshooting that a missing spaCy model can make spaCy exit while trying to download it; verify `grep -n "spacy download" docs/operators/quality/pii_and_hap_readme.md src/docpipe/core/operators/quality/pii_and_hap` returns nothing.

## 4. Integration checks

- [ ] 4.1 [backend] Run `pytest tests/unit/operators/pii_and_hap tests/unit/core/adapters/huggingface -v` and verify all tests pass.
- [ ] 4.2 [backend] Run `openspec validate add-slim-pii-hap-extras --strict` and verify it passes.
- [ ] 4.3 [backend] Commit with `git commit -s`, run `pre-commit run --from-ref origin/main --to-ref HEAD`, and verify all hooks pass (commit any hook fixes and rerun).

## Workflow follow-up

- Archive the change with `openspec archive add-slim-pii-hap-extras` after review and tests pass.
- Follow-up change: a Presidio guard that checks the spaCy model is installed before Presidio loads it, so a missing model is a validation error instead of a runtime download or `SystemExit`.
