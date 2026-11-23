# Custom Operators Guide

This guide explains how to create and use custom operators in docling-pipelines.

## Overview

Custom operators allow you to extend docling-pipelines with your own data processing logic. The system supports loading custom operators from:
- Local filesystem (single files or directories)
- S3 buckets

## Creating a Custom Operator

### Basic Structure

A custom operator must:
1. Inherit from `AbstractOperator`
2. Implement the `transform()`, `get_metadata()`, and `get_required_features()` methods
3. Define `short_name` and `category` class attributes
4. Set `owner` attribute to `DocpipeConstants.OWNER_CUSTOM` (for priority resolution)

**Important**: Custom operators should set `owner = DocpipeConstants.OWNER_CUSTOM`. Do NOT set `owner = DocpipeConstants.OWNER_DOCPIPE` as this is reserved for built-in operators and will cause validation errors.

Example:

```python
import pyarrow as pa

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory

class ExampleCustomOperator(AbstractOperator):
    short_name: str = "example_custom"
    category: OperatorCategory = OperatorCategory.Functional  # Use appropriate standard category
    owner: str | None = DocpipeConstants.OWNER_CUSTOM  # Mark as custom operator for priority resolution

    def __init__(self, *, config: dict):
        super().__init__(config=config)
        self.custom_field_value = config.get("custom_field_value", "default")

    def transform(self, *, table: pa.Table, file_name: str | None = None) -> tuple[list[pa.Table], dict]:
        # Add custom field to table
        custom_field = pa.array([self.custom_field_value] * len(table))
        table = table.append_column("custom_field", custom_field)

        # Return list of tables and metadata
        metadata = self.create_base_metadata(total_docs_count=table.num_rows)
        return [table], metadata

    @staticmethod
    def get_metadata() -> dict:
        """Return operator metadata for UI display."""
        return {
            "label": "Example Custom Operator",
            "description": "Adds a custom field to documents",
            "category": OperatorCategory.Functional.value,
            "owner": DocpipeConstants.OWNER_CUSTOM,
        }

    def get_required_features(self) -> list:
        """Return list of required input features."""
        return []
```

## Using Custom Operators

### 1. Set Environment Variable

Custom operators are disabled by default. Before running your flow, enable them and set the `DOCPIPE_CUSTOM_OPERATORS` environment variable:

```bash
# Required: custom operators are off unless enabled
export DOCPIPE_ENABLE_CUSTOM_OPERATORS=true

# Python package - must be importable (installed or in PYTHONPATH)
export DOCPIPE_CUSTOM_OPERATORS="my_custom_operators"

# Single local file - absolute or relative path
export DOCPIPE_CUSTOM_OPERATORS="/path/to/my_operator.py"
export DOCPIPE_CUSTOM_OPERATORS="./operators/my_operator.py"

# Local directory - scans recursively for .py files
export DOCPIPE_CUSTOM_OPERATORS="/path/to/operators/"
export DOCPIPE_CUSTOM_OPERATORS="./examples/custom_operators"

# S3 bucket
export DOCPIPE_CUSTOM_OPERATORS="s3://my-bucket/operators/my_operator.py"

# Multiple sources - comma-separated, mixed types (auto-detected)
export DOCPIPE_CUSTOM_OPERATORS="my_package,/path/to/local/operators/,s3://my-bucket/operators/"
```

**Source Type Auto-Detection:**
The system automatically detects the source type:
- **Python package**: If the path is importable (no `/` or `\` characters)
- **Filesystem**: If the path contains `/` or `\` or starts with `.`
- **S3**: If the path starts with `s3://`

### 2. Flow Definition

Create a flow JSON file using your custom operator:

```json
{
  "flow_name": "Custom Operator Example Flow",
  "description": "Example flow using a custom operator with extraction",
  "global_config": {
    "doc_column": "content",
    "disable_validation": false
  },
  "flow": [
    {
      "name": "ingest",
      "type": "ingest_source",
      "config": {
        "provider": "filesystem",
        "connection_params": {"paths": ["./data/input"]}
      }
    },
    {
      "name": "extract",
      "type": "extract_operator",
      "depends_on": ["ingest"],
      "config": {
        "text_extraction": {
          "provider": "docling_library",
          "doc_column": "content"
        }
      }
    },
    {
      "name": "custom",
      "type": "example_custom",
      "depends_on": ["extract"],
      "config": {
        "custom_field_value": "example_value"
      }
    }
  ]
}
```

### 3. Run with CLI

```bash
# Set environment variable
export DOCPIPE_CUSTOM_OPERATORS="/path/to/example_custom_operator.py"

# Execute flow
docling-pipelines --flow-file custom_flow.json
```

### 4. Run with REST API

```bash
# Set environment variable before starting the API server
export DOCPIPE_CUSTOM_OPERATORS="/path/to/operators/"

# Start API server
docling-pipelines-api

# Submit flow via API
curl -X POST http://localhost:8000/api/flows/execute \
  -H "Content-Type: application/json" \
  -d @custom_flow.json
```

### 5. Run Programmatically

```python
import os

from docpipe.lib.docpipe_flow_manager import DocpipeFlowManager

# Set custom operators path
os.environ["DOCPIPE_CUSTOM_OPERATORS"] = "/path/to/operators/"

# Create flow manager and execute
manager = DocpipeFlowManager()
result = manager.execute_flow_from_file(flow_file="custom_flow.json")
```

## S3 Configuration

### Authentication

The S3 adapter uses boto3's default credential chain:

1. **Environment variables**: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`
2. **Credentials file**: `~/.aws/credentials`
3. **IAM roles**: For EC2 instances or ECS tasks

### Example with Environment Variables

```bash
export AWS_ACCESS_KEY_ID="your-access-key"  # pragma: allowlist secret
export AWS_SECRET_ACCESS_KEY="your-secret-key"  # pragma: allowlist secret
export AWS_DEFAULT_REGION="us-east-1"
export DOCPIPE_CUSTOM_OPERATORS="s3://my-bucket/operators/"

docling-pipelines --flow-file flow.json
```

### S3 URI Format

```
s3://bucket-name/path/to/operator.py
s3://bucket-name/path/to/operators/  # Directory (downloads all .py files)
```

## Operator Discovery

### Validation

Custom operators are validated at discovery time:
- Must inherit from `AbstractOperator`
- Must implement `transform()` method
- Must define `SHORT_NAME` and `CATEGORY` attributes
- Invalid operators are logged and skipped

### Naming Conflicts

If a custom operator has the same `SHORT_NAME` as a built-in operator:
- Built-in operator takes precedence
- Warning is logged
- Custom operator is not loaded

### Caching (S3 only)

S3 operators are downloaded to `~/.docpipe/custom_operators_cache/` and cached for the session.

## Best Practices

1. **Use descriptive short_name**: Choose unique names to avoid conflicts
2. **Set category appropriately**: Use `OperatorConstants.Misc.CATEGORY_CUSTOM` for custom operators
3. **Set owner attribute**: Use `DocpipeConstants.OWNER_CUSTOM` for proper priority resolution
4. **Use keyword-only arguments**: Follow project standard with `*` in method signatures
5. **Handle errors gracefully**: Use try/except in transform() method
6. **Document parameters**: Add docstrings explaining configuration options
7. **Test locally first**: Validate operators work before deploying to S3

## Troubleshooting

### Operator Not Found

Check:
- `DOCPIPE_CUSTOM_OPERATORS` is set correctly
- File/directory exists and is readable
- S3 credentials are configured (for S3 sources)
- Operator short_name matches the one in flow JSON

### Validation Errors

Check logs for validation failures:
- Operator must inherit from `AbstractOperator`
- `transform()` method signature must use keyword-only arguments: `transform(self, *, table: pa.Table, file_name: str | None = None) -> tuple[list[pa.Table], dict]`
- `short_name`, `category`, and `owner` attributes must be defined

### S3 Access Issues

- Verify AWS credentials are configured
- Check S3 bucket permissions
- Ensure boto3 is installed: `pip install boto3`
