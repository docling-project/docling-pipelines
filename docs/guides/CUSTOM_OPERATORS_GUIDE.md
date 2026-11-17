# Custom Operators Guide

## Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Quick Start: Your First Custom Operator](#quick-start-your-first-custom-operator)
  - [Step 1: Create the Operator File](#step-1-get-the-example-operator-file)
  - [Step 2: Register the Operator](#step-2-register-the-operator)
  - [Step 3: Use in a Flow](#step-3-use-in-a-flow)
  - [Step 4: Verify Registration](#step-4-verify-registration)
- [Understanding Custom Operators](#understanding-custom-operators)
  - [Required Imports](#required-imports)
  - [Minimum Requirements](#minimum-requirements)
  - [Class Attributes](#class-attributes)
  - [Required Methods Overview](#required-methods-overview)
- [Core Methods: Basic Implementation](#core-methods-basic-implementation)
  - [transform()](#transform)
  - [get_metadata() - Basic](#get_metadata---basic)
  - [get_required_features()](#get_required_features)
- [Registration and Usage](#registration-and-usage)
  - [Which Registration Method Should I Use?](#which-registration-method-should-i-use)
  - [Method 1: Environment Variable (Recommended)](#method-1-environment-variable-recommended)
  - [Method 2: Programmatic API](#method-2-programmatic-api)
  - [Verifying Registration](#verifying-registration)
  - [Using Custom Operators in Flows](#using-custom-operators-in-flows)
- [Advanced Topics](#advanced-topics)
  - [get_metadata() - Advanced Configuration](#get_metadata---advanced-configuration)
  - [validate() - Runtime Validation](#validate---runtime-validation)
  - [Understanding Features vs Attributes](#understanding-features-vs-attributes)
  - [Package-Based Operators for Distribution](#package-based-operators-for-distribution)
  - [S3 Configuration for Enterprise Deployments](#s3-configuration-for-enterprise-deployments)
- [Best Practices](#best-practices)
- [Troubleshooting](#troubleshooting)
- [Complete Reference Example](#complete-reference-example)

---

## Overview

This guide covers creating, registering, and using custom operators in docpipe. Custom operators extend docpipe's functionality by allowing you to add your own data processing logic to pipelines.

**Custom operators can be provided in three ways:**

1. **Filesystem Paths (Recommended for Development)**: Python files in a local directory
   - Most common approach for development
   - No packaging or installation required
   - Just place `.py` files in a directory and register the path

2. **Python Packages (Recommended for Distribution)**: Pip-installable packages
   - Best for sharing operators across teams or projects
   - Standard Python packaging with entry points
   - Install once with `pip install`, use everywhere
   - Covered in [Advanced Topics](#package-based-operators-for-distribution)

3. **S3 URIs (Optional)**: Remote storage for enterprise deployments
   - For centralized operator management in cloud environments
   - Covered in [Advanced Topics](#s3-configuration-for-enterprise-deployments)

---

## Prerequisites

Before creating custom operators, ensure you have:

- ✅ **docpipe installed**: `pip install docling-pipelines`
- ✅ **Basic Python knowledge**: Classes, inheritance, type hints
- ✅ **PyArrow familiarity**: Understanding of PyArrow tables (basic level)
- ✅ **Docling Pipelines experience**: Successfully run at least one Docling Pipelines flow

**New to Docling Pipelines?** Complete the [`USER_GUIDE_PIPELINE_SETUP.md`](../../USER_GUIDE_PIPELINE_SETUP.md) first to understand the basics of flows and operators.

---

## Quick Start: Your First Custom Operator

Let's create a simple operator that adds a greeting column to your data.

### Step 1: Get the Example Operator File

A ready-made example operator is available at `examples/custom_operators/hello_operator.py`.
It adds a greeting column to the table — a minimal but complete custom operator.

Use it directly, or copy it as a starting point for your own operator:

```bash
# Use the example directly
export DOCPIPE_CUSTOM_OPERATORS="./examples/custom_operators/hello_operator.py"

# Or copy it to your own workspace
cp examples/custom_operators/hello_operator.py ~/my_custom_operators/hello_operator.py
```

### Step 2: Register the Operator

Custom operators are **disabled by default**. Enable them, then point `DOCPIPE_CUSTOM_OPERATORS` at a file or a directory:

```bash
# Required: custom operators are off unless enabled
export DOCPIPE_ENABLE_CUSTOM_OPERATORS=true

# Single file
export DOCPIPE_CUSTOM_OPERATORS="./examples/custom_operators/hello_operator.py"

# Directory (scans recursively for .py files)
export DOCPIPE_CUSTOM_OPERATORS="$HOME/my_custom_operators"
```

Custom operators run arbitrary Python inside the pipeline process, so enable them only where the operator sources are trusted. The `/api/v1/custom_operators` routes additionally require a bearer token, and every token holder can run code on the server once loading is enabled (see [Security Best Practices](SECURITY_BEST_PRACTICES.md#validate-custom-operators-before-use)). While loading is disabled, an upload or a script replacement returns 409 and nothing is stored.

### Step 3: Use in a Flow

Create a flow JSON file (`hello_flow.json`):

```json
{
  "flow_name": "Hello Custom Operator Flow",
  "description": "Example flow using custom hello operator",
  "global_config": {
    "doc_column": "content",
    "disable_validation": false
  },
  "flow": [
    {
      "name": "ingest_1",
      "type": "ingest_source",
      "config": {
        "provider": "filesystem",
        "connection_params": {"paths": ["./sample_documents"]}
      }
    },
    {
      "name": "hello_1",
      "type": "hello",
      "config": {},
      "depends_on": ["ingest_1"]
    }
  ]
}
```

Run the flow:

```bash
docling-pipelines --flow-file hello_flow.json
```

### Step 4: Verify Registration

Check that your operator is registered:

```bash
# List all operators (look for owner="custom")
docling-pipelines --list-operators

# Detailed view with parameters
docling-pipelines --list-operators --verbose
```

You should see output like:

```
Operator: hello
  Category: Functional
  Owner: custom
  Label: Hello Operator
```

**Congratulations!** You've created and run your first custom operator. Now let's understand how it works.

---

## Understanding Custom Operators

### Required Imports

Every custom operator needs these imports:

```python
# Core operator classes
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory

# Constants for metadata and configuration
from docpipe.core.constants.constants import DocpipeConstants, AttributeDataTypes
from docpipe.core.constants.operator_constants import OperatorConstants

# Data handling
import pyarrow as pa
from typing import Any
```

**Optional imports** (depending on your needs):
```python
# For logging
import logging

# For advanced type hints
from collections.abc import Callable

# For working with PyArrow schemas
import pyarrow.compute as pc
```

### Minimum Requirements

Custom operators must:

1. **Inherit from `AbstractOperator`**
2. **Define required class attributes**: `short_name`, `category`, `owner`
3. **Implement required methods**: `transform()`, `get_metadata()`, `get_required_features()`

### Class Attributes

```python
class MyCustomOperator(AbstractOperator):
    # Unique identifier used in flow JSON files
    short_name: str = "my_custom"

    # Operator category: Extract, Ingest, Functional, Quality, VectorDB, Storage
    category: OperatorCategory = OperatorCategory.Functional

    # Identifies as custom operator (always use this constant)
    owner: str | None = DocpipeConstants.OWNER_CUSTOM
```

**Important:** The `short_name` must be unique. If it conflicts with a built-in operator, your custom operator will override it (first discovered wins).

### Required Methods Overview

| Method | Purpose | When Called |
|--------|---------|-------------|
| `transform()` | Process data | During pipeline execution |
| `get_metadata()` | Define configuration schema | During flow authoring/validation |
| `get_required_features()` | Declare input dependencies | During flow validation |
| `validate()` | Runtime validation (optional) | Before pipeline execution |

---

## Core Methods: Basic Implementation

### transform()

The `transform()` method processes PyArrow tables and returns results with metadata.

**Method Signature:**
```python
def transform(self, table: pa.Table, file_name: str | None = None) -> tuple[list[pa.Table], dict[str, Any]]:
    """
    Process the input table and return transformed results.

    Args:
        table: Input PyArrow table with data to process
        file_name: Optional filename for context (e.g., for logging)

    Returns:
        Tuple of (list of output tables, metadata dictionary)
    """
```

**Basic Pattern:**
```python
def transform(self, table: pa.Table, file_name: str | None = None) -> tuple[list[pa.Table], dict[str, Any]]:
    # 1. Process the table (your custom logic here)
    result_table = table  # Replace with your transformation

    # 2. Create metadata
    metadata = self.create_base_metadata(total_docs_count=table.num_rows)
    metadata["processed_docs"] = table.num_rows
    metadata["custom_metric"] = 42  # Add your custom metrics

    # 3. Return results
    return [result_table], metadata
```

**Common Patterns:**

1. **Adding a new column:**
```python
def transform(self, table: pa.Table, file_name: str | None = None):
    # Create new column data
    new_values = [compute_value(row) for row in range(table.num_rows)]

    # Add column to table
    table = table.append_column("new_column", pa.array(new_values))

    return [table], self.create_base_metadata(total_docs_count=table.num_rows)
```

2. **Filtering rows:**
```python
def transform(self, table: pa.Table, file_name: str | None = None):
    # Filter based on condition
    mask = pc.greater(table["score"], 0.5)
    filtered_table = table.filter(mask)

    metadata = self.create_base_metadata(total_docs_count=filtered_table.num_rows)
    metadata["filtered_out"] = table.num_rows - filtered_table.num_rows

    return [filtered_table], metadata
```

3. **Splitting into multiple tables:**
```python
def transform(self, table: pa.Table, file_name: str | None = None):
    # Split based on condition
    high_quality = table.filter(pc.greater(table["score"], 0.8))
    low_quality = table.filter(pc.less_equal(table["score"], 0.8))

    metadata = self.create_base_metadata(total_docs_count=table.num_rows)
    return [high_quality, low_quality], metadata
```

### get_metadata() - Basic

The `get_metadata()` method defines your operator's configuration interface. Start with this basic structure:

```python
@staticmethod
def get_metadata() -> dict[str, Any]:
    """Return operator metadata for UI display and validation."""
    return {
        # Operator category
        OperatorConstants.Misc.CATEGORY: MyCustomOperator.category.value,

        # Availability flag
        OperatorConstants.Misc.IS_OPERATOR_AVAILABLE: True,

        # Display name for UI
        OperatorConstants.Misc.LABEL: "My Custom Operator",

        # Output columns this operator produces (see Advanced Topics)
        OperatorConstants.Config.FEATURES: {},

        # Input parameters for configuration (see Advanced Topics)
        OperatorConstants.Config.ATTRIBUTES: {},
    }
```

**For now, you can leave `FEATURES` and `ATTRIBUTES` empty.** We'll cover these in detail in the [Advanced Topics](#get_metadata---advanced-configuration) section.

### get_required_features()

This method declares which columns must exist in the input table.

```python
@staticmethod
def get_required_features() -> list[str]:
    """
    Return list of required input columns.

    These are columns that must be present in the PyArrow table
    coming from upstream operators.
    """
    return []  # No requirements
```

**Examples:**

```python
# Operator needs content column
@staticmethod
def get_required_features() -> list[str]:
    return ["content"]

# Operator needs multiple columns
@staticmethod
def get_required_features() -> list[str]:
    return ["content", "doc_id", "metadata"]

# Operator needs chunked content from ChunkerOperator
@staticmethod
def get_required_features() -> list[str]:
    return ["chunked_content"]
```

---

## Registration and Usage

### Which Registration Method Should I Use?

Choose based on your use case:

| Scenario | Recommended Method |
|----------|-------------------|
| 🏠 Local development | Environment variable (filesystem) |
| 📦 Sharing across projects/teams | Python package (pip install) |
| 🔧 Programmatic control needed | Python API |
| 👥 Team sharing operators | Python package or environment variable + version control |
| ☁️ Enterprise cloud deployment | S3 URIs (see Advanced Topics) |
| 🚀 Public distribution | Python package published to PyPI |

**For most users:** Use environment variable for development, Python packages for distribution.

### Method 1: Environment Variable (Recommended)

Enable custom operators and set the `DOCPIPE_CUSTOM_OPERATORS` environment variable to point to your operators directory:

```bash
# Custom operators are disabled by default
export DOCPIPE_ENABLE_CUSTOM_OPERATORS=true

# Single directory
export DOCPIPE_CUSTOM_OPERATORS="/path/to/custom_operators"

# Multiple directories (colon-separated on Unix, semicolon on Windows)
export DOCPIPE_CUSTOM_OPERATORS="/path/to/operators1:/path/to/operators2"

# Run your flow
docling-pipelines --flow-file flow.json
```

**Make it permanent** (add to `~/.bashrc` or `~/.zshrc`):
```bash
echo 'export DOCPIPE_CUSTOM_OPERATORS="$HOME/my_custom_operators"' >> ~/.bashrc
source ~/.bashrc
```

**Verify immediately:**
```bash
docling-pipelines --list-operators | grep "custom"
```

### Method 2: Programmatic API

Register operators programmatically in your Python code:

```python
from docpipe.lib.docpipe_flow_manager import DocpipeFlowManager

# Create flow manager
manager = DocpipeFlowManager(flow_file="flow.json")

# Register custom operators (using filesystem paths)
manager.register_custom_operators(package_names=["/path/to/custom_operators"])

# Execute flow
result = manager.execute()
```

**Note:** Supports filesystem paths, S3 URIs, and installed Python package names.

### Verifying Registration

After registering, verify your operators are loaded:

**Using CLI:**
```bash
# List all operators (custom operators show owner="custom")
docling-pipelines --list-operators

# Detailed view with parameters
docling-pipelines --list-operators --verbose
```

**Using Python:**
```python
from docpipe.lib.docpipe_flow_manager import DocpipeFlowManager

# List all operators
print(DocpipeFlowManager.list_operators())

# Detailed view
print(DocpipeFlowManager.list_operators(verbose=True))
```

**What to look for:**
- ✅ Your operator's `short_name` appears in the list
- ✅ `owner` field shows `"custom"`
- ✅ Correct `category` is displayed
- ⚠️ If a custom operator has the same `short_name` as a built-in operator, the custom one takes precedence

### Using Custom Operators in Flows

Reference custom operators by their `short_name` in flow JSON files:

```json
{
  "flow_name": "My Flow with Custom Operator",
  "description": "Example flow using custom operator",
  "global_config": {
    "doc_column": "content",
    "disable_validation": false
  },
  "flow": [
    {
      "name": "ingest_1",
      "type": "ingest_source",
      "config": {
        "provider": "filesystem",
        "connection_params": {"paths": ["./documents"]}
      }
    },
    {
      "name": "custom_1",
      "type": "my_custom",
      "config": {
        "param_name": "value"
      },
      "depends_on": ["ingest_1"]
    }
  ]
}
```

**Run the flow:**
```bash
export DOCPIPE_CUSTOM_OPERATORS="/path/to/custom_operators"
docling-pipelines --flow-file flow.json
```

---

## Advanced Topics

### get_metadata() - Advanced Configuration

Now let's explore the full power of `get_metadata()` for defining operator parameters and outputs.

#### Understanding Features vs Attributes

**Key Concept:**

- **ATTRIBUTES**: INPUT configuration parameters that control how your operator behaves
  - Example: `batch_size`, `threshold`, `mode`
  - Set in the flow JSON configuration
  - Define what users can configure

- **FEATURES**: OUTPUT columns that your operator adds to the PyArrow table
  - Example: `custom_score`, `processed_text`
  - Become available for downstream operators
  - Define what your operator produces

**Visual Example:**

```
Flow: Ingest → MyOperator → VectorDB

MyOperator ATTRIBUTES (inputs):     MyOperator FEATURES (outputs):
├─ mode: "advanced"                 ├─ custom_score (added to table)
├─ threshold: 0.8                   └─ processed_text (added to table)
└─ batch_size: 100                       ↓
                                    Available for VectorDB operator
```

#### Defining Features (Output Columns)

Features define the new columns your operator adds to the PyArrow table:

```python
OperatorConstants.Config.FEATURES: {
    "custom_score": {
        OperatorConstants.Misc.NAME: "Custom Score",
        OperatorConstants.Config.DESCRIPTION: "Computed quality score for the document",
        OperatorConstants.Misc.TYPE: AttributeDataTypes.FLOAT,
        OperatorConstants.Misc.TAGS: [OperatorConstants.Misc.MANDATORY],
        OperatorConstants.Config.AVAILABLE_FOR_VECTOR_DB: True,
    },
    "processed_text": {
        OperatorConstants.Misc.NAME: "Processed Text",
        OperatorConstants.Config.DESCRIPTION: "Text after custom processing",
        OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
        OperatorConstants.Misc.TAGS: [OperatorConstants.Misc.MANDATORY],
    },
}
```

**Feature Fields:**
- `name`: Display name for UI
- `description`: Clear explanation of what the feature contains
- `type`: Data type (string, integer, float, list, etc.)
- `tags`: List of tags (`MANDATORY` for required features, `INTERNAL_FEATURE` for system fields)
- `available_for_vector_db`: (Optional) Boolean for vector database compatibility

#### Defining Attributes (Input Parameters)

Attributes define the configuration parameters users can set:

**Required fields for all attributes:**
- `name`: Display name for UI
- `description`: Clear explanation of the parameter's purpose
- `type`: Data type (string, integer, float, boolean, json, list)
- `required`: Whether parameter is mandatory (True/False)
- `default`: Default value if not provided

**Optional fields for validation:**
- `valid_values`: List of allowed values (enum-like parameters)
- `min_value`/`max_value`: Numeric range constraints

**Complete Example with All Parameter Types:**

```python
OperatorConstants.Config.ATTRIBUTES: {
    # String parameter with valid values (enum-like)
    "mode": {
        OperatorConstants.Misc.NAME: "Processing Mode",
        OperatorConstants.Config.DESCRIPTION: "Mode for processing documents",
        OperatorConstants.Config.REQUIRED: True,
        OperatorConstants.Config.DEFAULT: "standard",
        OperatorConstants.Config.VALID_VALUES: ["standard", "advanced", "custom"],
        OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
    },

    # Integer parameter with range validation
    "batch_size": {
        OperatorConstants.Misc.NAME: "Batch Size",
        OperatorConstants.Config.DESCRIPTION: "Number of documents to process in each batch",
        OperatorConstants.Config.REQUIRED: False,
        OperatorConstants.Config.DEFAULT: 100,
        OperatorConstants.Filtering.MIN_VALUE: 1,
        OperatorConstants.Filtering.MAX_VALUE: 1000,
        OperatorConstants.Misc.TYPE: AttributeDataTypes.INTEGER,
    },

    # Float parameter with range validation
    "threshold": {
        OperatorConstants.Misc.NAME: "Confidence Threshold",
        OperatorConstants.Config.DESCRIPTION: "Minimum confidence score (0.0-1.0)",
        OperatorConstants.Config.REQUIRED: False,
        OperatorConstants.Config.DEFAULT: 0.8,
        OperatorConstants.Filtering.MIN_VALUE: 0.0,
        OperatorConstants.Filtering.MAX_VALUE: 1.0,
        OperatorConstants.Misc.TYPE: AttributeDataTypes.FLOAT,
    },

    # Boolean parameter (no validation needed)
    "enable_feature": {
        OperatorConstants.Misc.NAME: "Enable Feature",
        OperatorConstants.Config.DESCRIPTION: "Whether to enable advanced feature processing",
        OperatorConstants.Config.REQUIRED: False,
        OperatorConstants.Config.DEFAULT: False,
        OperatorConstants.Misc.TYPE: AttributeDataTypes.BOOLEAN,
    },

    # JSON parameter for complex configuration
    "custom_config": {
        OperatorConstants.Misc.NAME: "Custom Configuration",
        OperatorConstants.Config.DESCRIPTION: "JSON object with custom settings",
        OperatorConstants.Config.REQUIRED: False,
        OperatorConstants.Config.DEFAULT: None,
        OperatorConstants.Misc.TYPE: AttributeDataTypes.JSON,
    },
}
```

**Accessing Parameters in transform():**

Parameters defined in `ATTRIBUTES` are injected as instance variables at runtime. Access them using `getattr()` with a default value — direct attribute access (e.g. `self.batch_size`) will raise an `AttributeError` if the attribute is not present.

```python
def transform(self, table: pa.Table, file_name: str | None = None):
    mode = getattr(self, "mode", "standard")
    enable_feature = getattr(self, "enable_feature", False)
    batch_size = getattr(self, "batch_size", 100)

    if mode == "advanced":
        # Use advanced processing
        pass

    if enable_feature:
        # Feature is enabled
        pass

    # Use numeric parameters
    for i in range(0, table.num_rows, batch_size):
        batch = table.slice(i, batch_size)
        # Process batch
```

### validate() - Runtime Validation

The `validate()` method performs runtime validation before operator execution. This is **optional** but recommended for robust operators.

**Method Signature:**
```python
def validate(self, errors: list[str], warnings: list[str], available_features: list[str]) -> None:
    """
    Validate operator configuration at runtime.

    Args:
        errors: List to append blocking errors (prevent execution)
        warnings: List to append non-critical warnings (allow execution)
        available_features: List of columns available from upstream operators
    """
```

**When to Use:**
- Validate actual configuration values (not just schema)
- Check that required features are available from upstream operators
- Verify parameter combinations and logical consistency
- Validate external dependencies (services, models, etc.)

**Basic Pattern:**

```python
def validate(self, errors: list[str], warnings: list[str], available_features: list[str]) -> None:
    # 1. ALWAYS call parent first to validate required features
    super().validate(errors, warnings, available_features)

    # 2. Validate required fields
    if not self.mode:
        errors.append("mode is required for MyCustomOperator")

    # 3. Validate value ranges
    if self.batch_size < 1 or self.batch_size > 1000:
        errors.append("batch_size must be between 1 and 1000")

    # 4. Check feature availability
    if "content" not in available_features:
        errors.append("'content' column must be available from upstream operators")

    # 5. Warn about potential conflicts
    if "custom_score" in available_features:
        warnings.append("'custom_score' column already exists and will be overwritten")
```

**Common Validation Patterns:**

1. **Conditional validation** (skip expensive checks during flow validation):
```python
if self.should_validate_field(field_value=self.mode):
    if self.mode not in ["standard", "advanced", "custom"]:
        errors.append("mode must be one of: standard, advanced, custom")
```

2. **Parameter combination validation**:
```python
if self.enable_advanced and not self.custom_config:
    errors.append("custom_config is required when enable_advanced is True")
```

3. **External service validation**:
```python
if self.should_validate_field(field_value=self.api_endpoint):
    try:
        response = requests.get(self.api_endpoint, timeout=5)
        if response.status_code != 200:
            errors.append(f"API endpoint {self.api_endpoint} is not accessible")
    except Exception as e:
        errors.append(f"Failed to connect to API: {str(e)}")
```

**Key Differences: validate() vs get_metadata()**

| Aspect | `validate()` | `get_metadata()` |
|--------|-------------|------------------|
| **When Called** | Runtime (before execution) | Design-time (flow authoring) |
| **Purpose** | Validate actual values | Declare parameter schemas |
| **Context** | Has `available_features` | No execution context |
| **Validation Type** | Instance-specific | Schema-level (types, ranges) |

**Best Practices:**
- ✅ Always call `super().validate()` first
- ✅ Use `should_validate_field()` for expensive validation checks
- ✅ Append to error/warning lists, don't raise exceptions
- ✅ Provide clear, actionable error messages
- ✅ Use errors for blocking issues, warnings for non-critical ones
- ✅ Check feature availability before assuming columns exist

### Package-Based Operators for Distribution

Package-based operators allow you to distribute custom operators as standard Python packages that can be installed via pip. This is the **recommended approach** for sharing operators across teams or projects.

#### When to Use Package-Based Operators

- 📦 Distributing operators to multiple teams or projects
- 🔄 Version-controlled operator releases
- 🚀 Publishing operators to PyPI or private package repositories
- 👥 Sharing operators without requiring file system access
- ✅ Standard Python packaging workflow

#### Package Structure

A custom operator package follows standard Python package structure:

```
my_custom_operators/
├── pyproject.toml          # Package configuration with entry points
├── README.md               # Package documentation
└── my_custom_operators/    # Package source
    ├── __init__.py
    └── operators/          # Operators module
        ├── __init__.py
        ├── operator1.py
        └── operator2.py
```

**Complete example available at:** `examples/custom_operators/package_example/`

#### Creating a Package

**Step 1: Create pyproject.toml**

```toml
[project]
name = "my-custom-operators"
version = "0.1.0"
description = "Custom operators for Docling Pipelines"
requires-python = ">=3.12"
dependencies = [
    "docling-pipelines>=1.0.0",
]

# Register operators via entry points
[project.entry-points."docpipe.operators"]
my_operator = "my_custom_operators.operators.my_operator:MyOperator"
another_operator = "my_custom_operators.operators.another:AnotherOperator"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["my_custom_operators"]
```

**Key Points:**
- Entry points under `"docpipe.operators"` group enable automatic discovery
- Format: `operator_name = "package.module:ClassName"`
- Entry points are optional; operators can also be discovered by module inspection

**Step 2: Create Operator Files**

Place your operators in the `operators/` subdirectory:

```python
# my_custom_operators/operators/my_operator.py
from typing import Any
import pyarrow as pa
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory
from docpipe.core.constants.constants import DocpipeConstants

class MyOperator(AbstractOperator):
    short_name: str = "my_operator"
    category: OperatorCategory = OperatorCategory.Functional
    owner: str | None = DocpipeConstants.OWNER_CUSTOM

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        # Your initialization

    def transform(self, table: pa.Table, file_name: str | None = None):
        # Your transformation logic
        return [table], self.create_base_metadata(total_docs_count=table.num_rows)

    @staticmethod
    def get_metadata() -> dict[str, Any]:
        return {
            "short_name": MyOperator.short_name,
            "category": MyOperator.category.value,
            "description": "My custom operator",
        }
```

**Step 3: Build and Install**

```bash
# Install in development mode (editable)
pip install -e .

# Or build and install
pip install .

# Or build for distribution
pip install build
python -m build
# Creates dist/my_custom_operators-0.1.0.tar.gz and .whl
```

#### Using Package-Based Operators

**Method 1: Automatic Discovery (Recommended)**

Once installed, operators are automatically discovered:

```bash
# Install the package
pip install my-custom-operators

# Operators are automatically available
docling-pipelines --list-operators | grep "my_operator"

# Use in flows without any registration
docling-pipelines --flow-file flow.json
```

**Method 2: Explicit Registration in Flow**

You can also explicitly register packages in flow configuration:

```json
{
  "flow_name": "My Flow",
  "custom_operators": {
    "adapters": [
      {
        "type": "package",
        "package_name": "my_custom_operators",
        "operator_module": "operators"
      }
    ]
  },
  "flow": [...]
}
```

**Method 3: Programmatic Registration**

```python
from docpipe.lib.docpipe_flow_manager import DocpipeFlowManager

manager = DocpipeFlowManager(flow_file="flow.json")
manager.register_custom_operators(paths=["my_custom_operators"])
result = manager.execute()
```

#### Entry Points vs Module Inspection

The package adapter discovers operators through two methods:

1. **Entry Points** (Recommended): Explicitly registered in `pyproject.toml`
   - Faster discovery
   - Clear operator registration
   - Better for packages with many files

2. **Module Inspection**: Automatic scanning of operator module
   - No entry points needed
   - Discovers all operators in the module
   - Fallback if entry points not configured

**Both methods work together** - operators found via either method are loaded.

#### Publishing to PyPI

To share your operators publicly:

```bash
# Install twine
pip install twine

# Build the package
python -m build

# Upload to PyPI
twine upload dist/*

# Others can now install
pip install my-custom-operators

---

### Common Issues and Solutions

This section documents key learnings and gotchas discovered during package adapter implementation.

#### 1. Adapter Registration

**Issue**: PackageAdapter not discovering operators even though entry points are configured correctly.

**Root Cause**: The `PackageAdapter` class must be imported in `src/docpipe/core/orchestration/operator_loader/adapters/__init__.py` for the `@register_operator_source` decorator to work.

**Solution**: Ensure the adapter is imported in the adapters module:

```python
# src/docpipe/core/orchestration/operator_loader/adapters/__init__.py
from .package_adapter import PackageAdapter  # Required for registration
from .filesystem_adapter import FilesystemAdapter
```

Without this import, the decorator won't execute during module initialization, and the adapter won't be registered with the loader service.

#### 2. Operator Metadata Requirements

**Issue**: Custom operators not appearing in `docling-pipelines --list-operators` output, or appearing without proper identification.

**Root Cause**: Custom operators must include the `"owner"` field in their metadata to distinguish them from built-in docpipe operators.

**Solution**: Always include the `owner` field in your operator's `get_metadata()` method:

```python
@classmethod
def get_metadata(cls) -> dict:
    return {
        "operator_id": "my_custom_operator",
        "name": "My Custom Operator",
        "owner": "my_company",  # Required for custom operators
        "version": "1.0.0",
        "description": "Does something useful",
        # ... other metadata
    }
```

The operator listing uses this field to categorize operators by owner in the output.

#### 3. Entry Points Group Name

**Issue**: Entry points configured but operators not discovered by PackageAdapter.

**Root Cause**: The entry points must use the exact group name `"docpipe.operators"` in `pyproject.toml`.

**Solution**: Use the correct group name in your package configuration:

```toml
[project.entry-points."docpipe.operators"]
uppercase_operator = "my_custom_operators.operators.uppercase_operator:UppercaseOperator"
reverse_operator = "my_custom_operators.operators.reverse_operator:ReverseOperator"
```

**Incorrect examples that won't work:**
- `[project.entry-points."docpipe.operator"]` (missing 's')
- `[project.entry-points."docpipe_operators"]` (underscore instead of dot)
- `[project.entry-points."custom.operators"]` (wrong prefix)

#### 4. Package Name Filtering

**Issue**: Entry points registered but not discovered for a specific package.

**Root Cause**: PackageAdapter filters entry points by checking if `entry_point.value.startswith(package_name)`. The entry point value must start with the package name to be discovered.

**Example**:
```toml
# Package name: my_custom_operators
[project.entry-points."docpipe.operators"]
# ✅ Correct - value starts with package name
uppercase_operator = "my_custom_operators.operators.uppercase_operator:UppercaseOperator"

# ❌ Wrong - value doesn't start with package name
uppercase_operator = "operators.uppercase_operator:UppercaseOperator"
```

**Solution**: Ensure entry point values use the full module path starting with your package name:

```python
# When registering with DocpipeFlowManager
manager.register_custom_operators(packages=["my_custom_operators"])

# Entry point value must start with "my_custom_operators"
```

#### 5. Python 3.12 Compatibility

**Issue**: `TypeError: 'EntryPoints' object is not subscriptable` when running on Python 3.12+.

**Root Cause**: The older `entry_points()["group_name"]` syntax is deprecated in Python 3.12+.

**Solution**: Use the `group` parameter instead:

```python
# ❌ Old syntax (Python < 3.12)
from importlib.metadata import entry_points
eps = entry_points()["docpipe.operators"]

# ✅ New syntax (Python 3.12+)
from importlib.metadata import entry_points
eps = entry_points(group="docpipe.operators")
```

The PackageAdapter implementation uses the new syntax for compatibility.

#### 6. Module Import Errors

**Issue**: `ModuleNotFoundError` when loading operators from installed package.

**Common Causes**:
- Package not installed in the current environment
- Package installed in editable mode but source moved
- PYTHONPATH not including package location

**Solutions**:

```bash
# Verify package is installed
pip list | grep my-custom-operators

# Install in editable mode for development
pip install -e /path/to/package

# Or install from PyPI
pip install my-custom-operators

# Check if operators are discoverable
docling-pipelines --list-operators
```

#### 7. Operator Discovery Debugging

**Issue**: Operators not appearing in listing or not being loaded.

**Debugging Steps**:

1. **Verify entry points are registered**:
   ```python
   from importlib.metadata import entry_points
   eps = entry_points(group="docpipe.operators")
   for ep in eps:
       print(f"{ep.name}: {ep.value}")
   ```

2. **Check operator metadata**:
   ```python
   from my_custom_operators.operators.my_operator import MyOperator
   print(MyOperator.get_metadata())
   # Should include "owner" field
   ```

3. **Test operator loading directly**:
   ```python
   from docpipe.core.orchestration.operator_factory import OperatorFactory
   factory = OperatorFactory()
   factory.register_custom_operators(packages=["my_custom_operators"])

   # Try to get your operator
   operator = factory.get_operator("my_operator_id")
   ```

4. **Enable debug logging**:
   ```bash
   DS_LOG_LEVEL=DEBUG docling-pipelines --list-operators
   ```

#### Best Practices Summary

1. **Always import adapters** in `__init__.py` for decorator registration
2. **Include owner field** in all custom operator metadata
3. **Use exact group name** `"docpipe.operators"` in entry points
4. **Match package names** between entry point values and registration calls
5. **Use Python 3.12+ syntax** for entry points API
6. **Test operator discovery** before publishing packages
7. **Provide clear metadata** including version, description, and parameters

```

**For private repositories:**
```bash
# Upload to private PyPI server
twine upload --repository-url https://your-pypi-server.com dist/*

# Install from private repository
pip install my-custom-operators --index-url https://your-pypi-server.com
```

#### Version Management

Use semantic versioning in `pyproject.toml`:

```toml
[project]
version = "1.2.3"  # MAJOR.MINOR.PATCH
```

Users can install specific versions:
```bash
pip install my-custom-operators==1.2.3
pip install my-custom-operators>=1.0.0,<2.0.0
```

#### Best Practices for Packages

1. **Clear Documentation**: Include comprehensive README with usage examples
2. **Version Dependencies**: Specify compatible Docling Pipelines versions in dependencies
3. **Entry Points**: Register operators via entry points for better discovery
4. **Testing**: Include tests in your package
5. **Changelog**: Maintain a CHANGELOG.md for version history
6. **Semantic Versioning**: Follow semver for version numbers
7. **Type Hints**: Use proper type hints for better IDE support

#### Troubleshooting Package-Based Operators

**Package not found:**
```bash
# Verify package is installed
pip show my-custom-operators

# Check installed location
pip show -f my-custom-operators
```

**Operators not discovered:**
```bash
# Verify entry points are registered
python -c "import importlib.metadata; print(list(importlib.metadata.entry_points(group='docpipe.operators')))"

# Check operator module can be imported
python -c "from my_custom_operators.operators import MyOperator; print(MyOperator.short_name)"
```

**Import errors:**
- Ensure docpipe is installed in the same environment
- Check that all dependencies are listed in `pyproject.toml`
- Verify Python version compatibility

### S3 Configuration for Enterprise Deployments

S3 support is an **optional advanced feature** for enterprise deployments that need centralized operator management.

#### When to Use S3

- ☁️ Centralized operator distribution across multiple environments
- 🚀 Cloud-native deployments (AWS ECS, Lambda, etc.)
- 📦 Version-controlled operator releases in S3 buckets
- 👥 Teams that already use S3 for artifact management

#### Prerequisites

1. **Install boto3:**
```bash
# Using uv
uv pip install boto3
```

2. **Configure AWS credentials** (boto3 uses standard AWS credential chain):

**Option 1: Environment variables**
```bash
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"  # pragma: allowlist secret
export AWS_DEFAULT_REGION="us-east-1"  # Optional
```

**Option 2: Credentials file** (`~/.aws/credentials`)
```ini
[default]
aws_access_key_id = your-access-key
aws_secret_access_key = your-secret-key
```

**Option 3: IAM roles** (automatic for EC2/ECS/Lambda instances)

#### S3 URI Format

```
s3://bucket-name/path/to/operators/
```

Operators are downloaded to `~/.docpipe/custom_operators_cache/` and loaded from cache.

#### Usage Examples

**Environment variable:**
```bash
export DOCPIPE_CUSTOM_OPERATORS="s3://my-company-operators/production/"
docling-pipelines --flow-file flow.json
```

**Programmatic:**
```python
from docpipe.lib.docpipe_flow_manager import DocpipeFlowManager

manager = DocpipeFlowManager(flow_file="flow.json")
manager.register_custom_operators(package_names=["s3://my-company-operators/production/"])
result = manager.execute()
```

**Mixed sources** (filesystem + S3):
```bash
export DOCPIPE_CUSTOM_OPERATORS="/local/path:s3://bucket/path"
```

---

## Best Practices

1. **Unique short_name**: Ensure your operator's `short_name` doesn't conflict with built-in operators unless you intend to override them

2. **Proper validation**: Implement `get_required_features()` to validate input columns and `validate()` for runtime checks

3. **Comprehensive metadata**: Provide complete metadata with clear descriptions for all parameters

4. **Error handling**: Use `record_failed_document()` and `record_skipped_document()` for tracking processing issues

5. **Testing**: Test operators independently before integrating into flows

6. **Documentation**: Include docstrings and comments explaining your operator's purpose and usage

7. **Type hints**: Use proper type hints for better IDE support and code clarity

8. **Logging**: Use the logging module for debugging and monitoring

9. **Safe attribute access**: Always use `getattr(self, "param_name", default)` to access configuration attributes in `transform()` — direct attribute access will raise `AttributeError` at runtime

---

## Troubleshooting

**Operator not found:**
- ✅ Verify `DOCPIPE_ENABLE_CUSTOM_OPERATORS=true` is set (custom operators are disabled by default)
- ✅ Verify `DOCPIPE_CUSTOM_OPERATORS` is set correctly
- ✅ Check that the directory path exists and contains `.py` files
- ✅ Ensure the operator class inherits from `AbstractOperator`
- ✅ Verify `short_name` matches what you're using in the flow

**Import errors:**
- ✅ Ensure all dependencies are installed in the same environment
- ✅ Check that docpipe is installed: `pip show docling-pipelines`
- ✅ Verify Python version compatibility (Python 3.12+ recommended)

**S3 access denied:**
- ✅ Check AWS credentials are configured correctly
- ✅ Verify bucket permissions (s3:GetObject, s3:ListBucket)
- ✅ Ensure boto3 is installed: `pip show boto3`

**Duplicate operator warning:**
- ⚠️ Custom operators with same `short_name` as built-in operators will override them
- ⚠️ First discovered operator wins (check registration order)

**Validation errors:**
- ✅ Check that required features are available from upstream operators
- ✅ Verify parameter values are within valid ranges
- ✅ Review error messages for specific issues

**Operator not appearing in list:**
- ✅ Run `docling-pipelines --list-operators` to verify registration
- ✅ Check for Python syntax errors in your operator file
- ✅ Ensure class attributes (`short_name`, `category`, `owner`) are defined

**`AttributeError: 'MyOperator' object has no attribute '...'`:**
- ✅ Replace direct attribute access (e.g. `self.param`) with `getattr(self, "param", default_value)`
- ✅ Configuration attributes are injected at runtime and may not always be present on `self` — `getattr()` provides a safe fallback

---

## Complete Reference Example

A complete working example is available in the Docling Pipelines repository at:
- **File**: `examples/custom_operators/example_custom_operator.py`
- **Purpose**: Demonstrates adding a custom field to documents
- **Features**: Shows all required methods with proper implementation

**To use the example:**

```bash
# Clone the Docling Pipelines repository
git clone https://github.com/your-org/docling-pipelines.git

# Navigate to examples
cd docling-pipelines/examples/custom_operators

# Register and use
export DOCPIPE_CUSTOM_OPERATORS="$(pwd)"
docling-pipelines --list-operators | grep example
```

For more details on the base class implementation and loading mechanism, refer to:
- `src/docpipe/core/operators/abstract_operator.py` - Base operator class
- `src/docpipe/core/operators/operator_registry.py` - Operator registration system
- Built-in operators in `src/docpipe/core/operators/` - Real-world examples

---
