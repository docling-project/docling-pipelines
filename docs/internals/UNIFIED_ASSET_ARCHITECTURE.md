# Unified Asset Architecture — Complete Reference

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           DOMAIN LAYER                                      │
│                    core/assets/common/domain/models/                        │
└─────────────────────────────────────────────────────────────────────────────┘

                              Asset (ABC)
                    ┌─────────────────────────┐
                    │  asset_id: str | None   │
                    │  name: str              │
                    │  description: str|None  │
                    │  ─────────────────────  │
                    │  validate()             │
                    │  update_timestamp()     │
                    │  to_dict()              │
                    │  from_dict()            │
                    └─────────────────────────┘
                                  △
              ┌───────────────────┼──────────────────┐
              │                   │                  │
       ┌──────▼──────┐   ┌────────▼────────┐  ┌─────▼──────────┐
       │    Flow     │   │  DocumentSet    │  │DocumentLibrary │
       │             │   │                 │  │                │
       │ +created_on │   │ +created_at     │  │+document_      │
       │ +modified_on│   │ +updated_at     │  │  set_ids       │
       │ +definition │   │ +total_docs     │  │+add/remove_    │
       │             │   │ +storage_ref    │  │  document_set()│
       └─────────────┘   │ +data_card      │  └────────────────┘
                         └─────────────────┘


┌─────────────────────────────────────────────────────────────────────────────┐
│                        PORT LAYER (Interfaces)                              │
│                  core/assets/common/domain/ports/                           │
└─────────────────────────────────────────────────────────────────────────────┘

                     AssetRepository[T: Asset] (ABC)
                    ┌─────────────────────────────────┐
                    │  save(asset: T) -> T             │
                    │  find_by_id(asset_id) -> T|None  │
                    │  find_by_name(name) -> T|None    │
                    │  find_all() -> list[T]           │
                    │  list_all(limit, offset)         │
                    │  update(asset: T) -> T           │
                    │  partial_update(asset, updates)  │
                    │  delete(asset_id) -> bool        │
                    │  bulk_delete(asset_ids)          │
                    │  exists(asset_id) -> bool        │
                    │  exists_by_name(name) -> bool    │
                    │  health_check() -> dict          │
                    └─────────────────────────────────┘

                     DocumentSetStorage (ABC)
                    ┌─────────────────────────────────┐
                    │  store(doc_set_name, data)       │
                    │   -> StorageReference            │
                    │  load(storage_ref, limit)        │
                    │   -> pa.Table                    │
                    │  delete(storage_ref) -> bool     │
                    │  exists(storage_ref) -> bool     │
                    │  get_metrics(storage_ref) -> dict│
                    │  health_check()                  │
                    │  validate_config(config)         │
                    └─────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────────────┐
│                      ADAPTER LAYER (Generic)                                │
│          core/assets/common/adapters/repositories/                          │
└─────────────────────────────────────────────────────────────────────────────┘

                  DuckDBAssetRepository[T: Asset]
                  implements AssetRepository[T]
                 ┌────────────────────────────────┐
                 │  Works for ANY Asset subtype   │
                 │  Serialises via T.to_dict()    │
                 │  Deserialises via T.from_dict()│
                 │                                │
                 │  __init__(                     │
                 │    asset_type: type[T],        │
                 │    key_value_storage,          │
                 │    database_path: str          │
                 │  )                             │
                 │                                │
                 │  _collection auto-derived from │
                 │  asset_type name; overrideable │
                 │  by factory via repo._collection│
                 └────────────────────────────────┘
                               △
          ┌────────────────────┼────────────────────┐
          │                    │                    │
          │ pinned to          │ pinned to          │ pinned to
          │ "document_sets"    │ "document_libraries│ any future
          │                    │                    │ asset type
          ▼                    ▼                    ▼
   AssetRepository      AssetRepository       AssetRepository
   [DocumentSet]        [DocumentLibrary]     [T]
   (from factory)       (from factory)        (from factory)


┌─────────────────────────────────────────────────────────────────────────────┐
│                    DATA-PLANE ADAPTER (DocumentSet only)                    │
│           core/assets/document_sets/adapters/duckdb/data_store.py          │
└─────────────────────────────────────────────────────────────────────────────┘

          DuckDBDocumentSetStorage
          implements DocumentSetStorage
         ┌──────────────────────────────────┐
         │  __init__(                       │
         │    table_storage: TableStoragePort│
         │    database_path: str            │
         │  )                               │
         │                                  │
         │  store()  → upsert on id column  │
         │  load()   → read pa.Table        │
         │  delete() → DROP TABLE           │
         │  exists() → check table presence │
         │  get_metrics() → row/size counts │
         └──────────────────────────────────┘
         Registered via @DataStoreFactory.register(name="duckdb")
         Auto-triggered when adapters/duckdb/__init__.py is imported


┌─────────────────────────────────────────────────────────────────────────────┐
│                        FACTORY LAYER                                        │
└─────────────────────────────────────────────────────────────────────────────┘

   MetadataRepositoryFactory              DocumentLibraryRepositoryFactory
   (document_sets/factories/)             (document_libraries/factories/)
  ┌──────────────────────────┐           ┌──────────────────────────────┐
  │  create(                 │           │  create(                     │
  │    adapter_name="duckdb",│           │    adapter_name="duckdb",    │
  │    config                │           │    config                    │
  │  ) -> AssetRepository    │           │  ) -> AssetRepository        │
  │       [DocumentSet]      │           │       [DocumentLibrary]      │
  │                          │           │                              │
  │  Hardcodes duckdb path:  │           │  Hardcodes duckdb path:      │
  │  1. Validates config     │           │  1. Validates config         │
  │  2. Creates KV storage   │           │  2. Creates KV storage       │
  │  3. Creates DuckDBAsset  │           │  3. Creates DuckDBAsset      │
  │     Repository[DocSet]   │           │     Repository[DocLib]       │
  │  4. Pins _collection =   │           │  4. Pins _collection =       │
  │     "document_sets"      │           │     "document_libraries"     │
  │  5. Returns as port type │           │  5. Returns as port type     │
  │                          │           │                              │
  │  register() decorator    │           │  register() decorator        │
  │  for enterprise backends │           │  for enterprise backends     │
  └──────────────────────────┘           └──────────────────────────────┘

   DataStoreFactory
   (document_sets/factories/)
  ┌──────────────────────────┐
  │  create(                 │
  │    adapter_name="duckdb",│
  │    config                │
  │  ) -> DocumentSetStorage │
  │                          │
  │  Uses decorator registry │
  │  @register(name="duckdb")│
  │  on DuckDBDocumentSet    │
  │  Storage class           │
  └──────────────────────────┘


┌─────────────────────────────────────────────────────────────────────────────┐
│                        SERVICE LAYER                                        │
│                  core/assets/common/application/services/                   │
└─────────────────────────────────────────────────────────────────────────────┘

                         AssetService[T: Asset]
                    ┌──────────────────────────────────┐
                    │  __init__(*, repository:          │
                    │    AssetRepository[T])            │
                    │                                  │
                    │  get_by_id(asset_id) -> T        │
                    │  get_by_name(name) -> T          │
                    │  delete(asset_id) -> bool        │
                    │  exists(asset_id) -> bool        │
                    │  exists_by_name(name) -> bool    │
                    │  list_all(limit, offset)         │
                    │  count_all() -> int              │
                    │  health_check() -> dict          │
                    └──────────────────────────────────┘
                                    △
              ┌─────────────────────┼─────────────────────┐
              │                     │                     │
    ┌─────────▼──────────┐  ┌───────▼──────────┐  ┌──────▼──────────────┐
    │    FlowService     │  │DocumentSetService│  │DocumentLibraryService│
    │                    │  │                  │  │                      │
    │ extends            │  │ extends          │  │ extends              │
    │ AssetService[Flow] │  │ AssetService     │  │ AssetService         │
    │                    │  │ [DocumentSet]    │  │ [DocumentLibrary]    │
    │ __init__(          │  │                  │  │                      │
    │   repository:      │  │ __init__(        │  │ __init__(            │
    │   AssetRepository  │  │   metadata_repo: │  │   repository:        │
    │   [Flow]           │  │   AssetRepository│  │   AssetRepository    │
    │ )                  │  │   [DocumentSet], │  │   [DocumentLibrary], │
    │                    │  │   data_store:    │  │   document_set_      │
    │ Adds:              │  │   DocumentSet    │  │   service: optional  │
    │ create_flow()      │  │   Storage,       │  │ )                    │
    │ update_flow()      │  │   database_path, │  │                      │
    │ partial_update()   │  │   backend_type   │  │ Adds:                │
    │ validate_flow()    │  │ )                │  │ create_library()     │
    │ bulk_delete()      │  │                  │  │ update_library()     │
    │                    │  │ Adds:            │  │ add_document_set()   │
    └────────────────────┘  │ create_document_ │  │ add_document_sets_   │
                            │   set()          │  │   bulk()             │
                            │ update_document_ │  │ remove_document_set()│
                            │   set()          │  │ remove_document_sets_│
                            │ get_document_set()│  │   bulk()             │
                            │ list_document_   │  │ get_document_sets()  │
                            │   sets()         │  │ list_libraries()     │
                            │ delete_document_ │  │ delete_library()     │
                            │   set()          │  └──────────────────────┘
                            │ store_data()     │
                            │ preview_data()   │
                            │ compute_and_     │
                            │   update_metrics()│
                            └──────────────────┘


┌─────────────────────────────────────────────────────────────────────────────┐
│                      API LAYER (Dependency Injection)                       │
│                        api/dependencies.py                                  │
└─────────────────────────────────────────────────────────────────────────────┘

  get_flow_repository()                    get_document_set_repository()
  ┌────────────────────────────┐          ┌────────────────────────────────┐
  │ @lru_cache(maxsize=1)      │          │ @lru_cache(maxsize=1)          │
  │ RepositoryFactory          │          │ RepositoryFactory              │
  │   .create_repository(      │          │   .create_repository(          │
  │      asset_type=Flow       │          │      asset_type=DocumentSet    │
  │   )                        │          │   )                            │
  │ -> AssetRepository[Flow]   │          │ -> AssetRepository[DocumentSet]│
  └────────────────────────────┘          └────────────────────────────────┘

  get_document_set_data_store()
  ┌────────────────────────────┐
  │ @lru_cache(maxsize=1)      │
  │ DataStoreFactory.create(   │
  │   adapter_name="duckdb",   │
  │   config={database_path}   │
  │ )                          │
  │ -> DocumentSetStorage      │
  └────────────────────────────┘

  get_document_set_service()              get_document_library_service()
  ┌────────────────────────────────┐      ┌────────────────────────────────┐
  │ DocumentSetService(            │      │ DocumentLibraryService(        │
  │   metadata_repository=         │      │   repository=                  │
  │     get_document_set_          │      │     get_document_library_      │
  │     repository(),              │      │     repository(),              │
  │   data_store=                  │      │   document_set_service=        │
  │     get_document_set_          │      │     get_document_set_service() │
  │     data_store(),              │      │ )                              │
  │   database_path=...            │      └────────────────────────────────┘
  │ )                              │
  └────────────────────────────────┘
                    │
                    ▼
  Routes inject via Depends():
  • api/routes/document_sets.py     → Depends(get_document_set_service)
  • api/routes/document_libraries.py → Depends(get_document_library_service)
  • api/routes/flows.py              → Depends(get_flow_service)
```

---

## Key Design Decisions

### No asset-specific repository subclasses
`metadata_repository.py` files under each asset's `adapters/duckdb/` are **empty stubs** (documentation only).
`DuckDBAssetRepository[T]` implements the full `AssetRepository[T]` contract for any `T` — no subclass needed.

```python
# Before (old pattern — eliminated)
class DuckDBDocumentSetMetadataRepository(DocumentSetMetadataRepository):
    def __init__(self, ...):
        self._generic_repo = DuckDBAssetRepository[DocumentSet](...)
    def save(self, *, asset):
        return self._generic_repo.save(asset=asset)   # 574 lines of delegation

# After (current)
repo = DuckDBAssetRepository(asset_type=DocumentSet, ...)
repo._collection = "document_sets"                    # pin collection name
return repo                                           # used directly as the port
```

### Two separate factories for DocumentSet
DocumentSet has two storage concerns, each with its own factory:

| Factory | Creates | Purpose |
|---|---|---|
| `MetadataRepositoryFactory` | `DuckDBAssetRepository[DocumentSet]` | Stores `DocumentSet` domain object (name, description, stats, storage_reference) |
| `DataStoreFactory` | `DuckDBDocumentSetStorage` | Stores the actual PyArrow document table data |

### Decorator vs hardcoded registration
| Factory | Registration pattern | Why |
|---|---|---|
| `MetadataRepositoryFactory` | Hardcoded `if adapter_name == "duckdb"` | Only one built-in; enterprise adds via `register()` decorator |
| `DataStoreFactory` | `@DataStoreFactory.register(name="duckdb")` decorator on `DuckDBDocumentSetStorage` | Adapter registers itself on import; enterprise adds same way |

`DataStoreFactory` requires the adapter module to be imported before `create()` is called.
`adapters/duckdb/__init__.py` imports `DuckDBDocumentSetStorage`, so importing the package is sufficient.

---

## Summary Table

| Component | Flow | DocumentSet | DocumentLibrary |
|---|---|---|---|
| **Domain model** | `Flow(Asset)` | `DocumentSet(Asset)` | `DocumentLibrary(Asset)` |
| **Metadata port** | `AssetRepository[Flow]` | `AssetRepository[DocumentSet]` | `AssetRepository[DocumentLibrary]` |
| **Data-plane port** | — | `DocumentSetStorage` | — |
| **Generic adapter** | `DuckDBAssetRepository[Flow]` | `DuckDBAssetRepository[DocumentSet]` or `PostgresAssetRepository[DocumentSet]` | `DuckDBAssetRepository[DocumentLibrary]` or `PostgresAssetRepository[DocumentLibrary]` |
| **Data-plane adapter** | — | `DuckDBDocumentSetStorage` | — |
| **Metadata factory** | `RepositoryFactory` | `MetadataRepositoryFactory` | `DocumentLibraryRepositoryFactory` |
| **Data-plane factory** | — | `DataStoreFactory` | — |
| **Service** | `FlowService(AssetService[Flow])` | `DocumentSetService(AssetService[DocumentSet])` | `DocumentLibraryService(AssetService[DocumentLibrary])` |
| **DI provider** | `get_flow_service()` | `get_document_set_service()` | `get_document_library_service()` |
| **Collection name** | `flows` | `document_sets` | `document_libraries` |
| **Storage backend** | Local filesystem (JSON) | DuckDB or PostgreSQL (metadata) + DuckDB (data tables) | DuckDB or PostgreSQL |

---

## Verification

- 11 unit tests passing — `tests/unit/core/assets/document_sets/application/services/`
- `DuckDBAssetRepository[T]` and `PostgresAssetRepository[T]` are the shared implementations across all asset types (selected with `assets_management.<asset>_repository.type`: `duckdb` or `postgres`)
- No asset-specific repository subclass exists in the codebase
- `DocumentSetService` and `DocumentLibraryService` both extend `AssetService[T]`
- All dependencies injected via ports — services never import concrete adapter classes
