# Guide: Creating a New Connector for Docling Pipelines

This guide shows you how to add a new data source connector to Docling Pipelines using the hexagonal architecture adapter pattern.

## Table of Contents
1. [Overview](#overview)
2. [Directory Structure](#directory-structure)
3. [Step-by-Step Implementation](#step-by-step-implementation)
4. [Example: Dropbox Connector](#example-dropbox-connector)
5. [Testing](#testing)
6. [Reference Implementations](#reference-implementations)
7. [Architecture Diagram](#architecture-diagram)

## Overview

Docling Pipelines uses a **hexagonal architecture** with adapters for data sources. Each connector consists of:
- **Configuration Model** (Pydantic): Type-safe configuration with validation
- **Adapter Class**: Implements the `DocumentSourcePort` interface with required methods:
  - `fetch_documents()`: Async generator yielding `Document` objects
  - `test_connection()`: Validates connectivity to the source
  - `get_config_schema()`: Returns the Pydantic config model class
  - `build_config_from_operator_params()`: Maps operator params to adapter config
- **Auto-Registration**: Uses `@register_source_adapter` decorator (no parameters needed)
- **Metadata Attributes**: `SOURCE_NAME`, `SOURCE_DISPLAY_NAME`, `SOURCE_DESCRIPTION`, `SOURCE_VERSION`

## Directory Structure

Create your connector in this location:
```
src/docpipe/core/operators/ingest/adapters/outbound/sources/
└── your_connector/
    ├── __init__.py          # Export adapter and config
    ├── adapter.py           # Main adapter implementation
    ├── config.py            # Pydantic configuration model
    └── README.md            # Required connector documentation
```

## Architecture Diagram

```text
                    +--------------------------------------+
                    |           Flow JSON config           |
                    |   provider, connection, credentials  |
                    +------------------+-------------------+
                                       |
                                       v
                    +--------------------------------------+
                    |         IngestSourceOperator         |
                    | builds adapter-specific config model |
                    +------------------+-------------------+
                                       |
                                       v
                    +--------------------------------------+
                    |         DocumentSourcePort           |
                    | fetch_documents / test_connection    |
                    +------------------+-------------------+
                                       |
                    +------------------+-------------------+
                    |                                      |
                    v                                      v
      +-------------------------------+      +-------------------------------+
      |   YourConnectorSourceAdapter  |      |      SourceAdapterFactory     |
      | adapter.py                    |<-----| @register_source_adapter      |
      +---------------+---------------+      +-------------------------------+
                      |
                      v
      +-------------------------------+
      |      YourConnectorConfig      |
      | config.py (Pydantic model)    |
      +---------------+---------------+
                      |
                      v
      +-------------------------------+
      | Provider SDK / external API   |
      | aiohttp, boto3, msal, etc.    |
      +---------------+---------------+
                      |
                      v
      +-------------------------------+
      | Domain Document instances     |
      | yielded back to the operator  |
      +-------------------------------+
```

### Step 0: Determine Required Credentials

**Before writing any code**, identify what credentials your connector needs by consulting the API documentation:

#### Research Checklist:
1. **Authentication Method**:
   - API Key / Token?
   - OAuth 2.0?
   - Username/Password?
   - Certificate-based?

2. **Connection Parameters**:
   - API endpoint URL?
   - Server hostname?
   - Port number?
   - Database/Catalog name?
   - Workspace/Tenant ID?

3. **Data Location**:
   - Folder/Directory path?
   - Bucket name?
   - Table/Collection name?
   - Query parameters?

4. **Optional Settings**:
   - Recursive traversal?
   - File filters (extensions, size)?
   - Pagination settings?
   - Timeout values?

#### Example: Determining Google Drive Credentials

Check [Google Drive API docs](https://developers.google.com/drive/api/):

**Required:**
- `credentials_path`: Path to OAuth credentials JSON file
- `scopes`: OAuth scopes (e.g., `drive.readonly`)

**Optional:**
- `token_path`: Where to store OAuth token
- `folder_id`: Specific folder to ingest from
- `recursive`: Traverse subdirectories
- `file_extensions`: Filter by file type

**How to get these:**
1. Go to Google Cloud Console
2. Create OAuth 2.0 credentials
3. Download credentials JSON file
4. Set scopes based on access needed

#### Pattern: Organizing Config Fields

Group your configuration fields logically:

```python
class ConnectorConfig(BaseModel):
    """Configuration for Connector."""

    # 1. Connection Parameters (how to reach the service)
    host: str = Field(..., description="Service hostname")
    port: int = Field(443, description="Service port")

    # 2. Authentication (how to authenticate)
    api_key: str = Field(..., description="API key")
    # OR
    username: str = Field(..., description="Username")
    password: str = Field(..., description="Password")

    # 3. Data Location (what data to fetch)
    folder_path: str = Field("/", description="Folder to ingest")
    database: str = Field(..., description="Database name")

    # 4. Behavior (how to fetch)
    recursive: bool = Field(True, description="Recursive traversal")
    batch_size: int = Field(100, description="Batch size")

    # 5. Filters (what to include/exclude)
    file_extensions: List[str] = Field(default_factory=list)
    max_file_size_mb: Optional[int] = None
```
### Step 0.5: Add Adapter Dependencies

If your connector needs an external SDK or client library, add it to the project dependency manifest before implementing the adapter.

- Runtime dependencies belong in `pyproject.toml`
- Development and test-only packages belong under the appropriate optional/dev dependency group in `pyproject.toml`
- After updating dependencies, run `uv sync`

Examples:
- `boto3` for Amazon S3-compatible APIs
- `google-api-python-client` / `google-auth-*` for Google integrations
- `msal` for Microsoft Graph authentication
- `aiohttp` for async HTTP-based connectors

Document any new dependency in the connector `README.md` and in broader project docs if the dependency changes user setup.

## Step-by-Step Implementation

### Step 1: Create Configuration Model (`config.py`)

```python
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List

class YourConnectorConfig(BaseModel):
    """Configuration for Your Connector source."""

    # Connection parameters
    api_endpoint: str = Field(..., description="API endpoint URL")
    folder_path: str = Field("/", description="Folder path to start from")

    # Credentials
    access_token: str = Field(..., description="Access token for authentication")

    # Optional parameters
    recursive: bool = Field(True, description="Recursively list folders")
    file_types: Optional[List[str]] = Field(None, description="File types to include")

    @field_validator("access_token")
    @classmethod
    def validate_token(cls, v: str) -> str:
        """Validate access token format."""
        if not v or len(v) < 10:
            raise ValueError("Invalid access token")
        return v
```

**Key Points:**
- Use Pydantic `BaseModel` for type safety
- Add `Field()` with descriptions for documentation
- Use `@field_validator` for custom validation
- Separate connection params and credentials

### Step 2: Implement Adapter (`adapter.py`)

```python
from typing import AsyncGenerator
import aiohttp
import json

from docpipe.core.operators.ingest.ports.outbound.document_source import DocumentSourcePort
from docpipe.core.operators.ingest.domain.models import Document
from docpipe.core.operators.ingest.adapters.outbound.sources.factories.source_factory import register_source_adapter
from .config import YourConnectorConfig

@register_source_adapter
class YourConnectorSourceAdapter(DocumentSourcePort[YourConnectorConfig]):
    """Adapter for Your Connector data source."""

    # Metadata for connector discovery
    SOURCE_NAME = "your_connector"
    SOURCE_DISPLAY_NAME = "Your Connector"
    SOURCE_DESCRIPTION = "Ingest documents from Your Connector"
    SOURCE_VERSION = "1.0.0"

    async def fetch_documents(
        self, *, config: YourConnectorConfig
    ) -> AsyncGenerator[Document, None]:
        """
        Fetch documents from Your Connector.

        Args:
            config: Configuration for the connector

        Yields:
            Document: Domain document with content and metadata
        """
        async with aiohttp.ClientSession() as session:
            # List files from API
            files = await self._list_files(session=session, config=config)

            # Download and yield each file
            for file_metadata in files:
                try:
                    # Download file content
                    content = await self._download_file(
                        session=session,
                        config=config,
                        file_metadata=file_metadata,
                    )

                    # Create domain Document
                    doc = Document(
                        id=file_metadata["id"],
                        name=file_metadata["name"],
                        source_url=file_metadata["url"],
                        content=content,  # bytes
                        size=len(content),
                        mimetype=file_metadata.get("mime_type", "application/octet-stream"),
                        extension=self._get_extension(filename=file_metadata["name"]),
                        modified_time=file_metadata.get("modified_time"),
                        metadata={
                            "path": file_metadata.get("path"),
                            "custom_field": file_metadata.get("custom_field"),
                            # Add any connector-specific metadata
                        }
                    )

                    yield doc

                except Exception as e:
                    # Log error but continue processing other files
                    print(f"Error processing {file_metadata['name']}: {e}")
                    continue

    async def _list_files(
        self,
        *,
        session: aiohttp.ClientSession,
        config: YourConnectorConfig
    ) -> list[dict]:
        """List files from the connector API."""
        url = f"{config.api_endpoint}/files/list"
        headers = {"Authorization": f"Bearer {config.access_token}"}
        data = {
            "path": config.folder_path,
            "recursive": config.recursive
        }

        async with session.post(url, headers=headers, json=data) as response:
            response.raise_for_status()
            result = await response.json()
            return [entry for entry in result["entries"] if entry["type"] == "file"]

    async def _download_file(
        self,
        *,
        session: aiohttp.ClientSession,
        config: YourConnectorConfig,
        file_metadata: dict
    ) -> bytes:
        """Download file content."""
        url = f"{config.api_endpoint}/files/download"
        headers = {
            "Authorization": f"Bearer {config.access_token}",
            "File-Path": file_metadata["path"]
        }

        async with session.get(url, headers=headers) as response:
            response.raise_for_status()
            return await response.read()

    def _get_extension(self, *, filename: str) -> str:
        """Extract file extension."""
        return filename.split(".")[-1] if "." in filename else ""

    async def test_connection(self, *, config: YourConnectorConfig) -> tuple[bool, str]:
        """
        Test connection to Your Connector API.

        Args:
            config: Configuration for the connector

        Returns:
            Tuple[bool, str]: (success, message)
        """
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{config.api_endpoint}/health"
                headers = {"Authorization": f"Bearer {config.access_token}"}
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        return True, "Connection successful"
                    return False, f"Connection failed with status {response.status}"
        except Exception as e:
            return False, f"Connection error: {str(e)}"

    def get_config_schema(self) -> type[YourConnectorConfig]:
        """Get the Pydantic configuration model for this source."""
        return YourConnectorConfig

    def build_config_from_operator_params(
        self,
        *,
        connection_params: dict,
        credentials: dict,
        included_extensions: list[str] | None = None,
        max_files: int | None = None,
    ) -> YourConnectorConfig:
        """
        Build adapter-specific configuration from operator parameters.

        Args:
            connection_params: Connection parameters from operator config
            credentials: Credentials from operator config
            included_extensions: File extensions to include (optional)
            max_files: Maximum number of files to fetch (optional)

        Returns:
            YourConnectorConfig: Adapter-specific configuration object
        """
        return YourConnectorConfig(
            api_endpoint=connection_params.get("api_endpoint"),
            folder_path=connection_params.get("folder_path", "/"),
            access_token=credentials.get("access_token"),
            recursive=connection_params.get("recursive", True),
            file_types=included_extensions or connection_params.get("file_types"),
        )

**Parameter Naming Note:**
- Users configure file filtering using `include_filter` (comma-separated string) in their flow JSON
- The operator converts this to `included_extensions` (list) and passes it to your adapter
- Your adapter config model typically uses `file_extensions` or `file_types` as the field name
- This separation keeps the user API simple while allowing flexible internal implementation

```

**Key Points:**
- Use `@register_source_adapter` decorator (no parameter - uses `SOURCE_NAME`)
- Implement all required methods: `fetch_documents()`, `test_connection()`, `get_config_schema()`, `build_config_from_operator_params()`
- Use keyword-only arguments (`*,`) for all method parameters except `self`/`cls`
- Return `Document` objects from `domain.models`
- Handle errors gracefully (log and continue)
- Store binary content in `Document.content` as bytes

### Step 3: Register in `__init__.py`

```python
"""Your Connector source adapter."""

from .adapter import YourConnectorSourceAdapter
from .config import YourConnectorConfig

__all__ = ["YourConnectorSourceAdapter", "YourConnectorConfig"]
```

### Step 4: Add Required Documentation

Each connector should include a `README.md`. Do not treat this as optional.

At minimum, document:
- authentication method and required credentials
- required dependencies and how to install/sync them
- supported connection parameters
- supported file types or filtering behavior
- local test instructions
- example flow configuration
- known limitations or provider-specific caveats

This keeps the operator discoverable and reduces repeated setup/debugging work.

### Step 5: Create Flow Configuration

Create a JSON flow file (e.g., `sample_flows/use_cases/your_connector_pipeline.json`):

```json
{
  "name": "Your Connector to OpenSearch Pipeline",
  "description": "Ingest documents from Your Connector and store in OpenSearch",
  "nodes": [
    {
      "id": "ingest_your_connector",
      "operator_type": "ingest_source",
      "operator_params": {
        "provider": "your_connector",
        "connection_params": {
          "api_endpoint": "https://api.yourconnector.com",
          "folder_path": "/Documents",
          "recursive": true
        },
        "credentials": {
          "access_token": "${YOUR_CONNECTOR_ACCESS_TOKEN}"
        }
      }
    },
    {
      "id": "chunk_documents",
      "operator_type": "chunker",
      "operator_params": {
        "chunk_size": 512,
        "chunk_overlap": 50
      }
    },
    {
      "id": "generate_embeddings",
      "operator_type": "embeddings_operator",
      "operator_params": {
        "model_name": "nomic-embed-text"
      }
    },
    {
      "id": "store_opensearch",
      "operator_type": "opensearch_operator",
      "operator_params": {
        "index_name": "your_connector_docs",
        "dimension": 768
      }
    }
  ],
  "edges": [
    {"source": "ingest_your_connector", "target": "chunk_documents"},
    {"source": "chunk_documents", "target": "generate_embeddings"},
    {"source": "generate_embeddings", "target": "store_opensearch"}
  ]
}
```

## Example: Dropbox Connector

Here's a complete example implementing a Dropbox connector:

> **Note:** A production Dropbox connector now ships with the project. This section remains a simplified teaching example built on raw HTTP calls; the shipped adapter uses the Dropbox SDK, supports refresh-token authentication and paginates listings. See [`sources/dropbox/README.md`](../../src/docpipe/core/operators/ingest/adapters/outbound/sources/dropbox/README.md) for the real implementation.

### `dropbox/config.py`

```python
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List

class DropboxConfig(BaseModel):
    """Configuration for Dropbox connector."""

    access_token: str = Field(..., description="Dropbox access token")
    folder_path: str = Field("/", description="Folder path to start from")
    recursive: bool = Field(True, description="Recursively list folders")
    file_types: Optional[List[str]] = Field(None, description="File types to include")

    @field_validator("access_token")
    @classmethod
    def validate_token(cls, v: str) -> str:
        if not v or len(v) < 10:
            raise ValueError("Invalid access token")
        return v
```

### `dropbox/adapter.py`

```python
from typing import AsyncGenerator, List
import aiohttp
import json

from docpipe.core.operators.ingest.ports.outbound.document_source import DocumentSourcePort
from docpipe.core.operators.ingest.domain.models import Document
from docpipe.core.operators.ingest.adapters.outbound.sources.factories.source_factory import register_source_adapter
from .config import DropboxConfig

@register_source_adapter
class DropboxSourceAdapter(DocumentSourcePort[DropboxConfig]):
    """Adapter for Dropbox."""

    SOURCE_NAME = "dropbox"
    SOURCE_DISPLAY_NAME = "Dropbox"
    SOURCE_DESCRIPTION = "Ingest documents from Dropbox"
    SOURCE_VERSION = "1.0.0"

    async def fetch_documents(self, *, config: DropboxConfig) -> AsyncGenerator[Document, None]:
        """Fetch documents from Dropbox."""
        async with aiohttp.ClientSession() as session:
            # List files
            files = await self._list_files(session, config)

            # Download and yield each file
            for file_metadata in files:
                content = await self._download_file(session, config, file_metadata)

                doc = Document(
                    id=file_metadata["id"],
                    name=file_metadata["name"],
                    content=content,
                    source_url=f"https://www.dropbox.com/home{file_metadata['path_display']}",
                    modified_time=file_metadata.get("server_modified"),
                    size=len(content),
                    mimetype="application/octet-stream",
                    extension=file_metadata["name"].split(".")[-1] if "." in file_metadata["name"] else "",
                    metadata={}
                )

                yield doc

    async def _list_files(
        self,
        *,
        session: aiohttp.ClientSession,
        config: DropboxConfig
    ) -> list[dict]:
        """List files in Dropbox folder."""
        url = "https://api.dropboxapi.com/2/files/list_folder"
        headers = {"Authorization": f"Bearer {config.access_token}"}
        data = {"path": config.folder_path, "recursive": config.recursive}

        async with session.post(url, headers=headers, json=data) as response:
            response.raise_for_status()
            result = await response.json()
            return [entry for entry in result["entries"] if entry[".tag"] == "file"]

    async def _download_file(
        self,
        *,
        session: aiohttp.ClientSession,
        config: DropboxConfig,
        file_metadata: dict
    ) -> bytes:
        """Download file content from Dropbox."""
        url = "https://content.dropboxapi.com/2/files/download"
        headers = {
            "Authorization": f"Bearer {config.access_token}",
            "Dropbox-API-Arg": json.dumps({"path": file_metadata["path_lower"]})
        }

        async with session.post(url, headers=headers) as response:
            response.raise_for_status()
            return await response.read()

    async def test_connection(self, *, config: DropboxConfig) -> tuple[bool, str]:
        """Test connection to Dropbox."""
        try:
            async with aiohttp.ClientSession() as session:
                url = "https://api.dropboxapi.com/2/users/get_current_account"
                headers = {"Authorization": f"Bearer {config.access_token}"}
                async with session.post(url, headers=headers) as response:
                    if response.status == 200:
                        return True, "Connection successful"
                    return False, f"Connection failed with status {response.status}"
        except Exception as e:
            return False, f"Connection error: {str(e)}"

    def get_config_schema(self) -> type[DropboxConfig]:
        """Get the Pydantic configuration model."""
        return DropboxConfig

    def build_config_from_operator_params(
        self,
        *,
        connection_params: dict,
        credentials: dict,
        included_extensions: list[str] | None = None,
        max_files: int | None = None,
    ) -> DropboxConfig:
        """Build configuration from operator parameters."""
        return DropboxConfig(
            access_token=credentials.get("access_token"),
            folder_path=connection_params.get("folder_path", "/"),
            recursive=connection_params.get("recursive", True),
            file_types=included_extensions or connection_params.get("file_types"),
        )
```

## Testing

### Unit Tests (`tests/unit/operators/ingest/test_your_connector.py`)

```python
import pytest
from unittest.mock import AsyncMock, patch, Mock

from docpipe.core.operators.ingest.adapters.outbound.sources.your_connector.adapter import YourConnectorSourceAdapter
from docpipe.core.operators.ingest.adapters.outbound.sources.your_connector.config import YourConnectorConfig

@pytest.mark.asyncio
async def test_your_connector_fetch_documents():
    """Test fetching documents from Your Connector."""
    config = YourConnectorConfig(
        api_endpoint="https://api.test.com",
        access_token="test_token_1234567890",
        folder_path="/test"
    )

    adapter = YourConnectorSourceAdapter()

    with patch.object(adapter, '_list_files', new_callable=AsyncMock) as mock_list:
        with patch.object(adapter, '_download_file', new_callable=AsyncMock) as mock_download:
            # Mock API responses
            mock_list.return_value = [
                {
                    "id": "file1",
                    "name": "test.txt",
                    "path": "/test/test.txt",
                    "url": "https://connector.com/file1"
                }
            ]
            mock_download.return_value = b"test content"

            # Fetch documents
            documents = []
            async for doc in adapter.fetch_documents(config=config):
                documents.append(doc)

            # Assertions
            assert len(documents) == 1
            assert documents[0].name == "test.txt"
            assert documents[0].content == b"test content"
            assert documents[0].size == 12

def test_config_validation():
    """Test configuration validation."""
    # Valid config
    config = YourConnectorConfig(
        api_endpoint="https://api.test.com",
        access_token="valid_token_1234567890",
        folder_path="/test"
    )
    assert config.access_token == "valid_token_1234567890"

    # Invalid token (too short)
    with pytest.raises(ValueError, match="Invalid access token"):
        YourConnectorConfig(
            api_endpoint="https://api.test.com",
            access_token="short",
            folder_path="/test"
        )
```

### Integration Test

```python
@pytest.mark.asyncio
async def test_your_connector_integration():
    """Integration test with IngestSourceOperator."""
    from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

    config = {
        "provider": "your_connector",
        "connection_params": {
            "api_endpoint": "https://api.test.com",
            "folder_path": "/test",
            "recursive": True
        },
        "credentials": {
            "access_token": "test_token_1234567890"
        },
        "job_id": "test-job-123",
        "job_run_id": "test-run-456"
    }

    operator = IngestSourceOperator(config)

    # Mock the adapter
    with patch(
        "docpipe.core.operators.ingest.adapters.outbound.sources.factories.source_factory.SourceAdapterFactory.create"
    ) as mock_create:
        mock_adapter = Mock()

        async def mock_fetch(config):
            yield Mock(
                id="1",
                name="test.txt",
                content=b"content",
                source_url="https://test.com/file1",
                size=7,
                mimetype="text/plain",
                extension="txt",
                modified_time=None,
                metadata={}
            )

        mock_adapter.fetch_documents = mock_fetch
        mock_create.return_value = mock_adapter

        # Execute
        result_tables, metadata = operator.transform(empty_input_table)

        assert len(result_tables) == 1
        assert result_tables[0].num_rows > 0
```

## Reference Implementations

Study these existing connectors for best practices:

### 1. **SharePoint Adapter** (Microsoft Graph API)
- Location: `src/docpipe/core/operators/ingest/adapters/outbound/sources/sharepoint/`
- Features: OAuth authentication, recursive folder traversal, binary content handling
- Good for: Enterprise connectors with OAuth

### 2. **OneDrive Adapter** (Microsoft Graph API)
- Location: `src/docpipe/core/operators/ingest/adapters/outbound/sources/onedrive/`
- Features: Similar to SharePoint, personal cloud storage
- Good for: Personal cloud storage connectors

### 3. **Google Drive Adapter**
- Location: `src/docpipe/core/operators/ingest/adapters/outbound/sources/google_drive/`
- Features: Google OAuth, Drive API integration
- Good for: Google Workspace connectors

### 4. **Filesystem Adapter**
- Location: `src/docpipe/core/operators/ingest/adapters/outbound/sources/filesystem/`
- Features: Local file system access, simple implementation
- Good for: Local file sources, testing

### 5. **Amazon S3 Adapter**
- Location: `src/docpipe/core/operators/ingest/adapters/outbound/sources/s3/`
- Features: S3 bucket ingestion, cloud object storage patterns, credential-based access
- Good for: Object storage connectors and pagination/listing patterns

## Running Your Connector

### 1. Execute Flow
```bash
source .venv/bin/activate
export PYTHONPATH="$(pwd)/src:${PYTHONPATH}"
docling-pipelines --flow-file tests/flow_your_connector.json
```

### 2. Run Tests
```bash
source .venv/bin/activate
export PYTHONPATH="$(pwd)/src:${PYTHONPATH}"
uv run pytest tests/unit/operators/ingest/test_your_connector.py -v
```

## Best Practices

1. **Error Handling**: Catch and log errors, continue processing other files
2. **Binary Content**: Always store as `bytes` in `Document.content`
3. **Async Operations**: Use `aiohttp` for HTTP requests, `asyncio` for concurrency
4. **Configuration**: Use Pydantic for type-safe, validated configuration
5. **Testing**: Write both unit tests (mocked) and integration tests
6. **Documentation**: Add docstrings and a required README with usage examples, setup notes, and dependency details
7. **Credentials**: Never hardcode credentials, use environment variables
8. **Metadata**: Include useful metadata (path, modified time, custom fields)

## Troubleshooting

### Adapter Not Found
- Ensure `@register_source_adapter` decorator is present (no parameters)
- Check that `SOURCE_NAME` class attribute is defined
- Check that `__init__.py` exports the adapter class
- Verify the `SOURCE_NAME` matches the `provider` value in flow JSON

### Import Errors
- Set `PYTHONPATH` correctly before running
- Check all imports use correct module paths
- Ensure dependencies are installed (`uv sync`)

### Binary Content Issues
- Store content as `bytes`, not `str`
- Use `_binary_content` attribute for LangChain compatibility
- Check file encoding if text files

## Next Steps

1. Create your connector directory structure
2. Implement config and adapter classes
3. Write unit tests
4. Create flow JSON configuration
5. Test with sample data
6. Add integration tests
7. Document usage, dependencies, and examples

For questions or issues, refer to existing adapters and the [Ingest Source Operator documentation](../operators/ingest/ingest_source_readme.md).
