# SharePoint Source Adapter

A Microsoft Graph API-based adapter for ingesting documents from SharePoint document libraries with app-only authentication (client credentials flow).

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
3. **SharePoint Document Library ID** (required)

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
   - Name: "Docpipe SharePoint Connector"
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
   - Add **Sites.Read.All**
   - Click **Grant admin consent** (requires admin privileges)

#### 3. Get Your Document Library ID

To find your SharePoint document library ID:

**Method 1: Using Microsoft Graph Explorer**
1. Go to https://developer.microsoft.com/en-us/graph/graph-explorer
2. Sign in and run:
   ```
   GET https://graph.microsoft.com/v1.0/sites/{site-id}/drives
   ```
3. Find your document library in the response and copy its `id`

**Method 2: Using SharePoint URL**
1. Navigate to your document library in SharePoint
2. The URL will look like: `https://yourtenant.sharepoint.com/sites/yoursite/Shared%20Documents`
3. Use Graph API to get the drive ID:
   ```
   GET https://graph.microsoft.com/v1.0/sites/{site-id}/drives
   ```

**Method 3: Using PowerShell**
```powershell
Connect-PnPOnline -Url "https://yourtenant.sharepoint.com/sites/yoursite"
Get-PnPList | Where-Object {$_.BaseTemplate -eq 101} | Select Title, Id
```

#### 4. Set Environment Variables

```bash
export SHAREPOINT_CLIENT_ID='your-client-id-here'
export SHAREPOINT_CLIENT_SECRET='your-client-credential-here'  # pragma: allowlist secret
export SHAREPOINT_TENANT_ID='your-tenant-id-here'
export SHAREPOINT_DOCUMENT_LIBRARY_ID='your-document-library-id-here'
export SHAREPOINT_FOLDER_PATH='/Shared Documents'  # Optional
```

#### 5. Run the Test Script

```bash
# From project root
source .venv/bin/activate
python -m docpipe.core.operators.ingest.adapters.outbound.sources.sharepoint.adapter
```

## Usage

### Testing the Adapter

The adapter includes a built-in test script:

```bash
# Set environment variables
export SHAREPOINT_CLIENT_ID='your-client-id'
export SHAREPOINT_CLIENT_SECRET='your-client-credential'  # pragma: allowlist secret
export SHAREPOINT_TENANT_ID='your-tenant-id'
export SHAREPOINT_DOCUMENT_LIBRARY_ID='your-document-library-id'
export SHAREPOINT_FOLDER_PATH='/Shared Documents'  # Optional

# Run the test from project root
source .venv/bin/activate
python -m docpipe.core.operators.ingest.adapters.outbound.sources.sharepoint.adapter
```

### Configuration Example

```python
from .config import SharePointSourceConfig

config = SharePointSourceConfig(
    client_id="12345678-1234-1234-1234-123456789012",
    client_secret="your-client-credential",  # pragma: allowlist secret
    tenant_id="87654321-4321-4321-4321-210987654321",
    document_library_id="b!abc123...",
    folder_path="/Shared Documents",
    recursive=True,
    file_extensions=[".pdf", ".docx", ".txt"],
    exclude_patterns=["*.tmp", "~$*"],
    max_file_size_mb=100,
)
```

### Using in Code

```python
from .adapter import SharePointSourceAdapter
from .config import SharePointSourceConfig

# Create configuration
config = SharePointSourceConfig(
    client_id="your-client-id",
    client_secret="sample-credential-value",  # pragma: allowlist secret
    tenant_id="your-tenant-id",
    document_library_id="your-document-library-id",
    folder_path="/Shared Documents",
    recursive=True,
)

# Create adapter
adapter = SharePointSourceAdapter()

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
| `document_library_id` | str | Yes | - | SharePoint document library ID (drive ID) |
| `folder_path` | str | No | None | Folder path to start from (None = root) |
| `file_path` | str | No | None | Graph drive item id or SharePoint file URL to ingest on its own. When set, only this item is fetched. File events for `sharepoint` set this from `file_reference`. A URL must include an `id` or `sourcedoc` query parameter. |
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
   - Check **API permissions** includes **Sites.Read.All**
   - Ensure **Admin consent** is granted (green checkmark)
2. Wait a few minutes after granting permissions for changes to propagate

### "Folder path not found"

**Solution**:
- Verify the folder path exists in SharePoint
- Ensure path starts with `/` (e.g., `/Shared Documents`)
- Check that the app has access to the document library
- Try without `folder_path` to access root directory

### "Document library not found"

**Solution**:
- Verify `document_library_id` is correct
- Use Microsoft Graph Explorer to list available drives:
  ```
  GET https://graph.microsoft.com/v1.0/sites/{site-id}/drives
  ```
- Ensure the app has **Sites.Read.All** permission

### "No documents found"

**Solution**:
- Verify the document library contains files
- Check that files match `file_extensions` filter
- Ensure the app has **Sites.Read.All** permission
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

## SharePoint vs OneDrive

| Feature | SharePoint | OneDrive |
|---------|-----------|----------|
| **Use Case** | Team sites, document libraries | Personal/business OneDrive |
| **Required ID** | `document_library_id` (required) | `drive_id` (optional) |
| **API Permission** | Sites.Read.All | Files.Read.All |
| **Typical Path** | `/Shared Documents` | `/Documents` |

## Performance Considerations

- **Large Libraries**: Use `file_extensions` to filter unnecessary files
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
External Service (SharePoint via Microsoft Graph API)
```

## Version History

- **1.0.0**: Initial implementation with Microsoft Graph API and app-only authentication

## References

- [Microsoft Graph API](https://docs.microsoft.com/en-us/graph/overview)
- [SharePoint API](https://docs.microsoft.com/en-us/graph/api/resources/sharepoint)
- [Azure AD App Registration](https://docs.microsoft.com/en-us/azure/active-directory/develop/quickstart-register-app)
- [MSAL Python](https://github.com/AzureAD/microsoft-authentication-library-for-python)
