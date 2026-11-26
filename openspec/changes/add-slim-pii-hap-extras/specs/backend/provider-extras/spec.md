# Spec Delta

## Purpose

Defines how the optional local providers of docpipe operators are installed through package extras in the full and slim distributions, what each extra installs, and how a missing provider package is reported.

## ADDED Requirements

### Requirement: Extra name equals provider name
Each optional local provider SHALL be installable through an extra whose name equals the provider value that flows use to select it: `presidio` for the `presidio` provider and `huggingface` for the `huggingface` provider of every operator that offers it. Both the full and the slim distribution SHALL expose these extras. Where a distribution already has an extra's packages as core dependencies, the extra SHALL install nothing more.

#### Scenario: Same install command on both distributions
- **WHEN** either distribution is installed with `[presidio,huggingface]`, a spaCy model is installed, and the default HAP model's weights are available
- **THEN** a flow with `pii_provider: "presidio"` and `hap_provider: "huggingface"` starts without a missing-package error

#### Scenario: Full distribution's huggingface extra
- **WHEN** the full distribution is installed with `[huggingface]`
- **THEN** no package is installed beyond the full distribution's core dependencies

### Requirement: Presidio extra contents
The `presidio` extra SHALL install the package the `presidio` PII provider needs. It SHALL NOT declare a spaCy model.

#### Scenario: Presidio on slim
- **WHEN** `docling-pipelines-slim[presidio]` and a spaCy model are installed and a flow sets `pii_provider: "presidio"` with that model as `spacy_model`
- **THEN** flow validation and operator startup succeed without a missing-package error

#### Scenario: No spaCy model in the extra
- **WHEN** `docling-pipelines-slim[presidio]` is installed into an environment without spaCy models
- **THEN** no spaCy model package is installed by the extra

### Requirement: Hugging Face extra contents
On the slim distribution, the `huggingface` extra SHALL install the packages needed by the `huggingface` HAP provider of `pii_and_hap` and by the local `huggingface` provider of `embeddings`, without requiring the `extract` extra.

#### Scenario: Hugging Face HAP on slim
- **WHEN** `docling-pipelines-slim[huggingface]` is installed, the default HAP model's weights are available, and a flow sets `hap_provider: "huggingface"`
- **THEN** operator startup succeeds without a missing-package error

#### Scenario: Local Hugging Face embeddings on slim
- **WHEN** `docling-pipelines-slim[huggingface]` is installed without the `extract` extra, the embedding model is available locally, and an `embeddings` node uses the local `huggingface` provider
- **THEN** operator startup succeeds without a missing-package error

### Requirement: CPU-only torch satisfies the huggingface extra
The `huggingface` extra SHALL accept the CPU-only build of the pinned `torch` version, so that a consumer who installs that build first can then install the extra without the installer replacing `torch` or adding GPU libraries.

#### Scenario: CPU build installed first
- **WHEN** the CPU-only build of the pinned `torch` version is installed and `docling-pipelines-slim[huggingface]` is then installed
- **THEN** the CPU-only `torch` build remains installed and no CUDA library packages are added

### Requirement: Missing Hugging Face package names the extra
When a `huggingface` provider needs a module that is not installed (`torch` or `transformers` for HAP, `sentence_transformers` for local embeddings), the startup error SHALL name that module as Python imports it, give install commands for both `docling-pipelines[huggingface]` and `docling-pipelines-slim[huggingface]`, and state that the CPU-only `torch` build can be used. It SHALL NOT tell the user to `pip install` the single package.

#### Scenario: Local embeddings without sentence-transformers
- **WHEN** an `embeddings` node uses the local `huggingface` provider in an environment where `sentence-transformers` is not installed
- **THEN** startup fails with an error naming `sentence_transformers`, `docling-pipelines[huggingface]` and `docling-pipelines-slim[huggingface]`, and the error does not say `pip install sentence-transformers`
