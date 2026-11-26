# Spec Delta

## ADDED Requirements

### Requirement: Local providers installable on the slim distribution
The slim distribution SHALL provide a `presidio` extra that installs the package the `presidio` provider needs, and a `hap` extra that installs the packages the `huggingface` HAP provider needs. Neither extra SHALL declare a spaCy model.

#### Scenario: Presidio on slim
- **WHEN** `docling-pipelines-slim[presidio]` and a spaCy model are installed and a flow sets `pii_provider: "presidio"` with that model as `spacy_model`
- **THEN** flow validation and operator startup succeed without a missing-package error

#### Scenario: Hugging Face HAP on slim
- **WHEN** `docling-pipelines-slim[hap]` is installed, the default HAP model's weights are available, and a flow sets `hap_provider: "huggingface"`
- **THEN** operator startup succeeds without a missing-package error

#### Scenario: No spaCy model in the extras
- **WHEN** `docling-pipelines-slim[presidio]` is installed into an environment without spaCy models
- **THEN** no spaCy model package is installed by the extra

### Requirement: CPU-only torch satisfies the hap extra
The `hap` extra SHALL accept the CPU-only build of the pinned `torch` version, so that a consumer who installs that build first can then install the extra without the installer replacing `torch` or adding GPU libraries.

#### Scenario: CPU build installed first
- **WHEN** the CPU-only build of the pinned `torch` version is installed and `docling-pipelines-slim[hap]` is then installed
- **THEN** the CPU-only `torch` build remains installed and no CUDA library packages are added

### Requirement: Missing HAP provider dependency reported at startup
When `huggingface` is the `hap_provider` and `torch` or `transformers` is not installed, the operator SHALL fail at startup, before any document is processed and before any output table or transform metadata is produced, with an error that names the missing package and the slim `hap` extra, and that states the CPU-only `torch` build can be used.

#### Scenario: Slim without the hap extra
- **WHEN** a flow sets `hap_provider: "huggingface"` in an environment where `torch` is not installed
- **THEN** the operator fails at startup with an error naming `torch`, `docling-pipelines-slim[hap]` and the CPU-only build, and no document is processed

#### Scenario: Transformers missing
- **WHEN** a flow sets `hap_provider: "huggingface"` in an environment where `transformers` is not installed
- **THEN** the operator fails at startup with an error naming `transformers` and `docling-pipelines-slim[hap]`

### Requirement: Missing Presidio package reported at startup
When `presidio` is the `pii_provider` and its package is not installed, the operator SHALL fail at startup, before any document is processed, with an error that names the `presidio` extra of both the full and the slim distribution.

#### Scenario: Slim without the presidio extra
- **WHEN** a flow sets `pii_provider: "presidio"` in an environment where the Presidio package is not installed
- **THEN** the operator fails at startup with an error naming `docling-pipelines[presidio]` and `docling-pipelines-slim[presidio]`, and no document is processed

### Requirement: Presidio engine errors name the spaCy model wheel
When the Presidio engine cannot be initialised, the startup error SHALL name the configured spaCy model and tell the user to install that model's wheel at a version matching the installed spaCy minor version. No startup error or configuration description of the `presidio` provider SHALL tell users to run `python -m spacy download`.

#### Scenario: spaCy model unavailable
- **WHEN** `spacy_model` names a model that is not installed and cannot be obtained
- **THEN** the operator fails at startup with an error naming the model and the wheel to install, and the error does not mention `python -m spacy download`

#### Scenario: Config schema description
- **WHEN** the operator metadata for the `presidio` provider config is requested
- **THEN** the `spacy_model` description tells users to install the model wheel and does not mention `python -m spacy download`
