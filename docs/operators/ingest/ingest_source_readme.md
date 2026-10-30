# IngestSourceOperator

Ingests document metadata from cloud storage and collaboration platforms (S3, SharePoint, OneDrive, Google Drive, Box, Dropbox).

- **Short Name:** `ingest_source`
- **Category:** Ingest

---

## Overview

`IngestSourceOperator` provides a unified interface for multiple document sources. It is a **metadata-only** operator — it discovers files and emits path/metadata rows; text content is extracted by a downstream `ExtractOperator`.

---

## Key Features
- **Multi-Provider Support**: Single operator for multiple data sources
- **Automatic File Filtering**: Skips directories, hidden files, and empty objects by extension using [`OperatorConstants.FileExtensions.BASE_EXTENSIONS`](../../../src/docpipe/core/constants/operator_constants.py)
- **Extension Validation**: Validates file extensions against supported formats, defaulting to all supported extensions if not specified
- **Incremental Updates**: Skip previously processed documents (configurable)
- **Metadata Tracking**: Comprehensive tracking of processed, failed, and skipped documents
- **PyArrow Output**: Returns structured data in PyArrow table format
- **Error Handling**: Graceful error handling with detailed logging and metadata
- **Custom Loader Support**: Extensible architecture for custom implementations
- **AbstractOperator Pattern**: Consistent interface with other ingest operators

## Supported Providers

### 1. Local Filesystem
Ingest documents from one or more local directories or individual files. No credentials are required.

**Configuration:**
```python
node_config = {
    'provider': 'filesystem',
    'provider_config': {
        'paths': ['/data/invoices', '/data/contracts'],
        'recursive': True,
        'exclude_patterns': ['*.tmp', '__pycache__/*'],
        'max_file_size_mb': 100,
        'follow_symlinks': False
    }
}
```

**Parameters:**

| Parameter | Type | Required | Default | Description |
|---------|------|----------|---------|-------------|
| `paths` | `list[str]` | Yes | — | One or more absolute or relative paths to files or directories |
| `recursive` | bool | No | `True` | Recursively traverse subdirectories |
| `exclude_patterns` | list[str] | No | `[]` | Glob patterns to skip (e.g. `["*.tmp", "__pycache__/*"]`) |
| `max_file_size_mb` | int | No | `None` | Skip files larger than this size (MB). `None` means no limit |
| `follow_symlinks` | bool | No | `False` | Follow symbolic links during directory traversal |


**File filtering** is also controlled by the top-level `include_filter` / `exclude_filter` operator parameters (comma-separated extension list, e.g. `"pdf,docx,txt"`).

**Archive expansion:** The filesystem provider expands top-level `.zip`, `.tar`, `.tar.gz`, `.tgz`, and `.gz` files. Each regular archive entry is emitted as an independent row with a synthetic `zip://...#entry` source and the metadata fields `archive_depth=1`, `source_archive`, and `archive_entry`. Archive paths and member names are URL-encoded in that URI. Entry bytes are read lazily in memory when a downstream operator requests them; no temporary files are written.

Archive expansion is limited permanently to depth 1. An archive stored inside another archive is emitted as an opaque row and is never opened recursively. Regular filesystem rows carry `archive_depth=0`. Add the archive extension to `include_filter` when using an explicit filter (for example, `"zip,pdf,txt"`).

### 2. Amazon S3 and S3-Compatible Storage
Ingest documents from Amazon S3 buckets and S3-compatible storage services (IBM Cloud Object Storage, MinIO, etc.).

**Configuration (AWS S3):**
```python
node_config = {
    'provider': 's3',
    'provider_config': {
        'bucket': 'your-bucket-name',
        'prefix': 'optional/path/prefix/',  # Optional
        'region': 'us-east-1',             # Optional
        'access_key': 'YOUR_AWS_ACCESS_KEY',
        'secret_key': 'YOUR_AWS_SECRET_KEY'  # pragma: allowlist secret
    }
}
```

**Configuration (IBM Cloud Object Storage):**
```python
node_config = {
    'provider': 's3',
    'provider_config': {
        'bucket': 'your-bucket-name',
        'prefix': 'optional/path/prefix/',  # Optional
        'endpoint_url': 'https://s3.us-south.cloud-object-storage.appdomain.cloud',
        'access_key': 'YOUR_IBM_ACCESS_KEY',
        'secret_key': 'YOUR_IBM_SECRET_KEY'  # pragma: allowlist secret
    }
}
```

**Parameters:**
- `bucket` (required): S3 bucket name
- `prefix` (optional): S3 key prefix to filter objects. Supports both directory-level and single file ingestion:
  - **Directory ingestion**: `'documents/reports/'` - ingests all files in the directory
  - **Single file ingestion**: `'documents/report.pdf'` - ingests only the specified file
  - **Entire bucket**: `''` (empty string) - ingests all files in the bucket
- `endpoint_url` (optional): Custom S3 endpoint URL for S3-compatible storage (e.g., IBM COS, MinIO). Leave empty for AWS S3.
- `region` (optional): AWS region (e.g., 'us-east-1'). Optional for S3-compatible storage.
- `access_key` (required): AWS access key ID or S3-compatible access key
- `secret_key` (required): AWS secret access key or S3-compatible secret key
- `recursive` (optional): Whether to recursively traverse subdirectories (default: True)
- `exclude_patterns` (optional): List of glob patterns to exclude (e.g., ['*.tmp', '.DS_Store'])
- `max_file_size_mb` (optional): Maximum file size in MB to process
- `skip_hidden_files` (optional): Whether to skip hidden files (default: True)
- `skip_empty_files` (optional): Whether to skip files with zero size (default: True)
- `verify_expected_bucket_owner` (optional): When `True`, verifies that the S3 bucket is owned by the caller's AWS account via STS `GetCallerIdentity`. If the bucket owner does not match, AWS rejects the request. Default `False`. Has no effect for S3-compatible storage (IBM COS, MinIO).

**Note:** File extension filtering is configured at the operator level using `include_filter` and `exclude_filter` parameters (see [File Filtering](#file-filtering) section below).

### 3. Microsoft SharePoint
Ingest documents from SharePoint document libraries.

**Configuration:**
```python
node_config = {
    'provider': 'sharepoint',
    'provider_config': {
        'document_library_id': 'your-library-id',
        'client_id': 'YOUR_CLIENT_ID',
        'client_secret': 'YOUR_CLIENT_SECRET',  # pragma: allowlist secret
        'tenant_id': 'YOUR_TENANT_ID'
    }
}
```

**Prerequisites:**
- O365 package installed: `pip install O365`
- Azure AD app registration with SharePoint permissions

**Parameters:**
- `document_library_id` (required): SharePoint document library ID
- `client_id` (required): Azure AD application client ID
- `client_secret` (required): Azure AD application client secret
- `tenant_id` (required): Azure AD tenant ID

### 4. Microsoft OneDrive
Ingest documents from OneDrive folders.

**Configuration:**
```python
node_config = {
    'provider': 'onedrive',
    'provider_config': {
        'drive_id': 'your-drive-id',
        'folder_path': '/Documents/MyFolder',  # Optional
        'client_id': 'YOUR_CLIENT_ID',
        'client_secret': 'YOUR_CLIENT_SECRET',  # pragma: allowlist secret
        'tenant_id': 'YOUR_TENANT_ID'
    }
}
```

**Prerequisites:**
- O365 package installed: `pip install O365`
- Azure AD app registration with OneDrive permissions

**Parameters:**
- `drive_id` (required): OneDrive drive ID
- `folder_path` (optional): Path to specific folder
- `client_id` (required): Azure AD application client ID
- `client_secret` (required): Azure AD application client secret
- `tenant_id` (required): Azure AD tenant ID

### 5. Google Drive
Ingest documents from Google Drive folders using OAuth 2.0 authentication.

**Configuration:**
```python
node_config = {
    'provider': 'google_drive',
    'provider_config': {
        'folder_id': 'your-folder-id',
        'recursive': False,  # Optional: include subfolders
        'credentials_path': '/path/to/client_secret.json',
        'token_path': '/path/to/token.json',  # Optional
        'scopes': ['https://www.googleapis.com/auth/drive.readonly']  # Optional
    }
}
```

**Prerequisites:**
- Google Cloud Project with Drive API enabled
- OAuth 2.0 credentials (client secret JSON)
- Dependencies: `pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client`

**Parameters:**
- `folder_id` (required): Google Drive folder ID
- `recursive` (optional): Boolean, include subfolders (default: False)
- `credentials_json_path` (required): Path to OAuth client secret JSON
- `token_path` (optional): Path to store OAuth tokens (default: `~/.credentials/token.json`)
- `scopes` (optional): List of OAuth scopes (default: `['https://www.googleapis.com/auth/drive.readonly']`)

**OAuth Scopes:**
The operator uses read-only access by default for security. Available scopes:
- `https://www.googleapis.com/auth/drive.readonly` - Read-only access (recommended)
- `https://www.googleapis.com/auth/drive` - Full access to all files
- `https://www.googleapis.com/auth/drive.file` - Per-file access

**Important:** If you change scopes, you must delete the existing token file to re-authenticate with the new permissions.

### 6. Box
Ingest documents from Box folders using JWT authentication.

**Configuration:**
```python
node_config = {
    'provider': 'box_driver',
    'provider_config': {
        'folder_id': '0',  # Optional: Box folder ID to start from (default: '0' for root)
        'recursive': True,  # Optional: include subfolders
        'max_file_size_mb': 50,  # Optional: max file size in MB
        'exclude_patterns': ['*.tmp', 'Trash/*'],  # Optional: patterns to exclude
        'credentials_path': '/path/to/box_jwt_config.json'
    },
    'include_filter': 'pdf,docx,txt,pptx,xlsx',  # Optional: file extensions to include
    'max_files': 100  # Optional
}
```

**Prerequisites:**
- Box Enterprise account or Box Developer account
- Box JWT application configured with appropriate permissions
- JWT configuration file (JSON) downloaded from Box Developer Console
- Dependencies: `pip install box-sdk-gen`

**Parameters:**
- `folder_id` (optional): Box folder ID to start ingestion from (default: '0' for root folder)
- `recursive` (optional): Boolean, include subfolders (default: False)
- `max_file_size_mb` (optional): Maximum file size in MB to process
- `exclude_patterns` (optional): List of glob patterns to exclude (e.g., `['*.tmp', 'Trash/*']`)
- `credentials_json_path` (required): Path to Box JWT configuration JSON file

**Box JWT Setup:**
1. Create a Box application in the [Box Developer Console](https://app.box.com/developers/console)
2. Choose "Server Authentication (with JWT)" as authentication method
3. Configure application permissions:
   - Read all files and folders stored in Box
   - Manage enterprise properties
4. Generate a public/private keypair
5. Download the JWT configuration JSON file
6. Submit application for admin approval (if required)
7. Admin must authorize the application in Box Admin Console

**Authentication Flow:**
The adapter uses JWT (JSON Web Token) authentication which provides:
- Service account access without user interaction
- Secure authentication using public/private key cryptography
- Enterprise-level access control
- No OAuth redirect flow required

**Security Notes:**
- Store JWT configuration file securely with restricted permissions
- Never commit JWT configuration to version control
- Rotate keys periodically as per security policy
- Use environment variables for file paths in production

### 7. Dropbox
Ingest documents from a Dropbox account using the Dropbox SDK.

**Configuration:**
```python
node_config = {
    'provider': 'dropbox',
    'provider_config': {
        'folder_path': '/Reports',  # Optional: folder to ingest from ('' or '/' for account root)
        'recursive': True,  # Optional: include subfolders (default: True)
        'max_file_size_mb': 50,  # Optional: max file size in MB
        'exclude_patterns': ['*.tmp', '*/Archive/*'],  # Optional: patterns to exclude
        'access_token': '${DROPBOX_ACCESS_TOKEN}'
    },
    'include_filter': 'pdf,docx,txt',  # Optional: file extensions to include
    'max_files': 100  # Optional
}
```

**Prerequisites:**
- Dropbox account and a Dropbox app created in the [App Console](https://www.dropbox.com/developers/apps)
- App scopes: `account_info.read`, `files.metadata.read`, `files.content.read`
- An access token, or a refresh token with the app key and secret
- Dependencies: `pip install dropbox`

**Parameters:**
- `folder_path` (optional): Dropbox folder to ingest from; empty string or `/` means the account root
- `file_path` (optional): Ingest a single file by path (`/Reports/q1.pdf`) or file id (`id:abc123`); ignores folder settings and filters
- `recursive` (optional): Boolean, include subfolders (default: `True`)
- `max_file_size_mb` (optional): Maximum file size in MB to process
- `exclude_patterns` (optional): List of glob patterns to exclude (e.g., `['*.tmp', '*/Archive/*']`)
- `access_token` (credentials): Dropbox OAuth2 access token
- `refresh_token`, `app_key`, `app_secret` (credentials): Long-lived alternative to `access_token`

**Dropbox App Setup:**
1. Create a scoped app in the [Dropbox App Console](https://www.dropbox.com/developers/apps)
2. Choose **App folder** access to limit the app to a single folder, or **Full Dropbox**
3. On the **Permissions** tab enable `account_info.read`, `files.metadata.read` and `files.content.read`, then submit
4. Generate an access token on the **Settings** tab, or run the OAuth2 flow with `token_access_type=offline` to obtain a refresh token
5. Export the token as an environment variable and reference it as `${DROPBOX_ACCESS_TOKEN}` in the flow

**Authentication Notes:**
- Generated access tokens are short-lived (four hours); use the refresh-token flow for scheduled pipelines
- Tokens issued before new scopes were saved do not carry those scopes; re-issue the token after changing permissions
- Apps with **App folder** access see paths relative to their own app folder, not the account root

**Security Notes:**
- Never commit Dropbox tokens to version control; reference them through environment variables
- Grant only the scopes listed above; the adapter never writes to Dropbox
- Rotate tokens periodically and revoke unused app authorizations

### 8. Custom Loaders
Extend functionality with custom LangChain-compatible loaders.

**Configuration:**
```python
node_config = {
    'provider': 'custom',
    'provider_config': {
        'loader_class_path': 'my_package.loaders.CustomLoader',
        # Additional parameters specific to your loader (including credentials)
        'param1': 'value1',
        'param2': 'value2',
        'api_key': 'YOUR_API_KEY'  # pragma: allowlist secret
    }
}
```

**Parameters:**
- `loader_class_path` (required): Python import path to loader class (e.g., `my_package.loaders.FileNetLoader`)
- Additional parameters are passed to the loader's `__init__` method

**Requirements:**
- Loader class must be importable
- Loader must implement LangChain's document loader interface with a `load()` method
- `load()` method must return `List[Document]`

## Usage

### Basic Example
```python
from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator
import pyarrow as pa

# Configure the operator
node_config = {
    'provider': 's3',
    'provider_config': {
        'bucket': 'my-bucket',
        'prefix': 'documents/',
        'access_key': 'YOUR_ACCESS_KEY',
        'secret_key': 'YOUR_SECRET_KEY'  # pragma: allowlist secret
    },
    'job_id': 'my-job-123',
    'job_run_id': 'run-456',
    'max_files': 100,  # Optional: limit number of files
    'include_filter': 'pdf,txt,docx',  # Optional: file extensions to include
    'exclude_filter': 'tmp,log',  # Optional: file extensions to exclude
    'force_ingest': False  # Optional: re-ingest previously processed docs
}

# Create operator instance
ingest_node = IngestSourceOperator(node_config)

# Execute ingestion (input_table is used as trigger)
input_table = pa.Table.from_arrays([])
output_tables, metadata = ingest_node.transform(input_table)

# Access results
result_table = output_tables[0]
print(f"Status: {metadata['node_status']}")
print(f"Documents processed: {metadata['processed_docs']}")
print(f"Total documents: {metadata['total_docs_count']}")
print(f"Failed: {metadata['failed_docs_count']}")
print(f"Skipped: {metadata['skipped_docs_count']}")
print(f"Schema: {result_table.schema}")
```

### Output Schema

See [Output Columns](#output-columns) below for the full column reference.

---

## Parameters

See the [Usage](#usage) section above and per-provider configuration in [Supported Providers](#supported-providers).

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `provider` | string | **Yes** | — | Source provider: `filesystem`, `s3`, `ibm_cos`, `sharepoint`, `onedrive`, `google_drive`, `box_driver`, `dropbox`, `web` |
| `provider_config` | object | **Yes** | — | All provider-specific parameters including credentials in a single dict |
| `include_filter` | string | No | all types | Comma-separated file extensions to include (no dot) |
| `max_files` | integer | No | `100` | Maximum files to ingest |
| `force_ingest` | boolean | No | `false` | Re-ingest previously processed files |

---

## Output Columns

This operator produces a new table; it does not receive an input table.

| Column | PyArrow Type | Description |
|---|---|---|
| `id` | `string` | Document ID (MD5 hash of source path) |
| `name` | `string` | Source path/identifier |
| `document_format` | `string` | File extension (e.g. `.pdf`, `.docx`) |
| `metadata` | `string` | JSON-serialised metadata from the source |
| `source_id` | `string` | Source identifier (from `metadata.source`) |
| `path` | `string` | Source path/URL used for on-demand binary loading by `ExtractOperator` |
| `modified_time` | `int64` | Document modification timestamp (Unix epoch) |

---

## Operator Configuration

```json
{
  "type": "ingest_source",
  "name": "ingest_s3_documents",
  "config": {
    "provider": "s3",
    "provider_config": {
      "bucket": "my-bucket",
      "prefix": "documents/",
      "access_key": "${S3_ACCESS_KEY}",
      "secret_key": "${S3_SECRET_KEY}"
    },
    "include_filter": "pdf,docx",
    "max_files": 500
  }
}
```

### Accessing Results
```python
# Convert to pandas for analysis
df = result_table.to_pandas()

# Access individual documents
for i in range(result_table.num_rows):
    text = result_table['text'][i].as_py()
    metadata = json.loads(result_table['metadata'][i].as_py())
    source = result_table['source_id'][i].as_py()

    print(f"Document {i+1}:")
    print(f"  Source: {source}")
    print(f"  Text length: {len(text)}")
    print(f"  Metadata: {metadata}")
```
### Parameter Naming Clarification

**User Configuration (Flow JSON):**
- Use `include_filter` and `exclude_filter` parameters (comma-separated strings)
- Example: `"include_filter": "pdf,docx,txt"`

**Internal Implementation (For Connector Developers):**
- Internally converted to `included_extensions` (list) → `file_extensions` (config model field)
- Users should never use `included_extensions` or `file_extensions` in their flow configurations


## File Filtering

### Extension-Based Filtering
The operator validates and filters files by extension using centralized constants from [`OperatorConstants.FileExtensions`](../../../src/docpipe/core/constants/operator_constants.py):

**Supported Extensions:**
- **Documents**: PDF, DOCX, PPTX, XLSX
- **Text**: Markdown, Plain Text, HTML
- **Images**: PNG, JPEG, JPG, TIFF, TIF, BMP, WebP, GIF, JFIF
- **Audio** (with ASR): WAV, MP3, M4A, AAC, OGG, FLAC
- **Video** (with ASR): MP4, AVI, MOV

**Filter Parameters:**
- **include_filter**: Comma-separated list of extensions to include (e.g., "pdf,txt,docx")
  - If not specified, defaults to all supported extensions
  - Must be a subset of supported extensions (validation enforced)
- **exclude_filter**: Comma-separated list of extensions to exclude (e.g., "tmp,log")
  - Must be a subset of supported extensions (validation enforced)

**Validation Behavior:**
- Extensions are validated at operator initialization
- Unsupported extensions in `include_filter` or `exclude_filter` raise `ValueError`
- Error messages list the unsupported extensions and all supported extensions
- This ensures only valid file types are processed downstream

### S3 Filtering
The operator automatically filters out:
- **Directory markers**: Objects with keys ending in `/`
- **Hidden files**: Files or directories starting with `.` (except `.` and `..`)
- **Empty objects**: Objects with size 0 bytes

### Max Files Limit
Use the `max_files` parameter to limit the number of documents processed (default: 100).

This ensures only actual file content is processed, improving efficiency and data quality.

## Incremental Updates

The operator supports incremental processing to avoid re-ingesting unchanged documents:

```python
node_config = {
    'provider': 's3',
    'provider_config': {
        'bucket': 'my-bucket',
        'access_key': '...',
        'secret_key': '...'
    },
    'job_id': 'my-job-123',
    'force_ingest': False  # Set to True to re-ingest all documents
}
```

Documents are tracked by their ID and modification time. Previously processed documents are automatically skipped unless `force_ingest` is set to `True`.

## Error Handling

### Graceful Degradation
The operator handles errors gracefully following the AbstractOperator pattern:
- Individual file load failures are tracked in metadata
- Processing continues for remaining files
- Comprehensive error tracking with document-level details

### Metadata Response
```python
# Metadata structure (follows AbstractOperator pattern):
metadata = {
    "node_status": "completed" | "completed_with_errors" | "completed_with_warnings",
    "total_docs_count": 100,
    "processed_docs": 95,
    "failed_docs_count": 3,
    "failed_docs": [
        {"id": "doc1", "name": "file1.pdf", "reason": "Error description", "document_url": ""}
    ],
    "skipped_docs_count": 2,
    "skipped_docs": [
        {"id": "doc2", "name": "file2.pdf", "reason": "Already processed", "document_url": ""}
    ]
}
```

### Common Errors

**Authentication Errors:**
```
Error: Invalid credentials
```
**Solution:** Verify credentials are correct and have necessary permissions.

**Google Drive Scope Errors:**
```
Error: ('invalid_scope: Bad Request', {'error': 'invalid_scope', 'error_description': 'Bad Request'})
```
**Solution:** This error occurs when OAuth scopes are missing or incorrect. To fix:
1. Ensure the `scopes` parameter is included in credentials configuration
2. Delete the existing token file (default: `~/.credentials/token.json`)
3. Re-run the ingestion to trigger re-authentication with correct scopes
4. Use the default scope `['https://www.googleapis.com/auth/drive.readonly']` for read-only access

**Connection Errors:**
```
Error: Could not connect to endpoint
```
**Solution:** Check network connectivity and endpoint URLs (especially for S3-compatible storage like IBM COS).

**Permission Errors:**
```
Error: Access denied
```
**Solution:** Ensure credentials have read permissions for the specified resources.

## Performance Considerations

### Large Datasets
- S3/COS: Uses pagination to handle large buckets efficiently
- Google Drive: Set `recursive=False` for large folder structures
- Consider using `prefix` parameter to limit scope

### Memory Usage
- Documents are loaded into memory before conversion to PyArrow
- For very large files, consider chunking strategies
- Monitor memory usage with large document sets

### Optimization Tips
1. Use specific prefixes/folder IDs to limit scope
2. Filter file types at the source when possible
3. Process in batches for very large datasets
4. Use appropriate loader configurations for your use case

## Integration with Downstream Operators

The output format is designed for seamless integration with:
- **Embedding operators**: Text column ready for vectorization
- **Transform operators**: Metadata available for filtering/routing
- **Storage operators**: PyArrow format for efficient storage

### Example Pipeline
```python
# 1. Ingest documents
ingest_node = IngestSourceOperator(ingest_config)
tables, metadata = ingest_node.transform(input_table)

# 2. Process with downstream operators
# embedding_node = EmbeddingOperator(embedding_config)
# embedded_tables, _ = embedding_node.transform(tables[0])

# 3. Store results
# storage_node = StorageOperator(storage_config)
# storage_node.transform(embedded_tables[0])
```

## Security Best Practices

1. **Credential Management:**
   - Never hardcode credentials in source code
   - Use environment variables or secret management systems
   - Rotate credentials regularly

2. **Access Control:**
   - Use least-privilege principle for service accounts
   - Limit bucket/folder access to necessary resources
   - Monitor access logs for suspicious activity

3. **Data Protection:**
   - Use encrypted connections (HTTPS/TLS)
   - Consider encrypting sensitive data at rest
   - Implement data retention policies

4. **OAuth Tokens (Google Drive, SharePoint, OneDrive):**
   - Store tokens securely with restricted file permissions
   - Never commit token files to version control
   - Implement token refresh mechanisms

## Troubleshooting

### Debug Mode
Enable detailed logging by examining the operator output:
```python
output_tables, metadata = ingest_node.transform(input_table)
print(f"Metadata: {metadata}")
if metadata['status'] == 'error':
    print(f"Error: {metadata['message']}")
```

### Testing Connectivity
Test each provider independently:
```python
# Test S3 connectivity
import boto3
s3_client = boto3.client('s3',
    aws_access_key_id='YOUR_KEY',
    aws_secret_access_key='YOUR_SECRET')  # pragma: allowlist secret
response = s3_client.list_objects_v2(Bucket='your-bucket', MaxKeys=1)
print(f"Connection successful: {response['ResponseMetadata']['HTTPStatusCode'] == 200}")
```

### Common Issues

**Issue: No documents loaded**
- Verify folder/bucket contains files
- Check prefix/path parameters
- Ensure files are not filtered (hidden, empty, directories)

**Issue: Metadata parsing errors**
- Some loaders may return non-JSON-serializable metadata
- Check metadata structure in debug output
- Consider custom metadata handling

**Issue: Slow performance**
- Reduce scope with prefix/folder parameters
- Check network latency to storage provider
- Consider parallel processing for large datasets

## Dependencies

### Core Dependencies
```
langchain==1.2.10
langchain-core==1.2.14
pyarrow==24.0.0
pandas==2.3.3
botocore==1.42.55
```

### Provider-Specific Dependencies
- **AWS/S3:** `boto3==1.42.55`, `langchain-community==0.4.1`
- **Google Drive:** `google-auth-oauthlib==1.2.4`, `google-auth-httplib2==0.3.0`, `google-api-python-client==2.190.0`, `langchain-google-community==3.0.5`
- **SharePoint/OneDrive:** `O365==2.1.9`, `langchain-community==0.4.1`
- **Box:** `box-sdk-gen==1.17.0`, `langchain-community==0.4.1`
- **Dropbox:** `dropbox==12.2.1`
- **PDF Processing:** `pypdf2==3.0.1`, `unstructured[pdf]>=0.10.0`
- **GCP:** `google-cloud-storage==3.9.0`
- **Azure:** `azure-storage-blob==12.28.0`

### Installation

Using uv (recommended):
```bash
# From project root directory
# Core installation (includes langchain and langchain-core)
uv sync

# AWS/S3 support
uv sync --extra aws

# Google Drive support
uv sync --extra google-drive

# Microsoft (SharePoint/OneDrive) support
uv sync --extra microsoft

# Box support
uv sync --extra box

# All cloud providers
uv sync --extra all-cloud

# Development dependencies
uv sync --extra dev
```

Using pip:
```bash
# Core installation
pip install langchain==1.2.10 langchain-core==1.2.14 pyarrow==24.0.0 pandas==2.3.3

# AWS/S3 support
pip install boto3==1.42.55 langchain-community==0.4.1

# Google Drive support
pip install google-auth-oauthlib==1.2.4 google-auth-httplib2==0.3.0 google-api-python-client==2.190.0 langchain-google-community==3.0.5 pypdf2==3.0.1 "unstructured[pdf]>=0.10.0"

# Microsoft support
pip install O365==2.1.9 langchain-community==0.4.1

# Box support
pip install box-sdk-gen==1.17.0 langchain-community==0.4.1
```

## API Reference

### Class: IngestSourceOperator

Inherits from: [`AbstractOperator`](../../../src/docpipe/core/operators/abstract_operator.py)

#### `__init__(node_config: dict)`
Initialize the operator with configuration.

**Parameters:**
- `node_config` (dict): Configuration dictionary containing:
  - `provider` (str): Provider identifier (s3, google_drive, sharepoint, onedrive, box_driver, dropbox, filesystem, web, custom)
  - `provider_config` (dict): All provider-specific parameters including credentials in a single dict
  - `job_id` (str, optional): Job identifier for tracking
  - `job_run_id` (str, optional): Job run identifier
  - `max_files` (int, optional): Maximum number of files to process (default: 100)
  - `include_filter` (str, optional): Comma-separated file extensions to include (defaults to all supported extensions if not specified; must be subset of supported extensions)
  - `exclude_filter` (str, optional): Comma-separated file extensions to exclude (must be subset of supported extensions)
  - `force_ingest` (bool, optional): Force re-ingestion of previously processed documents (default: False)

**Raises:**
- `ValueError`: If `include_filter` or `exclude_filter` contain unsupported file extensions

#### `transform(input_table: pa.Table) -> tuple[list[pa.Table], dict]`
Execute document ingestion.

**Parameters:**
- `input_table` (pa.Table): Input PyArrow table (can be None for initial ingestion)

**Returns:**
- `tuple[list[pa.Table], dict]`:
  - List containing single output PyArrow table with schema (id, name, text, metadata, source_id)
  - Metadata dictionary following AbstractOperator pattern with comprehensive tracking

**Raises:**
- Returns error metadata instead of raising exceptions for graceful degradation

#### `get_metadata() -> dict`
Get operator metadata including features and attributes.

**Returns:**
- `dict`: Operator metadata with features, attributes, and availability information

## Examples

### Example 1: Filesystem — Single Directory (Python)
```python
node_config = {
    'provider': 'filesystem',
    'provider_config': {
        'paths': ['/data/customer_support_docs'],
        'recursive': True,
        'exclude_patterns': ['*.tmp', '__pycache__/*'],
        'max_file_size_mb': 100,
        'follow_symlinks': False
    },
    'include_filter': 'pdf,docx,txt',
    'max_files': 500
}
```

### Example 2: Filesystem — Multiple Directories (Python)
```python
node_config = {
    'provider': 'filesystem',
    'provider_config': {
        'paths': [
            '/data/invoices',
            '/data/contracts',
            '/data/reports'
        ],
        'recursive': True,
        'exclude_patterns': ['*.tmp'],
        'max_file_size_mb': 50,
        'follow_symlinks': False
    },
    'include_filter': 'pdf,docx',
    'force_ingest': False
}
```

### Example 3: Filesystem — Flow JSON (Multiple Directories)
```json
{
  "name": "ingest",
  "type": "ingest_source",
  "config": {
    "provider": "filesystem",
    "provider_config": {
      "paths": [
        "./data/invoices",
        "./data/contracts"
      ],
      "recursive": true,
      "exclude_patterns": ["*.tmp", "__pycache__/*"],
      "max_file_size_mb": 100,
      "follow_symlinks": false
    },
    "include_filter": "pdf,docx,txt",
    "max_files": 1000,
    "force_ingest": false
  }
}
```

### Example 4: S3 with Folder Prefix Filtering
```python
node_config = {
    'provider': 's3',
    'provider_config': {
        'bucket': 'company-documents',
        'prefix': '2024/invoices/',  # Ingests all files in this folder
        'access_key': os.getenv('AWS_ACCESS_KEY'),
        'secret_key': os.getenv('AWS_SECRET_KEY')
    }
}
```

### Example 5: S3 with File-Level Ingestion
```python
node_config = {
    'provider': 's3',
    'provider_config': {
        'bucket': 'company-documents',
        'prefix': '2024/invoices/report.pdf',  # Ingests only this specific file
        'access_key': os.getenv('AWS_ACCESS_KEY'),
        'secret_key': os.getenv('AWS_SECRET_KEY')
    }
}
```

### Example 6: S3-Compatible Storage (IBM COS)
```python
node_config = {
    'provider': 's3',
    'provider_config': {
        'bucket': 'enterprise-data',
        'prefix': 'contracts/',
        'endpoint_url': 'https://s3.eu-gb.cloud-object-storage.appdomain.cloud',
        'access_key': os.getenv('IBM_COS_ACCESS_KEY'),
        'secret_key': os.getenv('IBM_COS_SECRET_KEY')
    }
}
```

### Example 7: Google Drive Recursive
```python
node_config = {
    'provider': 'google_drive',
    'provider_config': {
        'folder_id': '1DKN_mxnoW1Uaacghz8vyEeqw-j4IOSFK',
        'recursive': True,
        'credentials_json_path': os.getenv('GOOGLE_CREDENTIALS_PATH'),
        'token_path': os.path.expanduser('~/.credentials/gdrive_token.json'),
        'scopes': ['https://www.googleapis.com/auth/drive.readonly']
    }
}
```

### Example 8: Box with JWT Authentication
```python
node_config = {
    'provider': 'box_driver',
    'provider_config': {
        'folder_id': '123456789',  # Specific Box folder ID (use '0' for root)
        'recursive': True,
        'max_file_size_mb': 50,
        'exclude_patterns': ['*.tmp', 'Trash/*'],
        'credentials_json_path': os.getenv('BOX_JWT_CONFIG_FILE')
    },
    'include_filter': 'pdf,docx,txt,pptx,xlsx',  # File extensions to include
    'max_files': 100
}
```

### Example 9: Dropbox Folder with Extension Filtering
```python
node_config = {
    'provider': 'dropbox',
    'provider_config': {
        'folder_path': '/Reports/2026',
        'recursive': True,
        'max_file_size_mb': 50,
        'exclude_patterns': ['*.tmp', '*/Archive/*'],
        'access_token': os.getenv('DROPBOX_ACCESS_TOKEN')
    },
    'include_filter': 'pdf,docx,txt',
    'max_files': 100
}
```

## Contributing

To add support for a new provider:

1. Add the provider to the `_get_loader()` method
2. Import the corresponding LangChain loader
3. Map configuration parameters to loader initialization
4. Update this documentation with provider details
5. Add example configuration and usage

## Sample Flow

See [`sample_flows/use_cases/s3_to_opensearch.json`](../../../sample_flows/use_cases/s3_to_opensearch.json) for a complete example ingesting from S3 through to OpenSearch.

## Related Documentation
- [Operators Overview](../../../README.md)

## License
See project LICENSE file for details.
