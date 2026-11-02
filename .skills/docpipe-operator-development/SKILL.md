---
name: docpipe-operator-development
description: >-
  Create or modify built-in docpipe operators that ship from src/docpipe. Use when implementing
  transform behavior, metadata and validation, DOCPIPE_OPERATORS registration, tests, a runnable
  flow, documentation, and changelog updates. Do not use for externally loaded custom operators
  or ingest source connectors.
---

# Built-in Docpipe Operator Development

Deliver a complete built-in operator change that respects the PyArrow data contract, is registered in `DOCPIPE_OPERATORS`, and is verified in isolation and through a runnable flow.

## Scope boundary

Use this skill only when the implementation belongs in this repository and ships with docpipe.

- Set `owner = DocpipeConstants.OWNER_DOCPIPE`.
- Place it under `src/docpipe/core/operators/<category>/` near the closest operator with similar behavior.
- Import it and add the class to `DOCPIPE_OPERATORS` in `src/docpipe/core/operators/operator_registry.py`.
- Never register a built-in through `register_operator_provider()`.

Use `.skills/docpipe-custom-operator/SKILL.md` when a consumer supplies the operator through a file, directory, package, S3 source, or provider hook. Use `.skills/docpipe-ingest-source-adapter/SKILL.md` for new `ingest_source` providers.

## Inspect before implementing

If modifying an operator that already has a spec under `openspec/specs/backend/` (for example `ededup-operator`), read that spec first and follow the OpenSpec change workflow described in `AGENTS.md` before writing code.

Read:

- `src/docpipe/core/operators/abstract_operator.py`;
- the closest current operator in the same category;
- `src/docpipe/core/constants/operator_constants.py` for existing column and config keys;
- `docs/reference/OPERATORS.md` before changing public parameters;
- related operator tests and sample flows.

Reuse existing constants, ports, adapters, and PyArrow helpers. Do not introduce a new abstraction until the operator behavior demonstrates a real need.

Read [references/reference-operators.md](references/reference-operators.md) and inspect only the examples matching the new operator’s table shape or dependency pattern.

## Required implementation contract

Every operator must:

- inherit `AbstractOperator`;
- define non-empty `short_name`, `category`, and `owner = DocpipeConstants.OWNER_DOCPIPE` as class attributes;
- accept configuration in `__init__` and call `super().__init__(config)`;
- accept and pass data between operators as `pa.Table`;
- implement `transform()` returning `tuple[list[pa.Table], dict]`;
- implement `get_metadata()` as `@staticmethod` when exposing parameters or features;
- use `self.create_base_metadata(total_docs_count=...)`;
- record row-level failures and skips with inherited helpers;
- leave orchestration, persistence, and database access outside operator business logic.

Use keyword-only parameters whenever a function has two or more parameters excluding `self` or `cls`. Do not add a legacy `file_name` parameter unless a real caller requires it; if required, make it keyword-only.

## Transform behavior

Define the table semantics before writing code:

- columns read and their PyArrow types;
- columns added, replaced, or removed;
- whether row order and document identifiers are preserved;
- behavior for empty tables, null values, missing columns, and multiple output branches;
- whether failures are row-local or abort the entire operation;
- processed, failed, and skipped metadata accounting.

Return an empty table with a stable schema for valid empty input unless the operator contract explicitly requires an error. Never use `if table:` with `pa.Table`; check `table is not None` and `table.num_rows`.

Use port interfaces for LLM inference, embeddings, text detection, storage, and other external behavior. Do not import concrete adapter implementations into operator business logic.

## Metadata and validation

Operator metadata is the public configuration and feature contract.

- Declare configuration inputs under `OperatorConstants.Config.ATTRIBUTES` with type, requirement, default, description, and bounds or valid values when applicable.
- Declare output columns under `OperatorConstants.Config.FEATURES` with stable names and types.
- Keep metadata defaults aligned with `__init__` defaults.
- Implement `get_required_features()` for upstream columns.
- Add `get_static_required_features()` when required features depend on instance configuration or discovery needs requirements without instantiation.
- Override `validate(errors, warnings, available_features)` for cross-field, range, provider, or runtime-availability rules that metadata cannot express.
- Keep `short_name` identical across the class, metadata, flow `type`, tests, and documentation.

## Logging and errors

- Use `docpipe.utils.infrastructure.logging.get_logger()`.
- Use lazy `%s` arguments in `logger.*()` calls; no f-strings.
- Do not put emoji or non-ASCII characters in Python logging statements.
- Include `extra=self.common_log_arguments` where job context is useful.
- Preserve actionable error context without logging document content or secrets.

## Registration and discovery verification

```bash
source .venv/bin/activate
docling-pipelines --list-operators --verbose
```

Confirm the `short_name`, owner, category, availability, attributes, and features. A successful import without correct discovery is not completion.

## Verification

Add focused unit tests under the matching `tests/unit/operators/` category. At minimum cover:

- valid table and exact output schema or values;
- zero-row input with a typed schema;
- invalid or conflicting configuration;
- missing required column and null values;
- a simulated downstream or port failure;
- processed, skipped, and failed metadata counts;
- registry membership and discovery through the CLI.

Mock external services in unit tests. Use `@pytest.mark.parametrize` rather than loops for input variants. Follow `docs/guides/TESTING_STANDARDS.md` and reuse fixtures from `tests/conftest.py` before creating duplicates.

Create the smallest valid flow with `ingest_source` as the single root, the minimum upstream chain, and the operator under test. Validate it before execution:

```bash
source .venv/bin/activate
docling-pipelines --flow-file /path/to/flow.json --validate
```

For runtime acceptance without relying on test cases, use `.skills/feature-testing-workflow/SKILL.md` and verify actual Parquet values and job metadata.

## Documentation and completion

- create or update `docs/operators/<category>/<operator_name>_readme.md` using the required section order in `docs/guides/DOCUMENTATION_STYLE_GUIDE.md`;
- update `docs/reference/OPERATORS.md` without duplicating the full operator README;
- add or update one focused sample flow when it demonstrates a distinct user scenario.

Every code or documentation change requires an entry under `## [Unreleased]` in `CHANGELOG.md`. Run focused tests, Ruff, formatting, relevant MyPy checks, flow validation, and registration discovery. Report what passed, what was not run, and any required external service.
