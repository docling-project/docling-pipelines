# Amazon S3 Source Adapter

A boto3-based adapter for ingesting documents from Amazon S3 or S3-compatible storage following the hexagonal architecture pattern.

## Features

- **AWS S3 Support**: Native support for Amazon S3
- **S3-Compatible Storage**: Works with IBM COS, MinIO, and other S3-compatible services
- **Recursive Traversal**: Optionally traverse subdirectories (prefixes)
- **File Filtering**: Filter by file extensions and exclude patterns
- **Hidden File Exclusion**: Skip hidden files and directories (starting with '.')
- **Size-Based Filtering**: Optional maximum file size limit
- **Direct Binary Download**: No temporary files, efficient memory usage
- **Metadata Preservation**: Maintains file metadata (modified time, size, content type, ETag, storage class)
- **Error Handling**: Detailed logging and graceful error handling

## Quick Start

### Prerequisites

1. **Python 3.8+** with pip or uv
2. **AWS Credentials** or S3-compatible storage credentials
3. **boto3** library (automatically installed with docpipe dependencies)

### Step-by-Step Setup

#### 1. Install Dependencies

```bash
# Using uv (recommended, from project root)
uv sync

# Or using pip
pip install boto3
```

#### 2. Configure AWS Credentials

**Option A: Environment Variables**
```bash
export AWS_ACCESS_KEY_ID='your-access-key'  # pragma: allowlist secret
export AWS_SECRET_ACCESS_KEY='your-secret-key'  # pragma: allowlist secret
export AWS_DEFAULT_REGION='us-east-1'  # Optional
```

**Option B: AWS Credentials File** (`~/.aws/credentials`)
```ini
[default]
aws_access_key_id = your-access-key  # pragma: allowlist secret
aws_secret_access_key = your-secret-key  # pragma: allowlist secret
region = us-east-1
```

**Option C: Flow Configuration** (Recommended for docpipe pipelines)
```json
{
  "credentials": {
    "access_key": "<your-access-key>",  # pragma: allowlist secret
    "secret_key": "<your-secret-key>"  # pragma: allowlist secret
  }
}
```

#### 3. Test the Adapter

```bash
# Set environment variables
export S3_ACCESS_KEY='your-access-key'  # pragma: allowlist secret
export S3_SECRET_KEY='your-secret-key'  # pragma: allowlist secret
export S3_BUCKET='your-bucket-name'
export S3_PREFIX='documents/'

# Run test script
python examples/connectors/test_s3_adapter.py
```

## Configuration

### S3SourceConfig Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `access_key` | str | Yes | - | AWS access key ID or S3-compatible access key |
| `secret_key` | str | Yes | - | AWS secret access key or S3-compatible secret key |
| `bucket` | str | Yes | - | S3 bucket name |
| `prefix` | str | No | "" | S3 key prefix to filter objects (e.g., 'documents/reports/') |
| `object_key` | str | No | None | Object key to ingest on its own (e.g., 'invoices/report.pdf'). When set, only this object is fetched. File events for `s3` and `ibm_cos` set this from `file_reference`. The value is a key, not an `s3://` URI. |
| `endpoint_url` | str | No | None | Custom S3 endpoint URL for S3-compatible storage (e.g., 'https://s3.example.com') |
| `region` | str | No | None | AWS region (e.g., 'us-east-1'). Optional for S3-compatible storage |
| `recursive` | bool | No | True | Whether to recursively traverse subdirectories (prefixes) |
| `file_extensions` | list[str] | No | [] | List of file extensions to include (e.g., ['.pdf', '.docx']). Empty list means all files |
| `exclude_patterns` | list[str] | No | [] | List of glob patterns to exclude (e.g., ['*.tmp', '.DS_Store']) |
| `max_file_size_mb` | int | No | None | Maximum file size in MB to process. None means no limit |
| `skip_hidden_files` | bool | No | True | Whether to skip hidden files and directories (starting with '.') |
| `skip_empty_files` | bool | No | True | Whether to skip files with zero size |
| `max_concurrent_downloads` | int | No | 20 | Maximum number of concurrent S3 downloads (1-20) |
| `download_timeout_seconds` | int | No | 300 | Timeout for downloading a single file in seconds (minimum 30) |

### Configuration Examples

#### AWS S3 Configuration
```python
from core.operators.ingest.adapters.outbound.sources.s3.config import S3SourceConfig

config = S3SourceConfig(
    access_key="<your-access-key>",  # pragma: allowlist secret
    secret_key="<your-secret-key>",  # pragma: allowlist secret
    bucket="my-documents-bucket",
    prefix="documents/reports/",
    region="us-east-1",
    recursive=True,
    file_extensions=[".pdf", ".docx", ".txt"],
    exclude_patterns=["*.tmp", ".DS_Store", "~$*"],
    max_file_size_mb=100,
    skip_hidden_files=True,
)
```

#### S3-Compatible Storage (IBM COS, MinIO)
```python
config = S3SourceConfig(
    access_key="<your-access-key>",  # pragma: allowlist secret
    secret_key="<your-secret-key>",  # pragma: allowlist secret
    bucket="my-bucket",
    prefix="data/",
    endpoint_url="https://s3.us-south.cloud-object-storage.appdomain.cloud",
    recursive=True,
    file_extensions=[".pdf", ".json"],
)
```

## Usage

### Standalone Usage

```python
import asyncio
from core.operators.ingest.adapters.outbound.sources.s3.adapter import S3SourceAdapter
from core.operators.ingest.adapters.outbound.sources.s3.config import S3SourceConfig

async def main():
    # Create configuration
    config = S3SourceConfig(
        access_key="<your-access-key>",  # pragma: allowlist secret
        secret_key="<your-secret-key>",  # pragma: allowlist secret
        bucket="my-bucket",
        prefix="documents/",
        file_extensions=[".pdf", ".txt"],
    )

    # Create adapter
    adapter = S3SourceAdapter()

    # Test connection
    success, message = await adapter.test_connection(config)
    print(f"Connection test: {message}")

    # Fetch documents
    async for document in adapter.fetch_documents(config):
        print(f"Document: {document.name} ({len(document.content)} bytes)")
        print(f"  URL: {document.source_url}")
        print(f"  Modified: {document.modified_time}")
        print(f"  Metadata: {document.metadata}")

if __name__ == "__main__":
    asyncio.run(main())
```

### Flow Configuration

```json
{
    "flow_name": "S3 Document Ingestion",
    "flow": [
        {
            "name": "ingest_s3_documents",
            "type": "ingest_source",
            "config": {
                "provider": "s3",
                "credentials": {
                    "access_key": "<your-s3-access-key>", # pragma: allowlist secret
                    "secret_key": "<your-s3-secret-key>" # pragma: allowlist secret
                },
                "connection_params": {
                    "bucket": "my-documents-bucket",
                    "prefix": "documents/",
                    "region": "us-east-1",
                    "recursive": true,
                    "skip_hidden_files": true,
                    "skip_empty_files": true,
                    "max_file_size_mb": 100
                },
                "include_filter": "pdf,docx,txt",
                "max_files": 100,
                "force_ingest": true
            }
        }
    ]
}
```

### IBM Cloud Object Storage (COS) Example

```json
{
    "provider": "s3",
    "credentials": {
        "access_key": "<your-cos-access-key>",  # pragma: allowlist secret
        "secret_key": "<your-cos-secret-key>"  # pragma: allowlist secret
    },
    "connection_params": {
        "bucket": "my-cos-bucket",
        "prefix": "data/",
        "endpoint_url": "https://s3.us-south.cloud-object-storage.appdomain.cloud",
        "recursive": true
    },
    "include_filter": "pdf,json,csv"
}
```

## Testing

### Unit Tests

```bash
# From project root
# Run S3 adapter unit tests
source .venv/bin/activate
uv run pytest tests/unit/operators/ingest/test_s3_source_adapter.py -v

# Run with coverage
uv run pytest tests/unit/operators/ingest/test_s3_source_adapter.py --cov=docpipe.core.operators.ingest.adapters.outbound.sources.s3 --cov-report=html
```

### Integration Tests

```bash
# Set up test environment
export S3_ACCESS_KEY='your-test-access-key'  # pragma: allowlist secret
export S3_SECRET_KEY='your-test-secret-key'  # pragma: allowlist secret
export S3_BUCKET='test-bucket'

# Run integration test
python examples/connectors/test_s3_adapter.py

# Or run flow-based test
docling-pipelines --flow-file sample_flows/use_cases/s3_to_opensearch.json
```

## Architecture

### Hexagonal Architecture Pattern

The S3 adapter follows the hexagonal architecture (ports and adapters) pattern:

```
┌─────────────────────────────────────────────────────────┐
│                    Domain Layer                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │  Document (domain model)                        │   │
│  │  - id, name, content, source_url                │   │
│  │  - modified_time, metadata, acl                 │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │  DocumentSourcePort (interface)                 │   │
│  │  - fetch_documents()                            │   │
│  │  - test_connection()                            │   │
│  │  - get_config_schema()                          │   │
│  │  - build_config_from_operator_params()          │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
                          ▲
                          │ implements
                          │
┌─────────────────────────────────────────────────────────┐
│                  Adapter Layer                          │
│  ┌─────────────────────────────────────────────────┐   │
│  │  S3SourceAdapter                                │   │
│  │  - Uses boto3 for S3 operations                 │   │
│  │  - Converts S3 objects to domain Documents      │   │
│  │  - Handles filtering, pagination, errors        │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │  S3SourceConfig (Pydantic model)                │   │
│  │  - Type-safe configuration                      │   │
│  │  - Automatic validation                         │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
                          │
                          │ uses
                          ▼
┌─────────────────────────────────────────────────────────┐
│              External Service (boto3/S3)                │
└─────────────────────────────────────────────────────────┘
```

### Key Components

1. **Domain Models** (`domain/models.py`):
   - `Document`: Technology-agnostic document representation
   - `DocumentACL`: Access control information
   - `IngestionResult`: Ingestion operation results

2. **Port Interface** (`ports/outbound/document_source.py`):
   - `DocumentSourcePort`: Abstract interface for all source adapters
   - Defines contract between domain and adapters

3. **Adapter Implementation** (`adapters/outbound/sources/s3/adapter.py`):
   - `S3SourceAdapter`: Concrete implementation using boto3
   - Handles S3-specific operations and error handling

4. **Configuration** (`adapters/outbound/sources/s3/config.py`):
   - `S3SourceConfig`: Pydantic model for type-safe configuration
   - Automatic validation and normalization

5. **Factory** (`adapters/outbound/sources/factories/source_factory.py`):
   - `SourceAdapterFactory`: Registry and factory for adapters
   - Automatic adapter discovery via `@register_source_adapter` decorator

## Error Handling

The adapter provides detailed error handling for common S3 scenarios:

### Connection Errors

```python
success, message = await adapter.test_connection(config)
if not success:
    if "does not exist" in message:
        # Bucket not found
    elif "Access denied" in message:
        # Permission issues
    elif "Invalid access key" in message:
        # Credential issues
```

### Document Fetch Errors

- **ClientError**: S3 API errors (logged and skipped)
- **BotoCoreError**: boto3 errors (logged and skipped)
- **Network errors**: Automatic retry with exponential backoff (boto3 default)

## Performance Considerations

### Optimization Tips

1. **Use Prefix Filtering**: Narrow down the search space
   ```python
   config = S3SourceConfig(
       bucket="large-bucket",
       prefix="specific/folder/",  # Much faster than scanning entire bucket
   )
   ```

2. **Limit File Extensions**: Reduce unnecessary downloads
   ```python
   config = S3SourceConfig(
       file_extensions=[".pdf", ".docx"],  # Only process these types
   )
   ```

3. **Set Max File Size**: Avoid downloading huge files
   ```python
   config = S3SourceConfig(
       max_file_size_mb=50,  # Skip files larger than 50MB
   )
   ```

4. **Use Exclude Patterns**: Skip known unwanted files
   ```python
   config = S3SourceConfig(
       exclude_patterns=["*.tmp", ".DS_Store", "~$*", "Thumbs.db"],
   )
   ```

### Pagination

The adapter uses boto3's paginator for efficient handling of large buckets:
- Automatically handles pagination
- Processes objects in batches
- Memory-efficient for buckets with millions of objects

## Troubleshooting

### Common Issues

#### 1. "Access Denied" Error

**Cause**: Insufficient IAM permissions

**Solution**: Ensure IAM user/role has these permissions:
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:ListBucket",
                "s3:GetObject"
            ],
            "Resource": [
                "arn:aws:s3:::your-bucket",
                "arn:aws:s3:::your-bucket/*"
            ]
        }
    ]
}
```

#### 2. "NoSuchBucket" Error

**Cause**: Bucket doesn't exist or wrong region

**Solution**:
- Verify bucket name is correct
- Specify correct region in configuration
- Check if bucket exists in AWS Console

#### 3. "SignatureDoesNotMatch" Error

**Cause**: Invalid secret key or clock skew

**Solution**:
- Verify secret key is correct
- Check system clock is synchronized (NTP)
- For S3-compatible storage, verify endpoint URL

#### 4. Slow Performance

**Cause**: Large bucket or no filtering

**Solution**:
- Use `prefix` to narrow search
- Add `file_extensions` filter
- Set `max_file_size_mb` limit
- Use `exclude_patterns` for known unwanted files

#### 5. Memory Issues

**Cause**: Processing very large files

**Solution**:
- Set `max_file_size_mb` to reasonable limit
- Process files in smaller batches using `max_files` in operator config
- Consider streaming processing for large files

## Migration from Legacy S3 Implementation

The new adapter is backward compatible with existing flow configurations. No changes required to existing flows using `provider: "s3"`.

### What Changed

1. **Architecture**: Now uses hexagonal architecture pattern
2. **Implementation**: Uses adapter pattern instead of direct boto3 calls in operator
3. **Configuration**: More flexible with Pydantic validation
4. **Error Handling**: More robust with detailed error messages
5. **Testing**: Better unit test coverage

### What Stayed the Same

1. **Provider Name**: Still use `"provider": "s3"`
2. **Flow Configuration**: Same JSON structure
3. **Credentials**: Same credential format
4. **Output**: Same PyArrow table schema

## Contributing

When adding new features to the S3 adapter:

1. Update `S3SourceConfig` with new parameters
2. Implement feature in `S3SourceAdapter`
3. Add unit tests in `test_s3_source_adapter.py`
4. Update this README
5. Add example in `examples/connectors/test_s3_adapter.py`

## License

This adapter is part of the docling-pipelines project.

## Support

For issues or questions:
1. Check this README
2. Review unit tests for usage examples
3. Check existing flow configurations in `tests/`
4. Open an issue in the project repository
