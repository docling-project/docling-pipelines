# Docling Pipelines Python API Guide

This guide explains how to use Docling Pipelines programmatically through the Python API for integration with custom applications, Jupyter notebooks, and automated workflows.

## Table of Contents

1. [Introduction](#introduction)
2. [Setup Requirements](#setup-requirements)
3. [Basic Usage: Execute Flow from File](#basic-usage-execute-flow-from-file)
4. [Execute Flow from Dictionary](#execute-flow-from-dictionary)
5. [Jupyter Notebook Integration](#jupyter-notebook-integration)
6. [Validation Before Execution](#validation-before-execution)
7. [Advanced Features](#advanced-features)
8. [Error Handling and Debugging](#error-handling-and-debugging)
9. [Production Considerations](#production-considerations)

---

## Introduction

The [`DocpipeFlowManager`](../../src/docpipe/lib/docpipe_flow_manager.py) class provides a Python API for programmatic flow execution, offering greater flexibility than the CLI for integration scenarios.

### When to Use the Programmatic API

- **Jupyter Notebooks**: Interactive data exploration and pipeline development
- **Custom Workflows**: Integration with existing Python applications
- **Dynamic Flow Generation**: Creating flows programmatically based on runtime conditions
- **Automated Testing**: Programmatic validation and execution in test suites
- **Multi-tenant Systems**: Generating and executing flows per tenant or dataset

### Key Benefits

- **Flexibility**: Define flows as Python dictionaries or load from JSON files
- **Error Handling**: Programmatic access to validation results and execution logs
- **Metadata Access**: Retrieve execution metadata, job IDs, and flow information
- **Integration**: Seamlessly integrate with pandas, PyArrow, and ML pipelines

---

## Setup Requirements

Before using the programmatic API, ensure your environment is properly configured:

### 1. Set PYTHONPATH

The `PYTHONPATH` must include the docpipe directory as the source root:

```bash
# From repository root
export PYTHONPATH="$(pwd)/src:${PYTHONPATH}"
```

### 2. Activate Virtual Environment

```bash
# From project root
source .venv/bin/activate
```

### 3. Verify Python Import

Test that the DocpipeFlowManager can be imported:

```bash
python -c "from docpipe.lib.docpipe_flow_manager import DocpipeFlowManager; print('Import successful')"
```

**Note:** This command may take a few seconds to complete as Python loads dependencies. If successful, you'll see: `Import successful`

### 4. Verify Prerequisites

Ensure Ollama and OpenSearch are running (see [User Guide: Pipeline Setup](../../USER_GUIDE_PIPELINE_SETUP.md)).

---

## Basic Usage: Execute Flow from File

The simplest way to use the programmatic API is to execute an existing flow JSON file.

### Example: Basic Flow Execution

```python
from pathlib import Path
from docpipe.lib.docpipe_flow_manager import DocpipeFlowManager

def execute_flow():
    """Execute a flow file with basic error handling."""
    flow_file = Path("sample_flows/quickstart/complete_pipeline_ollama.json")

    try:
        # Initialize the manager with a flow file
        manager = DocpipeFlowManager(
            flow_file=str(flow_file)
        )

        print(f"Loaded flow file: {flow_file}")

        # Execute the flow
        result = manager.execute()

        # Access execution metadata
        metadata = manager.get_execution_metadata()
        print(f"Flow executed successfully")
        print(f"Job ID: {metadata.get('job_id')}")
        print(f"Flow Name: {metadata.get('flow_name')}")

    except FileNotFoundError as exc:
        print(f"Flow file not found: {exc}")
    except ValueError as exc:
        print(f"Invalid configuration: {exc}")
    except Exception as exc:
        print(f"Execution failed: {exc}")

if __name__ == "__main__":
    execute_flow()
```

---

## Execute Flow from Dictionary

For dynamic flow generation, define flows as Python dictionaries instead of JSON files.

### Example: Inline Flow Definition

```python
from docpipe.lib.docpipe_flow_manager import DocpipeFlowManager

def build_flow_definition(input_folder: str, index_name: str) -> dict:
    """Build a complete flow definition as a Python dictionary."""
    return {
        "flow_name": "programmatic-inline-pipeline",
        "description": "Inline flow for document processing",
        "global_config": {
            "doc_column": "content",
            "disable_validation": False,
            "force_ingest": True,
            "storage": "in-memory",
            "execute_type": "local"
        },
        "flow": [
            {
                "name": "ingest_source_filesystem",
                "type": "ingest_source",
                "config": {
                    "provider": "filesystem",
                    "connection_params": {"paths": [input_folder]},
                    "include_filter": "pdf,txt,docx"
                }
            },
            {
                "name": "extract_operator",
                "type": "extract_operator",
                "depends_on": ["ingest_source_filesystem"],
                "config": {
                    "text_extraction": {
                        "provider": "docling_library"
                    },
                    "entity_extraction": {
                        "provider": "none"
                    }
                }
            },
            {
                "name": "chunk_documents",
                "type": "chunker",
                "depends_on": ["extract_operator"],
                "config": {
                    "chunk_type": "semantic",
                    "chunk_size": 512,
                    "chunk_overlap": 50
                }
            },
            {
                "name": "generate_embeddings",
                "type": "embeddings",
                "depends_on": ["chunk_documents"],
                "config": {
                    "provider": "litellm",
                    "provider_config": {
                        "model_id": "openai/nomic-embed-text",
                        "api_base": "http://localhost:11434"
                    },
                    "embeddings_column": "content"
                }
            },
            {
                "name": "store_vectors",
                "type": "vectordb",
                "depends_on": ["generate_embeddings"],
                "config": {
                    "provider": "opensearch",
                    "doc_id_column": "doc_id_hash",
                    "embeddings_column": "embeddings",
                    "vector_dimension": 768,
                    "provider_config": {
                        "index_name": index_name,
                        "host": "localhost",
                        "port": 9200,
                        "username": "admin",
                        "password": "<your-opensearch-password>",
                        "use_ssl": False,
                        "verify_certs": False,
                        "engine": "faiss",
                        "algorithm": "hnsw",
                        "space_type": "l2",
                        "batch_size": 100
                    }
                }
            }
        ]
    }

def execute_inline_flow():
    """Execute a flow defined as a Python dictionary."""
    flow_def = build_flow_definition(
        input_folder="./sample_documents",
        index_name="inline-documents-index"
    )

    try:
        manager = DocpipeFlowManager(
            flow_def=flow_def
        )

        result = manager.execute()
        print("Inline flow executed successfully")

    except Exception as exc:
        print(f"Execution failed: {exc}")

if __name__ == "__main__":
    execute_inline_flow()
```

### Use Cases

- **Dynamic Flow Generation**: Create flows based on runtime parameters (tenant ID, dataset type, etc.)
- **Template-Based Flows**: Build flow templates and customize per execution
- **Configuration Management**: Generate flows from external configuration systems

---

## Jupyter Notebook Integration

The programmatic API integrates seamlessly with Jupyter notebooks for interactive pipeline development.

#### Prerequisites: Installing Docling Pipelines in Your Notebook Environment

Before using `DocpipeFlowManager` in Jupyter notebooks, you must install the Docling Pipelines package as a wheel (WHL) file in your notebook environment.

**Step 1: Build the WHL Package**

From the project root directory, use `uv` to build the wheel package:

```bash
# From project root (docling-pipelines/)
uv build --wheel
```

This command will:
- Create a `dist/` directory in your project root
- Generate two files:
  - `docpipe-<version>.tar.gz` (source distribution)
  - `docpipe-<version>-py3-none-any.whl` (wheel package)

**Example output:**
```
Building docling-pipelines
  - Building sdist
  - Built docling-pipelines-1.0.0.tar.gz
  - Building wheel
  - Built docling_pipelines-1.0.0-py3-none-any.whl
```

**Step 2: Install the WHL Package in Your Notebook Environment**

```bash
uv pip install dist/docling_pipelines-<version>-py3-none-any.whl
```

**Step 3: Install Jupyter (if not already installed)**

```bash
# Install Jupyter using uv
uv pip install jupyter
```

**Step 2: Start Jupyter Notebook Server**

Note: Provide the full path instead of relative path here - https://github.com/docling-project/docling-pipelines/blob/main/sample_flows/quickstart/complete_pipeline_ollama.json

From the project root directory:

```bash
# Start Jupyter Notebook
jupyter notebook examples/docpipe_flow_manager/sample_jupyter_notebook.ipynb
```

This will:
- Start the Jupyter server (typically on `http://localhost:8888`)
- Open your default web browser automatically
- Display the Jupyter file browser showing your project directory and run results at the bottom of the page
```

### Benefits in Notebooks

- **Cell-by-Cell Execution**: Run validation, execution, and analysis in separate cells
- **Interactive Debugging**: Inspect results, metadata, and logs interactively
- **Visualization**: Combine with pandas/matplotlib for result visualization
- **Documentation**: Embed explanations and results in notebook format

---

## Validation Before Execution

Always validate flows before execution to catch configuration errors early.

### Example: Validation Pattern

```python
from docpipe.lib.docpipe_flow_manager import DocpipeFlowManager

def validate_and_execute(flow_file: str):
    """Validate flow before execution."""
    manager = DocpipeFlowManager(
        flow_file=flow_file
    )

    # Validate the flow
    validation_result = manager.validate()

    print("Validation Results:")
    print(f"  Valid: {validation_result['valid']}")
    print(f"  Errors: {validation_result['errors']}")
    print(f"  Warnings: {validation_result['warnings']}")

    # Only execute if validation passes
    if not validation_result["valid"]:
        print("Validation failed. Aborting execution.")
        for error in validation_result["errors"]:
            print(f"  ERROR: {error}")
        return None

    # Show warnings but continue
    if validation_result["warnings"]:
        print("Warnings detected:")
        for warning in validation_result["warnings"]:
            print(f"  WARNING: {warning}")

    # Execute after successful validation
    print("Validation passed. Executing flow...")
    result = manager.execute()
    print("Execution completed successfully.")

    return result
```

### Validation Checks

- **Operator Configuration**: Validates operator parameters and types
- **Edge Connectivity**: Ensures proper connections between operators
- **Required Fields**: Checks for missing required configuration fields
- **Data Flow**: Validates data flow through the pipeline

---

## Advanced Features

The programmatic API provides advanced features for production use cases.

### Custom Job and Flow IDs

```python
import uuid

manager = DocpipeFlowManager(
    flow_file="my_flow.json",
    job_id=str(uuid.uuid4()),
    job_run_id=str(uuid.uuid4()),
    flow_id="prod-document-pipeline-v2",
)
```

**Note:** `job_id` and `job_run_id` must be in UUID format (36 characters). If not provided, UUIDs are auto-generated.

### Accessing Execution Metadata

```python
# Execute the flow
result = manager.execute()

# Retrieve detailed metadata
metadata = manager.get_execution_metadata()

print(f"Job ID: {metadata.get('job_id')}")
print(f"Job Run ID: {metadata.get('job_run_id')}")
print(f"Flow ID: {metadata.get('flow_id')}")
print(f"Flow Name: {metadata.get('flow_name')}")
print(f"Description: {metadata.get('description')}")
print(f"Number of Operators: {metadata.get('num_operators')}")
print(f"Flow File: {metadata.get('flow_file')}")
```

### Retrieving Execution Logs

```python
# Get all captured logs
logs = manager.get_execution_logs()

print(f"Total log lines: {len(logs)}")

# Filter logs by level (if needed)
error_logs = [log for log in logs if 'ERROR' in log]
warning_logs = [log for log in logs if 'WARNING' in log]

print(f"Errors: {len(error_logs)}")
print(f"Warnings: {len(warning_logs)}")
```

### Listing Available Operators

```python
# Get operator summary (table with Owner, Attributes, Features columns)
# Sorted by category: Ingest, Extract, Quality, Functional, VectorDB, Storage
operators_summary = DocpipeFlowManager.list_operators()
print(operators_summary)

# Get detailed operator information (full parameters and descriptions)
operators_detailed = DocpipeFlowManager.list_operators(verbose=True)
print(operators_detailed)
```

**Summary table format:**

- **Owner**: Operator name
- **Attributes**: Count of configurable parameters
- **Features**: Count of special features/capabilities

---

## Error Handling and Debugging

Implement robust error handling for production deployments.

### Comprehensive Error Handling Pattern

```python
import traceback
from docpipe.lib.docpipe_flow_manager import DocpipeFlowManager

def execute_with_error_handling(flow_file: str):
    """Execute flow with comprehensive error handling."""
    try:
        manager = DocpipeFlowManager(
            flow_file=flow_file
        )

        # Validate first
        validation_result = manager.validate()
        if not validation_result["valid"]:
            print("Validation failed:")
            for error in validation_result["errors"]:
                print(f"  - {error}")
            return None

        # Execute the flow
        result = manager.execute()

        # Log success
        metadata = manager.get_execution_metadata()
        print(f"Success: {metadata.get('flow_name')} completed")

        return result

    except FileNotFoundError as exc:
        print(f"Flow file not found: {exc}")
        print("Check the file path and ensure it exists.")

    except ValueError as exc:
        print(f"Invalid configuration value: {exc}")
        print("Review operator parameters in the flow definition.")

    except ConnectionError as exc:
        print(f"Connection error: {exc}")
        print("Check Ollama (port 11434) and OpenSearch (port 9200) are running.")

    except Exception as exc:
        print(f"Unexpected error: {exc}")
        print("\nFull traceback:")
        print(traceback.format_exc())

        # Retrieve logs for debugging
        try:
            logs = manager.get_execution_logs()
            print(f"\nCaptured logs ({len(logs)} lines):")
            for line in logs[-20:]:  # Last 20 lines
                print(line)
        except:
            print("Could not retrieve execution logs.")

    return None
```

### Log Level Configuration

```python
# Control logging via DS_LOG_LEVEL environment variable
import os

# Development: Detailed debugging information
os.environ["DS_LOG_LEVEL"] = "DEBUG"
manager = DocpipeFlowManager(flow_file="flow.json")

# Production: Standard information logging
os.environ["DS_LOG_LEVEL"] = "INFO"
manager = DocpipeFlowManager(flow_file="flow.json")

# Quiet: Only warnings and errors
os.environ["DS_LOG_LEVEL"] = "WARNING"
manager = DocpipeFlowManager(flow_file="flow.json")

# Critical only: Only critical errors
os.environ["DS_LOG_LEVEL"] = "ERROR"
manager = DocpipeFlowManager(flow_file="flow.json")
```

**Note:** The `log_level` parameter has been removed from `DocpipeFlowManager`. Use the `DS_LOG_LEVEL` environment variable instead for consistent logging across all components.

### Embedded Usage: Disabling Docling Pipelines Log Configuration

When Docling Pipelines is used as a library inside an application that manages its own logging
infrastructure, pass `configure_logging=False` to prevent Docling Pipelines from installing its
own handlers. All Docling Pipelines log records will then propagate to the calling application's
root logger.

```python
# Application manages its own logging — Docling Pipelines defers entirely
manager = DocpipeFlowManager(
    flow_file="flow.json",
    configure_logging=False,
)
```

To rename the logger prefix in the output, attach a `Filter` to the handler that
receives Docling Pipelines records:

```python
import logging

class RenamingFilter(logging.Filter):
    def filter(self, record):
        record.name = record.name.replace("docpipe", "my_app")
        return True

# Attach filter to the handler on the "docpipe" root logger
docpipe_logger = logging.getLogger("docpipe")
for handler in docpipe_logger.handlers:
    handler.addFilter(RenamingFilter())
```

### Debugging Failed Executions

```python
# After a failed execution, inspect logs
logs = manager.get_execution_logs()

# Search for specific errors
for i, line in enumerate(logs):
    if 'ERROR' in line or 'Exception' in line:
        # Print context around the error
        start = max(0, i - 3)
        end = min(len(logs), i + 4)
        print(f"\nError context (lines {start}-{end}):")
        for j in range(start, end):
            print(f"  {logs[j]}")
```

---

## Production Considerations

### Security

- **Enable SSL for OpenSearch**: Set `use_ssl: true` and `verify_certs: true` in production
- **Use Strong Passwords**: Never hardcode passwords; use environment variables
- **Secure Credentials**: Store credentials in secure vaults (AWS Secrets Manager, HashiCorp Vault, etc.)

### Error Handling

- **Implement Retry Logic**: Add retry mechanisms for transient failures
- **Graceful Degradation**: Handle service unavailability gracefully
- **Comprehensive Logging**: Log all errors with context for debugging

### Monitoring and Logging

- **Centralized Logging**: Send logs to centralized logging systems (ELK, Splunk, etc.)
- **Metrics Collection**: Track execution times, success rates, and resource usage
- **Alerting**: Set up alerts for failures and performance degradation

### Scaling

- **Distributed Execution**: Use Prefect work pools for large-scale processing
- **Resource Management**: Monitor memory and CPU usage
- **Batch Processing**: Process documents in batches to manage resource consumption

### Testing

- **Unit Tests**: Test flow generation and validation logic
- **Integration Tests**: Test end-to-end flow execution with test data
- **Performance Tests**: Benchmark pipeline performance with representative data

---

## Related Documentation

- **[User Guide: Pipeline Setup](../../USER_GUIDE_PIPELINE_SETUP.md)** - Basic setup and first pipeline
- **[Flow Configuration Guide](FLOW_CONFIGURATION_GUIDE.md)** - Creating and configuring flows
- **[Advanced Configuration](ADVANCED_CONFIGURATION.md)** - Production deployment and scaling
- **[Operator Reference](../reference/OPERATORS.md)** - Complete operator specifications
- **[Examples Directory](../../examples/docpipe_flow_manager/)** - Code examples and patterns
