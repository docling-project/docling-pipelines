# Document Libraries Module

## Overview

The Document Libraries module provides metadata management for organizing collections of Document Sets. It follows hexagonal architecture (ports & adapters pattern) to ensure clean separation of concerns and testability.

## Architecture

### Hexagonal Architecture Layers

```
┌─────────────────────────────────────────────────────────────┐
│                        API Layer                             │
│  (FastAPI Routes, DTOs, Mappers)                            │
│  - document_libraries.py (routes)                           │
│  - document_library_dto.py (request/response models)        │
│  - document_library_mapper.py (domain ↔ DTO conversion)     │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    Application Layer                         │
│  (Business Logic Orchestration)                             │
│  - DocumentLibraryService                                   │
│    • Library lifecycle management                           │
│    • Document set relationship management                   │
│    • Business rule enforcement                              │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                      Domain Layer                            │
│  (Pure Business Logic - No Dependencies)                    │
│  - DocumentLibrary (domain model)                           │
│  - DocumentLibraryRepositoryPort (interface)                │
│  - Domain exceptions                                        │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                     Adapters Layer                           │
│  (Infrastructure Implementations)                           │
│  - DuckDBDocumentLibraryStorage (database layer)            │
│  - DuckDBDocumentLibraryMetadataRepository (port implementation)    │
└─────────────────────────────────────────────────────────────┘
```

## Directory Structure

```
document_libraries/
├── README.md                           # This file
├── __init__.py
├── domain/                             # Domain Layer (Pure Python)
│   ├── __init__.py
│   ├── models/
│   │   ├── __init__.py
│   │   └── document_library.py        # DocumentLibrary domain model
│   └── ports/
│       ├── __init__.py
│       └── document_library_repository.py  # Repository interface
├── adapters/                           # Adapters Layer (Infrastructure)
│   ├── __init__.py
│   ├── storage/
│   │   ├── __init__.py
│   │   └── duckdb_storage.py          # DuckDB storage implementation
│   └── repositories/
│       ├── __init__.py
│       └── duckdb_document_library_metadata_repository.py  # Repository implementation
└── application/                        # Application Layer (Services)
    ├── __init__.py
    └── services/
        ├── __init__.py
        └── document_library_service.py  # Business logic orchestration
```

## Domain Model

### DocumentLibrary

The core domain entity representing a collection of Document Sets.

**Attributes:**
- `library_id` (str): Unique identifier (UUID)
- `name` (str): Library name (3-100 characters)
- `description` (str): Optional description (max 500 characters)
- `tags` (List[str]): Optional tags for categorization (max 20 tags)
- `document_set_ids` (List[str]): References to Document Set IDs
- `created_at` (datetime): Creation timestamp
- `last_modified` (datetime): Last modification timestamp
- `total_document_sets` (int): Count of document sets
- `total_documents` (int): Aggregate document count
- `total_size_bytes` (int): Aggregate size in bytes

**Key Methods:**
- `create()`: Factory method for creating new libraries
- `validate()`: Validates all business rules
- `add_document_set()`: Adds a document set reference
- `remove_document_set()`: Removes a document set reference
- `update_aggregate_metrics()`: Updates computed metrics
- `update_timestamp()`: Updates last_modified timestamp

**Validation Rules:**
- Name: 3-100 characters, alphanumeric with spaces/hyphens/underscores
- Description: Max 500 characters
- Tags: Max 20 tags, each 1-50 characters
- Metrics: Non-negative integers

## Repository Pattern

### DocumentLibraryRepositoryPort (Interface)

Defines the contract for persistence operations:

**CRUD Operations:**
- `create(library)`: Create a new library
- `get_by_id(library_id)`: Retrieve by ID
- `get_by_name(name)`: Retrieve by name
- `list_all(skip, limit)`: List all libraries with pagination
- `update(library)`: Update existing library
- `delete(library_id)`: Delete library

**Relationship Management:**
- `add_document_set(library_id, document_set_id)`: Add document set to library
- `remove_document_set(library_id, document_set_id)`: Remove document set from library
- `get_document_sets_for_library(library_id)`: Get all document sets in library

**Query Operations:**
- `list_by_tags(tags, skip, limit)`: Filter by tags
- `search_by_name(name_pattern, skip, limit)`: Search by name

### DuckDBDocumentLibraryMetadataRepository (Implementation)

Concrete implementation using DuckDB for metadata storage only.

**Database Schema:**

1. **document_libraries table** (metadata):
```sql
CREATE TABLE document_libraries (
    library_id VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL UNIQUE,
    description VARCHAR,
    created_at TIMESTAMP NOT NULL,
    last_modified TIMESTAMP NOT NULL,
    total_document_sets INTEGER NOT NULL DEFAULT 0,
    total_documents INTEGER NOT NULL DEFAULT 0,
    total_size_bytes INTEGER NOT NULL DEFAULT 0
);
```

2. **library_documentset_junction table** (many-to-many relationships):
```sql
CREATE TABLE library_documentset_junction (
    library_id VARCHAR NOT NULL,
    document_set_id VARCHAR NOT NULL,
    added_at TIMESTAMP NOT NULL,
    PRIMARY KEY (library_id, document_set_id),
    FOREIGN KEY (library_id) REFERENCES document_libraries(library_id)
);
```

**Key Features:**
- Metadata-only storage (no document content)
- Many-to-many relationships with Document Sets
- Automatic timestamp management
- Transaction support for data consistency

## Service Layer

### DocumentLibraryService

Orchestrates business logic and coordinates between domain and repository layers.

**Key Responsibilities:**
- Library lifecycle management (create, read, update, delete)
- Document set relationship management
- Business rule enforcement
- Aggregate metrics computation
- Error handling and validation

**Main Operations:**
- `create_library()`: Create new library with validation
- `get_library()`: Retrieve library by ID
- `update_library()`: Update library metadata
- `delete_library()`: Delete library (preserves document sets)
- `add_document_set()`: Add single document set reference
- `remove_document_set()`: Remove single document set reference
- `add_document_sets_bulk()`: Add multiple document sets in bulk (efficient)
- `remove_document_sets_bulk()`: Remove multiple document sets in bulk (efficient)
- `list_libraries()`: List all libraries with pagination
- `search_libraries()`: Search by name and tags
- `get_document_sets()`: Get all document sets in library
- `update_aggregate_metrics()`: Update computed statistics

## API Layer

### REST Endpoints

Base URL: `/api/v1/document-libraries`

**Endpoints:**
- `POST /` - Create library
- `GET /{library_id}` - Get library
- `PUT /{library_id}` - Update library
- `DELETE /{library_id}` - Delete library
- `POST /{library_id}/document-sets/{set_id}` - Add document set
- `DELETE /{library_id}/document-sets/{set_id}` - Remove document set
- `GET /` - List all libraries
- `GET /search` - Search libraries

### DTOs (Data Transfer Objects)

**Request Models:**
- `CreateLibraryRequest`: For creating new libraries
- `UpdateLibraryRequest`: For updating existing libraries

**Response Models:**
- `LibraryResponse`: Single library response
- `LibraryListResponse`: List of libraries with pagination

**Mapper:**
- `DocumentLibraryMapper`: Converts between domain models and DTOs

## Testing

### Test Structure

```
tests/unit/core/assets_management/document_libraries/
├── conftest.py                         # Test fixtures
├── domain/
│   └── models/
│       └── test_document_library_validation.py  # Domain model tests
├── application/
│   └── services/
│       └── test_document_library_service.py     # Service tests
└── adapters/
    └── repositories/
        └── test_duckdb_document_library_repository.py  # Repository tests
```

### Test Coverage

- **Domain Model Tests**: 26 tests covering validation, business rules, and state management
- **Service Layer Tests**: 10 tests covering business logic orchestration
- **Repository Tests**: Integration tests with DuckDB (optional)

### Running Tests

```bash
# Run from the project root

# Set PYTHONPATH
export PYTHONPATH="$(pwd)/src:${PYTHONPATH}"

# Run all document library tests
uv run pytest tests/unit/core/assets_management/document_libraries/ -v

# Run specific test file
uv run pytest tests/unit/core/assets_management/document_libraries/domain/models/test_document_library_validation.py -v

# Run with coverage
uv run pytest tests/unit/core/assets_management/document_libraries/ --cov=core.assets_management.document_libraries --cov-report=html
```

## Usage Examples

### Creating a Library

```python
from core.assets_management.document_libraries.application.services.document_library_service import DocumentLibraryService
from core.assets_management.document_libraries.adapters.repositories.duckdb_document_library_metadata_repository import DuckDBDocumentLibraryMetadataRepository
from core.assets_management.document_libraries.adapters.storage.duckdb_storage import DuckDBDocumentLibraryStorage

# Initialize storage and repository
storage = DuckDBDocumentLibraryStorage(db_path="libraries.duckdb")
repository = DuckDBDocumentLibraryMetadataRepository(storage=storage)

# Create service
service = DocumentLibraryService(repository=repository)

# Create a library
library = service.create_library(
    name="Financial Documents Q1 2024",
    description="Collection of financial documents for Q1 2024",
    tags=["finance", "q1-2024", "reports"]
)

print(f"Created library: {library.library_id}")
```

### Adding Document Sets

```python
# Add single document set
service.add_document_set(
    library_id=library.library_id,
    document_set_id="docset-001"
)

# Add multiple document sets in bulk (more efficient)
service.add_document_sets_bulk(
    library_id=library.library_id,
    document_set_ids=["docset-002", "docset-003", "docset-004"]
)

# Update aggregate metrics
service.update_aggregate_metrics(
    library_id=library.library_id,
    total_document_sets=4,
    total_documents=200,
    total_size_bytes=52428800
)
```

### Removing Document Sets

```python
# Remove single document set
service.remove_document_set(
    library_id=library.library_id,
    document_set_id="docset-001"
)

# Remove multiple document sets in bulk (more efficient)
service.remove_document_sets_bulk(
    library_id=library.library_id,
    document_set_ids=["docset-002", "docset-003"]
)
```

### Searching Libraries

```python
# Search by name
results = service.search_libraries(
    name="financial",
    skip=0,
    limit=10
)

# Filter by tags
results = service.search_libraries(
    tags=["finance", "q1-2024"],
    skip=0,
    limit=10
)
```

## Design Decisions

### Why Hexagonal Architecture?

1. **Testability**: Domain logic can be tested without infrastructure dependencies
2. **Flexibility**: Easy to swap storage backends (DuckDB → PostgreSQL → MongoDB)
3. **Maintainability**: Clear boundaries between layers
4. **Independence**: Domain layer has no external dependencies

### Why Metadata-Only Storage?

1. **Separation of Concerns**: Libraries manage organization, not content
2. **Performance**: Lightweight metadata operations
3. **Scalability**: Document content stored separately in appropriate systems
4. **Flexibility**: Document Sets can belong to multiple libraries

### Why DuckDB?

1. **Embedded Database**: No separate server required
2. **SQL Support**: Rich query capabilities
3. **Performance**: Fast for analytical queries
4. **Simplicity**: Single file database, easy deployment

## Integration with Document Sets

Document Libraries reference Document Sets by ID but do not store document content. This design:

- Allows Document Sets to belong to multiple libraries
- Keeps library operations lightweight
- Maintains clear separation between organization (libraries) and content (sets)
- Enables independent scaling of metadata and content storage

## Error Handling

### Domain Exceptions

- `DocumentLibraryNotFoundError`: Library does not exist
- `DocumentLibraryAlreadyExistsError`: Library with same name exists
- `InvalidDocumentLibraryError`: Validation failure
- `DocumentLibraryInvalidDataException`: Invalid data state

### Error Propagation

1. **Domain Layer**: Raises domain-specific exceptions
2. **Service Layer**: Catches and re-raises with context
3. **API Layer**: Converts to HTTP status codes (404, 409, 422, 500)

## Performance Considerations

### Indexing

- Primary key index on `library_id`
- Unique index on `name`
- Composite index on `(library_id, document_set_id)` in junction table

### Pagination

All list operations support pagination via `skip` and `limit` parameters to handle large result sets efficiently.

### Caching

Consider implementing caching at the service layer for frequently accessed libraries.

## Future Enhancements

1. **Access Control**: Add user/role-based permissions
2. **Versioning**: Track library changes over time
3. **Audit Log**: Record all modifications
4. **Advanced Search**: Full-text search on descriptions
5. **Bulk Operations**: Batch add/remove document sets
6. **Export/Import**: Library configuration export/import
7. **Statistics**: Advanced analytics on library usage

## Related Documentation

- [USER_GUIDE_DOCUMENT_LIBRARIES.md](../guides/USER_GUIDE_DOCUMENT_LIBRARIES.md) - User guide with API examples
- [ARCHITECTURE.md](../../ARCHITECTURE.md) - System architecture overview
- [OPERATOR_REFERENCE.md](../reference/OPERATORS.md) - Operator documentation

## Contributing

When contributing to this module:

1. Follow hexagonal architecture principles
2. Write tests for all new functionality
3. Update documentation for API changes
4. Use keyword-only arguments in all functions
5. Follow Python coding standards (PEP 8)
6. Add docstrings to all public methods

## Support

For issues or questions:
1. Check the user guide for common workflows
2. Review test files for usage examples
3. Consult ARCHITECTURE.md for design decisions
4. Open an issue on the project repository
