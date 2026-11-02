# Contributing to docling-pipelines

Thank you for your interest in contributing to docling-pipelines! This guide will help you get started with contributing to the project.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Development Workflow](#development-workflow)
- [Code Style Guidelines](#code-style-guidelines)
- [Testing Requirements](#testing-requirements)
- [Pull Request Process](#pull-request-process)
- [Commit Message Guidelines](#commit-message-guidelines)
- [Documentation Requirements](#documentation-requirements)
- [Getting Help](#getting-help)

## Code of Conduct

Please read [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for the project’s conduct policy. See
[COMMUNITY.md](COMMUNITY.md) for project-specific reporting contacts and escalation details.

## Getting Started

### Prerequisites

- **Python 3.12** (required)
- **uv** package manager ([installation guide](https://docs.astral.sh/uv/))
- **Git** for version control
- **Ollama** (optional, for LLM operators)
- **OpenSearch** (optional, for vector database operators)

### Fork and Clone

1. Fork the repository on GitHub
2. Clone your fork locally:

```bash
git clone https://github.com/YOUR-USERNAME/docling-pipelines.git
cd docling-pipelines
```

3. Add the upstream repository:

```bash
git remote add upstream https://github.com/ORIGINAL-OWNER/docling-pipelines.git
```

## Development Setup

### Quick Setup (Automated)

Use the automated setup script for a complete environment:

```bash
./scripts/setup_docling_pipelines_environment.sh
```

This installs Python 3.12, uv, Ollama, OpenSearch, and all dependencies.

### Manual Setup

1. **Install uv** (if not already installed):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

2. **Install dependencies**:

```bash
# From project root
uv sync --extra dev
```

3. **Activate the virtual environment**:

```bash
# From project root
source .venv/bin/activate
```

4. **Install pre-commit hooks**:

```bash
# From project root
uv run pre-commit install
```

### Verify Installation

Run tests to verify your setup:

```bash
# From project root with activated venv
pytest -v
```

## Development Workflow

### Branch Naming Conventions

Use descriptive branch names following these patterns:

- `feature/description` - New features
- `fix/description` - Bug fixes
- `docs/description` - Documentation updates
- `refactor/description` - Code refactoring
- `test/description` - Test additions or modifications

Examples:
- `feature/add-pdf-extractor`
- `fix/opensearch-connection-timeout`
- `docs/update-api-reference`

### Creating a Feature Branch

1. **Sync with upstream**:

```bash
git checkout main
git pull upstream main
```

2. **Create your feature branch**:

```bash
git checkout -b feature/your-feature-name
```

### Making Changes

1. **Make your changes** following the [Code Style Guidelines](#code-style-guidelines)

2. **Run code quality checks**:

```bash
# Run pre-commit hooks on committed branch changes (from project root)
pre-commit run --from-ref origin/main --to-ref HEAD

# Or run individual tools (from project root)
uv run ruff check --fix .
uv run ruff format .
uv run mypy .
```

3. **Run tests**:

```bash
# From project root with activated venv
uv run pytest -v

# Run with coverage
uv run pytest -v --cov=src --cov-report=html
```

4. **Commit your changes** following [Commit Message Guidelines](#commit-message-guidelines)

### Job Metadata Aggregation Reminder

If your change adds or modifies operator-emitted metadata used in job stats:
- review [`DEFAULT_STRATEGIES`](src/docpipe/core/job_management/application/aggregation/strategies.py) in [`strategies.py`](src/docpipe/core/job_management/application/aggregation/strategies.py)
- add or update aggregation tests when the field should not use the default `LAST` behavior
- update [`docs/internals/NODE_METADATA_AGGREGATION_STRATEGY.md`](docs/internals/NODE_METADATA_AGGREGATION_STRATEGY.md) when the change introduces a new aggregation pattern or maintainer rule

## Code Style Guidelines

### Python Style Guide

We follow **PEP 8** with some project-specific conventions:

#### Line Length
- Maximum line length: **120 characters**

#### Import Organization

Imports should be organized in the following order:
1. Standard library imports
2. Third-party imports
3. Local application imports

Add a blank line between each import group.

Use `ruff` for automatic import sorting:

```bash
uv run ruff check --fix .
```

#### Type Hints

- **Always use type hints** for function parameters and return values
- Use `typing` module for complex types

```python
from typing import List, Dict, Optional

def process_documents(
    file_paths: List[str],
    config: Dict[str, any],
    batch_size: Optional[int] = None
) -> List[Dict[str, any]]:
    """Process documents with given configuration."""
    pass
```

#### Naming Conventions

- **Classes**: `PascalCase` (e.g., `DocumentProcessor`, `VectorDBOperator`)
- **Functions/Methods**: `snake_case` (e.g., `process_document`, `get_embeddings`)
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `MAX_BATCH_SIZE`, `DEFAULT_TIMEOUT`)
- **Private methods**: Prefix with `_` (e.g., `_validate_config`)

#### String Quotes

- Use **double quotes** for strings: `"example"`
- Configured automatically by `ruff format`

#### Documentation Standards

- **Docstrings**: Use Google-style docstrings for all public functions and classes
- **Comments**: Use inline comments sparingly, prefer self-documenting code

```python
def extract_text(file_path: str, use_ocr: bool = False) -> str:
    """Extract text content from a document.

    Args:
        file_path: Path to the document file
        use_ocr: Whether to use OCR for image-based documents

    Returns:
        Extracted text content

    Raises:
        FileNotFoundError: If the file does not exist
        ValueError: If the file format is not supported
    """
    pass
```

### Operator Development Guidelines

#### For Operator Users: Accessing Operator Metadata

Use the [`OperatorMetadata`](src/docpipe/core/operators/operator_metadata.py) class to query metadata about available operators, their features, and requirements:

```python
from docpipe.core.operators.operator_metadata import OperatorMetadata

# Initialize metadata manager
metadata = OperatorMetadata()

# Get metadata for all operators
all_operators = metadata.get_operator_metadata(internal_features=False)

# Access specific operator information
extract_meta = all_operators['extract_operator']
print(extract_meta['label'])           # "Extract Operator"
print(extract_meta['category'])        # "Extract"
print(extract_meta['required_features'])  # []

# Get features from a specific operator
features = metadata.get_features(short_name="extract_operator")

# Get only filterable features
filterable = metadata.get_features(
    short_name="extract_operator",
    purpose=OperatorConstants.Config.AVAILABLE_FOR_FILTER
)

# Get required input features for an operator
required = metadata.required_feature_names(short_name="chunker")
print(required)  # ['content']

# Build feature-to-operator mapping
feature_map = metadata.get_feature_operators_map()
print(feature_map['content'])  # ['Extract Docling', 'Extract Entities (Ollama)']
```

**Key Methods:**

- `get_operator_metadata()`: Returns metadata for all registered operators
- `get_features()`: Gets features from a specific operator, optionally filtered by purpose
- [`required_feature_names()`](src/docpipe/core/operators/operator_metadata.py:255): Returns list of required input features for an operator
- [`get_feature_operators_map()`](src/docpipe/core/operators/operator_metadata.py:278): Builds reverse mapping from features to operators that produce them

#### For Operator Developers: Implementing Metadata Methods

When creating new operators, you **must implement** two static methods so [`OperatorMetadata`](src/docpipe/core/operators/operator_metadata.py) can discover and aggregate your operator's information:

**Required Static Methods:**

```python
@staticmethod
def get_metadata() -> dict[str, Any]:
    """Return operator metadata for discovery by OperatorMetadata class."""
    return {
        OperatorConstants.Misc.CATEGORY: MyOperator.category.value,
        OperatorConstants.Misc.IS_OPERATOR_AVAILABLE: MyOperator.is_available(),
        OperatorConstants.Misc.LABEL: "My Custom Operator",
        OperatorConstants.Misc.DESCRIPTION: "Description of what this operator does",
        OperatorConstants.Config.FEATURES: {
            "output_feature": {
                "type": "string",
                "description": "Feature produced by this operator",
                "required": False,
                "available_for_filter": True,
                "available_for_vector_db": True,
            }
        }
    }

@staticmethod
def get_required_features() -> list[str]:
    """Return list of required input feature names."""
    return [OperatorConstants.Columns.DOC_COLUMN_DEFAULT]
```

**Implementation Requirements:**

- **Static Methods**: Use `@staticmethod` decorator - these methods must not access instance state
- **Class-Level Attributes**: Reference class attributes (e.g., `MyOperator.category`, `MyOperator.is_available()`)
- **No Instance Access**: Do not use `self` - information must be determinable without instantiation
- **Type Hints**: Always include return type annotations
- **Metadata Keys**: Use constants from `OperatorConstants`

**Complete Example:**

```python
from typing import Any
import pyarrow as pa
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory

class MyCustomOperator(AbstractOperator):
    """Custom operator that processes documents."""

    short_name: str = OperatorConstants.Operators.MY_CUSTOM
    category: OperatorCategory = OperatorCategory.Functional
    owner: str = "custom"  # REQUIRED: Identifies this as a custom operator

    def __init__(self, *, config: dict[str, Any]) -> None:
        """Initialize with runtime configuration."""
        super().__init__(config=config)
        # Instance-level configuration from flow JSON
        self.param1 = config.get("param1")

    @staticmethod
    def get_metadata() -> dict[str, Any]:
        """Provide metadata for OperatorMetadata discovery.

        This static method is called by OperatorMetadata.get_operator_metadata()
        to collect information about this operator without instantiation.
        """
        return {
            OperatorConstants.Misc.CATEGORY: OperatorCategory.Functional.value,
            OperatorConstants.Misc.IS_OPERATOR_AVAILABLE: MyCustomOperator.is_available(),
            OperatorConstants.Misc.LABEL: "My Custom Operator",
            OperatorConstants.Misc.DESCRIPTION: "Processes documents with custom logic",
            OperatorConstants.Config.FEATURES: {
                "processed_content": {
                    "type": "string",
                    "description": "Processed document content",
                    "required": False,
                    "available_for_filter": True,
                    "available_for_vector_db": True,
                }
            }
        }

    @staticmethod
    def get_required_features() -> list[str]:
        """Specify required input features.

        This static method is called by OperatorMetadata to determine
        what features this operator needs from previous operators.
        """
        return [OperatorConstants.Columns.DOC_COLUMN_DEFAULT]

    def transform(self, table: pa.Table) -> tuple[list[pa.Table], dict[str, Any]]:
        """Process PyArrow table using instance configuration."""
        # Implementation using self.param1 and other instance attributes
        pass

### Built-in Docling Pipelines Operator Requirements

When creating built-in docpipe operators (operators that ship with the docpipe package), you **must**:

1. **Set the owner attribute explicitly:**
   ```python
   from docpipe.core.constants.constants import DocpipeConstants

   class MyDocpipeOperator(AbstractOperator):
       short_name: str = "my_docpipe_operator"
       category: OperatorCategory = OperatorCategory.Functional
       owner: str = DocpipeConstants.OWNER_DOCPIPE  # REQUIRED for built-in operators
   ```

2. **Import DocpipeConstants:**
   All built-in operators must import `DocpipeConstants` to access the `OWNER_DOCPIPE` constant:
   ```python
   from docpipe.core.constants.constants import DocpipeConstants
   ```

3. **Follow all other operator requirements** (implement `get_metadata()`, `get_required_features()`, etc.)

4. **Register the operator in the operator registry:**

   All built-in docpipe operators must be registered in the operator registry frozenset to be discoverable by the operator factory.

   **Steps to register:**

   a. Add the import in [`src/docpipe/core/operators/operator_registry.py`](src/docpipe/core/operators/operator_registry.py):
   ```python
   from docpipe.core.operators.quality.my_operator import MyOperator
   ```

   b. Add the operator class to the `DOCPIPE_OPERATORS` frozenset in the appropriate category section:
   ```python
   DOCPIPE_OPERATORS = frozenset(
       {
           # ... other operators ...
           # Quality
           MyOperator,  # Add your operator here
           # ... other operators ...
       }
   )
   ```

   **Important:** Without registration in the frozenset, the operator will not be loaded by the operator factory and will fail with "Failed to get operator" errors when used in flows.

   **Verification:** After registration, verify the operator appears in the list:
   ```bash
   docling-pipelines --list-operators
   ```

### Custom Operator Requirements

When creating custom operators, you **must**:

1. **Set the owner attribute as a class variable:**

   The `owner` attribute must be declared at the class level, alongside `short_name` and `category`.

   **To override an existing docpipe operator**, use the **same `short_name`** as the docpipe operator:

   ```python
   class CustomChunkerOperator(AbstractOperator):
       """Custom chunker that overrides docpipe's chunker."""

       short_name: str = OperatorConstants.Operators.CHUNKER  # Same as docpipe!
       category: OperatorCategory = OperatorCategory.Functional
       owner: str = "custom"  # REQUIRED: Gives priority 1 (overrides docpipe)

       def __init__(self, *, config: dict[str, Any]) -> None:
           super().__init__(config=config)
   ```

   **To create a new custom operator**, use a unique `short_name`:

   ```python
   class MyNewOperator(AbstractOperator):
       """Completely new custom operator."""

       short_name: str = "my_new_operator"  # Unique name
       category: OperatorCategory = OperatorCategory.Functional
       owner: str = "custom"  # REQUIRED: Must be set to "custom"

       def __init__(self, *, config: dict[str, Any]) -> None:
           super().__init__(config=config)
   ```

   **Why This Matters:**
   - Custom operators with `owner="custom"` receive **priority 100**
   - Docling Pipelines operators with `owner="docpipe"` receive **priority 200**
   - When both have the same `short_name`, only the custom operator (priority 100) is loaded
   - Without setting `owner="custom"`, your operator inherits `owner=None` from `AbstractOperator`, which will be treated as a custom operator
   - The `owner` attribute appears in operator metadata returned by `get_operator_metadata()`
   - **All built-in docpipe operators must explicitly set** `owner = DocpipeConstants.OWNER_DOCPIPE`
   - To register a tier with higher precedence than `OWNER_CUSTOM`, see [External Operator Integration — Registering a Custom Priority Tier](docs/guides/EXTERNAL_OPERATOR_INTEGRATION.md#registering-a-custom-priority-tier)

2. **Use keyword-only arguments:**
   All function parameters must use `*` to enforce keyword-only arguments:
   ```python
   def __init__(self, *, config: dict[str, Any]) -> None:
       super().__init__(config=config)
   ```

3. **Implement required static methods:**
   - `get_metadata()` - Returns operator metadata
   - `get_required_features()` - Returns required input features

4. **Follow the operator contract:**
   - Inherit from `AbstractOperator`
   - Implement `transform()` method
   - Return `tuple[list[pa.Table], dict[str, Any]]`

### Environment Variables for Custom Operators

**DOCPIPE_CUSTOM_OPERATORS:**

Comma-separated list of Python package paths containing custom operators.

```bash
export DOCPIPE_CUSTOM_OPERATORS="my_company.operators,another_package.ops"
```

**Requirements:**
- Must be a string value (non-string values are ignored with a warning)
- Package paths separated by commas
- Packages must be importable from PYTHONPATH

**DOCPIPE_ENABLE_CUSTOM_OPERATORS:**

Boolean flag to enable/disable custom operator loading (default: `true`).

```bash
export DOCPIPE_ENABLE_CUSTOM_OPERATORS="true"  # or "false"
```

**Validation:**

The operator factory validates the `DOCPIPE_CUSTOM_OPERATORS` environment variable to ensure it's a string. Non-string values will trigger a warning and be ignored to prevent factory initialization failures. See [`OperatorFactory`](src/docpipe/core/orchestration/operator_factory.py:35) for implementation.

```

**Why Static Methods?**

The static method pattern enables [`OperatorMetadata`](src/docpipe/core/operators/operator_metadata.py) to:
- Discover operator capabilities without instantiation
- Validate flows before execution
- Build feature dependency graphs
- Provide metadata to UI and API consumers
- Improve performance by avoiding unnecessary object creation

**Distinction Between Class and Instance:**

- **Class-level information** (static methods): Operator capabilities, features, and requirements - same for all instances
- **Instance-level configuration** (`__init__`): Runtime parameters from flow JSON - specific to each operator instance in a pipeline

### Code Quality Tools

The project uses the following tools (configured in `pyproject.toml`):

- **Ruff**: Linting and formatting (replaces black, isort, flake8)
- **mypy**: Static type checking
- **detect-secrets**: Prevent committing secrets

All tools run automatically via pre-commit hooks.

## Testing Requirements

### Test Organization

Tests are organized by type:

- **Unit tests**: `tests/unit/` - Fast, isolated tests
- **Integration tests**: `tests/integration/` - Tests with external dependencies

### Writing Tests

1. **Create test files** matching the pattern `test_*.py`
2. **Use pytest fixtures** from `tests/conftest.py`
3. **Mark tests appropriately**:

```python
import pytest

@pytest.mark.unit
def test_document_processor():
    """Test document processing logic."""
    pass

@pytest.mark.integration
def test_opensearch_integration():
    """Test OpenSearch integration."""
    pass
```

### Running Tests

#### Default Behavior (All Tests)

By default, **all tests run locally** without any filtering:

```bash
# Run all tests (including slow tests)
pytest -v

# Run all tests with coverage
pytest -v --cov=src --cov-report=html
```

#### Filtering Tests by Speed

The project uses pytest markers to categorize tests by execution speed. This allows you to run fast tests during development and slow tests before committing changes.

**Run only fast tests (exclude slow tests):**

```bash
# Exclude slow tests - useful for rapid development iteration
pytest -v -m "not slow"
```

**Run only slow tests:**

```bash
# Run only slow tests - useful before committing changes
pytest -v -m slow
```

**Why filter by speed?**
- **Fast tests** (< 1 second): Run frequently during development for quick feedback
- **Slow tests**: Run before committing to ensure comprehensive validation
- **CI/CD**: GitHub Actions CI excludes slow tests to keep build times reasonable

#### The @pytest.mark.slow Marker

Mark slow-running tests (> 1 second) with the `@pytest.mark.slow` decorator:

```python
import pytest

@pytest.mark.slow
def test_extract_operator_with_large_document():
    """Test extraction on large documents (slow test)."""
    # This test takes several seconds to complete
    pass

def test_extract_operator_basic():
    """Test basic extraction (fast test)."""
    # This test completes in < 1 second
    pass
```

**When to use @pytest.mark.slow:**
- Tests that process large documents or datasets
- Tests with external service calls (even with mocking if slow)
- Tests that perform complex computations
- Tests that take > 1 second to complete

**Important for ExtractOperator developers:**
- Always run slow tests before committing changes to ExtractOperator
- Slow tests validate complex extraction scenarios and edge cases
- Use `pytest -v -m slow tests/unit/operators/extract/` to run ExtractOperator slow tests

#### Filtering by Test Type

```bash
# Run only unit tests
pytest -m unit -v

# Run only integration tests
pytest -m integration -v

# Run fast unit tests only
pytest -m "unit and not slow" -v

# Run specific test file
pytest tests/unit/operators/test_chunker.py -v
```

#### Local vs CI Testing

**Local Development:**
- All tests run by default (no filtering unless you specify markers)
- Use `-m "not slow"` during rapid development for faster feedback
- Run slow tests before committing with `-m slow`

**GitHub Actions CI:**
- Automatically excludes slow tests to maintain reasonable build times
- Configured in the CI workflow with `-m "not slow"`
- Ensures fast feedback on pull requests

**Best Practice:**
```bash
# During development (fast feedback)
pytest -v -m "not slow"

# Before committing (comprehensive validation)
pytest -v

# Before committing ExtractOperator changes (critical validation)
pytest -v -m slow tests/unit/operators/extract/
```

### Test Coverage Expectations

- **New features**: Minimum 80% coverage
- **Bug fixes**: Add tests that reproduce the bug
- **Critical paths**: Aim for 90%+ coverage

View coverage report:

```bash
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
```

### Test Best Practices

- Write clear, descriptive test names
- One assertion per test when possible
- Use fixtures for common setup
- Mock external dependencies in unit tests
- Clean up resources in teardown

## Pull Request Process

### Before Submitting

1. **Sync with upstream main**:

```bash
git checkout main
git pull upstream main
git checkout your-feature-branch
git rebase main
```

2. **Run all checks**:

```bash
# Code quality for committed branch changes (from project root)
pre-commit run --from-ref origin/main --to-ref HEAD

# Tests (from project root)
uv run pytest -v --cov=src
```

3. **Update documentation** if needed (see [Documentation Requirements](#documentation-requirements))

### PR Title Format

Use clear, descriptive titles following this format:

```
<type>: <short description>
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `refactor`: Code refactoring
- `test`: Test additions or modifications
- `chore`: Maintenance tasks

Examples:
- `feat: Add semantic chunking operator`
- `fix: Resolve OpenSearch connection timeout`
- `docs: Update API reference for VectorDB operator`

### PR Description

Include in your PR description:

1. **Summary**: Brief overview of changes
2. **Motivation**: Why this change is needed
3. **Changes**: Detailed list of modifications
4. **Testing**: How you tested the changes
5. **Screenshots**: If applicable (UI changes)
6. **Breaking Changes**: If any
7. **Related Issues**: Link to related issues

Template:

```markdown
## Summary
Brief description of the changes

## Motivation
Why this change is needed

## Changes
- Change 1
- Change 2
- Change 3

## Testing
- [ ] Unit tests added/updated
- [ ] Integration tests added/updated
- [ ] Manual testing performed

## Breaking Changes
None / List any breaking changes

## Related Issues
Closes #123
```

### Required Checks

All PRs must pass:

- ✅ Pre-commit hooks (ruff, mypy, detect-secrets)
- ✅ Unit tests
- ✅ Integration tests (if applicable)
- ✅ Code coverage threshold
- ✅ Documentation updates (if needed)
- ✅ All commits carry a `Signed-off-by` trailer (DCO — see [DCO Sign-off](#dco-sign-off) below)
- ✅ All commits are GPG-verified (see [Verified Commits](#verified-commits) below)

### Review Process

1. **Automated checks** run on PR submission
2. **Maintainer review** - typically within 2-3 business days
3. **Address feedback** - make requested changes
4. **Approval** - at least one maintainer approval required
5. **Merge** - maintainer will merge after approval

### Merge Requirements

- All checks passing
- At least one maintainer approval
- No unresolved conversations
- Up-to-date with main branch
- **All commits must include a `Signed-off-by` trailer** — the DCO bot blocks merging without it
- **All commits must be GPG-verified** — PRs containing unverified commits will not be merged

### DCO Sign-off

Every commit must carry a `Signed-off-by` trailer. This is enforced automatically by the
[DCO bot](https://probot.github.io/apps/dco/) (org-level, runs on all pushes) and by the
[Commit Verification workflow](.github/workflows/commit-verification.yml) (PR-level, also validates GPG signatures and PR template completeness).

The sign-off is your declaration that you authored the change and have the right to submit it
under the project licence (see [Developer Certificate of Origin](https://developercertificate.org/)).

**How to add the sign-off:**

```bash
# Append -s to every commit command
git commit -s -m "feat: my change"
```

To sign off automatically on every commit, add this to your global git config:

```bash
git config --global format.signoff true
```

**Fixing missing sign-offs before review:**

```bash
# Single commit
git commit --amend --no-edit -s

# Multiple commits — rebase and sign each
git rebase -i HEAD~N   # replace N with the number of commits
# Mark each as 'edit', then for each stop:
git commit --amend --no-edit -s
git rebase --continue
```

> **Note:** DCO sign-off is separate from GPG verification. Both are required.

### Verified Commits

Every commit merged into `main` must be GPG-signed and show the **Verified** badge on GitHub. This is enforced by the
[Commit Verification workflow](.github/workflows/commit-verification.yml) (PR-level, also validates DCO sign-off and PR template completeness).

**Why verified commits?**

Verified commits cryptographically prove that a commit was authored by the person whose name is on it,
protecting the repository from commit spoofing.

**How to set up GPG signing:**

For the full walkthrough, see the
[GitHub documentation on managing commit signature verification](https://docs.github.com/en/authentication/managing-commit-signature-verification).
Quick steps:

1. **Generate a GPG key** (skip if you already have one):

```bash
gpg --full-generate-key
# Choose: RSA and RSA, 4096 bits, no expiry (or your preference)
```

2. **Export your public key and add it to GitHub:**

```bash
gpg --armor --export YOUR_KEY_ID
# Copy the output and paste it at https://github.com/settings/keys → New GPG key
```

3. **Configure Git to sign all commits automatically:**

```bash
git config --global user.signingkey YOUR_KEY_ID
git config --global commit.gpgsign true
```

4. **Verify a commit is signed:**

```bash
git log --show-signature -1
# Output should include "gpg: Good signature from ..."
```

> **Note:** GPG verification is separate from DCO sign-off. Both are required.

**Fixing unverified commits before review:**

If your commits are not yet GPG-signed, amend and force-push before requesting a review:

```bash
# Single commit — add both sign-off and GPG signature in one step
git commit --amend --no-edit -s -S

# Multiple commits — interactive rebase, sign each
git rebase -i HEAD~N   # replace N with the number of commits
# Mark each as 'edit', then for each stop:
git commit --amend --no-edit -s -S
git rebase --continue
```

## Commit Message Guidelines

### Format

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Type

- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, no logic change)
- `refactor`: Code refactoring
- `test`: Test additions or modifications
- `chore`: Maintenance tasks

### Scope

Optional, indicates the area of change:
- `operators`: Operator-related changes
- `orchestrator`: Orchestration logic
- `api`: API changes
- `cli`: CLI changes
- `tests`: Test-related changes

### Subject

- Use imperative mood: "add" not "added" or "adds"
- Don't capitalize first letter
- No period at the end
- Maximum 50 characters

### Body

- Explain what and why, not how
- Wrap at 72 characters
- Separate from subject with blank line

### Footer

- Reference issues: `Closes #123`, `Fixes #456`
- Note breaking changes: `BREAKING CHANGE: description`
- **DCO sign-off every commit** — use `git commit -s` or set `format.signoff = true` globally
- **GPG sign every commit** — use `git commit -S` or set `commit.gpgsign = true` globally

### Examples

**Good commits:**

```
feat(operators): add semantic chunking operator

Implement semantic chunking using sentence transformers for
context-aware document splitting. Includes configurable
similarity threshold and minimum chunk size.

Closes #234
```

```
fix(opensearch): resolve connection timeout issue

Increase default timeout from 30s to 60s and add retry logic
for transient connection failures.

Fixes #456
```

```
docs: update API reference for VectorDB operator

Add examples for OpenSearch configuration and clarify
parameter descriptions.
```

**Bad commits:**

```
Fixed bug
```

```
Updated files
```

```
WIP
```

## Documentation Requirements

### When to Update Documentation

Update documentation when you:

- Add new operators or features
- Change existing APIs or behavior
- Add new configuration options
- Fix bugs that affect documented behavior
- Add new examples or use cases

### Documentation Files

- **[`README.md`](README.md)**: Project overview, setup, and quick start
- **[`ARCHITECTURE.md`](ARCHITECTURE.md)**: System design and architecture
- **[`docs/reference/OPERATORS.md`](docs/reference/OPERATORS.md)**: Detailed operator and API documentation
- **[`QUICKSTART.md`](QUICKSTART.md)**: Quick start guide
- **`docs/operators/`**: Operator-specific documentation
- **`examples/`**: Code examples and sample flows
- **[`CHANGELOG.md`](CHANGELOG.md)**: All notable changes per release
- **[`RELEASE_PROCESS.md`](RELEASE_PROCESS.md)**: How to cut a release (versioning, signing, announcements)
- **[`docs/guides/DEPRECATION_POLICY.md`](docs/guides/DEPRECATION_POLICY.md)**: How deprecated features are handled
- **[`docs/guides/MIGRATION_GUIDE_TEMPLATE.md`](docs/guides/MIGRATION_GUIDE_TEMPLATE.md)**: Template for writing migration guides
- **[`docs/guides/DOCUMENTATION_STYLE_GUIDE.md`](docs/guides/DOCUMENTATION_STYLE_GUIDE.md)**: Formatting, Mermaid, and writing conventions for all contributors

### Documentation Style

Follow the canonical **[Documentation Style Guide](docs/guides/DOCUMENTATION_STYLE_GUIDE.md)** for all writing, formatting, and Mermaid diagram rules. The key rules that apply to every PR:

**Markdown structure**

- Every file must begin with a single `# Title` heading (H1).
- Use only `##` / `###` / `####` for section hierarchy — never skip levels.
- Wrap all prose lines at 120 characters or fewer.
- Use `-` for unordered lists and `1.` for ordered lists consistently throughout a file.

**Code and diagram fences**

- Always use exactly **three backticks** ` ``` ` to open and close fenced blocks — never four or more.
- Always specify a language tag: ` ```python `, ` ```bash `, ` ```json `, ` ```mermaid `, etc.
- Mermaid diagrams must open with ` ```mermaid ` and close with ` ``` ` on its own line.
- Never nest fenced blocks.

**Mermaid diagrams**

- Prefer `graph TD` (top-down) for component hierarchies; `graph LR` (left-right) for data flows.
- Test every diagram in a Mermaid live editor before committing ([mermaid.live](https://mermaid.live)).
- Do not use the `%%` comment syntax inside node labels — place it on its own line.

**Links and references**

- Use relative links for all internal files (e.g., `[guide](docs/guides/FOO.md)`).
- Do not use bare URLs for internal files.
- Verify links resolve correctly before submitting a PR.

**Tables**

- Always include a header separator row (`| --- | --- |`).
- Align column widths consistently within a table for readability.

**Tone and language**

- Use present tense ("The operator returns…") not future tense ("The operator will return…").
- Avoid first-person ("I", "we") — write for the reader.
- Write for an intermediate developer audience; do not explain basic Python or git concepts.

### Code Comments

- Use docstrings for all public functions and classes
- Keep inline comments minimal and meaningful
- Explain "why" not "what" in comments
- Update comments when changing code

## Getting Help

### Resources

- **[Complete Pipeline Setup Guide](USER_GUIDE_PIPELINE_SETUP.md)**: Comprehensive setup and usage
- **[Architecture Documentation](ARCHITECTURE.md)**: System design details
- **[Operator Reference](docs/reference/OPERATORS.md)**: Detailed operator and API documentation
- **[Examples](examples/)**: Sample flows and code examples
- **[Release Process](RELEASE_PROCESS.md)**: Versioning, release steps, and announcement plan
- **[Deprecation Policy](docs/guides/DEPRECATION_POLICY.md)**: How features are deprecated and removed
- **[Migration Guide Template](docs/guides/MIGRATION_GUIDE_TEMPLATE.md)**: Template for upgrade guides

### Communication

For full details on support channels, response time expectations, and maintainer responsibilities, see **[COMMUNITY.md](COMMUNITY.md)**.

Quick reference:

- **[GitHub Issues](https://github.com/docling-project/docling-pipelines/issues)**: Bug reports and feature requests
- **[GitHub Discussions](https://github.com/docling-project/docling-pipelines/discussions)**: General questions and ideas
- **[Pull Requests](https://github.com/docling-project/docling-pipelines/pulls)**: Code contributions
- **Security issues**: Follow [SECURITY.md](SECURITY.md) — do not open a public issue

### Questions?

If you have questions:

1. Check existing documentation
2. Search [GitHub Discussions](https://github.com/docling-project/docling-pipelines/discussions)
3. Open a new Discussion in the Q&A category

---

Thank you for contributing to docling-pipelines! Your contributions help make this project better for everyone.
