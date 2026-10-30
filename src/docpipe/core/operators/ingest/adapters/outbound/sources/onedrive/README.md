# OneDrive Source Adapter

A Microsoft Graph API-based adapter for ingesting documents from OneDrive with app-only authentication (client credentials flow).

## Features

- **App-Only Authentication**: Uses Azure AD client credentials for unattended access
- **Recursive Traversal**: Optionally traverse subdirectories
- **Automatic Text Extraction**: Extracts text from PDF, DOCX, XLSX, TXT, and more
- **File Filtering**: Filter by file extensions and exclude patterns
- **Size Limits**: Optional maximum file size filtering
- **Microsoft Graph Integration**: Uses custom `MicrosoftGraphLoader` for reliable access

## Quick Start

### Prerequisites

1. **Python 3.8+** with pip or uv
2. **Azure AD App Registration** with Microsoft Graph API permissions
3. **OneDrive Drive ID** (optional, uses default drive if not specified)

### Step-by-Step Setup

#### 1. Install Dependencies

```bash
# Using uv (recommended, from project root)
uv pip install msal requests
```

**Required packages:**
- `msal` - Microsoft Authentication Library for app-only authentication
- `requests` - HTTP library for Microsoft Graph API calls

**Optional packages for enhanced text extraction:**
- `pypdf` or `pdfminer.six` - PDF text extraction
- `python-docx` - Word document text extraction
- `openpyxl` - Excel spreadsheet text extraction

#### 2. Create Azure AD App Registration

**Important**: You must create an Azure AD app registration before running the adapter.

1. Go to [Azure Portal](https://portal.azure.com/)
2. Navigate to **Azure Active Directory** > **App registrations**
3. Click **New registration**:
   - Name: "Docpipe OneDrive Connector"
   - Supported account types: "Accounts in this organizational directory only"
   - Click **Register**
4. Note the **Application (client) ID** and **Directory (tenant) ID**
5. Create a client secret:
   - Go to **Certificates & secrets**
   - Click **New client secret**
   - Add description and expiration
   - **Copy the secret value immediately** (you won't see it again)
6. Add API permissions:
   - Go to **API permissions**
   - Click **Add a permission** > **Microsoft Graph** > **Application permissions**
   - Add **Files.Read.All**
   - Click **Grant admin consent** (requires admin privileges)

#### 3. Get Your Drive ID (Optional)

To ingest from a specific OneDrive:

1. Use Microsoft Graph Explorer: https://developer.microsoft.com/en-us/graph/graph-explorer
2. Sign in and run: `GET https://graph.microsoft.com/v1.0/me/drive`
3. Copy the `id` field from the response

**Note**: If you don't specify a drive_id, the adapter will use the default drive.

#### 4. Set Environment Variables

```bash
export ONEDRIVE_CLIENT_ID='your-client-id-here'
export ONEDRIVE_CLIENT_SECRET='your-client-credential-here'  # pragma: allowlist secret
export ONEDRIVE_TENANT_ID='your-tenant-id-here'
export ONEDRIVE_DRIVE_ID='your-drive-id-here'  # Optional
export ONEDRIVE_FOLDER_PATH='/Documents'  # Optional, defaults to root
```

#### 5. Run the Test Script

```bash
# From project root
source .venv/bin/activate
python -m docpipe.core.operators.ingest.adapters.outbound.sources.onedrive.adapter
```

## Usage

### Testing the Adapter

The adapter includes a built-in test script:

```bash
# Set environment variables
export ONEDRIVE_CLIENT_ID='your-client-id'
export ONEDRIVE_CLIENT_SECRET='your-client-credential'  # pragma: allowlist secret
export ONEDRIVE_TENANT_ID='your-tenant-id'
export ONEDRIVE_DRIVE_ID='your-drive-id'  # Optional
export ONEDRIVE_FOLDER_PATH='/Documents'  # Optional

# Run the test from project root
source .venv/bin/activate
python -m docpipe.core.operators.ingest.adapters.outbound.sources.onedrive.adapter
```

### Configuration Example

```python
from .config import OneDriveSourceConfig

config = OneDriveSourceConfig(
    client_id="12345678-1234-1234-1234-123456789012",
    client_secret="your-client-credential",  # pragma: allowlist secret
    tenant_id="87654321-4321-4321-4321-210987654321",
    drive_id=None,  # Optional, uses default drive
    folder_path="/Documents",
    recursive=True,
    file_extensions=[".pdf", ".docx", ".txt"],
    exclude_patterns=["*.tmp", "~$*"],
    max_file_size_mb=100,
)
```

### Using in Code

```python
from .adapter import OneDriveSourceAdapter
from .config import OneDriveSourceConfig

# Create configuration
config = OneDriveSourceConfig(
    client_id="your-client-id",
    client_secret="sample-credential-value",  # pragma: allowlist secret
    tenant_id="your-tenant-id",
    folder_path="/Documents",
    recursive=True,
)

# Create adapter
adapter = OneDriveSourceAdapter()

# Test connection
success, message = await adapter.test_connection(config)
print(f"Connection: {message}")

# Fetch documents
async for document in adapter.fetch_documents(config):
    print(f"Document: {document.name} ({len(document.content)} bytes)")
```

## Configuration Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `client_id` | str | Yes | - | Azure AD application (client) ID |
| `client_secret` | str | Yes | - | Azure AD application client secret |
| `tenant_id` | str | Yes | - | Azure AD tenant (directory) ID |
| `drive_id` | str | No | None | Specific OneDrive drive ID (None = default) |
| `folder_path` | str | No | None | Folder path to start from (None = root) |
| `file_path` | str | No | None | Graph drive item id or OneDrive/SharePoint file URL to ingest on its own. When set, only this item is fetched. File events for `onedrive` set this from `file_reference`. A URL must include an `id` or `sourcedoc` query parameter. |
| `recursive` | bool | No | True | Traverse subdirectories |
| `file_extensions` | List[str] | No | [] | File extensions to include (empty = all) |
| `exclude_patterns` | List[str] | No | [] | Glob patterns to exclude |
| `max_file_size_mb` | int | No | None | Maximum file size in MB (None = no limit) |
| `graph_api_version` | str | No | "v1.0" | Microsoft Graph API version |

## Supported File Types

The adapter automatically extracts text from:

| File Type | Extensions | Extraction Method |
|-----------|------------|-------------------|
| Text files | .txt, .md, .csv, .json, .xml, .html, .py, .js, etc. | UTF-8 decode |
| PDF files | .pdf | pypdf or pdfminer.six |
| Word documents | .docx | python-docx |
| Excel spreadsheets | .xlsx | openpyxl |

## Troubleshooting

### "Failed to acquire Microsoft Graph token"

**Solution**:
1. Verify your `client_id`, `client_secret`, and `tenant_id` are correct
2. Ensure the client secret hasn't expired
3. Check that the app registration exists in Azure AD

### "Connection test failed: 401 Unauthorized"

**Solution**:
1. Verify API permissions are granted:
   - Go to Azure Portal > App registrations > Your app
   - Check **API permissions** includes **Files.Read.All**
   - Ensure **Admin consent** is granted (green checkmark)
2. Wait a few minutes after granting permissions for changes to propagate

### "Folder path not found"

**Solution**:
- Verify the folder path exists in OneDrive
- Ensure path starts with `/` (e.g., `/Documents`)
- Check that the app has access to the folder
- Try without `folder_path` to access root directory

### "No documents found"

**Solution**:
- Verify `drive_id` is correct (or omit to use default drive)
- Check that folder contains files matching `file_extensions` filter
- Ensure the app has **Files.Read.All** permission
- Try with `recursive=True` to search subdirectories

### "ImportError: No module named 'msal'"

**Solution**:
```bash
# From project root
uv pip install msal requests
```

### "Failed to extract text from PDF"

**Solution**:
```bash
# Install PDF extraction libraries
uv pip install pypdf pdfminer.six
```

## Performance Considerations

- **Large Folders**: Use `file_extensions` to filter unnecessary files
- **File Size**: Set `max_file_size_mb` to skip large files
- **Recursive Traversal**: Disable `recursive` for shallow scans
- **Rate Limiting**: The adapter handles Microsoft Graph API rate limits automatically

## Architecture

This adapter follows the Hexagonal Architecture pattern:

```
Domain Layer (models.py)
    ↑
Port Interface (document_source.py)
    ↑
Adapter Implementation (adapter.py)
    ↑
External Service (OneDrive via Microsoft Graph API)
```

## Version History

- **1.0.0**: Initial implementation with Microsoft Graph API and app-only authentication

## References

- [Microsoft Graph API](https://docs.microsoft.com/en-us/graph/overview)
- [OneDrive API](https://docs.microsoft.com/en-us/graph/api/resources/onedrive)
- [Azure AD App Registration](https://docs.microsoft.com/en-us/azure/active-directory/develop/quickstart-register-app)
- [MSAL Python](https://github.com/AzureAD/microsoft-authentication-library-for-python)
