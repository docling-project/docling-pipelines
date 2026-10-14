# Document Libraries User Guide

## Overview

Document Libraries provide a way to organize and manage collections of Document Sets in docpipe. A Document Library is a metadata container that groups related Document Sets together, enabling better organization, discovery, and management of your document collections.

## Key Concepts

### Document Library
A Document Library is a named collection that contains references to multiple Document Sets. It stores:
- **Metadata**: Name, description, tags, timestamps
- **Relationships**: References to Document Set IDs (many-to-many)
- **Aggregate Metrics**: Computed statistics from associated Document Sets

**Important**: Document Libraries store only metadata and references, not the actual document content or data.

### Relationship with Document Sets
- **One-to-Many**: A Document Library can contain multiple Document Sets
- **Many-to-Many**: A Document Set can belong to multiple Document Libraries
- **Reference-Based**: Libraries store Document Set IDs, not copies of data

### Storage Architecture
Document Libraries use the same generic asset storage as Document Sets and Flows:

- Each library is one JSON record in the `document_libraries` collection, stored through the
  `KeyValueStoragePort` interface (DuckDB by default).
- The record contains the library's `document_set_ids`, so adding or removing document sets
  updates that one record. There is no separate relationship table.
- The repository is `DuckDBAssetRepository[DocumentLibrary]`, created by `RepositoryFactory`.

## Prerequisites

### Environment Setup
```bash
# 1. Navigate to project root directory
cd /path/to/docling-pipelines

# 2. Activate virtual environment
source .venv/bin/activate

# 3. Set PYTHONPATH
export PYTHONPATH="$(pwd)/src:${PYTHONPATH}"

# 4. Ensure dependencies are installed
uv sync
```

### API Server
Document Libraries are accessed via REST API endpoints. Start the API server:

```bash
# Recommended — uses the installed console entry point
docling-pipelines-api

# Alternative — invoke uvicorn directly (with PYTHONPATH set)
uvicorn docpipe.api.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000` with interactive documentation at `http://localhost:8000/api/v1/docs`.

**Note:** The direct `uvicorn` command must be run from the project root with `PYTHONPATH` set to include the `src` directory.

**Troubleshooting:**
- **Error: "address already in use"**: Port 8000 is already occupied. Either:
  - Stop the existing server: `pkill -f "uvicorn docpipe.api.main:app"`
  - Use a different port: `uvicorn docpipe.api.main:app --port 8001`
- **Error: "Could not import module"**: Ensure `PYTHONPATH` is set correctly and you're in the project root directory

## API Endpoints

### Base URL
All Document Library endpoints are under: `/api/v1/document-libraries`

### Available Operations

#### 1. Create a Document Library
**Endpoint**: `POST /api/v1/document-libraries`

**Request Body**:
```json
{
  "name": "Financial Documents Q1 2024",
  "description": "Collection of financial documents for Q1 2024 analysis",
  "tags": ["finance", "q1-2024", "reports"]
}
```

**Validation Rules**:
- `name`: Required, 3-128 characters, must start with a letter, alphanumeric with spaces/underscores only (NO hyphens)
- `description`: Optional, max 2000 characters
- `tags`: Optional, no limit on count or individual tag length

**Response** (201 Created):
```json
{
  "library_id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Financial Documents Q1 2024",
  "description": "Collection of financial documents for Q1 2024 analysis",
  "tags": ["finance", "q1-2024", "reports"],
  "document_set_ids": [],
  "aggregate_metrics": {
    "total_document_sets": 0,
    "total_documents": 0,
    "total_size_bytes": 0
  },
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:30:00Z"
}
```

**Example using curl**:
```bash
curl -X POST "http://localhost:8000/api/v1/document-libraries" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Financial Documents Q1 20241",
    "description": "Collection of financial documents for Q1 2024 analysis",
    "tags": ["finance", "q1-2024", "reports"]
  }'
```

#### 2. Get a Document Library
**Endpoint**: `GET /api/v1/document-libraries/{library_id}`

**Response** (200 OK):
```json
{
  "library_id": "81cea322-ae1b-4142-8f27-e06ff39e211a",
  "name": "Financial Documents Q1 20241",
  "description": "Collection of financial documents for Q1 2024 analysis",
  "purpose": null,
  "original_size": null,
  "final_size": null,
  "tags": [
    "finance",
    "q1-2024",
    "reports"
  ],
  "created_by": null,
  "href": null
}
```

**Example using curl**:
```bash
curl -X GET "http://localhost:8000/api/v1/document-libraries/550e8400-e29b-41d4-a716-446655440000"
```

#### 3. Update a Document Library
**Endpoint**: `PATCH /api/v1/document-libraries/{library_id}`

**Request Body**:
- `name` (required): Library name (3-128 characters, must start with letter, can only contain letters/digits/spaces/underscores)
- `description` (optional): Updated description
- `purpose` (optional): Updated purpose
- `original_size` (optional): Updated original size
- `final_size` (optional): Updated final size
- `tags` (optional): Updated tags list

**Note:** Name field is currently required even for PATCH operations. Name cannot contain hyphens or special characters.

```json
{
  "name": "Financial Documents Q1 2024 Updated",
  "description": "Updated collection description",
  "tags": ["finance", "q1_2024", "reports", "audited"]
}
```

**Response** (200 OK): Returns updated library object

**Example using curl**:
```bash
curl -X PATCH "http://localhost:8000/api/v1/document-libraries/550e8400-e29b-41d4-a716-446655440000" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Financial Documents Q1 2024 Updated",
    "description": "Updated collection description",
    "tags": ["finance", "q1_2024", "reports", "audited"]
  }'
```

#### 4. Delete a Document Library
**Endpoint**: `DELETE /api/v1/document-libraries/{library_id}`

**Response** (204 No Content)

**Note**: Deleting a library does not delete the associated Document Sets, only the library metadata and relationships.

**Example using curl**:
```bash
curl -X DELETE "http://localhost:8000/api/v1/document-libraries/550e8400-e29b-41d4-a716-446655440000"
```

#### 5. Add Document Sets to Library (Bulk)
**Endpoint**: `PUT /api/v1/document-libraries/{library_id}/document-sets`

**Query Parameters**:
- `document_sets_ids` (required): Comma-separated list of document set UUIDs

**Response** (204 No Content): Document sets added successfully

**Example using curl**:
```bash
curl -X PUT "http://localhost:8000/api/v1/document-libraries/550e8400-e29b-41d4-a716-446655440000/document-sets?document_sets_ids=abc123,def456,ghi789"
```

#### 6. Remove Document Sets from Library (Bulk)
**Endpoint**: `DELETE /api/v1/document-libraries/{library_id}/document-sets`

**Query Parameters**:
- `document_sets_ids` (required): Comma-separated list of document set UUIDs

**Response** (204 No Content): Document sets removed successfully

**Note**: This removes the associations but does NOT delete the document sets themselves.

**Example using curl**:
```bash
curl -X DELETE "http://localhost:8000/api/v1/document-libraries/550e8400-e29b-41d4-a716-446655440000/document-sets?document_sets_ids=abc123,def456"
```

#### 7. List All Document Libraries
**Endpoint**: `GET /api/v1/document-libraries`

**Query Parameters**:
- `offset`: Number of records to skip (default: 0)
- `limit`: Maximum number of records to return (default: 100)

**Response** (200 OK):
```json
[
  {
    "library_id": "e8b2cf35-4d2a-4997-b1e2-2470cd05fd73",
    "name": "Financial Documents Q1 2024",
    "description": "Collection of financial documents for Q1 2024 analysis",
    "purpose": null,
    "original_size": null,
    "final_size": null,
    "tags": [
      "finance",
      "q1-2024",
      "reports"
    ],
    "created_by": null,
    "href": null
  },
  {
    "library_id": "81cea322-ae1b-4142-8f27-e06ff39e211a",
    "name": "Financial Documents Q1 20241",
    "description": "Collection of financial documents for Q1 2024 analysis",
    "purpose": null,
    "original_size": null,
    "final_size": null,
    "tags": [
      "finance",
      "q1-2024",
      "reports"
    ],
    "created_by": null,
    "href": null
  }
]
```

**Example using curl**:
```bash
curl -X GET "http://localhost:8000/api/v1/document-libraries?offset=0&limit=10"
```

#### 8. List Document Sets in a Library
**Endpoint**: `GET /api/v1/document-libraries/{library_id}/document-sets`

**Path Parameters**:
- `library_id` (required): UUID of the library

**Response** (200 OK):
```json
{
  "document_sets": [
    {
      "id": "f824b653-45af-45a6-9336-341c6aeb2d8a",
      "name": "Research Documents1",
      "container_id": null,
      "container_type": null,
      "description": "Collection of research papers and reports.",
      "documents": null,
      "tags": [],
      "propagate_source_acls": null,
      "is_derivative_available": null
    },
    {
      "id": "85d7a47f-9d81-4ffe-a112-a93b88cd9c70",
      "name": "Research Documents",
      "container_id": null,
      "container_type": null,
      "description": "Collection of research papers and reports.",
      "documents": null,
      "tags": [],
      "propagate_source_acls": null,
      "is_derivative_available": null
    }
  ]
}
```

**Example using curl**:
```bash
curl -X GET "http://localhost:8000/api/v1/document-libraries/550e8400-e29b-41d4-a716-446655440000/document-sets"
```

## Python Client Example

```python
import requests
import json

class DocumentLibraryClient:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.api_path = "/api/v1/document-libraries"

    def create_library(self, name: str, description: str = None, tags: list = None):
        """Create a new document library"""
        url = f"{self.base_url}{self.api_path}"
        payload = {"name": name}
        if description:
            payload["description"] = description
        if tags:
            payload["tags"] = tags

        response = requests.post(url, json=payload)
        response.raise_for_status()
        return response.json()

    def get_library(self, library_id: str):
        """Get a document library by ID"""
        url = f"{self.base_url}{self.api_path}/{library_id}"
        response = requests.get(url)
        response.raise_for_status()
        return response.json()

    def update_library(self, library_id: str, name: str = None,
                      description: str = None, tags: list = None):
        """Update a document library"""
        url = f"{self.base_url}{self.api_path}/{library_id}"
        payload = {}
        if name:
            payload["name"] = name
        if description:
            payload["description"] = description
        if tags:
            payload["tags"] = tags

        response = requests.patch(url, json=payload)
        response.raise_for_status()
        return response.json()

    def delete_library(self, library_id: str):
        """Delete a document library"""
        url = f"{self.base_url}{self.api_path}/{library_id}"
        response = requests.delete(url)
        response.raise_for_status()

    def add_document_sets(self, library_id: str, document_set_ids: list[str]):
        """Add document sets to a library (bulk operation)"""
        url = f"{self.base_url}{self.api_path}/{library_id}/document-sets"
        params = {"document_sets_ids": ",".join(document_set_ids)}
        response = requests.put(url, params=params)
        response.raise_for_status()

    def remove_document_sets(self, library_id: str, document_set_ids: list[str]):
        """Remove document sets from a library (bulk operation)"""
        url = f"{self.base_url}{self.api_path}/{library_id}/document-sets"
        params = {"document_sets_ids": ",".join(document_set_ids)}
        response = requests.delete(url, params=params)
        response.raise_for_status()

    def list_document_sets(self, library_id: str):
        """List document sets in a library"""
        url = f"{self.base_url}{self.api_path}/{library_id}/document-sets"
        response = requests.get(url)
        response.raise_for_status()
        return response.json()

# Usage example
if __name__ == "__main__":
    client = DocumentLibraryClient()

    # Create a library
    library = client.create_library(
        name="Invoice Processing Library",
        description="Collection of invoice document sets",
        tags=["invoices", "accounting", "q1-2024"]
    )
    print(f"Created library: {library['library_id']}")

    # Add document sets (bulk operation)
    client.add_document_sets(library['library_id'], ["docset-001", "docset-002"])

    # List document sets in library
    doc_sets = client.list_document_sets(library['library_id'])
    print(f"Library has {len(doc_sets['document_sets'])} document sets")
```

## Error Handling

### Common Error Responses

#### 404 Not Found
```json
{
  "detail": "Document library not found: 550e8400-e29b-41d4-a716-446655440000"
}
```

#### 409 Conflict
```json
{
  "detail": "Document library with name 'Financial Documents Q1 2024' already exists"
}
```

#### 422 Validation Error
```json
{
  "detail": [
    {
      "loc": ["body", "name"],
      "msg": "ensure this value has at least 3 characters",
      "type": "value_error.any_str.min_length"
    }
  ]
}
```

### Error Handling in Python

```python
import requests

try:
    response = requests.post(
        "http://localhost:8000/api/v1/document-libraries",
        json={"name": "My Library"}
    )
    response.raise_for_status()
    library = response.json()
except requests.exceptions.HTTPError as e:
    if e.response.status_code == 404:
        print("Library not found")
    elif e.response.status_code == 409:
        print("Library already exists")
    elif e.response.status_code == 422:
        print(f"Validation error: {e.response.json()}")
    else:
        print(f"HTTP error: {e}")
except requests.exceptions.RequestException as e:
    print(f"Request failed: {e}")
```

## Best Practices

### 1. Naming Conventions
- Use descriptive, meaningful names
- Include time periods or versions when relevant
- Names must start with a letter and contain only letters, digits, spaces, and underscores
- Example: "Financial Reports Q1 2024", "Legal Contracts 2024_v2"

### 2. Tagging Strategy
- Use consistent tag naming (lowercase, hyphenated)
- Create a tag taxonomy for your organization
- Examples: "finance", "q1-2024", "high-priority", "audited"

### 3. Organization Patterns
- **By Time Period**: "Q1 2024 Documents", "2024 Annual Reports"
- **By Department**: "HR Documents", "Legal Contracts", "Finance Reports"
- **By Project**: "Project Alpha Documents", "Customer Onboarding"
- **By Status**: "Draft Documents", "Approved Documents", "Archived"

### 4. Aggregate Metrics
- Metrics are automatically computed when document sets are added/removed
- Use metrics for monitoring and reporting
- Metrics include: total_document_sets, total_documents, total_size_bytes

### 5. Performance Considerations
- Use pagination (skip/limit) for large result sets
- Use search/filter endpoints instead of fetching all libraries
- Cache frequently accessed library metadata

## Troubleshooting

### Issue: Library Not Found
**Symptom**: 404 error when accessing a library

**Solutions**:
1. Verify the library_id is correct
2. Check if the library was deleted
3. Use the list endpoint to see all available libraries

### Issue: Duplicate Library Name
**Symptom**: 409 conflict error when creating a library

**Solutions**:
1. Choose a different name
2. Update the existing library instead
3. Delete the old library if no longer needed

### Issue: Validation Errors
**Symptom**: 422 validation error

**Solutions**:
1. Check name length (3-128 characters minimum)
2. Ensure name starts with a letter (a-z, A-Z)
3. Verify description length (max 2000 characters)
4. Use only alphanumeric characters, spaces, and underscores in names (no hyphens or special characters)
5. Name pattern: `^[a-zA-Z][a-zA-Z0-9_ ]*$` (example: "My Library Name" or "Test_Library_123")

### Issue: API Server Not Running
**Symptom**: Connection refused errors

**Solutions**:
1. Start the API server: `uvicorn app.main:app --reload`
2. Verify the server is running on the correct port (default: 8000)
3. Check firewall settings

## Advanced Topics

### Database Schema

The Document Library feature stores each library as one JSON record:

**Library records (`KeyValueStoragePort`, JSON)**:
```sql
CREATE TABLE document_libraries (
    key VARCHAR PRIMARY KEY,                         -- library id
    data JSON NOT NULL,                              -- Full library record as JSON
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**JSON Structure in `data` column**:
```json
{
  "library_id": "uuid",
  "asset_id": "uuid",
  "name": "Library Name",
  "description": "Description",
  "purpose": "Purpose",
  "original_size": 1024,
  "final_size": 512,
  "tags": ["tag1", "tag2"],
  "created_by": "user@example.com",
  "href": "https://...",
  "document_set_ids": ["docset-uuid-1", "docset-uuid-2"]
}
```

`document_set_ids` is stored inside `data`, in the order the document sets were added.

**Architecture Notes**:
- Library records use the `KeyValueStoragePort` interface, like Document Sets and Flows
- JSON storage enables a flexible schema
- Databases created by older versions may still contain an unused `library_documentset_junction` table; it can be dropped

### Hexagonal Architecture

The Document Library implementation follows hexagonal architecture (ports & adapters):

- **Domain Layer**: Pure Python business logic (DocumentLibrary model)
- **Ports**: Generic repository interface (`AssetRepository[DocumentLibrary]`)
- **Adapters**: Generic DuckDB implementation (`DuckDBAssetRepository[DocumentLibrary]`), created by `RepositoryFactory`
- **Application Layer**: Service orchestration (DocumentLibraryService)
- **API Layer**: FastAPI routes and DTOs

This architecture allows for:
- Easy testing with mocked repositories
- Swapping storage backends (e.g., PostgreSQL, MongoDB)
- Clear separation of concerns

## Related Documentation

- [ARCHITECTURE.md](../../ARCHITECTURE.md) - System architecture overview
- [OPERATOR_REFERENCE.md](../reference/OPERATORS.md) - Operator documentation
- [USER_GUIDE_PIPELINE_SETUP.md](../../USER_GUIDE_PIPELINE_SETUP.md) - Pipeline setup guide

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review the API documentation at `http://localhost:8000/docs`
3. Consult the ARCHITECTURE.md for technical details
4. Open an issue on the project repository
